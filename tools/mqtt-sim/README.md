# MQTT simulator: development and G1 tests

Publishes Volpak-shaped data to a **local** broker so monitor-core can be
built and tested without the machine. It replaces the `tools/opcua-sim`
planned in the SDD. It publishes one JSON message per machine area on
`Unilever_Ph_Nutrition/Dressings_Halal/Filling/Volpak/Filler/<area>`, with
every register zone's setpoint and actual plus `_timestamp`, in the shape seen
on the plant UNS.

```bash
pip install -r requirements.txt
docker run -d --name mosquitto -p 1883:1883 eclipse-mosquitto:2 mosquitto -c /mosquitto-no-auth.conf
python mqtt_sim.py                                  # steady values, 1 message/s per area
```

| Scenario | Flags |
|---|---|
| Operator tweaks (HMI mismatch, brief changes) | `--brief-every 30` |
| A mismatch nobody puts back for 10 min: the operator's reason request stays open (ADR-0025) | `--mismatch-every 300 --mismatch-for 600` |
| Edge clock offset like the plant (about −114 s) | `--skew-s -114` |
| One area stops publishing (stale data, pause gate) | `--stop-area SPC --stop-after 60` |
| SKU field present (ADR-0001 changeover tests) | `--sku-field SPC.SKU_Code --sku 67890123` |
| Retained messages (snapshot on resume) | `--retain` |
| A zone's actual leaving its band: Warning 60 s, and on every other drift Critical 60 s more (bands from the Rules proposal) | `--drift-every 150` |
| The machine stopping (Machine_Run 0): Actual rules pause (ADR-0010) | `--machine-stop-every 900 --machine-stop-for 120` |

It refuses to publish to any broker that isn't on this machine unless the
exact host is passed with `--allow-host`. Never point it at the plant UNS:
fake setpoints would reach Timebase and every other subscriber.
