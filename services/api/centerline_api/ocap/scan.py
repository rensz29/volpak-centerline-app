"""Malware scanning of uploads (SEC-01, ADR-0031): the file streamed to clamd (INSTREAM) before anything is stored.

With no scanner configured (`"scanner": {"type": "none"}`, a development PC only) every upload is marked not scanned.
A scanner that can't be reached refuses the upload rather than letting it through.
"""

from __future__ import annotations

import socket
import struct

from ..settings import ScannerSettings

CHUNK = 64 * 1024


class ScannerUnavailable(Exception):
    """clamd didn't answer, or answered with an error."""


def version(s: ScannerSettings) -> str:
    """clamd's version and its signatures' date, e.g. "ClamAV 1.4.3/27785/Tue Oct  7 08:23:45 2026" (the health page)."""
    try:
        with socket.create_connection((s.host, s.port), timeout=min(s.timeout_s, 5)) as sock:
            sock.sendall(b"zVERSION\0")
            reply = b""
            while not reply.endswith(b"\0"):
                got = sock.recv(4096)
                if not got:
                    break
                reply += got
    except OSError as e:
        raise ScannerUnavailable(f"clamd at {s.host}:{s.port}: {e}") from None
    return reply.rstrip(b"\0").decode("utf-8", "replace").strip()


def scan(data: bytes, s: ScannerSettings) -> tuple[str, str]:
    """("clean" | "not_scanned" | "infected", clamd's answer or why it wasn't asked)."""
    if s.type == "none":
        return "not_scanned", "No malware scanner is configured (development only)"
    if s.type != "clamd":
        raise ScannerUnavailable(f"Unknown scanner type {s.type!r}")
    try:
        with socket.create_connection((s.host, s.port), timeout=s.timeout_s) as sock:
            sock.sendall(b"zINSTREAM\0")
            for i in range(0, len(data), CHUNK):
                part = data[i:i + CHUNK]
                sock.sendall(struct.pack(">I", len(part)) + part)
            sock.sendall(struct.pack(">I", 0))
            reply = b""
            while not reply.endswith(b"\0"):
                got = sock.recv(4096)
                if not got:
                    break
                reply += got
    except OSError as e:
        raise ScannerUnavailable(f"clamd at {s.host}:{s.port}: {e}") from None
    answer = reply.rstrip(b"\0").decode("utf-8", "replace").strip()
    if answer.endswith(" OK"):
        return "clean", answer
    if answer.endswith(" FOUND"):
        return "infected", answer.removeprefix("stream: ").removesuffix(" FOUND")
    raise ScannerUnavailable(f"clamd answered {answer!r}")
