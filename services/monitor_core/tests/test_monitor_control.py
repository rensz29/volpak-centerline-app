"""Monitoring control (ADR-0017): zones switched off (MON-01) and maintenance windows (MNT-01, MNT-02)."""

from __future__ import annotations

from uuid import uuid4

from monitor_helpers import advance, at, start
from centerline_monitor.effects import Notify, OpenEvent, PauseStarted, StartTimer, Transition

HMI_TIMER = "P02.V1:hmi"


def off(*channels: str, t: float = 0, reason: str = "Sensor replaced") -> dict:
    """Zones switched off, as the store reads them: the latest switch of each."""
    return {ch: {"channel": ch, "enabled": False, "at": at(t), "by_user": "manager", "reason": reason} for ch in channels}


def window(scope: str, start_s: float, end_s: float, channels=(), reason: str = "Heater work") -> dict:
    return {"id": uuid4(), "scope": scope, "channels": list(channels), "reason": reason,
            "planned_start": at(start_s), "planned_end": at(end_s)}


def test_switching_a_zone_off_closes_its_events_without_a_recovery_notice_and_stops_judging_it():
    engine, store, line = start()
    line.set("P06.N1", actual=98 + 19)  # Critical from t=10
    line.set("P02.V1", setpoint=222)  # an HMI mismatch from t=31
    advance(engine, line, 0, 40, every=5)
    opened = {e.zone.channel: e.event_id for e in store.of(OpenEvent)}
    assert set(opened) == {"P06.N1", "P02.V1"}

    engine.set_control(off("P06.N1", "P02.V1", t=40), [], at(40))
    closed = store.of(Transition, state="CLOSED_MONITORING_DISABLED")
    assert {t.event_id for t in closed} == set(opened.values()) and not any(t.open for t in closed)
    advance(engine, line, 40, 30 * 60, every=5)  # still off: no repeats, no new events, nothing sent
    assert not store.of(Notify, kind="recovery") and not store.of(Notify, kind="critical_repeat")
    assert len(store.of(OpenEvent)) == 2
    assert [n.kind for n in store.of(Notify)] == ["initial", "initial"]  # the first notices stay on record
    control = engine.status()["zones"]["P06.N1"]["control"]
    assert (control["state"], control["by"], control["reason"]) == ("off", "manager", "Sensor replaced")
    assert engine.status()["judging"]  # the rest of the line is judged as usual


def test_a_zone_switched_on_again_is_judged_on_fresh_values_with_its_delays_from_zero():
    engine, store, line = start()
    engine.set_control(off("P02.V1", t=1), [], at(1))
    line.set("P02.V1", setpoint=222)
    advance(engine, line, 1, 100, every=5)
    assert not store.of(OpenEvent)  # never judged while off

    engine.set_control({}, [], at(100))
    assert engine.status()["zones"]["P02.V1"]["control"]["state"] == "waiting"
    advance(engine, line, 100, 130, every=5)
    assert not store.of(OpenEvent)  # the 30 s mismatch delay started with the first fresh value, at 105
    advance(engine, line, 130, 140, every=5)
    (event,) = store.of(OpenEvent)
    assert event.at == at(135) and engine.status()["zones"]["P02.V1"]["control"] is None


def test_a_zone_window_holds_its_events_and_repeats_and_they_resume_from_zero_after_it():
    engine, store, line = start()
    line.set("P06.N1", actual=98 + 19)  # Critical from t=10
    advance(engine, line, 0, 60, every=5)
    engine.set_control({}, [window("zones", 60, 20 * 60, ["P06.N1"])], at(60))
    line.set("P02.V1", setpoint=222)  # the rest of the line stays judged
    advance(engine, line, 60, 40 * 60, every=5)
    assert not store.of(Notify, kind="critical_repeat") and not store.of(Transition, state="RESOLVED")
    assert [e.zone.channel for e in store.of(OpenEvent)] == ["P06.N1", "P02.V1"]
    (overdue,) = store.of(Notify, kind="system")  # past its planned end it stays in force, once alerted
    assert overdue.payload["kind"] == "Maintenance overdue (MNT-01)" and at(20 * 60) < overdue.at <= at(20 * 60 + 5)
    assert overdue.dedup_key.endswith(":overdue")
    assert engine.status()["zones"]["P06.N1"]["control"]["state"] == "maintenance"

    engine.set_control({}, [], at(40 * 60))  # ended
    advance(engine, line, 40 * 60, 56 * 60, every=5)
    (repeat,) = store.of(Notify, kind="critical_repeat")
    assert repeat.at == at(40 * 60 + 5 + 15 * 60)  # restarted from zero on the first fresh value (MNT-02)
    assert len([e for e in store.of(OpenEvent) if e.zone.channel == "P06.N1"]) == 1  # the same event carried on


def test_a_line_window_pauses_judging_and_only_data_from_after_it_resumes_it():
    engine, store, line = start()
    advance(engine, line, 0, 10, every=5)
    assert engine.status()["judging"]
    engine.set_control({}, [window("line", 10, 600)], at(10))
    status = engine.status()
    assert not status["judging"] and status["reasons"][0].startswith("Maintenance: Heater work (planned to end ")
    assert store.of(PauseStarted, scope="line")[-1].reasons[0].startswith("Maintenance: ")
    line.set("P02.V1", setpoint=222)
    advance(engine, line, 10, 300, every=5)
    assert not store.of(OpenEvent)

    engine.set_control({}, [], at(300))  # ended early
    assert not engine.status()["judging"]  # waits for messages from after the window
    advance(engine, line, 300, 305, every=5)
    assert engine.status()["judging"]
    advance(engine, line, 305, 340, every=5)
    (event,) = store.of(OpenEvent)
    assert event.at == at(335)  # the mismatch delay started after the window


def test_a_scheduled_window_takes_effect_at_its_planned_start():
    engine, store, line = start()
    engine.set_control({}, [window("zones", 60, 600, ["P02.V1"])], at(5))
    advance(engine, line, 5, 40, every=5)
    line.set("P02.V1", setpoint=222)
    advance(engine, line, 40, 55, every=5)
    assert store.of(StartTimer, key=HMI_TIMER) and not store.of(OpenEvent)  # judged: the delay runs from 45
    advance(engine, line, 55, 120, every=5)
    assert not store.of(OpenEvent)  # at 60 the window started: the delay stopped before it would end at 75
    assert engine.status()["zones"]["P02.V1"]["control"]["state"] == "maintenance"
