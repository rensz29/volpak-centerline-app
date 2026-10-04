# notify-sink: see Centerline's messages without Teams or a relay

A stand-in for the Power Automate flow and the plant's SMTP relay, for development
([ADR-0023](../../docs/decisions/ADR-0023-notifier.md)). It answers like them (HTTP 202,
SMTP 250), prints a line per message, and keeps each one in `data/`: the JSON the flow
would receive (with its Adaptive Card) and the email as an `.eml` file you can open.

```bash
python tools/notify-sink/notify_sink.py      # Teams on :8025, SMTP on :2525, 127.0.0.1 only
```

Then on **Configuration → Connections → Notifications** set:

- Teams flow URL `http://127.0.0.1:8025/flow?sig=dev`. Plain `http` is accepted only for
  127.0.0.1 or localhost; a real flow URL is `https`.
- SMTP relay `127.0.0.1`, port `2525`, security None, no username.

It listens on 127.0.0.1 only and forwards nothing. `data/` is git-ignored.
