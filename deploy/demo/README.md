# The Centerline demo: working end to end on the simulator

Everything Centerline does, on this PC, apart from the real data:

```bash
services/.venv/bin/python deploy/demo/demo.py start     # then open http://localhost:5174
services/.venv/bin/python deploy/demo/demo.py status
services/.venv/bin/python deploy/demo/demo.py stop
services/.venv/bin/python deploy/demo/demo.py reset     # stop, delete its database and files
```

Sign in as **demo** (Manager and Administrator), with the password in `deploy/demo/state/demo-password`, or
as **operator** to give the reasons, with the password in `deploy/demo/state/operator-password`. This PC is
the operator workstation. The operator's session ends with its shift (06:00, 14:00 and 22:00 Manila), after a
5-min warning, and the next sign-in starts the new shift ([ADR-0025](../../docs/decisions/ADR-0025-shifts-and-reasons.md)).

| Runs | Where |
|---|---|
| A Mosquitto broker, fed by `tools/mqtt-sim` | 127.0.0.1:18833 |
| monitor-core and the notifier | the demo's own database `centerline_demo` |
| `tools/notify-sink` in place of Teams and email | 127.0.0.1:8025 and 2525; messages in `state/sink/` |
| The api and the web app | 127.0.0.1:8010, http://localhost:5174 |

**What happens:**
- Every 45 s the simulator moves a setpoint for 5–40 s. Those that last past the 30 s
  mismatch delay open an HMI mismatch; the others are recorded as brief changes.
- Every 5 min a setpoint moves and stays off target for 10 min: an HMI mismatch whose
  reason request stays open, for the operator to answer on the Reasons page.
- Every 2½ min a zone's actual leaves its band: Warning for 60 s, and on every other
  drift Critical for 60 s more. A Manager can acknowledge a Critical in its event sheet.
- Every 15 min the machine stops for 2 min, and the Actual rules pause.
- Every message goes to the sink, and shows on the Notifications page.

The first start sets it up the way an Administrator and a Manager would on the
Configuration page:
- the broker;
- a mapping found on it;
- the SKU `SIM-SKU-1`, whose targets are the simulator's setpoints;
- the Phase 0 rules proposal;
- the channels and a routing.

Every start also brings the routing up to date: when a newer Centerline has a kind of message the
routing in effect doesn't send, it saves and activates a new version with it.

It never touches the `centerline` database, the plant broker, Timebase, Teams or email.
The real app on :5173 is unchanged.

## The real machine, read-only (`--plant`)

```bash
services/.venv/bin/python deploy/demo/demo.py start --plant     # then open http://localhost:5175
services/.venv/bin/python deploy/demo/demo.py stop --plant
```

monitor-core subscribes to the plant broker saved on the real Configuration page, and
only subscribes ([ADR-0024](../../docs/decisions/ADR-0024-plant-trial.md)). It uses the real
mapping with the placeholder SKU and the Phase 0 rules proposal, so the actual values are judged.
On its first start it also gives the placeholder targets: each zone's HMI setpoint at that moment,
as a new rules version. The Digital Centerline page then shows every zone's target, and HMI
mismatch is judged against it (owner, 2026-10-02). Change the targets on the trial's
Configuration → Rules. It has its own database `centerline_plant_trial`, an api on :8011,
the web app on :5175 and no notifier; sign in as **demo** with the password in
`deploy/demo/plant-state/demo-password`.

It needs the laptop on the plant network, and checks that the broker answers before starting.
