"""monitor-core is read-only on the broker (ADR-0006 M6): it can't publish, leaves no Last Will, and has no code that sends."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import centerline_monitor
from centerline_monitor.mqtt import Subscriber, retry_delay

SENDS = {"publish", "will_set", "_send_publish"}  # paho's ways to put a message on the broker


def sends(*packages: Path) -> list[str]:
    """Every call in the packages that could publish, and every import of paho's publish helpers."""
    found = []
    for path in sorted(p for package in packages for p in package.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in SENDS:
                found.append(f"{path.name}:{node.lineno} .{node.func.attr}()")
            elif isinstance(node, ast.ImportFrom) and (node.module == "paho.mqtt.publish" or (
                    node.module == "paho.mqtt" and any(a.name == "publish" for a in node.names))):
                found.append(f"{path.name}:{node.lineno} imports paho.mqtt.publish")
            elif isinstance(node, ast.Import) and any(a.name == "paho.mqtt.publish" for a in node.names):
                found.append(f"{path.name}:{node.lineno} imports paho.mqtt.publish")
    return found


def test_the_subscriber_refuses_to_publish_and_sets_no_last_will():
    sub = Subscriber({"host": "127.0.0.1", "subscriptions": ["Volpak/#"]}, lambda *_: None, lambda *_: None)
    with pytest.raises(RuntimeError, match="read-only"):
        sub.client.publish("centerline/acl-test", b"x")
    assert sub.client._will is False  # nothing the broker would publish for us when the connection drops


def test_no_code_in_monitor_core_publishes_or_sets_a_last_will():
    assert sends(Path(centerline_monitor.__file__).parent) == []


def test_a_lost_broker_is_tried_every_5_s_for_a_minute_then_every_30_s():
    t0 = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
    assert [retry_delay(t0, t0 + timedelta(seconds=s)) for s in (0, 5, 59, 60, 61, 600)] == [5, 5, 5, 30, 30, 30]  # OPC-03
    sub = Subscriber({"host": "127.0.0.1", "subscriptions": ["Volpak/#"]}, lambda *_: None, lambda *_: None)
    delays = lambda: (sub.client._reconnect_min_delay, sub.client._reconnect_max_delay)  # noqa: E731 (paho waits this between tries)
    assert delays() == (5, 5)
    sub.paced(t0)  # the connection dropped
    sub.paced(t0 + timedelta(seconds=55))  # a try failed
    assert delays() == (5, 5)
    sub.paced(t0 + timedelta(seconds=60))
    assert delays() == (30, 30)
    sub.reached()  # connected again
    assert delays() == (5, 5) and sub.lost_at is None
    sub.paced(t0 + timedelta(hours=1))  # a new loss starts with the 5 s tries
    assert delays() == (5, 5)
