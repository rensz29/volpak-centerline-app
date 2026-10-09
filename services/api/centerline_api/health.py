"""The System health page (ADR-0038): each part of Centerline graded OK, warning or critical, with what to do.

The api gathers what each part reports: monitor-core's and the notifier's heartbeats, the backup agent's status file,
clamd's signatures, the database and Timebase. `grade` turns those readings into checks. It reads nothing itself, so
it's tested without any of them. A check's summary says what is wrong and where to act, in the page's words.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

STATES = ("ok", "unknown", "warning", "critical")  # worst last
DEFAULT_FRESHNESS_S = 30  # an area connections.json doesn't list, as monitor-core judges it (ADR-0006)
EVALUATION_LIMIT_MS = 2000  # PER-01: rule evaluation within 2 s
BACKUP_LATE_S = 75 * 60  # hourly sets (ADR-0035): one missed is a warning…
BACKUP_STALE_S = 3 * 3600  # …three, critical
CHECK_STALE_S = 26 * 3600  # the restore check runs on the first set of each UTC day
SIGNATURES_STALE_DAYS = 7


def worst(states) -> str:
    return max(states, key=STATES.index, default="ok")


def duration(seconds: float) -> str:
    s = max(0, round(seconds))
    if s < 90:
        return f"{s} s"
    if s < 90 * 60:
        return f"{round(s / 60)} min"
    if s < 48 * 3600:
        return f"{s / 3600:.1f} h"
    return f"{round(s / 86400)} days"


def _parse(t: str | None) -> datetime | None:
    if not t:
        return None
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def _age(t: str | None, now: datetime) -> float | None:
    at = _parse(t)
    return None if at is None else (now - at).total_seconds()


def check(id: str, area: str, title: str, state: str, summary: str, link: str | None = None) -> dict:
    return {"id": id, "area": area, "title": title, "state": state, "summary": summary, "link": link}


def _service(id: str, area: str, name: str, beat: dict | None, never: str) -> dict:
    """A service's own heartbeat: every 2 s; late after 10 s; not running after 60 s (guide §6.7)."""
    if beat is None:
        return check(id, area, name, "critical", never)
    age = float(beat["ageS"])
    if age >= 60:
        return check(id, area, name, "critical", f"Not running: its last heartbeat was {duration(age)} ago")
    if age >= 10:
        return check(id, area, name, "warning", f"Its heartbeat is {duration(age)} late: it may be stuck")
    return check(id, area, name, "ok", f"Running: heartbeat {duration(age)} ago")


def monitoring(beat: dict | None, freshness: dict, now: datetime) -> list[dict]:
    area = "Monitoring"
    out = [_service("monitor", area, "monitor-core", beat, "monitor-core has never run here: nothing is judged")]
    if beat is None or float(beat["ageS"]) >= 60:
        return out  # what it last said is out of date
    st = beat["status"]
    if st.get("judging"):
        out.append(check("judging", area, "Judging", "ok", f"Judging the line: rules v{st.get('rulesVersion')}, mapping v{st.get('mappingVersion')}"))
    else:
        reasons = "; ".join(st.get("reasons") or []) or "no reason given"
        out.append(check("judging", area, "Judging", "warning", f"Paused: {reasons}", "/centerline"))
    out.append(check("broker", area, "Plant broker", "ok", "Connected") if st.get("connected")
               else check("broker", area, "Plant broker", "critical", "Not connected: nothing new arrives from the machine",
                          "/configuration"))
    last = st.get("lastLive") or {}
    if not last:
        out.append(check("areas", area, "Machine messages", "warning", "No message from the machine yet"))
    else:
        parts, stale = [], []
        for topic, at in sorted(last.items()):
            name = topic.rsplit("/", 1)[-1]
            age = _age(at, now) or 0.0
            limit = float(freshness.get(name, DEFAULT_FRESHNESS_S))
            parts.append(f"{name} {duration(age)} ago")
            if age > limit:
                stale.append(f"{name} silent for {duration(age)} (limit {limit:g} s)")
        out.append(check("areas", area, "Machine messages", "warning", "; ".join(stale)) if stale
                   else check("areas", area, "Machine messages", "ok", " · ".join(parts)))
    skew = st.get("clockSkewWarning")
    out.append(check("clock", area, "Machine clocks", "warning", skew) if skew
               else check("clock", area, "Machine clocks", "ok", "Within 5 s of ours"))
    ev = st.get("evaluation")
    if ev is None:
        out.append(check("evaluation", area, "Time to judge", "unknown", "Not reported by this monitor-core"))
    elif ev.get("maxMs") is None:
        out.append(check("evaluation", area, "Time to judge", "ok", "No message in the last minute"))
    elif ev["maxMs"] > EVALUATION_LIMIT_MS:
        out.append(check("evaluation", area, "Time to judge", "warning",
                         f"A message waited {ev['maxMs']} ms to be judged in the last minute (PER-01: 2 s)"))
    else:
        out.append(check("evaluation", area, "Time to judge", "ok",
                         f"At most {ev['maxMs']} ms over {ev['messages']} messages in the last minute (limit 2 s)"))
    journal = st.get("journal")
    if journal and journal.get("steps"):
        since = _age(journal.get("oldestAt"), now)
        out.append(check("journal", area, "Disk journal", "warning",
                         f"{journal['steps']} step(s) waiting for the database"
                         + (f" for {duration(since)}" if since is not None else "")))
    elif journal is not None:
        out.append(check("journal", area, "Disk journal", "ok", "Empty: every step is in the database"))
    return out


def storage(beat: dict | None) -> list[dict]:
    area, title = "Storage and backups", "Disk"
    s = (beat or {}).get("status", {}).get("storage") if beat and float(beat["ageS"]) < 60 else None
    if not s:
        return [check("disk", area, title, "unknown", "Not measured: monitor-core reports it")]
    pct = s.get("usedPct")
    state = {"normal": "ok", "warning": "warning", "cleanup": "warning", "degraded": "critical"}.get(s.get("state"), "unknown")
    words = {"normal": f"{pct} % used", "warning": f"{pct} % used: free space before 90 %",
             "cleanup": f"{pct} % used: the cleanup is running; degraded mode follows in 10 min unless it drops under 90 %",
             "degraded": f"{pct} % used: protected degraded mode, uploads refused until it's under 85 %"}
    out = [check("disk", area, title, state, words.get(s.get("state"), f"{pct} % used"))]
    if s.get("error"):
        out.append(check("disk-read", area, "Disk readings", "warning", f"Couldn't measure: {s['error']}"))
    return out


def backups(status: dict | None, configured: bool, now: datetime) -> list[dict]:
    area = "Storage and backups"
    if not configured:
        return [check("backup", area, "Backups", "unknown", "Backups run in the Docker stack (ADR-0035): not on this setup")]
    if status is None:
        return [check("backup", area, "Backups", "critical", "No backup status: is the backup container running?")]
    out = []
    age = _age(status.get("last_success"), now)
    if age is None:
        out.append(check("backup", area, "Backups", "critical", f"No backup has succeeded yet{': ' + status['error'] if status.get('error') else ''}"))
    elif age > BACKUP_STALE_S:
        out.append(check("backup", area, "Backups", "critical", f"The last good backup is {duration(age)} old"
                         + (f": {status['error']}" if status.get("error") else "")))
    elif age > BACKUP_LATE_S or status.get("error"):
        out.append(check("backup", area, "Backups", "warning",
                         status.get("error") or f"The last good backup is {duration(age)} old: one was missed"))
    else:
        out.append(check("backup", area, "Backups", "ok", f"Last good set {duration(age)} ago; {status.get('sets', 0)} kept"))
    chk = status.get("last_check") or {}
    chk_age = _age(chk.get("at"), now)
    if chk.get("result") == "failed":
        out.append(check("restore-check", area, "Restore check", "critical", f"The last set didn't restore: {chk.get('error')}"))
    elif chk_age is None:
        out.append(check("restore-check", area, "Restore check", "warning", "No set has been restored and checked yet"))
    elif chk_age > CHECK_STALE_S:
        out.append(check("restore-check", area, "Restore check", "warning", f"The last restore check was {duration(chk_age)} ago"))
    else:
        out.append(check("restore-check", area, "Restore check", "ok",
                         f"Restored {duration(chk_age)} ago: {chk.get('tables')} tables, audit chain intact"))
    off = status.get("offhost") or {}
    if not off.get("configured"):
        out.append(check("offhost", area, "Off-host copy", "warning",
                         "Backups are on this PC only: set CENTERLINE_BACKUP_OFFHOST in deploy/.env (O-27)"))
    elif off.get("error"):
        out.append(check("offhost", area, "Off-host copy", "critical", f"The last copy failed: {off['error']}"))
    else:
        copied = _age(off.get("last_copy"), now)
        out.append(check("offhost", area, "Off-host copy", "ok" if copied is not None and copied <= BACKUP_LATE_S else "warning",
                         f"Last copied {duration(copied)} ago" if copied is not None else "Not copied yet"))
    return out


def notifications(beat: dict | None, outbox: dict, now: datetime) -> list[dict]:
    area = "Notifications"
    out = [_service("notifier", area, "Notifier", beat, "The notifier has never run here: nothing reaches Teams or email")]
    lanes = (beat or {}).get("status", {}).get("lanes") or {}
    for name, label in (("teams", "Teams"), ("email", "Email")):
        lane = lanes.get(name)
        if lane is None:
            continue
        error = lane.get("lastError") or {}
        if not lane.get("configured"):
            out.append(check(f"lane-{name}", area, label, "warning",
                             f"Not set: messages for {label} aren't sent (Configuration → Connections, O-05)", "/configuration"))
        elif error and (not lane.get("lastOk") or (_parse(error.get("at")) or now) > (_parse(lane["lastOk"]) or now)):
            out.append(check(f"lane-{name}", area, label, "warning", f"The last delivery failed: {error.get('error')}", "/notifications"))
        else:
            out.append(check(f"lane-{name}", area, label, "ok", "Set; the last delivery went through" if lane.get("lastOk") else "Set; nothing sent yet"))
    waiting, failed = outbox.get("waiting", 0), outbox.get("failed", 0)
    oldest = _age(outbox.get("oldestWaitingAt"), now)
    if failed:
        out.append(check("outbox", area, "Outbox", "warning", f"{failed} delivery(ies) failed for good: re-drive them", "/notifications"))
    elif oldest is not None and oldest > 15 * 60:
        out.append(check("outbox", area, "Outbox", "warning", f"{waiting} waiting, the oldest for {duration(oldest)}", "/notifications"))
    else:
        out.append(check("outbox", area, "Outbox", "ok", f"{waiting} waiting" if waiting else "Nothing waiting"))
    return out


def database(db: dict) -> list[dict]:
    area = "Database"
    if not db.get("reachable"):
        return [check("database", area, "PostgreSQL", "critical", f"Not reachable: {db.get('error')}")]
    out = [check("database", area, "PostgreSQL", "ok", f"Reachable; {db.get('size', '?')}")]
    chain = db.get("auditChain")
    out.append(check("audit", area, "Audit chain", "ok", "Intact") if chain == "intact"
               else check("audit", area, "Audit chain", "critical", f"The audit chain is {chain}: an entry was changed or removed"))
    return out


def scanner(s: dict, now: datetime) -> list[dict]:
    area, title = "Uploads and history", "Malware scanner"
    if s.get("type") == "none":
        return [check("scanner", area, title, "unknown", "None configured (a development PC): uploads aren't scanned")]
    if s.get("error"):
        return [check("scanner", area, title, "warning", f"clamd isn't answering: uploads are refused ({s['error']})")]
    answer = s.get("version") or ""
    m = re.match(r"ClamAV ([^/]+)/(\d+)/(.+)$", answer)
    if not m:
        return [check("scanner", area, title, "ok", answer or "Answering")]
    try:
        signed = datetime.strptime(" ".join(m.group(3).split()), "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return [check("scanner", area, title, "ok", f"ClamAV {m.group(1)}, signatures {m.group(2)}")]
    days = (now - signed).total_seconds() / 86400
    when = signed.strftime("%Y-%m-%d")
    if days > SIGNATURES_STALE_DAYS:
        return [check("scanner", area, title, "warning", f"Signatures from {when}, {round(days)} days old: bring an update in (O-24)")]
    return [check("scanner", area, title, "ok", f"ClamAV {m.group(1)}, signatures of {when}")]


def historian(t: dict) -> list[dict]:
    area, title = "Uploads and history", "Timebase"
    if t.get("reachable"):
        return [check("timebase", area, title, "ok", f"Answered in {t.get('latencyMs')} ms")]
    return [check("timebase", area, title, "warning", "Not reachable: Analytics waits for it; monitoring doesn't use it")]


def ai(a: dict | None) -> list[dict]:
    """The local model that writes the follow-up questions (ADR-0041), and the embedding model of the OCAP search by
    meaning (ADR-0048). Without them the fixed questions are asked and the search goes by keywords, so nothing worse
    than a warning."""
    return [*_chat_model(a), *_search_model(a)]


def _chat_model(a: dict | None) -> list[dict]:
    area, title = "Uploads and history", "AI model"
    if not a or not a.get("enabled"):
        return [check("ai", area, title, "unknown", "Off: operators get the fixed follow-up questions")]
    model = a.get("model")
    if not a.get("reachable"):
        return [check("ai", area, title, "warning", f"Ollama isn't answering, so the fixed questions are asked ({a.get('error')})")]
    if not a.get("digest"):
        return [check("ai", area, title, "warning", f"{model} isn't on this PC, so the fixed questions are asked: pull it into Ollama")]
    if a.get("pinned") and a["digest"].removeprefix("sha256:") != a["pinned"].removeprefix("sha256:"):
        return [check("ai", area, title, "warning", f"The installed {model} isn't the pinned one, so the fixed questions are asked")]
    last = a.get("last")
    if last and last.get("outcome") != "used":
        why = {"timeout": "it was too slow", "rejected": "its answer broke a rule", "failed": "it failed"}.get(last["outcome"], last["outcome"])
        return [check("ai", area, title, "warning", f"{model} is ready, but its last questions weren't used: {why} ({last.get('detail')})")]
    timing = f"; its last questions took {last['latencyMs'] / 1000:.1f} s" if last and last.get("latencyMs") is not None else ""
    gpu = a.get("gpu")
    if gpu == 0:  # loaded, none of it on the GPU: Docker didn't reach one (ADR-0049)
        return [check("ai", area, title, "warning", f"{model} runs on the CPU only, so its answers are slower{timing}: give Ollama "
                                                    "the GPU (CENTERLINE_GPU=nvidia in deploy/.env, then deploy/compose.sh up -d ollama)")]
    where = f" on the GPU ({gpu:.0%} of it)" if gpu else ""
    return [check("ai", area, title, "ok", f"{model} ready{where}{timing}")]


def _search_model(a: dict | None) -> list[dict]:
    area, title = "Uploads and history", "OCAP search by meaning"
    e = (a or {}).get("embed")
    if not a or not a.get("enabled") or not e:
        return [check("ai.search", area, title, "unknown", "Off: the OCAP search goes by keywords")]
    model = e["model"]
    if not a.get("reachable"):
        return [check("ai.search", area, title, "warning", "Ollama isn't answering, so the OCAP search goes by keywords")]
    if not e.get("digest"):
        return [check("ai.search", area, title, "warning",
                      f"{model} isn't on this PC, so the OCAP search goes by keywords: pull it into Ollama")]
    if e.get("pinned") and e["digest"].removeprefix("sha256:") != e["pinned"].removeprefix("sha256:"):
        return [check("ai.search", area, title, "warning", f"The installed {model} isn't the pinned one, so the OCAP search goes by keywords")]
    if e.get("total") and e.get("done", 0) < e["total"]:
        return [check("ai.search", area, title, "ok", f"{model} ready; embedding the Active OCAPs: {e['done']} of {e['total']} parts so far")]
    return [check("ai.search", area, title, "ok", f"{model} ready: the Active OCAPs are searched by meaning too")]


def grade(readings: dict, now: datetime | None = None) -> dict:
    """Every check, in the page's order, and the worst state of all."""
    now = now or datetime.now(timezone.utc)
    checks = [
        *monitoring(readings.get("monitor"), readings.get("freshness") or {}, now),
        *notifications(readings.get("notifier"), readings.get("outbox") or {}, now),
        *storage(readings.get("monitor")),
        *backups(readings.get("backup"), readings.get("backupConfigured", False), now),
        *database(readings.get("database") or {}),
        *scanner(readings.get("scanner") or {}, now),
        *historian(readings.get("timebase") or {}),
        *ai(readings.get("ai")),
    ]
    return {"overall": worst(c["state"] for c in checks), "checks": checks}
