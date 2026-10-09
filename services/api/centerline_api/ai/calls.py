"""One call to the local model, checked and kept (AI-01, AI-02, DAT-01, ADR-0041, ADR-0042): the model answers JSON
held to a schema; `check` turns the answer into a result or says why it can't be used; every call is a row in
`ai_call`, used or not, with what was sent and what came back."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Callable

from centerline_common.db import uuid7

from . import ollama


def bare(digest: str) -> str:
    """A digest without its "sha256:" prefix: Ollama lists them bare, `ollama show` and the docs often don't."""
    return digest.removeprefix("sha256:")


def number(v) -> str:
    if v is None:
        return "—"
    return format(Decimal(str(v)).normalize(), "f")


def alarm_text(zone: dict, ev: dict) -> str:
    """The mismatch as the model reads it: zone, parameter, setpoint against target, raised or lowered."""
    unit = f" {zone['unit']}" if zone.get("unit") else ""
    way = ""
    if ev["raw_hmi"] is not None and ev["raw_target"] is not None and ev["raw_hmi"] != ev["raw_target"]:
        way = ": the setpoint was raised" if ev["raw_hmi"] > ev["raw_target"] else ": the setpoint was lowered"
    return (f"The alarm: HMI mismatch on {zone.get('zoneName') or ev['zone_id']} ({zone.get('parameterName') or ev['parameter_id']}). "
            f"The HMI setpoint is {number(ev['raw_hmi'])}{unit}; its target is {number(ev['raw_target'])}{unit}{way}.")


def run(settings, conn, request_id, purpose: str, version: str, system: str, user: str, schema: dict,
        check: Callable[[str], tuple[object, str | None]], section_ids: list, now) -> tuple[object, object]:
    """(the checked result or None, the call's id). The caller commits."""
    call = {"id": uuid7(), "digest": None, "raw": None, "outcome": "failed", "detail": None}
    result = None
    started = time.monotonic()
    try:
        call["digest"] = ollama.digest(settings)
        if call["digest"] is None:
            call["detail"] = f"the model {settings.model} isn't pulled on this host"
        elif settings.model_digest and bare(call["digest"]) != bare(settings.model_digest):
            call["detail"] = f"the installed {settings.model} isn't the pinned one ({bare(settings.model_digest)[:12]})"
        else:
            call["raw"] = ollama.chat(settings, system, user, schema)
            result, problem = check(call["raw"])
            call["outcome"], call["detail"] = ("used", None) if result else ("rejected", problem)
    except ollama.AiTimeout as e:
        call["outcome"], call["detail"] = "timeout", str(e)
    except ollama.AiUnavailable as e:
        call["detail"] = str(e)
    conn.execute("""INSERT INTO ai_call (id, request_id, purpose, model, model_digest, prompt_version, sections, prompt, raw_output,
                                         outcome, detail, latency_ms, at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                 (call["id"], request_id, purpose, settings.model, call["digest"], version, list(section_ids),
                  f"{system}\n\n---\n\n{user}", call["raw"], call["outcome"], call["detail"],
                  round((time.monotonic() - started) * 1000), now))
    return result, call["id"]
