"""Connection tests for the Configuration page. Both are read-only.

The MQTT test connects, subscribes, listens for a few seconds and reports what
arrived, and where each register tag was found. `publish` is disabled on the
client and no Last Will is set, so it can't send anything to the plant broker.
"""

from __future__ import annotations

import json
import socket
import ssl
import threading
import time
from collections import defaultdict

import paho.mqtt.client as mqtt
from centerline_common.historian import TimebaseClient, TimebaseError
from centerline_common.register import Register

SKU_HINTS = ("sku", "recipe", "product", "material", "order", "batch")


def check_historian(cfg: dict, namespace: str) -> dict:
    t0 = time.monotonic()
    try:
        client = TimebaseClient({**cfg, "timeout_s": min(int(cfg.get("timeout_s", 60)), 15)})
    except (ValueError, OSError) as e:  # e.g. the token file is missing
        return {"ok": False, "error": str(e)}
    try:
        datasets = [d.get("n") for d in client.datasets()]
        latency = round((time.monotonic() - t0) * 1000)
        found = cfg["dataset"] in datasets
        tags = len(client.tag_names(contains=namespace)) if found else 0
        offset = None if client.last_server_date is None else round(client.last_server_date - time.time(), 1)
        return {"ok": found, "latencyMs": latency, "datasets": datasets, "datasetFound": found,
                "tagsUnderNamespace": tags, "namespace": namespace, "clockOffsetS": offset,
                "error": None if found else f"Dataset {cfg['dataset']!r} isn't on this server"}
    except TimebaseError as e:
        return {"ok": False, "error": str(e)}
    finally:
        client.close()


def _register_tags(reg: Register) -> list[tuple[str, str]]:
    tags = [(f"{z.zone_name} setpoint", z.setpoint) for z in reg.zones]
    tags += [(f"{z.zone_name} actual", z.actual) for z in reg.zones]
    tags += [(f"{v.zone_name} actual", v.tag) for v in reg.analytics if v.kind == "actual"
             and v.tag not in {z.actual for z in reg.zones}]
    tags += [(f"context: {k}", t) for k, t in reg.context.items()]
    if reg.sku_tag:
        tags.append(("SKU", reg.sku_tag))
    first: dict[str, str] = {}
    for label, tag in tags:  # one row per tag, under its first (most specific) label
        first.setdefault(tag, label)
    return [(label, tag) for tag, label in first.items()]


def check_mqtt(cfg: dict, reg: Register, seconds: float) -> dict:
    v5 = str(cfg.get("protocol", "5")) == "5"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=cfg.get("client_id") or f"centerline-check-{socket.gethostname()}",
                         protocol=mqtt.MQTTv5 if v5 else mqtt.MQTTv311,
                         clean_session=None if v5 else True)

    def _refuse(*_a, **_k):
        raise RuntimeError("the connection test is read-only: publish is disabled")

    client.publish = _refuse  # type: ignore[method-assign]
    tls = cfg.get("tls") or {}
    if tls.get("enabled"):
        try:
            # A CA pasted on the form (not saved yet) or the saved CA file; otherwise the system's CAs.
            ctx = ssl.create_default_context(cafile=tls.get("ca_file") or None, cadata=tls.get("ca_pem") or None)
            if tls.get("verify_hostname") is False:
                ctx.check_hostname = False  # the certificate chain is still verified
            client.tls_set_context(ctx)
        except (ssl.SSLError, OSError, ValueError) as e:
            return {"connected": False, "error": f"TLS setup failed: {e}"}
    if cfg.get("username"):
        client.username_pw_set(cfg["username"], cfg.get("password"))

    subs = cfg.get("subscriptions") or []
    state: dict = {"connect": None, "subscribe": None}
    done = threading.Event()
    lock = threading.Lock()
    stats: dict[str, dict] = defaultdict(lambda: {"messages": 0, "retained": None, "fields": {}, "sample": None,
                                                  "format": None})

    def on_connect(c, _u, _flags, reason, _props):
        state["connect"] = str(reason)
        if not reason.is_failure:
            c.subscribe([(s, 1) for s in subs])
        done.set()

    def on_subscribe(_c, _u, _mid, reasons, _props):
        state["subscribe"] = [str(r) for r in reasons]

    def on_message(_c, _u, msg):
        with lock:
            st = stats[msg.topic]
            st["messages"] += 1
            if st["retained"] is None:
                st["retained"] = bool(msg.retain)
            if st["sample"] is None:
                st["sample"] = msg.payload[:400].decode("utf-8", "replace")
            try:
                obj = json.loads(msg.payload)
                st["format"] = "JSON object" if isinstance(obj, dict) else "JSON value"
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        st["fields"].setdefault(k, v)
            except (json.JSONDecodeError, UnicodeDecodeError):
                st["format"] = "Sparkplug B (binary)" if msg.topic.startswith("spBv1.0/") else "text or binary"

    client.on_connect, client.on_subscribe, client.on_message = on_connect, on_subscribe, on_message
    port = int(cfg.get("port") or (8883 if tls.get("enabled") else 1883))
    started = time.monotonic()
    try:
        client.connect(cfg["host"], port, keepalive=int(cfg.get("keepalive_s", 5)),
                       **({"clean_start": True} if v5 else {}))
    except (OSError, ValueError, ssl.SSLError) as e:
        return {"connected": False, "error": f"Can't reach {cfg['host']}:{port}: {e}"}
    client.loop_start()
    try:
        if not done.wait(10):
            return {"connected": False, "error": "No answer from the broker within 10 s"}
        if state["connect"] and state["connect"].lower() != "success":
            return {"connected": False, "error": f"The broker refused the connection: {state['connect']}"}
        time.sleep(seconds)
    finally:
        client.loop_stop()
        client.disconnect()
    elapsed = time.monotonic() - started

    lookup: dict[str, tuple[str, str | None]] = {}
    for topic, st in stats.items():
        dotted = topic.replace("/", ".")
        if st["fields"]:
            for k in st["fields"]:
                lookup[f"{dotted}.{k}"] = (topic, k)
        else:
            lookup[dotted] = (topic, None)
    mapped, missing = [], []
    for label, tag in _register_tags(reg):
        hit = lookup.get(tag)
        rel = tag.split(reg.namespace + ".")[-1]
        if hit:
            mapped.append({"label": label, "tag": rel, "topic": hit[0], "field": hit[1]})
        else:
            missing.append({"label": label, "tag": rel})
    topics = sorted(({"topic": t, "messages": s["messages"], "perMinute": round(s["messages"] / max(elapsed / 60, 1e-9), 1),
                      "retained": bool(s["retained"]), "format": s["format"], "fields": len(s["fields"]),
                      "fieldNames": sorted(s["fields"])[:500], "sample": s["sample"]} for t, s in stats.items()),
                    key=lambda r: -r["messages"])
    sku = [{"topic": t, "field": k, "value": str(v)[:60]} for t, s in stats.items() for k, v in s["fields"].items()
           if any(h in k.lower() for h in SKU_HINTS) and not isinstance(v, bool)
           and str(v).strip().lower() not in ("true", "false")]  # not flags such as Product_Inlet_Valve
    warnings = []
    if not tls.get("enabled"):
        warnings.append("TLS is off: the password and all values cross the network in clear (ADR-0006, control M1).")
    if not stats:
        warnings.append(f"Connected, but nothing arrived in {seconds:g} s on {', '.join(subs)}. Check the topic filter "
                        "and that the account may subscribe to it.")
    if stats and not sku:
        warnings.append("No SKU-like field was seen: the edge team still has to add it (O-15).")
    return {"connected": True, "connect": state["connect"], "subscriptions": state["subscribe"],
            "listenedS": round(elapsed, 1), "topics": topics[:50], "topicCount": len(topics),
            "mapped": mapped, "missing": missing, "skuCandidates": sku[:10], "warnings": warnings}
