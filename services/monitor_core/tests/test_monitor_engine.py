"""The engine against the G1 acceptance scenarios (AT-01…03), with a simulated line and clock."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from monitor_helpers import at, advance, make_config, rule_rows, start
from centerline_monitor.effects import BriefChange, Notify, OpenEvent, PauseEnded, PauseStarted, Transition

# -- AT-01: complete, fresh snapshots only -------------------------------------------------


def ack(event_id, period: int) -> dict:
    """An acknowledgment as the api stores it and the store reads it."""
    return {"event_id": event_id, "by_user": "manager", "note": "on it", "critical_period": period}


def test_judging_starts_only_on_a_complete_fresh_snapshot():
    engine, store, line = start()
    assert engine.gate.open and store.of(PauseStarted)[0].reasons[0].startswith("Starting")
    assert len(store.of(PauseEnded, scope="line")) == 1 and not store.of(OpenEvent)


def test_a_silent_area_pauses_and_only_a_fresh_message_from_every_area_resumes():
    engine, store, line = start()
    line.silent.add("Dosing_Parameters")  # SPC carries on; Dosing may be silent for 90 s
    advance(engine, line, 0, 80)
    line.set("P02.V1", setpoint=222)  # an SPC zone: its mismatch delay would end at t=111
    advance(engine, line, 80, 120)
    pause = store.of(PauseStarted, scope="line")[-1]
    assert not engine.gate.open and pause.at == at(91) and "Dosing_Parameters silent" in pause.reasons[0]
    assert not store.of(OpenEvent)  # the delay stopped with the pause
    line.silent.clear()
    advance(engine, line, 120, 121)
    assert engine.gate.open and len(store.of(PauseEnded, scope="line")) == 2
    advance(engine, line, 121, 150)  # the delay starts again from zero on the fresh snapshot
    assert not store.of(OpenEvent)
    advance(engine, line, 150, 151)
    assert store.of(OpenEvent)[0].at == at(151)

def test_a_lost_connection_and_a_missing_value_close_the_gate():
    engine, store, line = start()
    engine.set_connected(False, at(1))
    assert not engine.gate.open and "connection" in engine.reasons[0]
    engine.set_connected(True, at(2))
    assert not engine.gate.open  # still waiting for a fresh message from every area
    line.values[next(iter(line.values))] = float("nan")
    line.publish(engine, at(3))
    assert not engine.gate.open and any("No valid value" in r for r in engine.reasons)


def test_an_unconfigured_or_missing_sku_pauses_and_alerts_management_once():
    engine, store, line = start(cfg=make_config(skus=("A",), rows=rule_rows(("A",))))
    line.sku = "UNKNOWN"
    advance(engine, line, 0, 5)
    assert not engine.gate.open and "SKU UNKNOWN has no complete rules in effect" in engine.reasons
    assert len(store.of(Notify, kind="system")) == 1  # OPC-08, once per pause


# -- AT-02: HMI mismatch ------------------------------------------------------------------


def test_mismatch_opens_after_the_delay_and_resolves_with_a_recovery_notice():
    engine, store, line = start()
    line.set("P02.V1", setpoint=221.4)  # whole numbers differ: 221 vs 220, from the message at t=1
    advance(engine, line, 0, 30)
    assert not store.of(OpenEvent)
    advance(engine, line, 30, 31)
    event = store.of(OpenEvent, kind="HMI_MISMATCH")[0]
    assert event.at == at(31) and event.raw_hmi == Decimal("221.4") and event.raw_target == 220  # raw decimals (HMI-01)
    assert store.of(Notify, kind="initial")[0].event_id == event.event_id
    line.set("P02.V1", setpoint=220.8)  # truncates to 220: back at target
    advance(engine, line, 31, 32)
    assert store.of(Transition, event_id=event.event_id, state="RESOLVED")
    assert store.of(Notify, kind="recovery")[0].event_id == event.event_id

def test_a_change_back_before_the_delay_is_a_brief_change_and_never_notifies():
    engine, store, line = start()
    line.set("P03.FRONT", setpoint=182)
    advance(engine, line, 0, 12)
    line.set("P03.FRONT", setpoint=180)
    advance(engine, line, 12, 60)
    brief = store.of(BriefChange)[0]
    assert brief.mode == "lightweight" and (brief.started_at, brief.ended_at) == (at(1), at(13))
    assert not store.of(OpenEvent) and not store.of(Notify)


def test_a_new_off_target_value_supersedes_and_restarts_the_delay():
    engine, store, line = start()
    line.set("P04.FRONT", setpoint=187)
    advance(engine, line, 0, 40)
    first = store.of(OpenEvent)[0]
    line.set("P04.FRONT", setpoint=189)
    advance(engine, line, 40, 60)
    assert store.of(Transition, event_id=first.event_id, state="SUPERSEDED")
    assert len(store.of(OpenEvent)) == 1  # the new delay is still running
    advance(engine, line, 60, 75)
    second = store.of(OpenEvent)[1]
    assert second.supersedes == first.event_id and second.raw_hmi == 189


def test_separate_brief_periods_are_never_added_together():
    engine, store, line = start()
    for s in (0, 40, 80):
        line.set("P02.V2", setpoint=217)
        advance(engine, line, s, s + 20)
        line.set("P02.V2", setpoint=215)
        advance(engine, line, s + 20, s + 40)
    assert len(store.of(BriefChange)) == 3 and not store.of(OpenEvent)  # 3 × 20 s, each under the 30 s delay


# -- AT-03: Actual boundaries, escalation, downgrade, recovery, Critical repeats and acknowledgment --------------


def test_actual_escalates_downgrades_and_recovers_each_after_its_own_delay():
    engine, store, line = start()
    line.set("P03.REAR", actual=186)  # 6 above the HMI setpoint: Warning (5 < d ≤ 10)
    advance(engine, line, 0, 31)
    event = store.of(OpenEvent, kind="ACTUAL")[0]
    assert event.severity == "WARNING" and event.at == at(31)  # the Warning delay, 30 s from t=1
    line.set("P03.REAR", actual=191)  # 11 above: Critical
    advance(engine, line, 31, 42)
    assert [t.at for t in store.of(Transition, event_id=event.event_id, state="CRITICAL")] == [at(42)]  # 10 s
    assert store.of(Notify, kind="escalated")
    line.set("P03.REAR", actual=187)  # back in the Warning band: the downgrade waits the Warning delay
    advance(engine, line, 42, 72)
    assert store.of(Transition, event_id=event.event_id, state="WARNING") == store.of(Transition, event_id=event.event_id,
                                                                                       state="WARNING")[:1]
    advance(engine, line, 72, 73)
    downgrades = [t.at for t in store.of(Transition, event_id=event.event_id, state="WARNING")]
    assert downgrades == [at(31), at(73)]
    line.set("P03.REAR", actual=185)  # on the Warning edge, which belongs to Normal
    advance(engine, line, 73, 88)
    assert not store.of(Transition, event_id=event.event_id, state="RESOLVED")  # recovery takes 15 s
    advance(engine, line, 88, 89)
    assert store.of(Transition, event_id=event.event_id, state="RESOLVED")[0].at == at(89)
    assert store.of(Notify, kind="recovery")

def test_a_critical_repeats_four_times_then_escalates_once_at_75_minutes():
    engine, store, line = start()
    line.set("P06.N1", actual=98 + 19)  # beyond +18: Critical
    advance(engine, line, 0, 90 * 60, every=5)
    event = store.of(OpenEvent)[0]
    assert event.severity == "CRITICAL"
    repeats = store.of(Notify, kind="critical_repeat")
    assert [round((n.at - event.at).total_seconds() / 60) for n in repeats] == [15, 30, 45, 60]
    final = store.of(Notify, kind="critical_escalation")
    assert len(final) == 1 and round((final[0].at - event.at).total_seconds() / 60) == 75
    assert len(store.of(Notify, event_id=event.event_id)) == 6  # A-03: at most six messages


def test_a_managers_acknowledgment_stops_the_repeats():
    engine, store, line = start()
    line.set("P06.N2", actual=98 - 19)
    advance(engine, line, 0, 20 * 60, every=5)
    event = store.of(OpenEvent)[0]
    engine.acknowledge(ack(event.event_id, 1), at(20 * 60))
    advance(engine, line, 20 * 60, 90 * 60, every=5)
    assert len(store.of(Notify, kind="critical_repeat")) == 1 and not store.of(Notify, kind="critical_escalation")
    (done,) = store.of(Transition, event_id=event.event_id, state="ACKNOWLEDGED")
    assert done.inputs == {"acknowledged_by": "manager", "note": "on it"}


def test_an_acknowledgment_counts_only_for_the_critical_period_it_was_given_in():
    engine, store, line = start()
    line.set("P06.N1", actual=98 + 19)  # Critical from t=10: period 1
    advance(engine, line, 0, 60, every=5)
    event = store.of(OpenEvent)[0]
    engine.acknowledge(ack(event.event_id, 1), at(60))
    line.set("P06.N1", actual=98 + 10)  # down to Warning after 30 s
    advance(engine, line, 60, 120, every=5)
    line.set("P06.N1", actual=98 + 19)  # Critical again after 10 s: period 2
    advance(engine, line, 120, 300, every=5)
    engine.acknowledge(ack(event.event_id, 1), at(300))  # period 1's, read again after a restart: ignored
    assert len(store.of(Transition, event_id=event.event_id, state="ACKNOWLEDGED")) == 1
    advance(engine, line, 300, 20 * 60, every=5)
    assert len(store.of(Notify, kind="critical_repeat")) == 1  # period 2 repeats at +15 min
    engine.acknowledge(ack(event.event_id, 2), at(20 * 60))
    advance(engine, line, 20 * 60, 90 * 60, every=5)
    assert len(store.of(Transition, event_id=event.event_id, state="ACKNOWLEDGED")) == 2
    assert len(store.of(Notify, kind="critical_repeat")) == 1 and not store.of(Notify, kind="critical_escalation")


def test_warning_notifications_can_be_switched_off_but_criticals_cannot():
    settings = {"pause_when_stopped": {"enabled": True, "long_stop_min": 10, "warmup_min": 30},
                "defaults": {**make_config().settings["defaults"], "warning_notifications": False}}
    engine, store, line = start(cfg=make_config(settings=settings))
    line.set("P03.FRONT", actual=186)
    advance(engine, line, 0, 40)
    assert store.of(OpenEvent) and not store.of(Notify)
    line.set("P03.FRONT", actual=191)
    advance(engine, line, 40, 60)
    assert store.of(Notify, kind="escalated")


# -- pauses, changeovers and versions -------------------------------------------------


def test_actual_rules_pause_while_stopped_and_warm_up_after_a_long_stop():
    engine, store, line = start()
    line.set("P03.FRONT", actual=186)
    advance(engine, line, 0, 10)  # Warning delay running
    line.run(0)
    advance(engine, line, 10, 11 * 60)
    assert engine.actual_paused and not store.of(OpenEvent)  # the delay stopped with the machine
    line.set("P02.V1", setpoint=222)  # HMI monitoring carries on while stopped
    advance(engine, line, 11 * 60, 12 * 60)
    assert store.of(OpenEvent, kind="HMI_MISMATCH")
    line.run(1)  # after an 11-minute stop: a 30-minute warm-up
    advance(engine, line, 12 * 60, 41 * 60, every=5)
    assert engine.actual_paused and not store.of(OpenEvent, kind="ACTUAL")
    advance(engine, line, 41 * 60, 43 * 60, every=5)
    assert not engine.actual_paused and store.of(OpenEvent, kind="ACTUAL")


def test_a_short_stop_resumes_actual_rules_at_once():
    engine, store, line = start()
    line.run(0)
    advance(engine, line, 0, 60)
    line.run(1)
    advance(engine, line, 60, 61)
    assert not engine.actual_paused
    assert [p.scope for p in store.of(PauseEnded)].count("actual") == 1


def test_a_sku_changeover_closes_open_events_without_recovery_notices():
    engine, store, line = start()
    line.set("P02.V1", setpoint=222)
    advance(engine, line, 0, 40)
    event = store.of(OpenEvent)[0]
    line.sku = "B"
    advance(engine, line, 40, 41)
    assert store.of(Transition, event_id=event.event_id, state="CLOSED_SKU_CHANGEOVER")
    assert not store.of(Notify, kind="recovery") and len(store.of(Notify, kind="changeover")) == 1
    advance(engine, line, 41, 42)
    assert engine.gate.open and engine.sku == "B"


def test_an_open_event_keeps_the_rule_it_opened_under():
    engine, store, line = start()
    line.set("P02.V1", setpoint=222)
    advance(engine, line, 0, 40)
    event = store.of(OpenEvent)[0]
    # Rules v2 moves Vertical 1's target for SKU A to 222
    rows = [dict(r, target=Decimal(222)) if (r["sku"], r["parameter_id"], r["zone_id"]) == ("A", "P02", "V1") else r
            for r in rule_rows()]
    engine.configure(make_config(rows=rows, rules_number=2), at(41))
    advance(engine, line, 41, 45)
    assert not store.of(Transition, event_id=event.event_id, state="RESOLVED")  # still judged against 220 (OPC-07)
    line.set("P02.V1", setpoint=220)
    advance(engine, line, 45, 46)
    assert store.of(Transition, event_id=event.event_id, state="RESOLVED")
    advance(engine, line, 46, 80)
    assert len(store.of(OpenEvent)) == 2 and store.of(OpenEvent)[1].rule["target"] == "222"  # 220 is off-target under v2


def test_the_status_carries_each_zones_values_bands_and_pending_timers():
    engine, store, line = start()
    line.set("P03.FRONT", actual=186)
    line.set("P02.V1", setpoint=222)
    advance(engine, line, 0, 5)
    z = engine.status()["zones"]
    front, v1 = z["P03.FRONT"], z["P02.V1"]
    assert (front["setpoint"], front["actual"], front["target"]) == ("180", "186", "180")
    assert front["bands"] == {"warnLow": "175", "warnHigh": "185", "critLow": "170", "critHigh": "190"}
    assert front["actualSeverity"] == "NORMAL" and front["actualPending"] == "WARNING" and front["actualDue"] == at(31).isoformat()
    assert v1["hmi"] == "PENDING" and v1["hmiSince"] == at(1).isoformat() and v1["hmiDue"] == at(31).isoformat()
    assert engine.status()["judging"] and engine.status()["sku"] == "A"


def test_the_status_takes_the_target_and_the_bands_each_from_their_own_rule():
    engine, store, line = start()
    line.set("P02.V1", setpoint=222)
    advance(engine, line, 0, 40)
    assert store.of(OpenEvent)
    # Rules v2 moves the target to 222 and widens P02's Warning band below the setpoint to 3
    rows = [dict(r, target=Decimal(222)) if (r["sku"], r["parameter_id"], r["zone_id"]) == ("A", "P02", "V1") else r
            for r in rule_rows()]
    rows = [dict(r, warn_low=Decimal(3)) if (r["sku"], r["parameter_id"], r["zone_id"]) == (None, "P02", None) else r
            for r in rows]
    engine.configure(make_config(rows=rows, rules_number=2), at(41))
    advance(engine, line, 41, 42)
    v1 = engine.status()["zones"]["P02.V1"]
    assert (v1["target"], v1["hmiRulesVersion"]) == ("220", 1)  # the open mismatch is still judged against 220 (OPC-07)
    assert (v1["bands"]["warnLow"], v1["actualRulesVersion"]) == ("219", 2)  # no Actual event is open: v2's limits


def test_the_machines_clock_is_kept_as_evidence_and_warned_about_but_never_used_as_time():
    engine, store, line = start()
    line.clock_behind_s = 114  # the plant's edge clock, measured (ADR-0006, O-18)
    line.set("P02.V1", setpoint=222)
    advance(engine, line, 0, 31)
    event = store.of(OpenEvent, kind="HMI_MISMATCH")[0]
    assert event.at == at(31)  # judged on our own clock (invariant 13)
    (opened,) = store.of(Transition, event_id=event.event_id, state="OPEN")
    stamped = {t: v for t, v in opened.inputs["payload_clock"].items()}
    assert stamped and all(v == (at(31) - timedelta(seconds=114)).isoformat() for v in stamped.values())  # the machine's stamp, as evidence
    status = engine.status()
    assert set(status["clockSkewS"].values()) == {114.0}
    assert status["clockSkewWarning"].startswith("The machine's clock is 114 s behind ours")
    line.clock_behind_s = 2  # within 5 s: no warning
    advance(engine, line, 31, 32)
    assert engine.status()["clockSkewWarning"] is None
