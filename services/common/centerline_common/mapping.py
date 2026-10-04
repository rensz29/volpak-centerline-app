"""Tag mappings: where each register tag arrives on MQTT (ADR-0013). Pure functions, no I/O.

monitor-core subscribes to the connection's topic filters and reads each tag
from its place: a JSON field of the message on a topic, or the whole payload
when field is None. A mapping covers the register when every monitored zone's
setpoint and actual and every machine-state tag (Machine_Run, for the stop
pause) has a place. Only a mapping that covers the register can be activated.

The SKU comes from a field on a topic ({"topic", "field"}). While the machine publishes none
(O-15), a placeholder code can stand in ({"placeholder"}): monitor-core then judges actual
values only (ADR-0022).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass

SKU_ROW = "SKU"  # the SKU field's row in a CSV file; no register tag is called that
SKU_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,39}")  # as on the Rules tab's SKU list


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


def validate(rows: list[dict], sku: dict | None, register, subscriptions: list[str]) -> tuple[list[dict], list[str]]:
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
    if sku and "placeholder" in sku:
        code = sku["placeholder"]
        if "topic" in sku:
            errors.append({"field": "skuPlaceholder", "message": "Either the machine's SKU field or a placeholder, not both"})
        elif not SKU_CODE.fullmatch(code or ""):
            errors.append({"field": "skuPlaceholder",
                           "message": "Up to 40 letters, digits, '.', '_', '/' or '-', starting with a letter or digit"})
        else:
            warnings.append(f"Placeholder SKU {code}: only actual values are judged, and HMI mismatch waits for the "
                            "machine's SKU field and its targets (O-15, ADR-0022)")
    elif sku:
        if problem := topic_problem(sku.get("topic")):
            errors.append({"field": "sku.topic", "message": problem})
        elif subscriptions and not any(matches(f, sku["topic"]) for f in subscriptions):
            unheard.add(sku["topic"])
        if not (sku.get("field") or "").strip():
            errors.append({"field": "sku.field", "message": "Name the JSON field that carries the SKU"})
    else:
        warnings.append("No SKU field yet: on the real machine, monitoring pauses until one is mapped "
                        "or a placeholder is set (OPC-08, O-15)")
    warnings += [f"{t} isn't under the connection's topic filters, so nothing from it would arrive" for t in sorted(unheard)]
    return errors, warnings


def coverage(rows: list[dict], register) -> dict:
    """How many of the tags monitor-core needs have a place; missing ones as Required."""
    need = required(register)
    have = {r["tag"] for r in rows}
    missing = [r for r in need if r.tag not in have]
    return {"required": len(need), "mapped": len(need) - len(missing), "missing": missing}


def digest(rows: list[dict], sku: dict | None) -> str:
    """SHA-256 of a version's content, stored with it and checked on every read."""
    place = (None if not sku else {"placeholder": sku["placeholder"]} if "placeholder" in sku
             else {"topic": sku["topic"], "field": sku["field"]})  # versions before ADR-0022 hash as they did
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


def from_csv(text: str) -> tuple[list[dict], dict | None, list[dict]]:
    """A tag,topic,field file → rows, the SKU row if any, and problems as {line, message}."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    heads = [h.strip().lower() for h in reader.fieldnames or []]
    if heads[:3] != ["tag", "topic", "field"]:
        return [], None, [{"line": 1, "message": "The first line must be: tag,topic,field"}]
    rows, sku, problems = [], None, []
    for n, raw in enumerate(reader, start=2):
        values = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        tag, topic, field = values.get("tag", ""), values.get("topic", ""), values.get("field") or None
        if not tag and not topic:
            continue
        if not tag or not topic:
            problems.append({"line": n, "message": "Each line needs a tag and a topic"})
        elif tag == SKU_ROW:
            sku = {"topic": topic, "field": field}
        else:
            rows.append({"tag": tag, "topic": topic, "field": field})
    return rows, sku, problems


def to_csv(rows: list[dict], sku: dict | None) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["tag", "topic", "field"])
    for r in sorted(rows, key=lambda r: r["tag"]):
        w.writerow([r["tag"], r["topic"], r.get("field") or ""])
    if sku and "topic" in sku:  # a placeholder isn't a place on the broker, so the file leaves it out
        w.writerow([SKU_ROW, sku["topic"], sku["field"]])
    return out.getvalue()
