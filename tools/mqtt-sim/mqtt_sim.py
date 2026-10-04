"""Simulated Volpak publisher for development and the G1 tests (replaces tools/opcua-sim).

    python mqtt_sim.py [--host 127.0.0.1] [--port 1883] [options]

Publishes one JSON message per machine area (SPC, Dosing_Parameters) in the
shape observed on the plant's UNS: topic = register namespace with '/'
separators + '/' + area; payload = the area's fields plus `_timestamp` (epoch
ms), `_name`, `_model` and ISA-95 identity fields. Values come from the
parameter register: each zone's setpoint holds a target and its actual follows
with noise.

Scenarios (combine freely):
  --brief-every N     every N s a random zone's setpoint moves ±2 for 5–40 s
  --mismatch-every N --mismatch-for S   every N s a random zone's setpoint moves ±2 and stays there S s
                      (default 600): a mismatch nobody puts back, which asks the operator why (ADR-0025)
  --skew-s S          payload clock offset from this PC (the plant edge runs about −114 s)
  --stop-area A --stop-after N   stop publishing area A after N s (stale data)
  --sku-field F --sku CODE       also publish a SKU field (e.g. SPC.SKU_Code) to test ADR-0001
  --drift-every N     every N s a random zone's actual leaves its band: Warning for 60 s, and on every
                      other drift Critical for 60 s more, then back (the bands are the Rules proposal's)
  --machine-stop-every N --machine-stop-for S   the machine stops (Machine_Run 0) for S s every N s

SAFETY: this publishes. It refuses any broker that isn't on this machine
unless the exact host is passed with --allow-host, so it can't inject fake
setpoints into the plant UNS by accident.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import random
import socket
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import register  # noqa: E402

TARGETS = {"P02": [220, 215, 215, 220, 214, 214], "P03": [180, 180], "P04": [185, 185], "P06": [98, 98, 98], "P09": [1.3]}
NOISE = {"P09": 0.01}
PROPOSAL = Path(__file__).resolve().parents[2] / "db" / "seed" / "rules-proposal.json"
WARNING_S = CRITICAL_S = 60  # how long a drift holds each band: longer than the Warning and Critical delays


def bands() -> dict[str, tuple[float, float]]:
    """Each parameter's Warning and Critical offsets above its setpoint, from the Rules proposal."""
    try:
        rules = json.loads(PROPOSAL.read_text(encoding="utf-8"))["rules"]
    except (OSError, ValueError, KeyError):
        return {}
    return {r["parameter_id"]: (float(r["warn_high"]), float(r["crit_high"])) for r in rules
            if r.get("sku") is None and r.get("zone_id") is None and r.get("warn_high") is not None}


def is_local(host: str) -> bool:
    try:
        return all(ipaddress.ip_address(a[4][0]).is_loopback for a in socket.getaddrinfo(host, None))
    except (socket.gaierror, ValueError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--allow-host", help="publish to this non-local host (a test broker, never the plant UNS)")
    ap.add_argument("--rate", type=float, default=1.0, help="messages per second per area")
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long (0 = run until Ctrl+C)")
    ap.add_argument("--qos", type=int, default=0, choices=(0, 1))
    ap.add_argument("--retain", action="store_true")
    ap.add_argument("--skew-s", type=float, default=0.0)
    ap.add_argument("--brief-every", type=float, default=0)
    ap.add_argument("--mismatch-every", type=float, default=0)
    ap.add_argument("--mismatch-for", type=float, default=600)
    ap.add_argument("--stop-area")
    ap.add_argument("--stop-after", type=float, default=0)
    ap.add_argument("--sku-field", help="publish the SKU as AREA.FIELD, e.g. SPC.SKU_Code")
    ap.add_argument("--sku", default="SIM-SKU-1")
    ap.add_argument("--drift-every", type=float, default=0)
    ap.add_argument("--machine-stop-every", type=float, default=0)
    ap.add_argument("--machine-stop-for", type=float, default=120)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    if args.sku_field and "." not in args.sku_field:
        ap.error("--sku-field needs AREA.FIELD, e.g. SPC.SKU_Code")

    if not is_local(args.host) and args.host != args.allow_host:
        sys.exit(f"refusing to publish to {args.host}: not this machine. Pass --allow-host {args.host} "
                 "only for a test broker, never the plant UNS.")

    reg = register.load()
    rng = random.Random(args.seed)
    base_topic = reg.namespace.replace(".", "/")
    setpoints: dict[str, float] = {}
    for z in reg.zones:
        idx = [q.zone_id for q in reg.zones if q.parameter_id == z.parameter_id].index(z.zone_id)
        setpoints[z.channel] = TARGETS.get(z.parameter_id, [100])[idx % len(TARGETS.get(z.parameter_id, [100]))]
    brief: dict[str, tuple[float, float]] = {}  # channel -> (until, original)
    limits = bands()
    # Drift only where the band is wide against the noise, so the noise alone can't flicker it in and out
    drifting = [z.channel for z in reg.zones if z.parameter_id in limits
                and limits[z.parameter_id][1] - limits[z.parameter_id][0] > 5 * NOISE.get(z.parameter_id, 0.2)]
    drift: tuple[str, float, bool] | None = None  # (channel, started, goes Critical)
    drifts = 0

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"centerline-sim-{socket.gethostname()}",
                         protocol=mqtt.MQTTv5)
    client.connect(args.host, args.port, keepalive=10)
    client.loop_start()
    t_start = time.time()
    next_brief = t_start + args.brief_every if args.brief_every else float("inf")
    next_mismatch = t_start + min(args.mismatch_every, 60) if args.mismatch_every else float("inf")  # the first soon
    next_drift = t_start + args.drift_every if args.drift_every and drifting else float("inf")
    next_stop = t_start + args.machine_stop_every if args.machine_stop_every else float("inf")
    stopped_until = 0.0
    print(f"publishing to {args.host}:{args.port} under {base_topic}/<area>, Ctrl+C to stop")
    try:
        while not args.seconds or time.time() - t_start < args.seconds:
            now = time.time()
            if now >= next_brief:
                ch = rng.choice(list(setpoints))
                if ch not in brief:
                    brief[ch] = (now + rng.uniform(5, 40), setpoints[ch])
                    setpoints[ch] += rng.choice([-2, 2])
                next_brief = now + args.brief_every
            if now >= next_mismatch:
                ch = rng.choice(list(setpoints))
                if ch not in brief:
                    brief[ch] = (now + args.mismatch_for, setpoints[ch])
                    setpoints[ch] += rng.choice([-2, 2])
                next_mismatch = now + args.mismatch_every
            for ch, (until, original) in list(brief.items()):
                if now >= until:
                    setpoints[ch] = original
                    del brief[ch]
            if now >= next_drift and drift is None:
                drifts += 1
                drift = (rng.choice(drifting), now, drifts % 2 == 0)
                next_drift = now + args.drift_every
            offset: dict[str, float] = {}
            if drift:
                ch, started, critical = drift
                warn, crit = limits[ch.split(".", 1)[0]]
                if now - started < WARNING_S:
                    offset[ch] = (warn + crit) / 2  # in the Warning band
                elif critical and now - started < WARNING_S + CRITICAL_S:
                    offset[ch] = crit * 1.5  # beyond Critical
                else:
                    drift = None
            if now >= next_stop:
                stopped_until, next_stop = now + args.machine_stop_for, now + args.machine_stop_every
            running = now >= stopped_until

            areas: dict[str, dict] = {}
            for z in reg.zones:
                sp = setpoints[z.channel]
                noise = NOISE.get(z.parameter_id, 0.2)
                areas.setdefault(reg.group_of(z.setpoint), {})[z.setpoint.rsplit(".", 1)[1]] = sp
                actual = sp + offset.get(z.channel, 0) + rng.gauss(0, noise)
                areas.setdefault(reg.group_of(z.actual), {})[z.actual.rsplit(".", 1)[1]] = round(actual, 2)
            for name, tag in reg.context.items():
                value = (1 if running else 0) if name == "machine_run" else (41 if running else 0)
                areas.setdefault(reg.group_of(tag), {})[tag.rsplit(".", 1)[1]] = value
            if args.sku_field:
                area, field = args.sku_field.split(".", 1)
                areas.setdefault(area, {})[field] = args.sku

            for area, fields in areas.items():
                if args.stop_area == area and now - t_start >= args.stop_after:
                    continue
                payload = {"_name": area, "_model": area, "_timestamp": round((now + args.skew_s) * 1000),
                           "plantID": "Unilever_Ph_Nutrition", "areaID": "Filling", "lineID": "Volpak",
                           "machineID": "Filler", **fields}
                client.publish(f"{base_topic}/{area}", json.dumps(payload), qos=args.qos, retain=args.retain)
            time.sleep(max(0.0, 1 / args.rate - (time.time() - now)))
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
