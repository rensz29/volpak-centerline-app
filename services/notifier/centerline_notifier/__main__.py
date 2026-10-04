"""python -m centerline_notifier [--config notifier.json]"""

from __future__ import annotations

import argparse
import logging
import signal

from .service import Service, load_settings


def main() -> int:
    ap = argparse.ArgumentParser(prog="centerline_notifier", description="notifier: deliver the outbox to Teams and email")
    ap.add_argument("--config", help="settings file (default: CENTERLINE_NOTIFIER_CONFIG or services/notifier/config.json)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    service = Service(load_settings(args.config))
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: service.stop())
    service.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
