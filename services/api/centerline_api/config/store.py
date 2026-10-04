"""Connection settings behind the Configuration page (ADR-0011, ADR-0012).

Files under the configured config dir, next to their secrets:

* ``connections.json``: MQTT broker and historian settings, without secrets (git-ignored)
* ``secrets/``: passwords, tokens and the broker's CA certificate, readable by this user only

They are deployment settings the tools and, later, monitor-core read at start-up,
so they stay files. Every change is audited in the database (config/audit.py);
the register and the rules live there too (register_store.py, rules_store.py).

Secrets are write-only: they're stored, never returned. The page only learns
whether one is set.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import urllib.parse
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from centerline_common import connections as connections_mod
from centerline_common import routing as routing_mod

from ..problems import Problem
from . import audit

DEFAULT_FRESHNESS_S = {"SPC": 30, "Dosing_Parameters": 90}  # ADR-0006, measured on 28 days


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_atomic(path: Path, text: str, mode: int | None = None) -> None:
    """Write via a temporary file and rename, so readers never see half a file.

    Without ``mode`` an existing file keeps its permissions and a new one gets 0644
    (mkstemp alone would leave 0600).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def invalid(message: str, errors: list[dict]) -> Problem:
    return Problem(422, "invalid-configuration", "The configuration is invalid",
                   message if not errors else "; ".join(e["message"] for e in errors), errors=errors)


class ConnectionsStore:
    """connections.json plus secrets/. The historian falls back to the api config file."""

    def __init__(self, config_dir: Path, default_historian: dict, namespace: str):
        self.dir = config_dir
        self.path = config_dir / "connections.json"
        self.secrets = config_dir / "secrets"
        self.default_historian = default_historian
        self.namespace = namespace

    # -- files ------------------------------------------------------------------

    def _read(self) -> dict:
        return connections_mod.load(self.dir)

    def _write(self, data: dict) -> None:
        data["updatedAt"] = now_iso()
        write_atomic(self.path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def put_secret(self, name: str, value: str) -> str:
        self.secrets.mkdir(parents=True, exist_ok=True)
        os.chmod(self.secrets, 0o700)
        write_atomic(self.secrets / name, value.strip() + "\n", mode=0o600)
        return f"secrets/{name}"

    def drop_secret(self, name: str) -> None:
        (self.secrets / name).unlink(missing_ok=True)

    def resolve(self, ref: str | None) -> str | None:
        return connections_mod.resolve(self.dir, ref)

    def secret_set(self, ref: str | None) -> bool:
        path = self.resolve(ref)
        return bool(path) and Path(path).exists()

    def read_secret(self, ref: str | None) -> str | None:
        return connections_mod.read_secret(self.dir, ref)

    # -- historian --------------------------------------------------------------

    def historian(self) -> dict:
        return self._read().get("historian") or deepcopy(self.default_historian)

    def historian_client_config(self, stored: dict | None = None) -> dict:
        cfg = deepcopy(stored or self.historian())
        auth = dict(cfg.get("auth") or {"type": "none"})
        for key in ("token_file", "password_file"):
            if auth.get(key):
                auth[key] = self.resolve(auth[key])
        cfg["auth"] = auth
        return cfg

    def build_historian(self, body, keep_existing: bool = True) -> dict:
        """Stored-form historian settings from the page's fields; empty secrets keep the saved ones."""
        old_auth = (self.historian().get("auth") or {}) if keep_existing else {}
        auth: dict = {"type": body.auth_type}
        errors = []
        if body.auth_type == "bearer":
            ref = self.put_secret("timebase-token", body.token) if body.token else old_auth.get("token_file")
            if not ref:
                errors.append({"field": "token", "message": "Enter the bearer token"})
            auth["token_file"] = ref
        elif body.auth_type == "basic":
            if not body.username:
                errors.append({"field": "username", "message": "Enter the user name"})
            ref = self.put_secret("timebase-password", body.password) if body.password else old_auth.get("password_file")
            if not ref:
                errors.append({"field": "password", "message": "Enter the password"})
            auth |= {"username": body.username, "password_file": ref}
        if errors:
            raise invalid("Historian settings are incomplete", errors)
        return {"type": "timebase", "base_url": body.base_url.rstrip("/"), "dataset": body.dataset,
                "timeout_s": body.timeout_s, "verify_tls": body.verify_tls, "auth": auth}

    def save_historian(self, stored: dict, reason: str, conn) -> None:
        """Write the file and audit it; the caller commits."""
        audit.record(conn, "connections.historian",
                     f"Historian set to {stored['base_url']} · dataset {stored['dataset']} · auth {stored['auth']['type']}", reason)
        data = self._read()
        data["historian"] = stored
        self._write(data)

    # -- MQTT -------------------------------------------------------------------

    def mqtt(self) -> dict:
        stored = self._read().get("mqtt")
        if stored:
            return stored
        return {"host": "", "port": 8883, "protocol": "5",
                "tls": {"enabled": True, "ca_file": None, "verify_hostname": True},
                "username": "", "password_file": None, "client_id": "", "keepalive_s": 5,
                "subscriptions": [self.namespace.replace(".", "/") + "/#"],
                "freshness_s": dict(DEFAULT_FRESHNESS_S)}

    def build_mqtt(self, body) -> dict:
        old = self.mqtt()
        errors = []
        ca_ref = old.get("tls", {}).get("ca_file")
        if body.clear_ca:
            self.drop_secret("mqtt-ca.pem")
            ca_ref = None
        if body.ca_pem:
            if "-----BEGIN CERTIFICATE-----" not in body.ca_pem:
                errors.append({"field": "caPem", "message": "Paste a PEM certificate (-----BEGIN CERTIFICATE-----)"})
            else:
                ca_ref = self.put_secret("mqtt-ca.pem", body.ca_pem)
        pw_ref = old.get("password_file")
        if body.clear_password:
            self.drop_secret("mqtt-password")
            pw_ref = None
        if body.password:
            pw_ref = self.put_secret("mqtt-password", body.password)
        if errors:
            raise invalid("MQTT settings are invalid", errors)
        return {"host": body.host.strip(), "port": body.port, "protocol": body.protocol,
                "tls": {"enabled": body.tls_enabled, "ca_file": ca_ref, "verify_hostname": body.verify_hostname},
                "username": body.username.strip(), "password_file": pw_ref,
                "client_id": body.client_id.strip(), "keepalive_s": body.keepalive_s,
                "subscriptions": [s.strip() for s in body.subscriptions if s.strip()],
                "freshness_s": {k: int(v) for k, v in body.freshness_s.items()}}

    def save_mqtt(self, stored: dict, reason: str, conn) -> None:
        """Write the file and audit it; the caller commits."""
        audit.record(conn, "connections.mqtt",
                     f"MQTT broker set to {stored['host']}:{stored['port']} · TLS "
                     f"{'on' if stored['tls']['enabled'] else 'off'} · user {stored['username'] or '(anonymous)'}", reason)
        data = self._read()
        data["mqtt"] = stored
        self._write(data)

    def mqtt_client_config(self, stored: dict | None = None, password: str | None = None) -> dict:
        return connections_mod.mqtt_client_config(self.dir, stored or self.mqtt(), password)

    # -- notifications (ADR-0023) ------------------------------------------------------

    def notifications(self) -> dict:
        return self._read().get("notifications") or {}

    def build_notifications(self, body) -> dict:
        """Stored-form channel settings from the page's fields; secrets are written only once the form is valid."""
        old = self.notifications()
        errors = []
        app_url = body.app_url.strip().rstrip("/")
        if app_url and not re.fullmatch(r"https?://[^\s/]+(/\S*)?", app_url):
            errors.append({"field": "appUrl", "message": "The address people open Centerline at, e.g. https://centerline.plant.local"})
        teams_url = body.teams_url.strip()
        if teams_url:
            parts = urllib.parse.urlsplit(teams_url)
            local = parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost")  # tools/notify-sink, for development
            if not (parts.scheme == "https" or local) or not parts.hostname:
                errors.append({"field": "teamsUrl", "message": "Paste the flow's HTTP POST URL; it starts with https://"})
        host, sender = body.smtp_host.strip(), body.email_sender.strip()
        if host and not sender:
            errors.append({"field": "emailSender", "message": "The From address, e.g. centerline@plant.local"})
        elif sender and not routing_mod.EMAIL.fullmatch(sender):
            errors.append({"field": "emailSender", "message": f"{sender} isn't an email address"})
        if sender and not host:
            errors.append({"field": "smtpHost", "message": "The plant's SMTP relay, from IT"})
        if errors:
            raise invalid("Notification settings are invalid", errors)

        teams = dict(old.get("teams") or {})
        if body.clear_teams:
            self.drop_secret("teams-flow-url")
            teams = {}
        if teams_url:
            teams = {"url_file": self.put_secret("teams-flow-url", teams_url), "timeout_s": 15}
        email = dict(old.get("email") or {})
        pw_ref = email.get("password_file")
        if body.clear_smtp_password:
            self.drop_secret("smtp-password")
            pw_ref = None
        if body.smtp_password:
            pw_ref = self.put_secret("smtp-password", body.smtp_password)
        email = {"host": host, "port": body.smtp_port, "security": body.smtp_security, "username": body.smtp_username.strip(),
                 "password_file": pw_ref, "sender": sender, "timeout_s": 20} if host else {}
        return {"app_url": app_url or None, "line": old.get("line") or "Volpak", "teams": teams or None, "email": email or None}

    def save_notifications(self, stored: dict, reason: str, conn) -> None:
        """Write the file and audit it; the caller commits."""
        e = stored["email"]
        email = f"via {e['host']}:{e['port']} from {e['sender']}" if e else "not set"
        audit.record(conn, "connections.notifications",
                     f"Notifications: Teams {'set' if stored['teams'] else 'not set'} · email {email} · links to "
                     f"{stored['app_url'] or '(none)'}", reason)
        data = self._read()
        data["notifications"] = stored
        self._write(data)

    def email_check_config(self, body) -> dict:
        """The form's relay, with the saved password unless one was typed: for the test, nothing is stored."""
        saved = (self.notifications().get("email") or {}).get("password_file")
        return {"host": body.smtp_host.strip(), "port": body.smtp_port, "security": body.smtp_security,
                "username": body.smtp_username.strip(), "sender": body.email_sender.strip() or "centerline@localhost",
                "password": body.smtp_password or (None if body.clear_smtp_password else self.read_secret(saved)), "timeout_s": 10}

    def notifications_public(self) -> dict:
        n = self.notifications()
        teams, email = n.get("teams") or {}, n.get("email") or {}
        url = self.read_secret(teams.get("url_file"))
        parts = urllib.parse.urlsplit(url) if url else None
        return {"appUrl": n.get("app_url") or "", "line": n.get("line") or "Volpak",
                "teams": {"configured": bool(url), "where": f"{parts.scheme}://{parts.hostname}" if parts else None},
                "email": {"configured": bool(email.get("host") and email.get("sender")), "host": email.get("host", ""),
                          "port": email.get("port", 25), "security": email.get("security", "none"),
                          "username": email.get("username", ""), "passwordSet": self.secret_set(email.get("password_file")),
                          "sender": email.get("sender", "")}}

    # -- what the page may see ----------------------------------------------------

    def public(self) -> dict:
        data = self._read()
        h = self.historian()
        auth = h.get("auth") or {}
        m = self.mqtt()
        tls = m.get("tls") or {}
        return {
            "historian": {"baseUrl": h.get("base_url", ""), "dataset": h.get("dataset", ""),
                          "timeoutS": h.get("timeout_s", 60), "verifyTls": h.get("verify_tls", True),
                          "authType": auth.get("type", "none"), "username": auth.get("username", ""),
                          "tokenSet": self.secret_set(auth.get("token_file")),
                          "passwordSet": self.secret_set(auth.get("password_file")),
                          "source": "configuration page" if data.get("historian") else "api config file"},
            "mqtt": {"configured": bool(data.get("mqtt")), "host": m.get("host", ""), "port": m.get("port", 8883),
                     "protocol": str(m.get("protocol", "5")), "tlsEnabled": bool(tls.get("enabled")),
                     "verifyHostname": tls.get("verify_hostname", True), "caSet": self.secret_set(tls.get("ca_file")),
                     "username": m.get("username", ""), "passwordSet": self.secret_set(m.get("password_file")),
                     "clientId": m.get("client_id", ""), "keepaliveS": m.get("keepalive_s", 5),
                     "subscriptions": m.get("subscriptions", []), "freshnessS": m.get("freshness_s", {})},
            "notifications": self.notifications_public(),
            "updatedAt": data.get("updatedAt"),
        }
