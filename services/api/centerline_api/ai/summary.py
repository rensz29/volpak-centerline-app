"""The AI's summary of the OCAP sections offered (OCP-02, AI-02, LAN-01, ADR-0046).

Once a request's sections are offered (up to three, OCP-01), the local model sums up what they say for this mismatch,
in English and Filipino, and says which of them it used. It runs beside the requests, in the api, like the opening
question: the operator reads the sections meanwhile, and without a summary they still do (the deterministic path).

A summary is shown only when it passes every check (OCP-02's "verify"); otherwise there's none:
- it cites at least one section, and only sections that were offered;
- every number in it is in the sections it cites (or the alarm);
- every instruction verb in it (clean, replace, stop, call, adjust, …) is in the sections it cites: the trial model
  invents and swaps instructions (ADR-0045's measurement).
Its Filipino passes the OCAP translation's checks against the English (every number and instruction word kept both
ways) and says each instruction as many times as the English does, else the English is shown. An "English" summary
that came back in Tagalog isn't shown. Every call is kept in `ai_call`; a summary that passed, in `workflow_summary`.
"""

from __future__ import annotations

import json
import logging
import re

from centerline_common.db import DatabaseUnavailable
from psycopg import Error as PsycopgError

from ..ocap.store import OcapStore
from . import calls, translate

PROMPT_VERSION = "summary-v1"
MAX_SECTIONS = 3
SECTION_CHARS = 2500  # of each section's text in the prompt
LOCK = "centerline.ai.summary"

SYSTEM = """You help the operators of a Volpak pouch-filling machine read their plant's OCAP (Out of Control Action Plan).
An HMI setpoint moved off its target; the operator gave a reason and answered questions. The OCAP sections found for it are numbered [1], [2], [3].
Sum up, in two to four short sentences, what those sections say for this situation: what to check, the likely causes, and what to do, in the OCAP's own words and order. Name the section each point comes from, like [1].
Use only what the sections say. Never add a step, a number, a part or a fact that isn't in them, and never give advice of your own. Leave out a section that doesn't fit what the operator wrote.
List the sections you used, by number.
Also write the summary in Filipino, the way operators at a Philippine plant talk: everyday Tagalog, keeping technical words in English (seal, sealer, jaw, film, pouch, preset, setpoint, temperature, HMI, Maintenance, Cell Lead). Same points, same order, same section numbers.
Words to use in Filipino: clean = linisin; replace = palitan; remove = alisin; stop = itigil; isolate = ihiwalay; call = tumawag sa; return to = ibalik sa; check = suriin; verify = tiyakin; do not = huwag; cause = sanhi.
Reply with JSON only: {"summary": "...", "summary_fil": "...", "sections": [1, 2]}"""

SCHEMA = {"type": "object", "required": ["summary", "summary_fil", "sections"],
          "properties": {"summary": {"type": "string"}, "summary_fil": {"type": "string"},
                         "sections": {"type": "array", "minItems": 1, "maxItems": MAX_SECTIONS, "items": {"type": "integer"}}}}

# An instruction verb in the summary must be in the sections it cites (or the alarm, for "raised"/"lowered")
VERBS = [re.compile(v + r"\w*", re.I) for v in (
    r"\bclean", r"\breplac", r"\bremov", r"\bstop", r"\b(isolat|segregat)", r"\bcall", r"\breturn", r"\btighten",
    r"\bloosen", r"\bhold", r"\bset\b", r"\badjust", r"\b(raise|increas)", r"\b(lower|decreas|reduc)", r"\brun\b",
    r"\bdocument", r"\brecord", r"\b(do not|don't|never|avoid)\b", r"\bwipe", r"\blubricat", r"\brestart", r"\bcompensat",
    r"\bdisassembl", r"\bshut")]
CITE = re.compile(r"\[\d\]")
# The Filipino must say each instruction as often as the English: one "palitan" for one "replace" (the trial model
# wrote "palitan ... kung hindi matitiyak" where the English said "tighten if needed", then "palitan" again for the
# real "replace", so every word was there)
COUNTED = [(re.compile(e, re.I), re.compile(t, re.I)) for e, t in (
    (r"\bclean(ed)?\b", r"linis|\bclean"), (r"\breplac\w*", r"p(in)?alit|replac"), (r"\bremov\w*", r"\b(alisin|inalis|naalis|maalis\w*|tanggalin|tinanggal)\b|remov"),
    (r"\bstop\w*", r"t(um|in)?igil|h(um|in)?into|\bstop"), (r"\b(isolat|segregat)\w*", r"ihiwalay|inihiwalay|isolat|segregat"),
    (r"\bcall\w*", r"t(um|in)?awag|\bcall"), (r"\b(return\w*|back|restor\w*|revert\w*)\b", r"b(um|in)?alik|return"),
    (r"\btighten\w*", r"h(in)?igpit|tighten"), (r"\bclose\b", r"sara|\bclose"), (r"\b(do not|don't|never)\b", r"huwag"))]
# Words that mark a text as Tagalog: an "English" summary with them came back in Tagalog
TAGALOG = {"ang", "ng", "mga", "ay", "sa", "kung", "hindi", "nang", "para", "kailangan"}

log = logging.getLogger("centerline.api.ai")


def prompt(alarm: str, written: list[tuple[str | None, str]], sections: list[dict]) -> str:
    parts = [alarm]
    for question, body in written:
        parts.append(f'The operator\'s reason, as they wrote it: "{body}"' if question is None
                     else f'Asked "{question}", they answered: "{body}"')
    parts.append("The OCAP sections found for it:")
    for i, s in enumerate(sections[:MAX_SECTIONS], start=1):
        parts.append(f"[{i}] {s['citation']}\n{source(s)}")
    parts.append("Sum up what these sections say for this situation.")
    return "\n\n".join(parts)


def source(section: dict) -> str:
    """A section's text as the model reads it: what a summary can be grounded in."""
    return f"{section.get('heading') or ''}\n{section['body'][:SECTION_CHARS]}"


def validate(raw: str, sections: list[dict], alarm: str) -> tuple[tuple[str, str | None, list[int]] | None, str | None]:
    """(English, Filipino or None, the indexes of the sections it cites, from 0), or why it can't be shown."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None, "not JSON"
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str):
        return None, "no summary"
    text = " ".join(data["summary"].split())
    if not 30 <= len(text) <= 700:
        return None, f"a summary of {len(text)} characters"
    if sum(1 for w in re.findall(r"[a-z]+", text.lower()) if w in TAGALOG) >= 2:
        return None, "its English summary isn't in English"
    cited = data.get("sections")
    offered = len(sections[:MAX_SECTIONS])
    if not isinstance(cited, list) or not cited or not all(isinstance(i, int) for i in cited):
        return None, "cites no section"
    outside = sorted({i for i in cited if not 1 <= i <= offered} | {int(m[1:-1]) for m in CITE.findall(text) if not 1 <= int(m[1:-1]) <= offered})
    if outside:
        return None, f"cites a section that wasn't offered: {', '.join(f'[{i}]' for i in outside)}"
    cited = sorted(set(cited) | {int(m[1:-1]) for m in CITE.findall(text)})
    grounds = "\n".join(source(sections[i - 1]) for i in cited) + "\n" + alarm
    bare = CITE.sub(" ", text)
    numbers = set(translate.NUMBER.findall(grounds))
    invented = [n for n in translate.NUMBER.findall(bare) if n not in numbers]
    if invented:
        return None, f"a number its sections don't have: {invented[0]}"
    for verb in VERBS:
        if (m := verb.search(bare)) and not verb.search(grounds):
            return None, f"an instruction its sections don't have: {m.group(0)!r}"
    fil = data.get("summary_fil")
    if isinstance(fil, str) and fil.strip():
        fil = " ".join(fil.split())
        checked, _ = translate.check(json.dumps({"lines": ["", "", CITE.sub(" ", fil)]}), ["", "", bare])
        same = all(len(e.findall(bare)) == len(t.findall(fil)) for e, t in COUNTED)
        fil = fil if checked and same else None
    else:
        fil = None
    return (text, fil, [i - 1 for i in cited]), None


def pass_once(app) -> int:
    """A summary for each request whose sections are offered and that hasn't had one tried. Returns how many were tried.
    One api at a time writes them (an advisory lock); each is committed on its own."""
    settings = app.state.settings
    tried = 0
    with settings.database.connect() as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS ok", (LOCK,)).fetchone()["ok"]:
            return 0
        try:
            rows = conn.execute("""SELECT r.id, e.parameter_id, e.zone_id, e.raw_hmi, e.raw_target FROM workflow_request r
                                     JOIN event e ON e.id = r.event_id
                                    WHERE r.status = 'waiting_ocap' AND r.updated_at > clock_timestamp() - interval '2 hours'
                                      AND EXISTS (SELECT 1 FROM ocap_recommendation o WHERE o.request_id = r.id)
                                      AND NOT EXISTS (SELECT 1 FROM ai_call c WHERE c.request_id = r.id AND c.purpose = 'summary')
                                    ORDER BY r.updated_at LIMIT 5""").fetchall()
            names = {}
            if rows:
                names = {z.channel: {"parameterName": z.parameter_name, "zoneName": z.zone_name, "unit": z.unit}
                         for z in app.state.register_store.load(conn).zones}
            conn.commit()
            for r in rows:
                ids = [o["section_id"] for o in conn.execute("""SELECT section_id FROM ocap_recommendation WHERE request_id = %s
                                                                 ORDER BY rank LIMIT %s""", (r["id"], MAX_SECTIONS))]
                found = OcapStore.sections(conn, ids)
                ids = [i for i in ids if i in found]
                sections = [found[i] for i in ids]
                written = [(e["question"], e["body"]) for e in conn.execute(
                    """SELECT question, body FROM workflow_entry WHERE request_id = %s AND kind IN ('reason', 'answer') ORDER BY seq""",
                    (r["id"],))]
                alarm = calls.alarm_text(names.get(f"{r['parameter_id']}.{r['zone_id']}", {}), r)
                now = conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]
                result, call_id = calls.run(settings.ai, conn, r["id"], "summary", PROMPT_VERSION, SYSTEM,
                                            prompt(alarm, written, sections), SCHEMA,
                                            lambda raw: validate(raw, sections, alarm), [s["sectionId"] for s in sections], now)
                if result:
                    text, fil, cited = result
                    conn.execute("""INSERT INTO workflow_summary (request_id, summary, summary_fil, section_ids, ai_call_id, at)
                                    VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                                 (r["id"], text, fil, [ids[i] for i in cited], call_id, now))
                conn.commit()
                tried += 1
        finally:
            conn.rollback()
            conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK,))
            conn.commit()
    return tried


def keep_summarising(app, stop) -> None:
    """Every `summary_every_s`, the summaries still to write (ADR-0046). Ends with the process."""
    every = max(0.5, app.state.settings.ai.summary_every_s)
    while not stop.wait(every):
        try:
            if n := pass_once(app):
                log.info("AI summary tried for %d request(s)", n)
        except (DatabaseUnavailable, PsycopgError) as e:
            log.warning("AI summaries wait for the database: %s", e)
