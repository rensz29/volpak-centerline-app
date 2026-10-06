# MQTT probe: Phase 0 (ADR-0006)

A read-only listener for the plant broker. It shows what the machine actually
publishes (topics, rates, gaps, payload format, clock offset), where each tag
in the parameter register lives. It
writes `data/topic-map.json`, the tag → topic/field mapping that monitor-core
will import.

The client never publishes and sets no Last Will; `publish` is disabled in
code.

## 1. Install and configure

```bash
pip install -r requirements.txt          # paho-mqtt 2.x
cp config.example.json config.json       # config.json is git-ignored
```

Fill in `host`, `port`, `tls`, `username`, and a `password_file` outside the
repo (`chmod 600`). Leave `subscriptions` as the Volpak subtree unless the
edge team tells you otherwise.

**Or use the broker saved on the Configuration page**
([ADR-0011](../../docs/decisions/ADR-0011-configuration-page.md)) and skip
`config.json`: pass `../../config/connections.json` instead. The probe then
uses the saved host, account, password, CA certificate and topic filters, and
the register next to it.

## 2. Run

```bash
python mqtt_probe.py config.json --seconds 3600
python mqtt_probe.py ../../config/connections.json --seconds 3600   # the broker saved on the Configuration page
python mqtt_probe.py ../../config/connections.json --seconds 3600 --out data/running   # keep each run's files apart
```

The `topic-map.json` it writes can be loaded on **Configuration → Mappings**
([ADR-0013](../../docs/decisions/ADR-0013-tag-mappings.md)).

Run it for an hour at least once while the machine runs and once while it's
stopped. Output lands in `data/`, or the folder given with `--out`:

| File | Contents |
|---|---|
| `mqtt-probe-report.md` | Connection result, topics, gaps, "silent at end" (a stopped publisher), tag mapping, freshness threshold |
| `topic-map.json` | `tag → {topic, field}` for every register tag seen, plus the ones not seen |
| `samples.jsonl` | The first payloads per topic |

Record the results in [ADR-0006](../../docs/decisions/ADR-0006-mqtt-acquisition.md).

## 3. Publish-rejection test (control M4)

Prove the Centerline account can't publish. Use a **dedicated test topic,
never a data or command topic**:

```bash
read -rs MQTT_PW          # type the password; keeps it out of shell history
mosquitto_pub -h <broker> -p 8883 --cafile ~/.secrets/plant-ca.pem -V mqttv5 -q 1 -d \
  -u <centerline-user> -P "$MQTT_PW" -t centerline/acl-test -m "ACL test, no production data"
```

**Pass:** `received PUBACK (… rc:135)` (Not authorized), or the broker drops
the connection. **Fail:** `rc:0`, which means the account can publish. Stop
and have the broker admin fix the ACL before Centerline connects again.

## Questions for the UNS / edge team

Send these before the first run. Most of them close items in ADR-0006 and ADR-0007.

1. **Broker:** host, port, TLS on 8883 and the CA certificate.
2. **Account:** a dedicated Centerline user, allowed to **subscribe only** to
   `Unilever_Ph_Nutrition/Dressings_Halal/Filling/Volpak/Filler/#`, and denied
   publish everywhere (control M3).
3. **Payload:** confirm one JSON message per machine area (`SPC`,
   `Dosing_Parameters`) carrying every field plus `_timestamp` (epoch ms).
   Timebase suggests this shape.
4. **Publish mode:** fixed interval or on change? Is there a maximum interval?
   Are messages retained? Timebase shows gaps of up to about 20 s on SPC
   during the last day, but about 1 s in the last hour.
5. **Liveness:** is there a status topic, Last Will or heartbeat when the edge
   publisher or PLC connection dies?
6. **Missing tags:** setpoint/actual pairs for P10 Feed and P11 Film Reel
   (only one tag each so far), and tags for P01 Sealing Temperature,
   P05 Hopper Pressure, P07 Discharge Time and a P08 speed setpoint.
7. **P09 Pressure:** the tag named `Pressure_Setpoint` behaves like a sensor
   (about 21,000 changes a day, 0 when stopped) and `Pressure_Actual` like an
   operator setting (about 35 clean changes a day). Are the names swapped?
8. **Clocks:** the publisher's `_timestamp` runs about 114 s behind real time,
   and the Timebase server about 279 s. Please NTP-sync both.
