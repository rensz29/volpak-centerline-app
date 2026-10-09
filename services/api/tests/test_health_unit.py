"""The System health page's grading (ADR-0038): readings in, checks out, without the parts they come from."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from centerline_api.health import grade, worst

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat().replace("+00:00", "Z")


def healthy() -> dict:
    """A plant where everything is as it should be."""
    return {
        "monitor": {"ageS": 1.2, "status": {
            "judging": True, "connected": True, "rulesVersion": 3, "mappingVersion": 2, "reasons": [],
            "lastLive": {"Plant/Volpak/Filler/SPC": ago(seconds=2), "Plant/Volpak/Filler/Dosing_Parameters": ago(seconds=40)},
            "clockSkewWarning": None, "evaluation": {"maxMs": 35, "messages": 118, "windowS": 60},
            "journal": {"steps": 0, "oldestAt": None},
            "storage": {"state": "normal", "usedPct": 41.0, "error": None}}},
        "freshness": {"SPC": 30, "Dosing_Parameters": 90},
        "notifier": {"ageS": 0.8, "status": {"lanes": {"teams": {"configured": True, "lastOk": ago(minutes=5), "lastError": None},
                                                         "email": {"configured": True, "lastOk": ago(minutes=5), "lastError": None}}}},
        "outbox": {"waiting": 0, "failed": 0, "oldestWaitingAt": None},
        "backupConfigured": True,
        "backup": {"last_success": ago(minutes=20), "error": None, "sets": 52,
                   "last_check": {"at": ago(hours=3), "result": "restored", "tables": 46},
                   "offhost": {"configured": True, "last_copy": ago(minutes=20)}},
        "database": {"reachable": True, "auditChain": "intact", "size": "12 MB"},
        "scanner": {"type": "clamd", "version": "ClamAV 1.4.3/27785/Tue Oct  6 08:23:45 2026"},
        "timebase": {"reachable": True, "latencyMs": 120},
        "ai": {"enabled": True, "model": "qwen3.5:4b", "url": "http://host.docker.internal:11434", "pinned": None, "reachable": True,
               "digest": "sha256:abc", "gpu": 0.56,
               "last": {"outcome": "used", "detail": None, "latencyMs": 2400, "at": ago(minutes=8)},
               "embed": {"model": "bge-m3", "pinned": None, "digest": "sha256:e3b", "total": 20, "done": 20}},
    }


def by_id(report: dict) -> dict:
    return {c["id"]: c for c in report["checks"]}


def test_a_healthy_plant_is_all_ok_and_says_so_in_numbers():
    report = grade(healthy(), NOW)
    assert report["overall"] == "ok"
    assert {c["state"] for c in report["checks"]} == {"ok"}
    c = by_id(report)
    assert c["areas"]["summary"] == "Dosing_Parameters 40 s ago · SPC 2 s ago"
    assert c["evaluation"]["summary"] == "At most 35 ms over 118 messages in the last minute (limit 2 s)"
    assert c["scanner"]["summary"] == "ClamAV 1.4.3, signatures of 2026-10-06"


def test_monitor_core_not_running_is_critical_and_its_old_readings_are_not_trusted():
    r = healthy()
    r["monitor"]["ageS"] = 95
    report = grade(r, NOW)
    c = by_id(report)
    assert c["monitor"]["state"] == "critical" and "not running" in c["monitor"]["summary"].lower()
    assert "broker" not in c and c["disk"]["state"] == "unknown"  # what it last said is out of date
    r["monitor"] = None
    assert by_id(grade(r, NOW))["monitor"]["summary"] == "monitor-core has never run here: nothing is judged"


def test_a_silent_area_a_lost_broker_a_slow_judge_and_a_full_journal_each_show():
    r = healthy()
    st = r["monitor"]["status"]
    st["lastLive"]["Plant/Volpak/Filler/Dosing_Parameters"] = ago(minutes=3)
    st["connected"] = False
    st["judging"], st["reasons"] = False, ["Dosing_Parameters silent for 180 s"]
    st["evaluation"]["maxMs"] = 2600
    st["journal"] = {"steps": 4, "oldestAt": ago(minutes=2)}
    c = by_id(grade(r, NOW))
    assert c["broker"]["state"] == "critical"
    assert c["areas"]["state"] == "warning" and "Dosing_Parameters silent for 3 min (limit 90 s)" in c["areas"]["summary"]
    assert c["judging"]["summary"] == "Paused: Dosing_Parameters silent for 180 s" and c["judging"]["link"] == "/centerline"
    assert c["evaluation"]["state"] == "warning" and "PER-01" in c["evaluation"]["summary"]
    assert c["journal"]["summary"] == "4 step(s) waiting for the database for 2 min"


def test_storage_follows_monitor_cores_states():
    for state, graded in (("warning", "warning"), ("cleanup", "warning"), ("degraded", "critical")):
        r = healthy()
        r["monitor"]["status"]["storage"] = {"state": state, "usedPct": 91.0, "error": None}
        assert by_id(grade(r, NOW))["disk"]["state"] == graded


def test_backups_late_missing_unchecked_or_only_here():
    r = healthy()
    r["backup"]["last_success"] = ago(minutes=90)
    assert by_id(grade(r, NOW))["backup"]["state"] == "warning"
    r["backup"]["last_success"] = ago(hours=4)
    assert by_id(grade(r, NOW))["backup"]["state"] == "critical"
    r = healthy()
    r["backup"]["last_check"] = {"at": ago(hours=1), "result": "failed", "error": "the restored audit chain breaks at row 7"}
    assert by_id(grade(r, NOW))["restore-check"]["state"] == "critical"
    r = healthy()
    r["backup"]["offhost"] = {"configured": False}
    assert "O-27" in by_id(grade(r, NOW))["offhost"]["summary"]
    r["backup"] = None
    assert by_id(grade(r, NOW))["backup"]["summary"] == "No backup status: is the backup container running?"
    r["backupConfigured"] = False
    assert by_id(grade(r, NOW))["backup"]["state"] == "unknown"  # a development PC: backups run in the Docker stack


def test_notifications_unset_failing_or_stuck():
    r = healthy()
    r["notifier"]["status"]["lanes"]["teams"] = {"configured": False, "lastOk": None, "lastError": None}
    r["notifier"]["status"]["lanes"]["email"]["lastError"] = {"at": ago(minutes=1), "error": "550 relay denied"}
    r["outbox"] = {"waiting": 3, "failed": 2, "oldestWaitingAt": ago(minutes=40)}
    c = by_id(grade(r, NOW))
    assert c["lane-teams"]["state"] == "warning" and "O-05" in c["lane-teams"]["summary"]
    assert c["lane-email"]["summary"] == "The last delivery failed: 550 relay denied"
    assert c["outbox"]["summary"].startswith("2 delivery(ies) failed for good") and c["outbox"]["link"] == "/notifications"


def test_old_signatures_a_silent_scanner_a_broken_chain_and_no_timebase():
    r = healthy()
    r["scanner"]["version"] = "ClamAV 1.4.3/27770/Mon Sep 21 08:23:45 2026"
    assert "16 days old" in by_id(grade(r, NOW))["scanner"]["summary"]
    r["scanner"] = {"type": "clamd", "error": "clamd at clamav:3310: timed out"}
    assert "uploads are refused" in by_id(grade(r, NOW))["scanner"]["summary"]
    r["database"]["auditChain"] = "broken at entry 12"
    r["timebase"] = {"reachable": False}
    report = grade(r, NOW)
    assert by_id(report)["audit"]["state"] == "critical" and report["overall"] == "critical"
    assert by_id(report)["timebase"]["state"] == "warning"


def test_the_worst_state_wins():
    assert worst(["ok", "unknown"]) == "unknown"
    assert worst(["ok", "warning", "unknown"]) == "warning"
    assert worst([]) == "ok"


def test_the_ai_model_off_down_missing_unpinned_or_unused_only_warns():
    assert by_id(grade(healthy(), NOW))["ai"]["summary"] == "qwen3.5:4b ready on the GPU (56% of it); its last questions took 2.4 s"
    for change, state, words in (({"enabled": False}, "unknown", "fixed follow-up questions"),
                                 ({"url": ""}, "warning", "No Ollama to ask"),  # deploy/.env names none (ADR-0050)
                                 ({"reachable": False, "error": "connection refused"}, "warning", "isn't answering"),
                                 ({"digest": None}, "warning", "isn't on this PC"),
                                 ({"pinned": "sha256:def"}, "warning", "isn't the pinned one"),
                                 ({"last": {"outcome": "timeout", "detail": "no answer within 25 s", "latencyMs": 25000}}, "warning", "too slow"),
                                 ({"gpu": 0}, "warning", "runs on the CPU only"),  # Docker didn't reach the GPU (ADR-0049)
                                 ({"gpu": None}, "ok", "qwen3.5:4b ready; its last")):  # not loaded right now
        r = healthy()
        r["ai"].update(change)
        c = by_id(grade(r, NOW))["ai"]
        assert c["state"] == state and words in c["summary"], change


def test_the_search_by_meaning_off_missing_or_unpinned_only_warns_and_says_how_far_it_got():
    assert by_id(grade(healthy(), NOW))["ai.search"]["summary"] == "bge-m3 ready: the Active OCAPs are searched by meaning too"
    for change, state, words in (({"done": 7}, "ok", "7 of 20 parts so far"),
                                 ({"digest": None}, "warning", "bge-m3 isn't on this PC, so the OCAP search goes by keywords"),
                                 ({"pinned": "sha256:fff"}, "warning", "isn't the pinned one")):
        r = healthy()
        r["ai"]["embed"].update(change)
        c = by_id(grade(r, NOW))["ai.search"]
        assert c["state"] == state and words in c["summary"], change
    r = healthy()
    del r["ai"]["embed"]
    assert by_id(grade(r, NOW))["ai.search"]["state"] == "unknown"
    r = healthy()
    r["ai"].update(reachable=False, error="refused")
    assert "isn't answering" in by_id(grade(r, NOW))["ai.search"]["summary"]
