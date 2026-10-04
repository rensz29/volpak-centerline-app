"""Notification routing (ADR-0023): who gets which messages, on which channel. Pure functions, no I/O.

A routing version is a list of rules {name, types, channel, targets}. Each notification has
one type, from its kind and what it says. Every rule listing that type sends it to each of
its targets on its channel. The SDD matches line × type × severity × channel: there is one
line today, and the severity is part of the type (an Actual Warning, an Actual Critical).
"""

from __future__ import annotations

import hashlib
import json
import re

# code → label, in the order the page lists them
TYPES = {
    "hmi_mismatch": "HMI mismatch",
    "actual_warning": "Actual Warning",
    "actual_critical": "Actual Critical",
    "critical_repeat": "Critical reminder (every 15 min)",
    "critical_escalation": "Critical escalation (75 min)",
    "recovery": "Back to normal",
    "changeover": "SKU changeover",
    "reason_overdue": "Reason overdue (15 min)",
    "system": "System alert",
}
CRITICAL = ("actual_critical", "critical_repeat", "critical_escalation")  # can't be switched off (ACT-03)
CHANNELS = {"teams": "Teams", "email": "Email"}
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PLACEHOLDER_DOMAINS = (".invalid", ".example", "example.com", "example.org", "example.net")
MAX_RULES, MAX_TARGETS = 50, 50

_INITIAL = {"HMI mismatch": "hmi_mismatch", "Actual Warning": "actual_warning", "Actual Critical": "actual_critical"}
_KINDS = {"escalated": "actual_critical", "critical_repeat": "critical_repeat", "critical_escalation": "critical_escalation",
          "recovery": "recovery", "superseded": "hmi_mismatch", "changeover": "changeover", "system": "system", "test": "test",
          "workflow_escalation": "reason_overdue"}


def type_of(kind: str, payload: dict) -> str:
    """A notification's routing type, from the outbox row monitor-core wrote."""
    if kind == "initial":
        return _INITIAL.get(payload.get("kind", ""), "system")
    return _KINDS.get(kind, "system")


def normalize(rules: list[dict]) -> list[dict]:
    """Trimmed, in a fixed order, so equal routings hash the same."""
    out = []
    for r in rules:
        types = [t for t in TYPES if t in set(r.get("types") or [])]
        out.append({"name": (r.get("name") or "").strip(), "types": types, "channel": r.get("channel"),
                    "targets": [t.strip() for t in r.get("targets") or [] if t and t.strip()]})
    return out


def validate(rules: list[dict]) -> list[dict]:
    """Problems that stop a version being saved, as {field, message} with fields like rules[2].targets."""
    errors: list[dict] = []
    if len(rules) > MAX_RULES:
        errors.append({"field": "rules", "message": f"At most {MAX_RULES} rules"})
    names: dict[str, int] = {}
    for i, r in enumerate(rules):
        name = r["name"]
        if not name:
            errors.append({"field": f"rules[{i}].name", "message": "Name the rule, e.g. Management by email"})
        elif len(name) > 80:
            errors.append({"field": f"rules[{i}].name", "message": "At most 80 characters"})
        elif name.lower() in names:
            errors.append({"field": f"rules[{i}].name", "message": f"Rule {names[name.lower()] + 1} has the same name"})
        names.setdefault(name.lower(), i)
        if not r["types"]:
            errors.append({"field": f"rules[{i}].types", "message": "Pick at least one kind of message"})
        if r["channel"] not in CHANNELS:
            errors.append({"field": f"rules[{i}].channel", "message": "Teams or Email"})
        targets = r["targets"]
        if not targets:
            errors.append({"field": f"rules[{i}].targets", "message": "Add at least one recipient"})
        elif len(targets) > MAX_TARGETS:
            errors.append({"field": f"rules[{i}].targets", "message": f"At most {MAX_TARGETS} recipients"})
        seen = set()
        for t in targets:
            if len(t) > 200:
                errors.append({"field": f"rules[{i}].targets", "message": "A recipient has more than 200 characters"})
            elif r["channel"] == "email" and not EMAIL.fullmatch(t):
                errors.append({"field": f"rules[{i}].targets", "message": f"{t} isn't an email address"})
            elif t.lower() in seen:
                errors.append({"field": f"rules[{i}].targets", "message": f"{t} is listed twice"})
            seen.add(t.lower())
    return errors


def critical_gaps(rules: list[dict]) -> list[str]:
    """The Critical types no rule sends anywhere: a version with any can't be activated (ACT-03)."""
    sent = {t for r in rules if r["targets"] for t in r["types"]}
    return [t for t in CRITICAL if t not in sent]


def warnings(rules: list[dict]) -> list[str]:
    out = []
    if gaps := critical_gaps(rules):
        out.append("Critical alerts must reach someone before this can be activated (ACT-03): "
                   + ", ".join(TYPES[t] for t in gaps))
    unsent = [label for t, label in TYPES.items() if not any(t in r["types"] for r in rules)]
    if unsent and len(unsent) < len(TYPES):
        out.append("Not sent to anyone: " + ", ".join(unsent))
    placeholders = sorted({t for r in rules if r["channel"] == "email" for t in r["targets"]
                           if t.lower().endswith(PLACEHOLDER_DOMAINS)})
    if placeholders:
        out.append(f"Placeholder addresses nothing will reach: {', '.join(placeholders)} (O-05)")
    return out


def digest(rules: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rules, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def match(rules: list[dict], type_: str) -> list[tuple[str, str, str]]:
    """(rule, channel, target) for each place the routing sends this type, each channel × target once."""
    out, seen = [], set()
    for r in rules:
        if type_ in r["types"]:
            for t in r["targets"]:
                key = (r["channel"], t.lower())
                if key not in seen:
                    seen.add(key)
                    out.append((r["name"], r["channel"], t))
    return out
