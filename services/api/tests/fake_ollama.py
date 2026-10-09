"""A stand-in for Ollama's API (ADR-0041): /api/tags and /api/chat on a free local port, answering what the test sets."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

DIGEST = "sha256:5f0c8e0d3b0a" + "0" * 52
EMBED_DIGEST = "sha256:e3b0c44298fc" + "1" * 52
# The stand-in embedding (ADR-0048): one dimension per idea, its English and Tagalog words alike, as a multilingual
# model would place them; plus one shared dimension, so no text is all zeros
IDEAS = [("burnt", "brittle", "darkened", "sunog", "nasunog", "maitim", "marupok"),
         ("separates", "separate", "weak", "matanggal", "natatanggal", "mahina", "humihiwalay"),
         ("centred", "centered", "cutter", "scissors", "gitna", "gunting"),
         ("narrower", "narrow", "thin", "manipis", "makitid", "kulang"),
         ("sticks", "stick", "sticking", "dumidikit", "dikit"),
         ("bottom", "ilalim"), ("top", "itaas", "ibabaw"), ("vertical", "patayo")]


def idea_vector(text: str) -> list[float]:
    words = [w.strip(".,:;()!?'\"").lower() for w in text.split()]
    return [float(sum(1 for w in words if w in idea)) for idea in IDEAS] + [1.0]


class FakeOllama:
    def __init__(self):
        self.reply: dict | str | Callable[[dict], dict | str] = {"questions": ["Which side of the pouch had the weak seal?",
                                                "Had the heater reached its preset when it happened?"]}
        self.delay = 0.0  # seconds before answering a chat
        self.status = 200  # of a chat
        self.models = [{"name": "qwen3.5:4b", "model": "qwen3.5:4b", "digest": DIGEST},
                       {"name": "bge-m3:latest", "model": "bge-m3:latest", "digest": EMBED_DIGEST}]
        self.embeds: list[dict] = []  # each embed request's body
        self.chats: list[dict] = []  # each chat request's body
        self.running: list[dict] = []  # what /api/ps lists as loaded
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def _send(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._send(200, {"models": fake.models})
                elif self.path == "/api/ps":
                    self._send(200, {"models": fake.running})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if self.path == "/api/embed":
                    fake.embeds.append(body)
                    if fake.status != 200:
                        self._send(fake.status, {"error": "model failed to load"})
                        return
                    self._send(200, {"model": body.get("model"), "embeddings": [idea_vector(t) for t in body["input"]]})
                    return
                fake.chats.append(body)
                time.sleep(fake.delay)
                if fake.status != 200:
                    self._send(fake.status, {"error": "model failed to load"})
                    return
                reply = fake.reply(body) if callable(fake.reply) else fake.reply  # a function answers from the request
                content = reply if isinstance(reply, str) else json.dumps(reply)
                self._send(200, {"model": body.get("model"), "message": {"role": "assistant", "content": content}, "done": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
