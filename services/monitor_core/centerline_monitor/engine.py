"""monitor-core's judging loop (SDD §5). The clock and the store are passed in, so every
scenario runs without a broker or a database.

Each step (a message, a due timer, a connection change, an acknowledgment) runs the
snapshot gate, the stop pause and the zone state machines, then hands the store all their
effects at once. Time is our own arrival clock; the payload's _timestamp is kept only as
evidence (invariant 13).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from centerline_common.isotime import iso

from .config import EngineConfig
from .effects import (CancelTimer, Notify, OpenEvent, PauseEnded, PauseStarted, StartTimer, TimerDone, Transition,
                      ZoneRef)
from .gate import RULES_INCOMPLETE, Gate, GateInputs
from .machines import ActualMachine, HmiMachine, ZoneRule, text
from .rules import decimal
from .stoppause import StopPause

log = logging.getLogger("centerline.monitor")
MANILA = timezone(timedelta(hours=8))  # for the reasons people read; everything else is UTC


def number(raw) -> float | None:
    """A JSON number, or a true/false flag as 1/0; anything else isn't a valid reading."""
    if isinstance(raw, bool):
        return float(raw)
    if isinstance(raw, (int, float)) and math.isfinite(raw):
        return float(raw)
    return None


def _window(w: dict) -> dict:
    return {"window": str(w["id"]), "scope": w["scope"], "reason": w["reason"],
            "plannedStart": iso(w["planned_start"]), "plannedEnd": iso(w["planned_end"])}


SKEW_WARN_S = 5  # payload clock this far from ours: a warning on the health view (guide §6.1)


def _label(kind: str, channel: str, zone_name: str) -> str:
    return f"{'HMI mismatch' if kind == 'HMI_MISMATCH' else 'Actual'} on {channel} {zone_name}"


class Engine:
    def __init__(self, cfg: EngineConfig, store, now: datetime):
        self.store = store
        self.connected = False
        self.last_live: dict[str, datetime] = {}
        self.values: dict[str, float | None] = {}
        self.source_ts: dict[str, tuple[datetime, datetime]] = {}  # topic → (the payload's _timestamp, when it arrived)
        self.timers: dict[str, tuple[datetime, str, str]] = {}  # key → (due, kind, channel)
        self.hmi: dict[str, HmiMachine] = {}
        self.actual: dict[str, ActualMachine] = {}
        self.stop = StopPause()
        self.actual_paused = False
        self.gate: Gate | None = None
        self.reasons: list[str] = ["Starting: waiting for a complete, fresh snapshot"]
        self.rules_alerted = False  # Management told the rules are incomplete, once per pause (OPC-08)
        self.labels: dict = {}  # open event → "Actual on P06.N2 Nozzle 2", for the log
        self.zone_of: dict = {}  # open event → its zone, for the payload clock in its evidence
        self.arrived: dict[str, datetime] = {}  # tag → when its latest value arrived (our clock)
        # Monitoring control (ADR-0017), as the api stored it
        self.switched_off: dict[str, dict] = {}  # zone → the switch that turned it off (MON-01)
        self.windows: list[dict] = []  # maintenance windows not ended (MNT-01)
        self.held: dict[str, dict] = {}  # zone → the zone window in force on it
        self.line_window: dict | None = None  # a whole-line window in force
        self.waiting: dict[str, datetime] = {}  # zone back on: judged again on values that arrived after this (MNT-02)
        self.overdue_sent: set = set()
        self.degraded: str | None = None  # the database away past the journal's limit (RES-01)
        self.configure(cfg, now)
        self.gate.closed_since = now
        self._apply([PauseStarted("line", now, list(self.reasons))], now)

    # -- configuration --------------------------------------------------------------

    def configure(self, cfg: EngineConfig, now: datetime) -> None:
        """Take a new configuration. Machines keep their state; open events keep their pinned rules."""
        self.cfg = cfg
        self.zones = {z.channel: z for z in cfg.register.zones}
        for ch, z in self.zones.items():
            ref = ZoneRef(z.parameter_id, z.parameter_name, z.zone_id, z.zone_name, z.unit)
            self.hmi.setdefault(ch, HmiMachine(ref))
            self.actual.setdefault(ch, ActualMachine(ref))
        self.by_topic: dict[str, list[tuple[str, str | None]]] = {}
        for tag in cfg.needed_tags():
            if tag in cfg.mapping:
                topic, field = cfg.mapping[tag]
                self.by_topic.setdefault(topic, []).append((tag, field))
        previous = self.gate
        self.gate = Gate(cfg.topic_freshness(), cfg.needed_tags(), cfg.ready, cfg.blockers())
        if previous is not None:
            self.gate.open, self.gate.closed_since = previous.open, previous.closed_since
        pause = (cfg.settings or {}).get("pause_when_stopped") or {}
        self.stop.configure(bool(pause.get("enabled", True)), int(pause.get("long_stop_min", 10)), int(pause.get("warmup_min", 30)))
        if previous is not None:
            self._check(now)

    def restore(self, open_events: list[dict], now: datetime) -> None:
        """After a restart: open events continue under their pinned rules; delays start again from zero."""
        for e in open_events:
            ch = f"{e['parameter_id']}.{e['zone_id']}"
            if ch not in self.zones:
                continue
            rule = ZoneRule.from_pinned(e["rule"], e["versions"])
            self.labels[e["id"]] = _label(e["kind"], ch, self.zones[ch].zone_name)
            self.zone_of[e["id"]] = ch
            if e["kind"] == "HMI_MISMATCH":
                self.hmi[ch].restore(e["id"], rule, e["raw_hmi"])
            else:
                self.actual[ch].restore(e["id"], rule, e["severity"], e["acknowledged"], now,
                                        e.get("critical_periods", 0), e.get("repeats", 0), e.get("escalated", False))

    # -- inputs -----------------------------------------------------------------------

    def set_connected(self, connected: bool, now: datetime) -> None:
        self.connected = connected
        self._check(now)

    def on_message(self, topic: str, payload: bytes, retained: bool, now: datetime) -> None:
        if retained:
            return  # never counts as fresh (guide §6.2)
        places = self.by_topic.get(topic, [])
        if not places:
            return  # not a mapped topic (DFOS, for instance)
        try:
            obj = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            obj = None
        self.last_live[topic] = now
        fields = obj if isinstance(obj, dict) else {}
        stamp = fields.get("_timestamp")
        if isinstance(stamp, (int, float)) and math.isfinite(stamp):
            try:  # the machine's own clock (epoch ms): evidence only, never time (invariant 13)
                self.source_ts[topic] = (datetime.fromtimestamp(stamp / 1000, timezone.utc), now)
            except (OverflowError, OSError, ValueError):
                pass
        for tag, field in places:
            self.values[tag] = number(obj if field is None else fields.get(field))
            self.arrived[tag] = now
        self._check(now, touched=topic)

    def acknowledge(self, ack: dict, now: datetime) -> None:
        """A Manager's acknowledgment, as the api stored it (event_id, by_user, note, critical_period)."""
        fx = []
        for m in self.actual.values():
            fx += m.acknowledge(now, ack)
        self._apply(fx, now)

    def set_control(self, switched_off: dict[str, dict], windows: list[dict], now: datetime) -> None:
        """Zones switched off (MON-01) and maintenance windows not ended (MNT-01), as the api stored them.

        Switching off closes the zone's open event as "Monitoring disabled", with no recovery notice,
        and stops its delays and repeats. Switched on again, the zone is judged on fresh values only,
        its delays starting from zero (MNT-02)."""
        switched_off = {ch: s for ch, s in switched_off.items() if ch in self.zones}
        fx: list = []
        for ch in sorted(set(switched_off) - set(self.switched_off)):
            fx += self.hmi[ch].close(now, "CLOSED_MONITORING_DISABLED") + self.actual[ch].close(now, "CLOSED_MONITORING_DISABLED")
            self.waiting.pop(ch, None)
            log.info("monitoring switched off on %s: %s", ch, switched_off[ch].get("reason"))
        for ch in sorted(set(self.switched_off) - set(switched_off)):
            self.waiting[ch] = now
            log.info("monitoring switched on again on %s", ch)
        self.switched_off, self.windows = switched_off, windows
        self._apply(fx, now)
        self._maintenance(now)
        self._check(now, judge=False)

    def _maintenance(self, now: datetime) -> None:
        """Which windows are in force now, what that changes, and one overdue alert per window (MNT-01).

        A window is in force from its planned start until an Administrator ends it; past its planned
        end it stays in force, overdue, because the work may not be done. On its zones delays and
        repeats stop and open events stay open; a whole-line window closes the gate instead."""
        live = [w for w in self.windows if w["planned_start"] <= now]
        line = max((w for w in live if w["scope"] == "line"), key=lambda w: w["planned_end"], default=None)
        held: dict[str, dict] = {}
        for w in live:
            if w["scope"] == "zones":
                for ch in w["channels"]:
                    if ch in self.zones:
                        held.setdefault(ch, w)
        fx: list = []
        for ch in sorted(set(held) - set(self.held)):
            fx += self.hmi[ch].pause() + self.actual[ch].pause()
            self.waiting.pop(ch, None)
        for ch in sorted(set(self.held) - set(held)):
            if ch not in self.switched_off:
                self.waiting[ch] = now
        ended_line = self.line_window is not None and line is None
        self.held, self.line_window = held, line
        for w in live:
            if now > w["planned_end"] and w["id"] not in self.overdue_sent:
                self.overdue_sent.add(w["id"])
                fx.append(Notify(f"maintenance:{w['id']}:overdue", "system", now, {
                    "kind": "Maintenance overdue (MNT-01)", "window": str(w["id"]), "scope": w["scope"],
                    "zones": list(w["channels"]), "reason": w["reason"], "plannedEnd": iso(w["planned_end"])}))
                log.info("maintenance overdue: %s (planned to end %s)", w["reason"], w["planned_end"].isoformat())
        self._apply(fx, now)
        if ended_line and not self.gate.open:
            self.gate.closed_since = now  # only data from after the window counts (MNT-02)

    def set_degraded(self, reason: str | None, now: datetime) -> None:
        """The database has been away longer than the journal holds: the gate closes with the reason (RES-01)."""
        if reason != self.degraded:
            self.degraded = reason
            if reason:
                log.warning("%s", reason)
            self._check(now, judge=False)

    def _judged(self, ch: str) -> bool:
        return ch not in self.switched_off and ch not in self.held and ch not in self.waiting

    def tick(self, now: datetime) -> None:
        """Fire due timers in order, then re-check the gate: an area can go silent with no message at all."""
        for due, key in sorted((d, k) for k, (d, _, _) in self.timers.items() if d <= now):
            if key not in self.timers or self.timers[key][0] != due:
                continue  # cancelled or restarted by an earlier timer in this tick
            _, kind, ch = self.timers.pop(key)
            fx: list = [TimerDone(key, due)]
            if kind == "warmup_end":
                if self.stop.warmup_done(due):
                    fx += self._resume_actual(due)
            elif self.gate.open:
                rule = self._rule(ch)
                if kind == "hmi_delay" and rule and rule.target is not None:
                    fx += self.hmi[ch].on_timer(due, rule)
                elif kind.startswith("to_") and rule:
                    fx += self.actual[ch].on_timer(due, rule)
                elif kind in ("critical_repeat", "critical_escalation"):
                    fx += self.actual[ch].on_repeat(due)
            self._apply(fx, now)
        self._maintenance(now)
        self._check(now, judge=False)

    def next_due(self) -> datetime | None:
        return min((d for d, _, _ in self.timers.values()), default=None)

    # -- the step -----------------------------------------------------------------------

    def _inputs(self) -> GateInputs:
        return GateInputs(self.connected, self.last_live, self.values)

    def _rule(self, ch: str) -> ZoneRule | None:
        return self.cfg.zone_rule(self.zones[ch]) if ch in self.zones else None

    def _check(self, now: datetime, touched: str | None = None, judge: bool = True) -> None:
        """Open or close the gate; judge the zones touched by new values, or all of them on a fresh snapshot."""
        fx: list = []
        reasons = self.gate.reasons(now, self._inputs())
        if self.degraded:
            reasons.insert(0, self.degraded)
        if self.line_window is not None:
            w = self.line_window
            end = w["planned_end"].astimezone(MANILA).strftime("%H:%M")
            reasons.insert(0, f"Maintenance: {w['reason']} (planned to end {end} Manila)")
        if reasons:
            if self.gate.open:
                fx += self._close(now, reasons)
            # OPC-08 as ADR-0027 amends it: alert Management once when the data is complete but the rules aren't
            if reasons == [RULES_INCOMPLETE] and not self.rules_alerted:
                self.rules_alerted = True
                fx.append(Notify(f"rules:{now.isoformat()}", "system", now, {"reasons": reasons, "kind": "Rules incomplete (OPC-08)"}))
            self.reasons = reasons
        else:
            if not self.gate.open:
                fx += self._open(now)
                touched, judge = None, True  # a fresh snapshot: judge every zone
            if judge:
                fx += self._evaluate(now, touched)
        self._apply(fx, now)

    def _close(self, now: datetime, reasons: list[str]) -> list:
        self.gate.open, self.gate.closed_since = False, now
        fx: list = [PauseStarted("line", now, reasons)]
        for m in [*self.hmi.values(), *self.actual.values()]:
            fx += m.pause()
        log.info("paused: %s", "; ".join(reasons))
        return fx

    def _open(self, now: datetime) -> list:
        self.gate.open, self.reasons, self.rules_alerted = True, [], False
        fx: list = [PauseEnded("line", now)]
        if not self.actual_paused:
            for ch, m in self.actual.items():
                if self._judged(ch):
                    fx += m.resume(now)
        log.info("judging by rules v%s", self.cfg.rules_number)
        return fx

    def _evaluate(self, now: datetime, touched: str | None) -> list:
        fx = self._stop_pause(now)
        on_topic = {t for t, _ in self.by_topic.get(touched, [])} if touched else None
        for ch, z in self.zones.items():
            if ch in self.switched_off or ch in self.held:
                continue  # MON-01, MNT-01
            sp, act = self.cfg.rel(z.setpoint), self.cfg.rel(z.actual)
            if on_topic is not None and sp not in on_topic and act not in on_topic:
                continue
            rule = self._rule(ch)
            if rule is None:
                continue
            if ch in self.waiting:
                back = self.waiting[ch]
                if self.arrived.get(sp, back) <= back or self.arrived.get(act, back) <= back:
                    continue  # judged again only on values that arrived after it came back (MNT-02)
                del self.waiting[ch]
                if not self.actual_paused:
                    fx += self.actual[ch].resume(now)
            if rule.target is not None:  # a zone without a target isn't judged on HMI (ADR-0027)
                fx += self.hmi[ch].evaluate(now, self.values[sp], rule)
            if not self.actual_paused:
                fx += self.actual[ch].evaluate(now, self.values[act], self.values[sp], rule)
        return fx

    def _stop_pause(self, now: datetime) -> list:
        tag = self.cfg.machine_run_tag()
        change = self.stop.update(now, self.values.get(tag) if tag else None)
        if change == "pause":
            fx: list = [CancelTimer("line:warmup")] if "line:warmup" in self.timers else []  # stopped again in the warm-up
            if not self.actual_paused:
                self.actual_paused = True
                fx.append(PauseStarted("actual", now, ["The machine is stopped (ADR-0010)"]))
                for m in self.actual.values():
                    fx += m.pause()
            return fx
        if change == "warmup":
            return [StartTimer("line:warmup", "warmup_end", self.stop.warmup_until)]
        if change == "resume" and self.actual_paused:
            return self._resume_actual(now)
        return []

    def _resume_actual(self, now: datetime) -> list:
        self.actual_paused = False
        fx: list = [PauseEnded("actual", now)]
        for ch, m in self.actual.items():
            if self._judged(ch):
                fx += m.resume(now)
        return fx

    def _apply(self, fx: list, now: datetime) -> None:
        if not fx:
            return
        out = []
        for e in fx:
            if isinstance(e, StartTimer):
                self.timers[e.key] = (e.due, e.kind, e.key.rsplit(":", 1)[0])
            elif isinstance(e, CancelTimer):
                self.timers.pop(e.key, None)
            elif isinstance(e, OpenEvent):
                self.labels[e.event_id] = _label(e.kind, e.zone.channel, e.zone.zone_name)
                self.zone_of[e.event_id] = e.zone.channel
            elif isinstance(e, Transition):
                clock = self._payload_clock(self.zone_of.get(e.event_id)) if e.state != "ACKNOWLEDGED" else {}
                if clock:  # the machine's stamps on the messages its values came in, beside our own time
                    e = replace(e, inputs={**e.inputs, "payload_clock": clock})
                self._log(e)
                if not e.open:
                    self.zone_of.pop(e.event_id, None)
            out.append(e)
        self.store.apply(out, now)

    def _payload_clock(self, ch: str | None) -> dict:
        """Each of a zone's areas → the _timestamp of its latest message, as the machine stamped it (invariant 13)."""
        z = self.zones.get(ch) if ch else None
        out = {}
        for tag in (z.setpoint, z.actual) if z else ():
            place = self.cfg.mapping.get(self.cfg.rel(tag)) if tag else None
            if place and place[0] in self.source_ts:
                out[place[0]] = iso(self.source_ts[place[0]][0])
        return out

    def clock_skew(self) -> dict:
        """Each area → how far its payload clock is from ours: our arrival time minus the machine's stamp (guide §6.1)."""
        return {t: round((arrived - stamped).total_seconds(), 1) for t, (stamped, arrived) in sorted(self.source_ts.items())}

    def _log(self, t: Transition) -> None:
        """One line per change of state; the full record is in the database."""
        label = self.labels.get(t.event_id) if t.open else self.labels.pop(t.event_id, None)
        values = ", ".join(f"{name} {t.inputs[key]}" for key, name in (("actual", "actual"), ("hmi", "HMI"), ("target", "target"),
                                                                        ("acknowledged_by", "by"))
                           if t.inputs.get(key) is not None)
        log.info("%s: %s%s", label or f"event {t.event_id}", t.state, f" ({values})" if values else "")

    # -- what the page and the heartbeat show ---------------------------------------------

    def zone_names(self) -> dict:
        """(parameter, zone) → (parameter name, zone name, unit), for messages written outside the engine."""
        return {(z.parameter_id, z.zone_id): (z.parameter_name, z.zone_name, z.unit) for z in self.zones.values()}

    def _control_of(self, ch: str) -> dict | None:
        """Why a zone isn't judged right now, if it isn't (ADR-0017)."""
        if ch in self.switched_off:
            s = self.switched_off[ch]
            return {"state": "off", "since": iso(s["at"]), "by": s["by_user"], "reason": s["reason"]}
        if ch in self.held:
            return {"state": "maintenance", **_window(self.held[ch])}
        if self.line_window is not None:
            return {"state": "maintenance", **_window(self.line_window)}
        if ch in self.waiting:
            return {"state": "waiting", "since": iso(self.waiting[ch])}
        return None

    def status(self) -> dict:
        """What the heartbeat carries, and the Digital Centerline page shows: every zone's values and states."""
        zones = {}
        for ch, z in self.zones.items():
            h, a = self.hmi[ch], self.actual[ch]
            sp, act = self.values.get(self.cfg.rel(z.setpoint)), self.values.get(self.cfg.rel(z.actual))
            current = self._rule(ch)
            # Each check shows the rule it judges by: an open event's pinned rule wins (OPC-07)
            hmi_rule, actual_rule = h.rule or current, a.rule or current
            limits = actual_rule.limits if actual_rule else None
            due = lambda key: iso(self.timers[key][0]) if key in self.timers else None  # noqa: E731
            zones[ch] = {"setpoint": text(sp), "actual": text(act), "target": text(hmi_rule.target) if hmi_rule else None,
                         "bands": None if limits is None or sp is None else {
                             "warnLow": text(decimal(sp) - limits.warn_low), "warnHigh": text(decimal(sp) + limits.warn_high),
                             "critLow": text(decimal(sp) - limits.crit_low), "critHigh": text(decimal(sp) + limits.crit_high)},
                         # A zone with no target in the rules has its HMI setpoint unjudged (ADR-0027)
                         "hmi": "NO_TARGET" if hmi_rule is not None and hmi_rule.target is None else h.state,
                         "hmiSince": iso(h.since), "hmiDue": due(h.timer),
                         "hmiEvent": str(h.event_id) if h.event_id else None,
                         "actualSeverity": a.state.name, "actualPending": a.pending.name if a.pending else None,
                         "actualDue": due(a.timer), "actualEvent": str(a.event_id) if a.event_id else None,
                         "hmiRulesVersion": hmi_rule.rules_number if hmi_rule else None,
                         "actualRulesVersion": actual_rule.rules_number if actual_rule else None,
                         "control": self._control_of(ch)}
        # The machine's clock more than 5 s from ours: judging goes by ours, but the payload times in the evidence are off (O-18)
        skew = self.clock_skew()
        worst = max(skew.items(), key=lambda kv: abs(kv[1]), default=None)
        skew_warning = (f"The machine's clock is {abs(worst[1]):g} s {'behind' if worst[1] > 0 else 'ahead of'} ours "
                        f"on {worst[0].rsplit('/', 1)[-1]} (O-18)") if worst and abs(worst[1]) > SKEW_WARN_S else None
        return {"judging": self.gate.open, "reasons": self.reasons,
                "connected": self.connected, "actualPaused": self.actual_paused, "stop": self.stop.state,
                "warmupUntil": iso(self.stop.warmup_until),
                "rulesVersion": self.cfg.rules_number, "mappingVersion": self.cfg.mapping_number,
                "registerVersion": self.cfg.register.version, "zones": zones,
                "maintenance": [_window(w) for w in self.windows if w is self.line_window or w in self.held.values()],
                "lastLive": {t: iso(d) for t, d in self.last_live.items()},
                "clockSkewS": skew, "clockSkewWarning": skew_warning}
