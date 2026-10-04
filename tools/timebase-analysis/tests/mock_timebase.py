"""Mock of the plant Timebase API, reproducing the quirks probed on 2026-09-29.

    python tests/mock_timebase.py [port]

* `{"s","e","tl":[...]}` envelope, carry-in point at the window start, store-on-change values
* tag listing as `{"User": [...], "System": []}`
* unknown tag → HTTP 404 `Error.TagNotFound` for the whole request
* one unreadable span for Vertical 1 setpoint: HTTP 500 alone, truncated body when mixed with other tags
* `_timestamp` per machine area with the payload clock 164.74 s ahead
* HTTP `Date` header at the synthetic "now" (end of the generated day)

Data: one synthetic day from 2026-09-02 00:00 Manila for every active zone in
config/parameter-register.json. Setpoints hold a target with 20 brief changes
(5–40 s) and 3 long ones (20 min) per zone; P09's setpoint flips 1 ↔ 0.99
every 1–3 s like the real one.
"""

from __future__ import annotations

import json
import random
import socket
import sys
from datetime import datetime, timedelta, timezone
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
import register  # noqa: E402

T0 = int(datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc).timestamp())  # 2026-09-02 00:00 Manila
N = 86400
NOW = T0 + N
SKEW_S = 164.74
REG = register.load()
NS = REG.namespace
BAD_TAG = f"{NS}.SPC.SetPointTemperatureVertical1"
BAD_SPAN = (T0 + 7 * 3600 + 600, T0 + 7 * 3600 + 900)  # 5 unreadable minutes

rng = random.Random(7)
DATA: dict[str, list[tuple[float, object]]] = {}


def setpoint_series(target: float) -> list[tuple[float, object]]:
    pts = [(T0 - 3 * 86400, target)]  # last change days ago: arrives as the carry-in
    events = [(rng.randint(60, N - 100), rng.randint(5, 40)) for _ in range(20)]
    events += [(rng.randint(60, N - 2000), 1200) for _ in range(3)]
    for s, dur in sorted(events):
        pts += [(T0 + s, target + rng.choice([-2, 2])), (T0 + s + dur, target)]
    pts.sort()
    out = []
    for t, v in pts:  # store on change
        if not out or out[-1][1] != v:
            out.append((t, v))
    return out


def actual_series(sp: list[tuple[float, object]], noise: float, step: int) -> list[tuple[float, object]]:
    out, j, h = [], 0, sp[0][1]
    for t in range(T0, NOW, step):
        while j < len(sp) and sp[j][0] <= t:
            h = sp[j][1]
            j += 1
        v = round(h + rng.gauss(0, noise), 1)
        if not out or out[-1][1] != v:
            out.append((t + rng.random() * 0.9, v))
    return out


for z in REG.zones:
    if z.parameter_id == "P09":
        sp, t = [(T0 - 60, 1)], T0
        while t < NOW:
            t += rng.choice([1, 2, 3])
            sp.append((t + rng.random() * 0.5, 0.99 if sp[-1][1] == 1 else 1))
        DATA[z.setpoint] = sp
        DATA[z.actual] = actual_series([(T0 - 60, 1.0)], 0.02, 5)
    else:
        target = {"P02": 215, "P03": 180, "P04": 185, "P06": 98}.get(z.parameter_id, 100)
        DATA[z.setpoint] = setpoint_series(target)
        DATA[z.actual] = actual_series(DATA[z.setpoint], 0.3, 4)
for group, spacing in (("SPC", (1, 9)), ("Dosing_Parameters", (1, 1))):
    t, pts = float(T0), []
    while t < NOW:
        pts.append((t, (t + SKEW_S) * 1000))
        t += rng.uniform(*spacing) if spacing[1] > spacing[0] else spacing[0]
    DATA[f"{NS}.{group}._timestamp"] = pts
for rel, v in (("SPC.Machine_Run", 1), ("SPC.Machine_Speed", 41)):
    DATA[f"{NS}.{rel}"] = [(T0 - 3600, v)]


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def block(tag: str, a: float | None, b: float | None) -> dict:
    pts = DATA[tag]
    if a is None:
        sel = pts[-1:]
    else:
        before = [p for p in pts if p[0] <= a][-1:]
        sel = before + [p for p in pts if a < p[0] <= b]
    return {"t": {"n": tag}, "d": [{"t": iso(t), "v": v, "q": 192} for t, v in sel]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def date_time_string(self, timestamp=None):
        return formatdate(NOW, usegmt=True)

    def send_json(self, code: int, obj, truncate: bool = False):
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if truncate:
            self.wfile.write(body[: len(body) // 2])
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True
        else:
            self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/datasets":
            return self.send_json(200, [{"n": "dressings", "pa": 0, "ps": 0}])
        if u.path == "/api/datasets/dressings/tags":
            c = (q.get("contains") or [""])[0]
            return self.send_json(200, {"User": [{"n": k, "t": "System.Double"} for k in DATA if c in k], "System": []})
        if u.path == "/api/datasets/dressings/data":
            tags = q.get("tagname", [])
            for t in tags:
                if t not in DATA:
                    return self.send_json(404, {"key": "Error.TagNotFound",
                                                "message": f"Tag '{t}' could not be found.", "errorCode": 1})
            a = float(q["unixStart"][0]) if "unixStart" in q else None
            b = float(q["unixEnd"][0]) if "unixEnd" in q else None
            hits_bad = BAD_TAG in tags and a is not None and a < BAD_SPAN[1] and b > BAD_SPAN[0]
            if hits_bad and len(tags) == 1:
                return self.send_response(500) or self.end_headers()
            payload = {"s": iso(a if a is not None else NOW), "e": iso(b if b is not None else NOW),
                       "tl": [block(t, a, b) for t in tags]}
            return self.send_json(200, payload, truncate=hits_bad)
        self.send_json(404, {})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 45116
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
