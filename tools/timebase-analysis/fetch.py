"""Download raw history for every monitored tag in the parameter register.

    python fetch.py config.json 2026-09-22 2026-09-29

Dates are Asia/Manila calendar days (start inclusive, end exclusive); queries
run in UTC. Tags come from config/parameter-register.json: each active zone's
setpoint and actual, the SKU tag once it exists, and the context tags.

Output in data/raw/: one CSV per tag (t ISO UTC, v, q), gaps.csv listing spans
the server couldn't return, and manifest.json, which lets an interrupted
download resume. Tags are requested per machine area in groups, one window at a
time, so the historian never gets one huge query. Read-only.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))

import register as register_mod  # noqa: E402
from timebase import Gap, Sample, TimebaseClient, iso_z, parse_ts, utc  # noqa: E402

MANILA = timezone(timedelta(hours=8))
RAW = Path(__file__).parent / "data" / "raw"


def safe_name(tag: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in tag)


def load_config(path: str) -> tuple[dict, register_mod.Register]:
    cfg_path = Path(path).resolve()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    reg_path = cfg.get("register")
    reg = register_mod.load((cfg_path.parent / reg_path) if reg_path else None)
    return cfg, reg


def wanted_tags(reg: register_mod.Register) -> list[str]:
    return list(dict.fromkeys(reg.monitored_tags() + list(reg.context.values())))


class TagWriter:
    """Appends samples to a tag's CSV, keeping time strictly increasing."""

    def __init__(self, path: Path, fresh: bool):
        self.path = path
        self.last_t: datetime | None = None
        self.last_unknown = False
        if fresh or not path.exists():
            with path.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["t", "v", "q"])
        else:
            self._load_tail()
        self.f = path.open("a", newline="", encoding="utf-8")
        self.w = csv.writer(self.f)
        self.count = 0

    def _load_tail(self) -> None:
        with self.path.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            lines = [ln for ln in f.read().decode("utf-8", "replace").splitlines() if ln and not ln.startswith("t,")]
        if lines:
            row = next(csv.reader([lines[-1]]))
            self.last_t = parse_ts(row[0])
            self.last_unknown = row[1] == "" and int(row[2]) < 0

    def add(self, samples: list[Sample], window_start: int) -> None:
        for s in samples:
            if self.last_t is not None and s.t <= self.last_t:
                # A carry-in after an unreadable span is the value in force at the window start.
                if self.last_unknown and s.v is not None and utc(window_start) > self.last_t:
                    s = Sample(utc(window_start), s.v, s.q)
                else:
                    continue
            self.w.writerow([iso_z(s.t), "" if s.v is None else s.v, s.q])
            self.last_t, self.last_unknown = s.t, s.v is None
            self.count += 1

    def close(self) -> None:
        self.f.close()


def main(cfg_path: str, day_from: str, day_to: str) -> int:
    cfg, reg = load_config(cfg_path)
    tb = TimebaseClient(cfg)
    start = int(datetime.fromisoformat(day_from).replace(tzinfo=MANILA).timestamp())
    end = int(datetime.fromisoformat(day_to).replace(tzinfo=MANILA).timestamp())
    if end <= start:
        sys.exit("end date must be after start date")
    window = int(cfg.get("fetch_window_s", 3600))
    group_size = int(cfg.get("group_size", 10))
    min_window = int(cfg.get("min_window_s", 60))

    tags = wanted_tags(reg)
    known = tb.tag_names(contains=reg.namespace)
    missing = [t for t in tags if t not in known]
    for t in missing:
        print(f"WARNING: not in Timebase, skipped: {t}")
    tags = [t for t in tags if t in known]

    RAW.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    same_job = (manifest.get("from"), manifest.get("to"), manifest.get("tags")) == (iso_z(utc(start)), iso_z(utc(end)), tags)
    resume_at = int(manifest["done_until"]) if same_job and manifest.get("done_until") else start
    fresh = not same_job
    if fresh:
        (RAW / "gaps.csv").write_text("tag,from,to,reason\n", encoding="utf-8")
        manifest = {"from": iso_z(utc(start)), "to": iso_z(utc(end)), "tags": tags,
                    "missing_tags": missing, "register_version": reg.version, "done_until": start}
        manifest_path.write_text(json.dumps(manifest, indent=2))
    elif resume_at >= end:
        print("already downloaded")
        return 0
    else:
        print(f"resuming from {iso_z(utc(resume_at))}")

    writers = {t: TagWriter(RAW / f"{safe_name(t)}.csv", fresh) for t in tags}
    by_group: dict[str, list[str]] = {}
    for t in tags:
        by_group.setdefault(reg.group_of(t), []).append(t)
    chunks = [g[i:i + group_size] for g in by_group.values() for i in range(0, len(g), group_size)]

    total_windows = -(-(end - resume_at) // window)
    n_gaps = 0
    try:
        for i, w0 in enumerate(range(resume_at, end, window), 1):
            w1 = min(end, w0 + window)
            gaps: list[Gap] = []
            for chunk in chunks:
                for tag, samples in tb.read_window(chunk, w0, w1, min_window, gaps).items():
                    writers[tag].add(samples, w0)
            if gaps:
                n_gaps += len(gaps)
                with (RAW / "gaps.csv").open("a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerows([g.tag, iso_z(utc(g.start)), iso_z(utc(g.end)), g.reason] for g in gaps)
            for wr in writers.values():
                wr.f.flush()
            manifest["done_until"] = w1
            manifest_path.write_text(json.dumps(manifest, indent=2))
            if i % 24 == 0 or w1 == end:
                day = utc(w1).astimezone(MANILA).strftime("%Y-%m-%d %H:%M")
                print(f"  {i}/{total_windows} windows · up to {day} Manila · "
                      f"{sum(w.count for w in writers.values())} points · {n_gaps} unreadable spans")
    finally:
        for wr in writers.values():
            wr.close()
    print(f"done → {RAW}" + (f"  ({n_gaps} unreadable spans listed in gaps.csv)" if n_gaps else ""))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
