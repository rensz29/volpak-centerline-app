"""Phase 0 MQTT probe: what the plant broker actually delivers (ADR-0006).

    python mqtt_probe.py config.json [--seconds 120]
    python mqtt_probe.py ../../config/connections.json [--seconds 120]   # the broker saved on the Configuration page
    python mqtt_probe.py ... --out data/running                          # keep each run's files apart

Subscribes to the configured topic filters, listens, and writes to data/:
* mqtt-probe-report.md: connection and subscription result, every topic seen
  (message rate, gaps, retained flag, payload format, fields, payload clock
  offset), where each register tag was found, SKU-like fields, and the
  freshness threshold the measured gaps support;
* topic-map.json: register tag → {topic, field}, the mapping monitor-core imports;
* samples.jsonl: the first payloads of each topic, for inspection.

Read-only: the client never publishes and sets no Last Will. `publish` is
disabled on the client object, so a code change can't slip one in.
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import statistics
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import register as register_mod  # noqa: E402

OUT = Path(__file__).parent / "data"
TS_FIELDS = ("_timestamp", "timestamp", "Timestamp", "ts")
SKU_HINTS = ("sku", "recipe", "product", "material", "order", "batch")


def sku_like(field: str, value) -> bool:
    """A field named like a SKU or recipe, and not a true/false flag such as Product_Inlet_Valve."""
    return any(h in field.lower() for h in SKU_HINTS) and not isinstance(value, bool) \
        and str(value).strip().lower() not in ("true", "false")


class TopicStats:
    def __init__(self) -> None:
        self.arrivals: list[float] = []
        self.first_retained: bool | None = None
        self.formats: set[str] = set()
        self.fields: dict[str, object] = {}
        self.skew: list[float] = []
        self.sizes: list[int] = []
        self.samples: list[str] = []


def classify(topic: str, payload: bytes) -> tuple[str, object]:
    if topic.startswith("spBv1.0/"):
        return "sparkplug-b (binary, not decoded)", None
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return "binary", None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        try:
            return "scalar number", float(text)
        except ValueError:
            return "text", text
    if isinstance(obj, dict):
        return "json object", obj
    if isinstance(obj, list):
        return "json array", obj
    return "json scalar", obj


def payload_time(obj: dict) -> float | None:
    for k in TS_FIELDS:
        v = obj.get(k)
        if isinstance(v, (int, float)):
            return v / 1000 if v > 1e11 else float(v)
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
    return None


def read_secret(path: str | None) -> str | None:
    return Path(path).expanduser().read_text(encoding="utf-8").strip() if path else None


def from_connections(path: Path, saved: dict) -> dict:
    """The broker saved on the Configuration page (ADR-0011): secrets/ and the register sit next to it."""
    cfg = saved.get("mqtt")
    if not cfg or not cfg.get("host"):
        raise SystemExit("No MQTT broker saved yet: enter it on Configuration → Connections and Save")

    def local(ref: str | None) -> str | None:
        return str(path.parent / ref) if ref and ref.startswith("secrets/") else ref

    tls = {**(cfg.get("tls") or {}), "ca_file": local((cfg.get("tls") or {}).get("ca_file"))}
    return {**cfg, "tls": tls, "password_file": local(cfg.get("password_file")), "register": "parameter-register.json"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--out", type=Path, default=OUT, help="folder for the report, topic map and samples (default data/)")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if "mqtt" in cfg or "historian" in cfg:
        cfg = from_connections(cfg_path, cfg)
    reg = register_mod.load((cfg_path.parent / cfg["register"]) if cfg.get("register") else None)
    listen = args.seconds or float(cfg.get("listen_s", 120))
    subs = cfg.get("subscriptions") or [reg.namespace.replace(".", "/") + "/#"]
    v5 = str(cfg.get("protocol", "5")) == "5"

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=cfg.get("client_id") or f"centerline-probe-{socket.gethostname()}",
                         protocol=mqtt.MQTTv5 if v5 else mqtt.MQTTv311,
                         clean_session=None if v5 else True)

    def _refuse(*_a, **_k):
        raise RuntimeError("mqtt_probe is read-only: publish is disabled")

    client.publish = _refuse  # type: ignore[method-assign]

    tls = cfg.get("tls") or {}
    if tls.get("enabled"):
        def _p(key: str) -> str | None:
            return str(Path(tls[key]).expanduser()) if tls.get(key) else None
        client.tls_set(ca_certs=_p("ca_file"), certfile=_p("cert_file"), keyfile=_p("key_file"))
        if tls.get("verify_hostname") is False:
            client.tls_insecure_set(True)
    if cfg.get("username"):
        client.username_pw_set(cfg["username"], read_secret(cfg.get("password_file")))

    stats: dict[str, TopicStats] = defaultdict(TopicStats)
    result: dict[str, object] = {}
    connected = threading.Event()
    lock = threading.Lock()

    def on_connect(c, _u, _flags, reason, _props):
        result["connect"] = str(reason)
        if reason.is_failure:
            connected.set()
            return
        result["subscribe_mid"] = c.subscribe([(s, 1) for s in subs])[1]
        connected.set()

    def on_subscribe(_c, _u, _mid, reasons, _props):
        result["subscribe"] = [str(r) for r in reasons]

    def on_disconnect(_c, _u, _flags, reason, _props):
        result.setdefault("disconnects", []).append(f"{datetime.now(timezone.utc):%H:%M:%S} {reason}")

    def on_message(_c, _u, msg):
        now = time.time()
        fmt, obj = classify(msg.topic, msg.payload)
        with lock:
            st = stats[msg.topic]
            if st.first_retained is None:
                st.first_retained = bool(msg.retain)
            if not msg.retain:
                st.arrivals.append(now)
            st.formats.add(fmt)
            st.sizes.append(len(msg.payload))
            if isinstance(obj, dict):
                for k, v in obj.items():
                    st.fields.setdefault(k, v)
                pt = payload_time(obj)
                if pt is not None:
                    st.skew.append(pt - now)
            if len(st.samples) < 3:
                st.samples.append(msg.payload[:2048].decode("utf-8", "replace"))

    client.on_connect, client.on_subscribe = on_connect, on_subscribe
    client.on_disconnect, client.on_message = on_disconnect, on_message

    host, port = cfg["host"], int(cfg.get("port", 8883 if tls.get("enabled") else 1883))
    print(f"connecting to {host}:{port} ({'MQTT 5' if v5 else 'MQTT 3.1.1'}, TLS {'on' if tls.get('enabled') else 'off'})")
    t_connect = time.time()
    try:
        client.connect(host, port, keepalive=int(cfg.get("keepalive_s", 10)),
                       **({"clean_start": True} if v5 else {}))
    except (OSError, ValueError) as e:
        result["connect"] = f"network error: {e}"
    else:
        client.loop_start()
        connected.wait(15)
        if result.get("connect") and not str(result["connect"]).lower().startswith("success"):
            print(f"connect failed: {result['connect']}")
        else:
            print(f"listening {listen:.0f} s on {', '.join(subs)} …")
            time.sleep(listen)
        client.loop_stop()
        client.disconnect()
    t_end = time.time()
    return write_report(cfg, reg, subs, host, port, v5, tls, result, stats, t_end - t_connect, t_end, args.out)


def write_report(cfg, reg, subs, host, port, v5, tls, result, stats, elapsed, t_end, out: Path = OUT) -> int:
    out.mkdir(parents=True, exist_ok=True)
    ns = reg.namespace
    L = [f"# MQTT probe, {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
         f"- Broker `{host}:{port}` · {'MQTT 5' if v5 else 'MQTT 3.1.1'} · TLS {'on' if tls.get('enabled') else '**off**'} · "
         f"user `{cfg.get('username') or '(anonymous)'}`",
         f"- Connect: **{result.get('connect', 'no answer')}**",
         f"- Subscriptions {subs}: {result.get('subscribe', 'not acknowledged')}",
         f"- Listened {elapsed:.0f} s; topics seen: {len(stats)}; messages: {sum(len(s.arrivals) for s in stats.values())} live"
         f" + {sum(1 for s in stats.values() if s.first_retained)} retained"]
    if result.get("disconnects"):
        L.append(f"- Disconnects: {result['disconnects']}")
    if not tls.get("enabled"):
        L.append("- **TLS is off:** credentials and values cross the network in clear (ADR-0006 control M1).")

    L += ["", "## Topics", "",
          "| Topic | Live msgs | Msgs / min | Median gap | p99 gap | Max gap | Silent at end | First msg retained | Format | Fields | Payload clock − this PC |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    fresh_rows = []
    for topic, st in sorted(stats.items()):
        gaps = sorted(b - a for a, b in zip(st.arrivals, st.arrivals[1:]))
        med = f"{statistics.median(gaps):.1f} s" if gaps else "–"
        p99 = gaps[min(len(gaps) - 1, int(0.99 * len(gaps)))] if gaps else None
        mx = gaps[-1] if gaps else None
        skew = f"{statistics.median(st.skew):+.1f} s" if st.skew else "–"
        silent = t_end - st.arrivals[-1] if st.arrivals else None
        silent_txt = "–" if silent is None else (f"**{silent:.0f} s**" if mx is not None and silent > 3 * max(mx, 1) else f"{silent:.0f} s")
        L.append(f"| `{topic}` | {len(st.arrivals)} | {len(st.arrivals) / max(elapsed / 60, 1e-9):.0f} | {med} | "
                 f"{'–' if p99 is None else f'{p99:.1f} s'} | {'–' if mx is None else f'{mx:.1f} s'} | {silent_txt} | "
                 f"{'yes' if st.first_retained else 'no'} | {', '.join(sorted(st.formats))} | {len(st.fields)} | {skew} |")
        if mx is not None:
            fresh_rows.append((topic, p99, mx))

    # Where does each register tag live?
    lookup: dict[str, tuple[str, str | None]] = {}
    for topic, st in stats.items():
        dotted = topic.replace("/", ".")
        if st.fields:
            for k in st.fields:
                lookup[f"{dotted}.{k}"] = (topic, k)
        else:
            lookup[dotted] = (topic, None)
    labelled = [(f"{z.channel} setpoint", z.setpoint) for z in reg.zones] + \
               [(f"{z.channel} actual", z.actual) for z in reg.zones] + \
               ([("SKU", reg.sku_tag)] if reg.sku_tag else []) + \
               [(f"context: {k}", v) for k, v in reg.context.items()] + reg.candidate_tags()
    topic_map, missing = {}, []
    L += ["", "## Register tags on MQTT", "", "| Role | Tag | Topic | Field | Sample |", "|---|---|---|---|---|"]
    for role, tag in labelled:
        hit = lookup.get(tag)
        if hit:
            topic, field = hit
            sample = stats[topic].fields.get(field) if field else ""
            topic_map[tag] = {"topic": topic, "field": field}
            L.append(f"| {role} | `{tag.split(ns + '.')[-1]}` | `{topic}` | `{field or '(whole payload)'}` | {sample} |")
        else:
            missing.append(tag)
            L.append(f"| {role} | `{tag.split(ns + '.')[-1]}` | **not seen** | | |")

    candidates = [(t, k, v) for t, st in stats.items() for k, v in st.fields.items() if sku_like(k, v)]
    L += ["", "## SKU field (ADR-0007)", ""]
    L += [f"- Candidate: `{t}` field `{k}` = {v!r}" for t, k, v in candidates] or \
         ["- No SKU-, recipe- or product-like field seen: the edge team still has to add it."]

    L += ["", "## Freshness threshold (ADR-0006)", "",
          "A topic is stale when no message has arrived for longer than the threshold. It must sit above "
          "the largest *regular* gap, or monitoring pauses during normal running.", ""]
    for topic, p99, mx in fresh_rows:
        if any(v["topic"] == topic for v in topic_map.values()):
            thr = max(10, 5 * math.ceil(1.5 * mx / 5))
            L.append(f"- `{topic}`: p99 gap {p99:.1f} s, max {mx:.1f} s → threshold ≥ **{thr} s**"
                     + (" (the SDD's 10 s works)" if thr <= 10 else ""))
    if elapsed < 600:
        L.append(f"- Listened only {elapsed:.0f} s: run again for an hour, while running and while stopped, before fixing the value.")

    (out / "topic-map.json").write_text(json.dumps({"generated": datetime.now(timezone.utc).isoformat(),
                                                    "register_version": reg.version, "broker": f"{host}:{port}",
                                                    "tags": topic_map, "not_seen": missing}, indent=2))
    with (out / "samples.jsonl").open("w", encoding="utf-8") as f:
        for topic, st in sorted(stats.items()):
            for s in st.samples:
                f.write(json.dumps({"topic": topic, "payload": s}) + "\n")
    (out / "mqtt-probe-report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {out / 'mqtt-probe-report.md'} and topic-map.json ({len(topic_map)} tags mapped, {len(missing)} not seen)")
    return 0 if result.get("connect", "").lower().startswith("success") else 2


if __name__ == "__main__":
    raise SystemExit(main())
