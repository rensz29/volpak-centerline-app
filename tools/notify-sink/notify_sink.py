#!/usr/bin/env python3
"""A local stand-in for the Teams flow and the SMTP relay (ADR-0023), for development only.

    python tools/notify-sink/notify_sink.py            # Teams on http://127.0.0.1:8025, SMTP on 127.0.0.1:2525

It answers like the real ones (HTTP 202, SMTP 250), prints a line for each message, and saves
each one under tools/notify-sink/data/: the JSON the flow would get, the email as an .eml file.
It listens on 127.0.0.1 only and sends nothing anywhere. Stdlib only.
"""

from __future__ import annotations

import argparse
import email
import email.policy
import json
import socketserver
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def teams_server(port: int, out: Path) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                msg = json.loads(body)
            except ValueError:
                self.send_response(400)
                self.end_headers()
                return
            path = out / f"teams-{stamp()}.json"
            path.write_text(json.dumps(msg, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Teams  → {msg.get('target')}: {msg.get('title')}  [{path.name}]", flush=True)
            self.send_response(202)  # what Power Automate answers
            self.end_headers()

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def smtp_server(port: int, out: Path) -> socketserver.ThreadingTCPServer:
    class Handler(socketserver.StreamRequestHandler):
        def say(self, line: str):
            self.wfile.write(line.encode() + b"\r\n")

        def handle(self):
            self.say("220 notify-sink ESMTP")
            while line := self.rfile.readline():
                verb = line.decode("utf-8", "replace").strip().split(" ", 1)[0].upper()
                if verb == "DATA":
                    self.say("354 go ahead")
                    data = b""
                    while (chunk := self.rfile.readline()) not in (b".\r\n", b""):
                        data += chunk[1:] if chunk.startswith(b"..") else chunk
                    path = out / f"email-{stamp()}.eml"
                    path.write_bytes(data)
                    m = email.message_from_bytes(data, policy=email.policy.default)
                    print(f"Email  → {m['To']}: {m['Subject']}  [{path.name}]", flush=True)
                    self.say("250 2.0.0 queued by notify-sink")
                elif verb == "QUIT":
                    self.say("221 bye")
                    return
                else:
                    self.say("250 notify-sink" if verb in ("EHLO", "HELO") else "250 OK")

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    return Server(("127.0.0.1", port), Handler)


def main() -> int:
    ap = argparse.ArgumentParser(description="A local Teams flow and SMTP relay that keep what they receive")
    ap.add_argument("--http-port", type=int, default=8025)
    ap.add_argument("--smtp-port", type=int, default=2525)
    ap.add_argument("--out", type=Path, default=HERE / "data")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    http, smtp = teams_server(args.http_port, args.out), smtp_server(args.smtp_port, args.out)
    threading.Thread(target=smtp.serve_forever, daemon=True).start()
    print(f"On Configuration → Connections → Notifications:\n"
          f"  Teams flow URL  http://127.0.0.1:{args.http_port}/flow?sig=dev\n"
          f"  SMTP relay      127.0.0.1 port {args.smtp_port}, no security, no sign-in\n"
          f"Saving to {args.out}. Ctrl+C to stop.", flush=True)
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
