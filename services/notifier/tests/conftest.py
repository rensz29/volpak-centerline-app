"""A fresh, migrated database per test, and fake Teams and SMTP endpoints for the notifier to send to."""

from __future__ import annotations

import json
import os
import socketserver
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from psycopg.types.json import Jsonb

from centerline_common import migrate, roles
from centerline_common import routing as routing_mod
from centerline_common.db import DatabaseConfig, DatabaseUnavailable, uuid7

SERVER = DatabaseConfig()  # only creates and drops the test databases
ALL_TYPES = list(routing_mod.TYPES)
SIG = "sig=NOT-A-REAL-SIGNATURE-9f8e7d"


@pytest.fixture(scope="session")
def notifier_template():
    try:
        admin = SERVER.connect(autocommit=True)
    except DatabaseUnavailable as e:
        pytest.skip(f"needs the development database ({e}); start it with docker compose -f deploy/dev/compose.yaml up -d")
    name = f"centerline_test_notifier_{os.getpid()}"
    admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
    admin.execute(f'CREATE DATABASE "{name}"')
    with replace(SERVER, dbname=name).connect() as conn:
        migrate.apply(conn)
    roles.ensure_password(admin)
    yield admin, name
    admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    admin.close()


@pytest.fixture
def database(notifier_template) -> DatabaseConfig:
    admin, template = notifier_template
    name = f"centerline_test_{uuid.uuid4().hex[:12]}"
    admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
    yield roles.app_database(replace(SERVER, dbname=name))  # the notifier runs as centerline_app (ADR-0020)
    admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def owner(database) -> DatabaseConfig:
    """The same database as its owner, for what the services' role mustn't be able to do."""
    return replace(SERVER, dbname=database.dbname)


def now() -> datetime:
    return datetime.now(timezone.utc)


def use_routing(conn, rules: list[dict], number: int = 1) -> None:
    """A routing version in effect, as the Notifications tab would leave it."""
    rules = routing_mod.normalize(rules)
    vid = uuid7()
    conn.execute("INSERT INTO routing_version (id, number, rules, sha256, reason) VALUES (%s, %s, %s, %s, 'test')",
                 (vid, number, Jsonb(rules), routing_mod.digest(rules)))
    conn.execute("""INSERT INTO routing_activation (id, routing_version_id, effective_at, reason)
                    VALUES (%s, %s, clock_timestamp() - interval '1 s', 't')""", (uuid7(), vid))
    conn.commit()


def notify(conn, kind: str = "system", payload: dict | None = None, at: datetime | None = None, key: str | None = None) -> str:
    """An outbox row as monitor-core writes it (without an event, so no configuration is needed)."""
    nid = uuid7()
    conn.execute("INSERT INTO notification (id, dedup_key, kind, event_id, created_at, payload) VALUES (%s, %s, %s, NULL, %s, %s)",
                 (nid, key or f"test:{nid}", kind, at or now(), Jsonb(payload or {"kind": "Maintenance overdue (MNT-01)",
                                                                                   "reason": "Heater work",
                                                                                   "plannedEnd": now().isoformat()})))
    conn.commit()
    return str(nid)


def write_channels(config_dir, teams_url: str | None = None, smtp_port: int | None = None, app_url: str = "http://centerline.test"):
    """connections.json and the flow URL's secret file, as the Configuration page writes them."""
    (config_dir / "secrets").mkdir(parents=True, exist_ok=True)
    stored: dict = {"app_url": app_url, "line": "Volpak", "teams": None, "email": None}
    if teams_url:
        (config_dir / "secrets" / "teams-flow-url").write_text(teams_url + "\n")
        stored["teams"] = {"url_file": "secrets/teams-flow-url", "timeout_s": 5}
    if smtp_port:
        stored["email"] = {"host": "127.0.0.1", "port": smtp_port, "security": "none", "username": "", "password_file": None,
                           "sender": "centerline@plant.test", "timeout_s": 5}
    (config_dir / "connections.json").write_text(json.dumps({"notifications": stored}))


class FakeTeams:
    """A Power Automate HTTP trigger: records each POST's JSON and answers `status` (202, as the flow does)."""

    def __init__(self):
        self.received: list[dict] = []
        self.status = 202
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fake.received.append({"path": self.path, "json": json.loads(body)})
                self.send_response(fake.status)
                self.end_headers()

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/workflows/x/triggers/manual/paths/invoke?api-version=2016-06-01&{SIG}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class FakeSmtp:
    """Just enough of an SMTP relay: records each message it answers 250 to. It can refuse a recipient
    with 550, or drop the connection after a message's body, before answering it."""

    def __init__(self):
        self.messages: list[dict] = []
        self.refuse: set[str] = set()
        self.drops = 0  # how many more messages to drop before their 250
        self.dropped: list[bytes] = []
        fake = self

        class Handler(socketserver.StreamRequestHandler):
            def say(self, line: str):
                self.wfile.write(line.encode() + b"\r\n")

            def handle(self):
                self.say("220 fake-relay ESMTP")
                sender, rcpt = None, None
                while line := self.rfile.readline():
                    cmd = line.decode("utf-8", "replace").strip()
                    verb = cmd.split(" ", 1)[0].upper()
                    if verb in ("EHLO", "HELO"):
                        self.say("250 fake-relay")
                    elif verb == "MAIL":
                        sender = cmd.split(":", 1)[1].strip("<> ")
                        self.say("250 OK")
                    elif verb == "RCPT":
                        rcpt = cmd.split(":", 1)[1].strip("<> ")
                        self.say("550 no such user" if rcpt in fake.refuse else "250 OK")
                    elif verb == "DATA":
                        self.say("354 go ahead")
                        data = b""
                        while (chunk := self.rfile.readline()) not in (b".\r\n", b""):
                            data += chunk
                        if fake.drops > 0:
                            fake.drops -= 1
                            fake.dropped.append(data)
                            return  # gone before the 250
                        fake.messages.append({"from": sender, "to": rcpt, "data": data})
                        self.say(f"250 2.0.0 queued as Q{len(fake.messages)}")
                    elif verb == "QUIT":
                        self.say("221 bye")
                        return
                    else:
                        self.say("250 OK")

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def teams():
    fake = FakeTeams()
    yield fake
    fake.close()


@pytest.fixture
def smtp():
    fake = FakeSmtp()
    yield fake
    fake.close()


def later(t: datetime, **delta) -> datetime:
    return t + timedelta(**delta)
