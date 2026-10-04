"""End-to-end check of probe → fetch → analyse against tests/mock_timebase.py.

    python tests/test_against_mock.py

Starts the mock, runs the three scripts into a temporary data folder, and
asserts on the results. Exit code 0 means every check passed.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
PORT = 45116


def run(*args: str) -> str:
    r = subprocess.run([sys.executable, *args], cwd=TOOL, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise SystemExit(f"{' '.join(args)} failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout


def main() -> int:
    data = TOOL / "data"
    backup = None
    if data.exists():
        backup = Path(tempfile.mkdtemp()) / "data"
        shutil.move(str(data), backup)
    mock = subprocess.Popen([sys.executable, str(HERE / "mock_timebase.py"), str(PORT)])
    failures = []

    def check(cond: bool, what: str) -> None:
        print(("PASS " if cond else "FAIL ") + what)
        if not cond:
            failures.append(what)

    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/datasets", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        cfg = Path(tempfile.mkdtemp()) / "config.json"
        cfg.write_text(json.dumps({"base_url": f"http://127.0.0.1:{PORT}", "dataset": "dressings",
                                   "auth": {"type": "none"},
                                   "register": str(HERE / "parameter-register.json")}))  # the register the mock was built for

        run("probe.py", str(cfg))
        probe = (data / "probe-report.md").read_text()
        check("| **NO** |" in probe and "SPC.Feed" in probe, "probe flags SPC.Feed as missing from Timebase")
        check("+164.7 s" in probe, "probe measures the payload clock offset")
        check("looks like a live value" in probe, "probe flags the flapping P09 setpoint")

        out = run("fetch.py", str(cfg), "2026-09-02", "2026-09-03")
        check("unreadable spans" in out, "fetch reports the unreadable span")
        with (data / "raw" / "gaps.csv").open() as f:
            gaps = list(csv.DictReader(f))
        check(len(gaps) >= 1 and all(g["tag"].endswith("SetPointTemperatureVertical1") for g in gaps),
              "every recorded gap is on Vertical 1 setpoint only")
        manifest = json.loads((data / "raw" / "manifest.json").read_text())
        check(len(manifest["tags"]) == 30, f"30 tags fetched (28 zone tags + 2 context), got {len(manifest['tags'])}")
        v1 = (data / "raw").glob("*SetPointTemperatureVertical1.csv")
        rows = list(csv.DictReader(next(v1).open()))
        check(any(r["v"] == "" and r["q"] == "-1" for r in rows), "unreadable marker written into the Vertical 1 series")
        times = [r["t"] for r in rows]
        check(times == sorted(times) and len(times) == len(set(times)), "Vertical 1 series strictly increasing")

        out2 = run("fetch.py", str(cfg), "2026-09-02", "2026-09-03")
        check("already downloaded" in out2, "re-running fetch resumes instead of downloading again")

        run("analyse_delays.py", str(cfg))
        rep = (data / "delay-report.md").read_text()
        check("No SKU tag yet" in rep, "analysis runs per shift without a SKU tag")
        check("Unreadable in Timebase: `SPC.SetPointTemperatureVertical1`" in rep, "analysis lists the unreadable span")
        check("behaves like a live value" in rep, "analysis flags P09's live-looking setpoint")
        line = next(ln for ln in rep.splitlines() if ln.startswith("Suggested global default"))
        check("**60 s**" in line, f"brief changes of 5–40 s give a 60 s suggestion: {line}")
    finally:
        mock.terminate()
        if data.exists():
            shutil.rmtree(data)
        if backup:
            shutil.move(str(backup), data)
    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
