"""The connection settings saved on the Configuration page (ADR-0011): config/connections.json
and the secret files beside it. Read by the api, monitor-core and the notifier; only the api writes them.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path


def load(config_dir: Path) -> dict:
    path = config_dir / "connections.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def resolve(config_dir: Path, ref: str | None) -> str | None:
    """Secrets saved by the page are relative to the config dir; others are the operator's own paths."""
    if not ref:
        return None
    return str(config_dir / ref) if ref.startswith("secrets/") else os.path.expanduser(ref)


def read_secret(config_dir: Path, ref: str | None) -> str | None:
    path = resolve(config_dir, ref)
    return Path(path).read_text(encoding="utf-8").strip() if path and Path(path).exists() else None


def mqtt_client_config(config_dir: Path, stored: dict | None = None, password: str | None = None) -> dict | None:
    """The saved broker ready to connect: CA path resolved, password read. None when none is saved."""
    stored = stored or load(config_dir).get("mqtt")
    if not stored:
        return None
    cfg = deepcopy(stored)
    cfg["tls"] = dict(cfg.get("tls") or {})
    cfg["tls"]["ca_file"] = resolve(config_dir, cfg["tls"].get("ca_file"))
    cfg["password"] = password if password is not None else read_secret(config_dir, cfg.get("password_file"))
    return cfg


def notifications_config(config_dir: Path) -> dict:
    """The saved notification channels, ready to send (ADR-0023): the link base, the line's name, the Power Automate flow with
    its URL read from its secret file, and the SMTP relay with its password. A channel not saved is None."""
    stored = load(config_dir).get("notifications") or {}
    teams = stored.get("teams") or {}
    url = read_secret(config_dir, teams.get("url_file"))
    email = deepcopy(stored.get("email") or {})
    if email.get("host") and email.get("sender"):
        email["password"] = read_secret(config_dir, email.get("password_file"))
    else:
        email = None
    return {"app_url": stored.get("app_url") or None, "line": stored.get("line") or "Volpak",
            "teams": {"url": url, "timeout_s": float(teams.get("timeout_s", 15))} if url else None,
            "email": email}
