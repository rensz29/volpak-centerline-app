"""The disk journal (RES-01, ADR-0018): steps that couldn't reach PostgreSQL, kept in order on disk.

While the database is away monitor-core keeps judging. Each step's effects are appended here as
one JSON line, flushed to disk before judging goes on. When the database is back the journal is
replayed in order, then emptied. Every write is safe to repeat (UUIDv7 keys, dedup keys), so a
replay cut short by a crash simply runs again, and a restart replays whatever the last run
left. The file and its folder are readable by monitor-core's user only.
"""

from __future__ import annotations

import dataclasses
import json
import os
import types
import typing
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from . import effects

TYPES = {cls.__name__: cls for cls in (effects.OpenEvent, effects.Transition, effects.BriefChange, effects.Notify,
                                       effects.StartTimer, effects.CancelTimer, effects.TimerDone, effects.PauseStarted,
                                       effects.PauseEnded)}
NESTED = {effects.Versions, effects.ZoneRef}


def _plain(v):
    if isinstance(v, UUID | Decimal):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if dataclasses.is_dataclass(v):
        return {f.name: _plain(getattr(v, f.name)) for f in dataclasses.fields(v)}
    return v


def encode(e) -> dict:
    return {"type": type(e).__name__, **_plain(e)}


def _unwrap(hint):
    """`UUID | None` → UUID; anything else as it is."""
    if typing.get_origin(hint) in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        return args[0] if len(args) == 1 else hint
    return hint


def _typed(hint, v):
    if v is None:
        return None
    base = _unwrap(hint)
    if base is UUID:
        return UUID(v)
    if base is datetime:
        return datetime.fromisoformat(v)
    if base is Decimal:
        return Decimal(v)
    if base in NESTED:
        return _build(base, v)
    return v


def _build(cls, d: dict):
    hints = typing.get_type_hints(cls)
    return cls(**{f.name: _typed(hints[f.name], d[f.name]) for f in dataclasses.fields(cls) if f.name in d})


def decode(d: dict):
    return _build(TYPES[d["type"]], d)


class Journal:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        self.steps, self.oldest = 0, None
        for _, at in self.entries():
            self.steps += 1
            self.oldest = self.oldest or at

    @property
    def pending(self) -> bool:
        return self.steps > 0

    def age_s(self, now: datetime) -> float:
        return 0.0 if self.oldest is None else (now - self.oldest).total_seconds()

    def append(self, fx: list, at: datetime) -> None:
        """One step, on disk before this returns."""
        line = json.dumps({"at": at.isoformat(), "effects": [encode(e) for e in fx]}, separators=(",", ":")) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        self.steps += 1
        self.oldest = self.oldest or at

    def entries(self):
        """The steps in the order they were made. A last line cut short by a crash was never on disk whole: skipped."""
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                try:
                    step = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield [decode(e) for e in step["effects"]], datetime.fromisoformat(step["at"])

    def clear(self) -> None:
        """Everything is in the database: start empty."""
        if self.path.exists():
            os.truncate(self.path, 0)
        self.steps, self.oldest = 0, None
