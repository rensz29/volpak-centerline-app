"""Fixtures: the mock Timebase from tools/timebase-analysis/tests, served in-process, a fresh
PostgreSQL database per test on the development server (deploy/dev/compose.yaml), and clients
signed in through the real login endpoint (ADR-0016).
"""

from __future__ import annotations

import importlib.util
import itertools
import os
import shutil
import threading
import uuid
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from centerline_api.analytics import service
from centerline_api.auth import users
from centerline_api.auth.deps import CSRF_HEADER
from centerline_api.main import create_app
from centerline_api.settings import AnalyticsSettings, AuthSettings, Settings
from centerline_common import migrate, roles
from centerline_common.db import DatabaseConfig, DatabaseUnavailable

REPO = Path(__file__).resolve().parents[3]
MOCK = REPO / "tools" / "timebase-analysis" / "tests" / "mock_timebase.py"
SERVER = DatabaseConfig()  # used only to create and drop the test databases, never for test data
# The register the mock Timebase was built for; the live config/ one changes as the owner edits it
REGISTER = MOCK.parent / "parameter-register.json"
# Cheap Argon2 parameters: a test signs in many times. The api's defaults are the production ones.
FAST_AUTH = AuthSettings(argon2_time_cost=1, argon2_memory_kib=8192, argon2_parallelism=1)
PASSWORD = "a test password nobody uses"
OWNER = ("MANAGER", "ADMINISTRATOR")  # what the owner's account will be: every test that isn't about roles uses it
_accounts = itertools.count(1)


@pytest.fixture(scope="session")
def mock_timebase():
    spec = importlib.util.spec_from_file_location("mock_timebase", MOCK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    server = ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield mod, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="session")
def db_server():
    try:
        admin = SERVER.connect(autocommit=True)
    except DatabaseUnavailable as e:
        pytest.skip(f"needs the development database ({e}); start it with docker compose -f deploy/dev/compose.yaml up -d")
    template = f"centerline_test_template_{os.getpid()}"
    admin.execute(f'DROP DATABASE IF EXISTS "{template}"')
    admin.execute(f'CREATE DATABASE "{template}"')
    with replace(SERVER, dbname=template).connect() as conn:
        migrate.apply(conn)
    roles.ensure_password(admin)  # the api runs as centerline_app, as in production (ADR-0020)
    yield admin, template
    admin.execute(f'DROP DATABASE IF EXISTS "{template}" WITH (FORCE)')
    admin.close()


@pytest.fixture
def database(db_server) -> DatabaseConfig:
    """A migrated database of this test's own, as the services' role (ADR-0020), dropped afterwards."""
    admin, template = db_server
    name = f"centerline_test_{uuid.uuid4().hex[:12]}"
    admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
    yield roles.app_database(replace(SERVER, dbname=name))
    admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def owner(database) -> DatabaseConfig:
    """The same database as its owner: migrations, and tampering the services' role can't do."""
    return replace(SERVER, dbname=database.dbname)


def make_settings(url: str, tmp_path: Path, database: DatabaseConfig, auth: AuthSettings | None = None,
                  **analytics) -> Settings:
    # Each test gets its own config dir with a copy of the register, so nothing touches config/.
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    register = config_dir / "parameter-register.json"
    if not register.exists():
        shutil.copy(REGISTER, register)
    migrations = replace(SERVER, dbname=database.dbname) if database.user == roles.APP_ROLE else None
    return Settings(timebase={"base_url": url, "dataset": "dressings", "auth": {"type": "none"}, "timeout_s": 10},
                    register_path=register, analytics=AnalyticsSettings(**analytics),
                    audit_log=tmp_path / "audit.jsonl", config_dir=config_dir, database=database, auth=auth or FAST_AUTH,
                    migrate_database=migrations)


def new_client(app, address: str = "127.0.0.1") -> TestClient:
    """A browser: https (the cookie is Secure) and the CSRF header on every request."""
    return TestClient(app, base_url="https://testserver", headers={CSRF_HEADER: "1"}, client=(address, 50000))


def add_account(app, database: DatabaseConfig, roles=OWNER, username: str | None = None, password: str = PASSWORD,
                **fields) -> str:
    """An account whose own password is already set, so it needn't change it first; returns the username."""
    username = username or f"user{next(_accounts)}"
    with database.connect() as conn:
        account, _ = users.create(conn, app.state.passwords, app.state.settings.auth,
                                  {"username": username, "display_name": fields.pop("display_name", username.title()),
                                   "roles": sorted(roles), **fields}, "test")
        conn.execute("UPDATE app_user SET password_hash = %s, must_change = false, temp_expires_at = NULL WHERE id = %s",
                     (app.state.passwords.hash(password), account["id"]))
        conn.commit()
    return username


def sign_in(client: TestClient, name: str, password: str = PASSWORD) -> dict:
    r = client.post("/api/v1/auth/login", json={"name": name, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def make_client(mock_timebase, tmp_path, database):
    service._tag_cache.clear()

    def _make(roles=OWNER, auth: AuthSettings | None = None, address: str = "127.0.0.1", **analytics) -> TestClient:
        """A client signed in with those roles (None: not signed in); the app is at client.app."""
        client = new_client(create_app(make_settings(mock_timebase[1], tmp_path, database, auth=auth, **analytics)), address)
        if roles:
            sign_in(client, add_account(client.app, database, roles))
        return client

    return _make
