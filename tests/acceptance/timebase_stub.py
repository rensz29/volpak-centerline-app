"""A stand-in for the plant Timebase serving the AT-ANA reference dataset (tests/fixtures/analytics).

It answers as the probed server does (tools/timebase-analysis): the `{"s", "e", "tl"}` envelope, the value in force
at a window's start as its first point, values stored on change, the tag list under `{"User": [...]}`. Each machine
area's `_timestamp` tag carries its message arrivals. Every request is recorded, so a test can show what the api
asked (AT-ANA-09); anything but GET is refused.
"""

from __future__ import annotations

import bisect
import importlib.util
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "analytics"
NS = "Unilever_Ph_Nutrition.Dressings_Halal.Filling.Volpak.Filler"


def _dataset_module():
    spec = importlib.util.spec_from_file_location("acceptance_dataset", FIXTURES / "dataset.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class TimebaseStub:
    def __init__(self):
        data = json.loads((FIXTURES / "dataset.json").read_text(encoding="utf-8"))
        self.points: dict[str, list[tuple[float, object, int]]] = {}
        for side in ("x", "y"):
            self.points[data[side]["tag"]] = sorted((t, v, q) for t, v, q in data[side]["samples"])
        for area, spec in data["heartbeats"].items():
            self.points[f"{NS}.{area}._timestamp"] = [(t, t * 1000, 192) for t in _dataset_module().arrivals(spec)]
        self.times = {tag: [p[0] for p in pts] for tag, pts in self.points.items()}
        self.requests: list[tuple[str, str]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def send_json(self, code: int, obj) -> None:
                body = json.dumps(obj, separators=(",", ":")).encode()  # NaN and Infinity as JSON's extension
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def refuse(self):
                stub.requests.append((self.command, self.path))
                self.send_response(405)
                self.end_headers()

            do_POST = do_PUT = do_DELETE = do_PATCH = refuse

            def do_GET(self):
                stub.requests.append(("GET", self.path))
                u, q = urlparse(self.path), parse_qs(urlparse(self.path).query)
                if u.path == "/api/datasets":
                    return self.send_json(200, [{"n": "dressings", "pa": 0, "ps": 0}])
                if u.path == "/api/datasets/dressings/tags":
                    c = (q.get("contains") or [""])[0]
                    return self.send_json(200, {"User": [{"n": k, "t": "System.Double"} for k in stub.points if c in k], "System": []})
                if u.path == "/api/datasets/dressings/data":
                    tags = q.get("tagname", [])
                    missing = [t for t in tags if t not in stub.points]
                    if missing:
                        return self.send_json(404, {"key": "Error.TagNotFound", "message": f"Tag '{missing[0]}' could not be found."})
                    a, b = float(q["unixStart"][0]), float(q["unixEnd"][0])
                    return self.send_json(200, {"s": _iso(a), "e": _iso(b), "tl": [stub.block(t, a, b) for t in tags]})
                self.send_json(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def block(self, tag: str, a: float, b: float) -> dict:
        """The value in force at `a`, then every change in (a, b]."""
        pts, times = self.points[tag], self.times[tag]
        i = bisect.bisect_right(times, a)
        sel = pts[max(0, i - 1):i] + pts[i:bisect.bisect_right(times, b)]
        return {"t": {"n": tag}, "d": [{"t": _iso(t), "v": v, "q": q} for t, v, q in sel]}

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
