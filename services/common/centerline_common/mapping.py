"""Tag mappings: where each register tag arrives on MQTT (ADR-0013). Pure functions, no I/O.

monitor-core subscribes to the connection's topic filters and reads each tag
from its place: a JSON field of the message on a topic, or the whole payload
when field is None. A mapping covers the register when every monitored zone's
setpoint and actual and every machine-state tag (Machine_Run, for the stop
pause) has a place. Only a mapping that covers the register can be activated.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Required:
    tag: str  # relative to the namespace, e.g. SPC.SetPointTemperatureVertical1
    kind: str  # setpoint | actual | context
    parameter_id: str | None
    parameter_name: str | None
    zone_id: str | None
    zone_name: str | None
    label: str


def relative(register, tag: str) -> str:
    ns = register.namespace
    return tag[len(ns) + 1:] if tag.startswith(ns + ".") else tag


def required(register) -> list[Required]:
    """The tags monitor-core needs, in register order: zones' setpoints and actuals, then machine state."""
    out, seen = [], set()
    for z in register.zones:
        for kind, tag in (("setpoint", z.setpoint), ("actual", z.actual)):
            rel = relative(register, tag)
            if rel not in seen:
                seen.add(rel)
                out.append(Required(rel, kind, z.parameter_id, z.parameter_name, z.zone_id, z.zone_name, f"{z.zone_name} {kind}"))
    for name, tag in register.context.items():
        rel = relative(register, tag)
        if rel not in seen:
            seen.add(rel)
            out.append(Required(rel, "context", None, None, None, None, name.replace("_", " ").capitalize()))
    return out


def topic_problem(topic: str | None) -> str | None:
    if not topic or topic != topic.strip():
        return "Enter the topic, without spaces around it"
    if "+" in topic or "#" in topic:
        return "Name one topic; + and # are for subscriptions, not mappings"
    if "\x00" in topic or len(topic.encode("utf-8")) > 65535:
        return "Not a valid MQTT topic"
    return None


def matches(topic_filter: str, topic: str) -> bool:
    """MQTT topic filter matching: + is one level, # is the rest (including the parent level)."""
    f, t = topic_filter.split("/"), topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(f) == len(t)


def validate(rows: list[dict], register, subscriptions: list[str]) -> tuple[list[dict], list[str]]:
    """Problems that stop a save ({field, message}, fields like rows[3].topic), and warnings that don't."""
    wanted = {r.tag for r in required(register)}
    errors: list[dict] = []
    warnings: list[str] = []
    tags: dict[str, int] = {}
    places: dict[tuple, int] = {}
    unheard: set[str] = set()
    for i, row in enumerate(rows):
        tag, topic, field = row["tag"], row.get("topic"), row.get("field")
        if tag not in wanted:
            errors.append({"field": f"rows[{i}].tag", "message": f"{tag} isn't a monitored or machine-state tag in the register"})
        elif tag in tags:
            errors.append({"field": f"rows[{i}].tag", "message": f"{tag} appears twice"})
        tags.setdefault(tag, i)
        if problem := topic_problem(topic):
            errors.append({"field": f"rows[{i}].topic", "message": problem})
            continue
        if field is not None and not field.strip():
            errors.append({"field": f"rows[{i}].field", "message": "Name the JSON field, or leave it empty for the whole payload"})
        place = (topic, field)
        if place in places:
            other = rows[places[place]]["tag"]
            errors.append({"field": f"rows[{i}].field",
                           "message": f"{tag} and {other} can't both come from {topic}{' · ' + field if field else ''}"})
        places.setdefault(place, i)
        if subscriptions and not any(matches(f, topic) for f in subscriptions):
            unheard.add(topic)
    warnings += [f"{t} isn't under the connection's topic filters, so nothing from it would arrive" for t in sorted(unheard)]
    return errors, warnings


def coverage(rows: list[dict], register) -> dict:
    """How many of the tags monitor-core needs have a place; missing ones as Required."""
    need = required(register)
    have = {r["tag"] for r in rows}
    missing = [r for r in need if r.tag not in have]
    return {"required": len(need), "mapped": len(need) - len(missing), "missing": missing}


def digest(rows: list[dict], legacy: dict | None = None) -> str:
    """SHA-256 of a version's content, stored with it and checked on every read. `legacy` is what a version saved
    before ADR-0027 recorded about a SKU ({"topic", "field"} or {"placeholder"}), so it keeps its fingerprint."""
    place = (None if not legacy else {"placeholder": legacy["placeholder"]} if "placeholder" in legacy
             else {"topic": legacy["topic"], "field": legacy["field"]})
    body = {"rows": sorted(({"tag": r["tag"], "topic": r["topic"], "field": r.get("field")} for r in rows), key=lambda r: r["tag"]),
            "sku": place}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- files ------------------------------------------------------------------------------


def from_topic_map(obj: dict, register) -> tuple[list[dict], list[str], list[str]]:
    """tools/mqtt-probe's topic-map.json → rows for the tags monitor-core needs, plus what was ignored and not seen."""
    wanted = {r.tag for r in required(register)}
    rows, ignored = [], []
    for full, place in (obj.get("tags") or {}).items():
        rel = relative(register, full)
        if rel in wanted:
            rows.append({"tag": rel, "topic": place["topic"], "field": place.get("field")})
        else:
            ignored.append(rel)
    not_seen = [relative(register, t) for t in obj.get("not_seen") or [] if relative(register, t) in wanted]
    return rows, sorted(ignored), not_seen


def from_csv(text: str) -> tuple[list[dict], list[dict]]:
    """A tag,topic,field file → rows, and problems as {line, message}."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    heads = [h.strip().lower() for h in reader.fieldnames or []]
    if heads[:3] != ["tag", "topic", "field"]:
        return [], [{"line": 1, "message": "The first line must be: tag,topic,field"}]
    rows, problems = [], []
    for n, raw in enumerate(reader, start=2):
        values = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        tag, topic, field = values.get("tag", ""), values.get("topic", ""), values.get("field") or None
        if not tag and not topic:
            continue
        if not tag or not topic:
            problems.append({"line": n, "message": "Each line needs a tag and a topic"})
        else:
            rows.append({"tag": tag, "topic": topic, "field": field})
    return rows, problems


def to_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["tag", "topic", "field"])
    for r in sorted(rows, key=lambda r: r["tag"]):
        w.writerow([r["tag"], r["topic"], r.get("field") or ""])
    return out.getvalue()
