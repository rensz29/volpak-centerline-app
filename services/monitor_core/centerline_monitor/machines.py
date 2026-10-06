"""The state machines for one zone, as in the SDD's diagrams. Pure: the engine passes the
time and the rule, and applies the effects they return.

HMI mismatch (HMI-01…05): At target → Pending (the mismatch delay runs) → Event open →
Resolved, with a recovery notice. A new off-target integer always restarts the delay;
while an event is open, it closes that event as Superseded and the next event links back
to it (HMI-03). Back at target before the delay ends is a brief change, recorded per the
rules' mode and never notified (HMI-04, HMI-05).

Actual severity (ACT-01…04): Normal, Warning and Critical; every change waits for its own
delay (Warning, Critical, the Warning delay again for Critical → Warning, and Recovery
back to Normal). A Critical always notifies, repeats every 15 min four times and escalates
once more at +75 min (A-03), until a Manager acknowledges it.

While an event is open it's judged by the rule it opened under (OPC-07). A pause stops
the timers; open events stay open, and the delays restart from zero afterwards (MNT-02).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from centerline_common.db import uuid7
from centerline_common.isotime import iso
from centerline_common.register import HmiMatch

from .effects import BriefChange, CancelTimer, Notify, OpenEvent, StartTimer, Transition, Versions, ZoneRef
from .rules import Limits, Severity, classify, decimal

REPEAT_EVERY = timedelta(minutes=15)  # ACT-04
REPEATS = 4  # then one final escalation, 75 min after the Critical began (A-03)
TRACE_LIMIT = 500  # values kept for a cleared-before-trigger record


def text(v) -> str | None:
    return None if v is None else format(decimal(v).normalize(), "f")


@dataclass(frozen=True)
class ZoneRule:
    """One zone's rule, resolved from the rules version in effect."""

    target: Decimal | None  # None when the rules give the zone no target: its HMI setpoint isn't judged (ADR-0027)
    limits: Limits
    mismatch_delay_s: int
    warning_delay_s: int
    critical_delay_s: int
    recovery_delay_s: int
    brief_change_mode: str
    warning_notifications: bool
    match: HmiMatch
    versions: Versions
    rules_number: int | None = None

    def pinned(self) -> dict:
        """Stored with an event, so it can be judged by the same rule after a restart."""
        return {"target": text(self.target), "rules_version": self.rules_number,
                "limits": {k: text(getattr(self.limits, k)) for k in ("warn_low", "warn_high", "crit_low", "crit_high")},
                "delays_s": {"mismatch": self.mismatch_delay_s, "warning": self.warning_delay_s,
                             "critical": self.critical_delay_s, "recovery": self.recovery_delay_s},
                "brief_change_mode": self.brief_change_mode, "warning_notifications": self.warning_notifications,
                "hmi_match": {"method": self.match.method, "decimals": self.match.decimals}}

    @classmethod
    def from_pinned(cls, d: dict, versions: Versions) -> ZoneRule:
        lim, dl = d["limits"], d["delays_s"]
        # Events pinned before ADR-0027 also carry their SKU: it's evidence, and judges nothing now
        return cls(target=None if d.get("target") is None else Decimal(d["target"]), rules_number=d.get("rules_version"),
                   limits=Limits(*(Decimal(lim[k]) for k in ("warn_low", "warn_high", "crit_low", "crit_high"))),
                   mismatch_delay_s=dl["mismatch"], warning_delay_s=dl["warning"], critical_delay_s=dl["critical"],
                   recovery_delay_s=dl["recovery"], brief_change_mode=d["brief_change_mode"],
                   warning_notifications=d["warning_notifications"],
                   match=HmiMatch(d["hmi_match"]["method"], int(d["hmi_match"]["decimals"])), versions=versions)


def _payload(zone: ZoneRef, rule: ZoneRule, **values) -> dict:
    return {"parameter": zone.parameter_id, "parameterName": zone.parameter_name, "zone": zone.zone_id,
            "zoneName": zone.zone_name, "unit": zone.unit,
            **{k: text(v) if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) else v
               for k, v in values.items()}}


class HmiMachine:
    def __init__(self, zone: ZoneRef):
        self.zone = zone
        self.timer = f"{zone.channel}:hmi"
        self.state = "AT_TARGET"  # AT_TARGET | PENDING | OPEN
        self.key: int | None = None  # the off-target whole number being timed, or the open event's
        self.since: datetime | None = None
        self.last: Decimal | None = None
        self.trace: list[tuple[str, str]] = []
        self.event_id = None
        self.rule: ZoneRule | None = None  # pinned while an event is open
        self.superseded = None  # the event the next one will supersede

    def _pend(self, now: datetime, key: int, rule: ZoneRule) -> list:
        self.state, self.key, self.since = "PENDING", key, now
        self.trace = [(iso(now), text(self.last))]
        return [StartTimer(self.timer, "hmi_delay", now + timedelta(seconds=rule.mismatch_delay_s))]

    def evaluate(self, now: datetime, hmi, rule: ZoneRule) -> list:
        r = self.rule or rule
        self.last = decimal(hmi)
        key, at_target = r.match.key(self.last), r.match.key(self.last) == r.match.key(r.target)
        fx: list = []
        if self.state == "AT_TARGET":
            if not at_target:
                fx += self._pend(now, key, r)
        elif self.state == "PENDING":
            if len(self.trace) < TRACE_LIMIT:
                self.trace.append((iso(now), text(self.last)))
            if at_target:
                fx.append(CancelTimer(self.timer))
                if r.brief_change_mode != "do_not_record":
                    fx.append(BriefChange(uuid7(), self.zone, r.brief_change_mode, self.since, now, r.versions,
                                          r.target, self.trace[0][1] and Decimal(self.trace[0][1]),
                                          {"values": self.trace} if r.brief_change_mode == "cleared_before_trigger" else None))
                self._reset()
            elif key != self.key:
                fx += [CancelTimer(self.timer), *self._pend(now, key, r)]  # a new off-target value restarts the delay
        elif self.state == "OPEN":
            if at_target:
                fx += [Transition(self.event_id, "RESOLVED", now, {"hmi": text(self.last), "target": text(r.target)}, open=False),
                       Notify(f"{self.event_id}:recovery", "recovery", now, _payload(self.zone, r, hmi=self.last, target=r.target),
                              self.event_id)]
                self._reset()
            elif key != self.key:
                fx.append(Transition(self.event_id, "SUPERSEDED", now, {"hmi": text(self.last), "target": text(r.target)},
                                     open=False))
                self.superseded, self.event_id, self.rule = self.event_id, None, None
                fx += self._pend(now, key, rule)  # the next event is judged by the rule in effect now
        return fx

    def on_timer(self, now: datetime, rule: ZoneRule) -> list:
        if self.state != "PENDING":
            return []
        eid = uuid7()
        inputs = {"hmi": text(self.last), "target": text(rule.target), "pending_since": iso(self.since)}
        fx = [OpenEvent(eid, "HMI_MISMATCH", self.zone, now, rule.versions, rule.pinned(),
                        raw_target=rule.target, raw_hmi=self.last, supersedes=self.superseded),
              Transition(eid, "OPEN", now, inputs),
              Notify(f"{eid}:initial", "initial", now,
                     _payload(self.zone, rule, kind="HMI mismatch", hmi=self.last, target=rule.target,
                              supersedes=str(self.superseded) if self.superseded else None), eid)]
        self.state, self.event_id, self.rule, self.superseded = "OPEN", eid, rule, None
        return fx

    def pause(self) -> list:
        """Timers stop; an open event stays open (OPC-03). A pending delay starts again later from zero."""
        if self.state == "PENDING":
            self.state, self.key, self.since = "AT_TARGET", None, None
            return [CancelTimer(self.timer)]
        return []

    def close(self, now: datetime, state: str) -> list:
        """End whatever is going on without a recovery notice: monitoring switched off (CLOSED_MONITORING_DISABLED, MON-01)."""
        fx = []
        if self.state == "OPEN":
            fx.append(Transition(self.event_id, state, now, {"hmi": text(self.last)}, open=False))
        elif self.state == "PENDING":
            fx.append(CancelTimer(self.timer))
        self._reset()
        self.superseded = None
        return fx

    def restore(self, event_id, rule: ZoneRule, hmi) -> None:
        """After a restart: the open event continues, judged by its pinned rule."""
        self.state, self.event_id, self.rule, self.last = "OPEN", event_id, rule, decimal(hmi)
        self.key = rule.match.key(self.last)

    def _reset(self) -> None:
        self.state, self.key, self.since, self.trace, self.event_id, self.rule = "AT_TARGET", None, None, [], None, None


class ActualMachine:
    def __init__(self, zone: ZoneRef):
        self.zone = zone
        self.timer = f"{zone.channel}:actual"
        self.repeat_timer = f"{zone.channel}:critical"
        self.state = Severity.NORMAL
        self.pending: Severity | None = None
        self.event_id = None
        self.rule: ZoneRule | None = None
        self.notified = False  # anything sent for this event, so a recovery notice makes sense
        self.critical_period = 0
        self.critical_since: datetime | None = None
        self.repeats = 0  # repeats sent in this Critical period
        self.escalated = False
        self.acknowledged = False
        self.last: tuple[Decimal, Decimal] | None = None

    @staticmethod
    def _delay(to: Severity, rule: ZoneRule) -> int:
        if to == Severity.NORMAL:
            return rule.recovery_delay_s
        if to == Severity.CRITICAL:
            return rule.critical_delay_s
        return rule.warning_delay_s  # Normal → Warning, and the Critical → Warning downgrade (ACT-02)

    def _inputs(self, band: Severity | None = None) -> dict:
        actual, hmi = self.last or (None, None)
        return {"actual": text(actual), "hmi": text(hmi), **({"band": band.name} if band is not None else {})}

    def evaluate(self, now: datetime, actual, hmi, rule: ZoneRule) -> list:
        r = self.rule or rule
        self.last = (decimal(actual), decimal(hmi))
        band = classify(actual, hmi, r.limits)
        fx: list = []
        if band == self.state:
            if self.pending is not None:
                fx.append(CancelTimer(self.timer))
                self.pending = None
            return fx
        if band == self.pending:
            return fx
        if self.pending is not None:
            fx.append(CancelTimer(self.timer))
        self.pending = band
        fx.append(StartTimer(self.timer, f"to_{band.name.lower()}", now + timedelta(seconds=self._delay(band, r)), self.event_id))
        return fx

    def on_timer(self, now: datetime, rule: ZoneRule) -> list:
        if self.pending is None:
            return []
        old, new = self.state, self.pending
        self.pending = None
        fx: list = []
        if old == Severity.NORMAL:
            eid, r = uuid7(), rule
            actual, hmi = self.last
            fx += [OpenEvent(eid, "ACTUAL", self.zone, now, r.versions, r.pinned(), raw_target=r.target,
                             raw_hmi=hmi, raw_actual=actual, severity=new.name),
                   Transition(eid, new.name, now, self._inputs(new), severity=new.name)]
            self.event_id, self.rule, self.state = eid, r, new
            if new == Severity.CRITICAL or r.warning_notifications:
                fx.append(Notify(f"{eid}:initial", "initial", now,
                                 _payload(self.zone, r, kind=f"Actual {new.name.title()}", actual=actual, hmi=hmi), eid))
                self.notified = True
            if new == Severity.CRITICAL:
                fx += self._critical(now)
        elif new == Severity.NORMAL:
            r = self.rule or rule
            fx.append(Transition(self.event_id, "RESOLVED", now, self._inputs(new), open=False))
            if self.notified:
                actual, hmi = self.last
                fx.append(Notify(f"{self.event_id}:recovery", "recovery", now, _payload(self.zone, r, actual=actual, hmi=hmi),
                                 self.event_id))
            fx += self._stop_repeats()
            self._reset()
        else:
            r = self.rule or rule
            fx.append(Transition(self.event_id, new.name, now, self._inputs(new), severity=new.name))
            self.state = new
            if new == Severity.CRITICAL:
                actual, hmi = self.last
                fx.append(Notify(f"{self.event_id}:critical:{self.critical_period + 1}", "escalated", now,
                                 _payload(self.zone, r, kind="Actual Critical", actual=actual, hmi=hmi), self.event_id))
                self.notified = True
                fx += self._critical(now)
            else:
                fx += self._stop_repeats()
        return fx

    def _critical(self, now: datetime) -> list:
        self.critical_period += 1
        self.critical_since, self.repeats, self.escalated, self.acknowledged = now, 0, False, False
        return [StartTimer(self.repeat_timer, "critical_repeat", now + REPEAT_EVERY, self.event_id)]

    def _stop_repeats(self) -> list:
        had = self.critical_since is not None and not self.escalated and not self.acknowledged
        self.critical_since = None
        return [CancelTimer(self.repeat_timer)] if had else []

    def on_repeat(self, now: datetime) -> list:
        """A Critical still unacknowledged: repeat, or after four repeats escalate once more."""
        if self.state != Severity.CRITICAL or self.acknowledged or self.escalated or self.critical_since is None:
            return []
        r = self.rule
        actual, hmi = self.last
        base = f"{self.event_id}:critical:{self.critical_period}"
        if self.repeats < REPEATS:
            self.repeats += 1
            return [Notify(f"{base}:repeat:{self.repeats}", "critical_repeat", now,
                           _payload(self.zone, r, repeat=self.repeats, actual=actual, hmi=hmi), self.event_id),
                    StartTimer(self.repeat_timer, "critical_repeat" if self.repeats < REPEATS else "critical_escalation",
                               now + REPEAT_EVERY, self.event_id)]
        self.escalated = True
        return [Notify(f"{base}:escalation", "critical_escalation", now, _payload(self.zone, r, actual=actual, hmi=hmi),
                       self.event_id)]

    def acknowledge(self, now: datetime, ack: dict) -> list:
        """A Manager's acknowledgment stops the Critical's repeats (ACT-04). It counts only for the Critical
        period it was given in: after a downgrade and a new Critical, the new period needs its own."""
        if ack["event_id"] != self.event_id or self.acknowledged:
            return []
        period = ack.get("critical_period")
        if period is not None and period != self.critical_period:
            return []
        self.acknowledged = True
        fx = [Transition(self.event_id, "ACKNOWLEDGED", now,
                         {"acknowledged_by": ack.get("by_user"), "note": ack.get("note")}, severity=self.state.name)]
        if self.state == Severity.CRITICAL and not self.escalated:
            fx.append(CancelTimer(self.repeat_timer))
        return fx

    def pause(self) -> list:
        """Timers stop, repeats too; the event stays open (OPC-03, ADR-0010)."""
        fx = []
        if self.pending is not None:
            fx.append(CancelTimer(self.timer))
            self.pending = None
        if self.state == Severity.CRITICAL and self.critical_since is not None and not self.escalated and not self.acknowledged:
            fx.append(CancelTimer(self.repeat_timer))
        return fx

    def resume(self, now: datetime) -> list:
        """An unacknowledged Critical's next repeat restarts from zero (MNT-02), keeping its count."""
        if self.state == Severity.CRITICAL and self.critical_since is not None and not self.escalated and not self.acknowledged:
            return [StartTimer(self.repeat_timer, "critical_repeat" if self.repeats < REPEATS else "critical_escalation",
                               now + REPEAT_EVERY, self.event_id)]
        return []

    def close(self, now: datetime, state: str) -> list:
        """End the event without a recovery notice, stopping its delays and repeats (ADR-0001, MON-01)."""
        fx = self.pause()
        if self.event_id is not None:
            fx.append(Transition(self.event_id, state, now, self._inputs(), open=False))
        self._reset()
        return fx

    def restore(self, event_id, rule: ZoneRule, severity: str, acknowledged: bool, now: datetime,
                critical_periods: int = 0, repeats: int = 0, escalated: bool = False) -> None:
        """After a restart: the open event continues under its pinned rule. A Critical carries on
        counting from the repeats already sent, so none is sent twice and none is lost."""
        self.event_id, self.rule, self.state, self.notified = event_id, rule, Severity[severity], True
        self.acknowledged, self.critical_period = acknowledged, critical_periods
        if self.state == Severity.CRITICAL:
            self.critical_since, self.repeats, self.escalated = now, repeats, escalated

    def _reset(self) -> None:
        self.state, self.pending, self.event_id, self.rule, self.notified = Severity.NORMAL, None, None, None, False
        self.critical_since, self.repeats, self.escalated, self.acknowledged = None, 0, False, False
