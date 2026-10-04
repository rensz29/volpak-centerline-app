"""The read-only MQTT subscriber (ADR-0006): it subscribes, never publishes, and sets no Last Will (M6).

Messages and connection changes are handed to callbacks with our own arrival time; the
engine never sees the payload clock as time (invariant 13).
"""

from __future__ import annotations

import logging
import socket
import ssl
from collections.abc import Callable
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

log = logging.getLogger("centerline.monitor")
RETRY_FAST_S, RETRY_SLOW_S, FAST_FOR_S = 5, 30, 60  # OPC-03: retry every 5 s for one minute, then every 30 s


def retry_delay(lost_at: datetime | None, now: datetime) -> int:
    """How long to wait before the next try at the broker (OPC-03)."""
    return RETRY_FAST_S if lost_at is None or (now - lost_at).total_seconds() < FAST_FOR_S else RETRY_SLOW_S


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Subscriber:
    def __init__(self, cfg: dict, on_message: Callable[[str, bytes, bool, datetime], None],
                 on_connection: Callable[[bool, datetime], None]):
        self.cfg = cfg
        self.v5 = str(cfg.get("protocol", "5")) == "5"
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=cfg.get("client_id") or f"centerline-monitor-{socket.gethostname()}",
                                  protocol=mqtt.MQTTv5 if self.v5 else mqtt.MQTTv311,
                                  clean_session=None if self.v5 else True)

        def refuse(*_a, **_k):
            raise RuntimeError("monitor-core is read-only: publish is disabled")

        self.client.publish = refuse  # type: ignore[method-assign]
        tls = cfg.get("tls") or {}
        if tls.get("enabled"):
            ctx = ssl.create_default_context(cafile=tls.get("ca_file") or None)
            if tls.get("verify_hostname") is False:
                ctx.check_hostname = False  # the certificate chain is still verified
            self.client.tls_set_context(ctx)
        if cfg.get("username"):
            self.client.username_pw_set(cfg["username"], cfg.get("password"))
        self.lost_at: datetime | None = None  # since when the broker has been out of reach
        self.pace = RETRY_FAST_S
        self.client.reconnect_delay_set(min_delay=RETRY_FAST_S, max_delay=RETRY_FAST_S)
        subs = cfg.get("subscriptions") or []

        def connected(c, _u, _flags, reason, _props):
            if reason.is_failure:
                log.warning("broker refused the connection: %s", reason)
                self.paced(utcnow())
                on_connection(False, utcnow())
                return
            self.reached()
            c.subscribe([(s, 1) for s in subs])
            log.info("connected to %s:%s, subscribed to %s", cfg["host"], self.port, ", ".join(subs))
            on_connection(True, utcnow())

        def disconnected(_c, _u, _flags, reason, _props):
            log.warning("broker connection lost: %s", reason)
            self.paced(utcnow())
            on_connection(False, utcnow())

        self.client.on_connect = connected
        self.client.on_disconnect = disconnected
        self.client.on_connect_fail = lambda _c, _u: self.paced(utcnow())  # a try that didn't reach the broker
        self.client.on_message = lambda _c, _u, msg: on_message(msg.topic, msg.payload, bool(msg.retain), utcnow())

    def paced(self, now: datetime) -> None:
        """The broker is out of reach: the next try comes 5 s after the last for the first minute, then 30 s (OPC-03).
        paho waits its reconnect delay after each failure; setting it starts that wait afresh."""
        if self.lost_at is None:
            self.lost_at = now
        delay = retry_delay(self.lost_at, now)
        if delay != self.pace:
            self.pace = delay
            self.client.reconnect_delay_set(min_delay=delay, max_delay=delay)
            log.info("broker still out of reach after %d s: trying every %d s", FAST_FOR_S, delay)

    def reached(self) -> None:
        """Connected again: the next loss starts with the 5 s tries again."""
        self.lost_at = None
        if self.pace != RETRY_FAST_S:
            self.pace = RETRY_FAST_S
            self.client.reconnect_delay_set(min_delay=RETRY_FAST_S, max_delay=RETRY_FAST_S)

    @property
    def port(self) -> int:
        return int(self.cfg.get("port") or (8883 if (self.cfg.get("tls") or {}).get("enabled") else 1883))

    def start(self) -> None:
        self.client.connect_async(self.cfg["host"], self.port, keepalive=int(self.cfg.get("keepalive_s", 5)),
                                  **({"clean_start": True} if self.v5 else {}))
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()
