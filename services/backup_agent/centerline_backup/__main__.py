"""python -m centerline_backup [--config backup.json] [run | now [--check] | list]

  run          the service: a backup set every hour, a few minutes past it (the default)
  now          one backup set now, copied off-host and pruned as the service does; --check restores it to check it
  list         the sets here and off-host, with their sizes and restore checks
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import threading
from datetime import datetime, timedelta, timezone

from .agent import Agent, BackupError, load_settings, sets

log = logging.getLogger("centerline.backup")


def next_due(now: datetime, minute: int) -> datetime:
    due = (now + timedelta(hours=1)).replace(minute=minute, second=0, microsecond=0)
    return due - timedelta(hours=1) if due - now > timedelta(hours=1) else due


def serve(agent: Agent) -> None:
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    s = agent.s
    log.info("backing up %s every hour to %s; off-host: %s", s.database.describe(), s.backup_dir,
             s.offhost_dir or "not set (CENTERLINE_BACKUP_OFFHOST in deploy/.env)")
    present = sets(s.backup_dir)
    now = datetime.now(timezone.utc)
    # At start, a set now unless the last is recent; then a few minutes past each hour
    due = now if not present or now - present[-1][0] >= timedelta(seconds=s.every_s - 300) else next_due(now, s.minute)
    cleaned_for = None  # the storage episode (its "since") last cleaned for
    while not stop.is_set():
        now = datetime.now(timezone.utc)
        if now >= due:
            agent.run_once()
            due = next_due(datetime.now(timezone.utc), s.minute)
        # Every minute: monitor-core at 90 % asks for the eligible cleanup, once per episode (RES-02)
        try:
            storage = agent.storage_state()
            if storage and storage.get("state") in ("cleanup", "degraded") and storage.get("since") != cleaned_for:
                agent.cleanup(storage)
                cleaned_for = storage.get("since")
        except BackupError as e:
            log.debug("storage state unknown: %s", e)
        stop.wait(max(1.0, min(60.0, (due - datetime.now(timezone.utc)).total_seconds())))


def show(agent: Agent) -> None:
    for title, folder in (("here", agent.s.backup_dir), ("off-host", agent.s.offhost_dir)):
        if folder is None:
            print(f"{title}: no off-host folder (CENTERLINE_BACKUP_OFFHOST in deploy/.env)")
            continue
        found = sets(folder)
        print(f"{title}: {folder} ({len(found)} sets)")
        for _, path in found:
            m = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
            size = sum(f["bytes"] for f in m["files"].values()) / 1e6
            check = m.get("check") or {}
            checked = {"restored": "restore check passed", "failed": f"restore check FAILED: {check.get('error')}"}.get(check.get("result"), "")
            print(f"  {path.name}  {size:7.2f} MB  {checked}")
    status = agent.status()
    if status:
        print(f"last success: {status.get('last_success') or 'never'}; last error: {status.get('error') or 'none'}")


def main() -> int:
    ap = argparse.ArgumentParser(prog="centerline_backup", description="the backup agent (BKP-01/02, ADR-0035)")
    ap.add_argument("--config", help="settings file (default: CENTERLINE_BACKUP_CONFIG or services/backup_agent/config.json)")
    ap.add_argument("command", nargs="?", default="run", choices=["run", "now", "list"])
    ap.add_argument("--check", action="store_true", help="now: restore the new set into a scratch database to check it")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.umask(0o077)  # the sets hold every record and this host's secrets: this user only
    agent = Agent(load_settings(args.config))
    if args.command == "list":
        show(agent)
        return 0
    if args.command == "now":
        return 0 if agent.run_once(check=True if args.check else None) else 1
    serve(agent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
