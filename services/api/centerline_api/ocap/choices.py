"""Which HMI mismatches offer an OCAP row as a reason (ADR-0039).

An Excel OCAP's row that names a phenomenon can be picked as the reason for an HMI mismatch. When it's offered is
proposed from the file at upload, then checked by a Manager:
- the parameters: those whose distinctive name words its sealer, area or Centerline-name columns all contain
  ("Top / Bottom / Vertical" → Vertical, Bottom and Top Temperature);
- the direction: raised when its cause says the temperature was too low, lowered when too high, otherwise either.
"""

from __future__ import annotations

import re

DIRECTIONS = ("raised", "lowered", "either")
GENERIC = {"temperature", "temp", "time", "point", "speed", "setpoint", "actual", "the", "of"}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def parameters(register) -> list[dict]:
    """The parameters whose HMI setpoints are judged, in the register's order: those a mismatch can be raised for."""
    seen: dict[str, str] = {}
    for z in register.zones:
        seen.setdefault(z.parameter_id, z.parameter_name)
    return [{"id": pid, "name": name} for pid, name in seen.items()]


def propose(area: str | None, phenomenon: str | None, cause: str | None, params: list[dict]) -> tuple[list[str], str]:
    words = _words(area or phenomenon or "")
    ids = [p["id"] for p in params if (key := _words(p["name"]) - GENERIC) and key <= words]
    c = (cause or "").lower()
    low, high = "too low" in c, bool(re.search(r"too high|excessive heat|overheat", c))
    return ids, ("raised" if low and not high else "lowered" if high and not low else "either")


def direction_of(hmi, target) -> str | None:
    """How the HMI setpoint left its target."""
    if hmi is None or target is None or hmi == target:
        return None
    return "raised" if hmi > target else "lowered"
