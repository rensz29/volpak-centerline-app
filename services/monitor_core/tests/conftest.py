"""A fresh, migrated database per test, seeded with what monitor-core judges against:
the test register, a tag mapping and rules in effect, with every zone's target."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace

import pytest
from psycopg.types.json import Jsonb

from centerline_common import mapping as mapping_mod
from centerline_common import migrate, roles
from centerline_common.db import DatabaseConfig, DatabaseUnavailable, uuid7
from monitor_helpers import BASE, PROPOSED, REG, REGISTER, targets

SERVER = DatabaseConfig()  # only creates and drops the test databases


@pytest.fixture(scope="session")
def monitor_template():
    try:
        admin = SERVER.connect(autocommit=True)
    except DatabaseUnavailable as e:
        pytest.skip(f"needs the development database ({e}); start it with docker compose -f deploy/dev/compose.yaml up -d")
    name = f"centerline_test_monitor_{os.getpid()}"
    admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
    admin.execute(f'CREATE DATABASE "{name}"')
    with replace(SERVER, dbname=name).connect() as conn:
        migrate.apply(conn)
    roles.ensure_password(admin)
    yield admin, name
    admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    admin.close()


@pytest.fixture
def database(monitor_template) -> DatabaseConfig:
    admin, template = monitor_template
    name = f"centerline_test_{uuid.uuid4().hex[:12]}"
    admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
    yield roles.app_database(replace(SERVER, dbname=name))  # monitor-core runs as centerline_app (ADR-0020)
    admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def owner(database) -> DatabaseConfig:
    """The same database as its owner, for what the services' role mustn't be able to do."""
    return replace(SERVER, dbname=database.dbname)


def seed(conn, delays: dict | None = None) -> None:
    """Register, mapping v1 and rules v1 in effect, as the Configuration page would leave them."""
    raw = json.loads(REGISTER.read_text(encoding="utf-8"))
    rid = uuid7()
    conn.execute("INSERT INTO register_version (id, number, content, sha256, reason) VALUES (%s, %s, %s, 'x', 'test')",
                 (rid, raw["version"], Jsonb(raw)))
    mid = uuid7()
    conn.execute("""INSERT INTO mapping_version (id, number, register_version_id, source, sha256, reason)
                    VALUES (%s, 1, %s, 'test', 'x', 'test')""", (mid, rid))
    for r in mapping_mod.required(REG):
        area, field = r.tag.split(".", 1)
        conn.execute("INSERT INTO tag_mapping (mapping_version_id, tag, topic, field) VALUES (%s, %s, %s, %s)",
                     (mid, r.tag, f"{BASE}/{area}", field))
    conn.execute("INSERT INTO mapping_activation (id, mapping_version_id, effective_at, reason) VALUES (%s, %s, now() - interval '1 s', 't')",
                 (uuid7(), mid))
    settings = {"pause_when_stopped": {"enabled": True, "long_stop_min": 10, "warmup_min": 30},
                "defaults": {"mismatch_delay_s": 30, "warning_delay_s": 30, "critical_delay_s": 10, "recovery_delay_s": 15,
                             "brief_change_mode": "lightweight", "warning_notifications": True, **(delays or {})}}
    cid = uuid7()
    conn.execute("""INSERT INTO config_version (id, number, register_version_id, settings, sha256, reason)
                    VALUES (%s, 1, %s, %s, 'x', 'test')""", (cid, rid, Jsonb(settings)))
    for pid, (a, b, c, d) in PROPOSED.items():
        conn.execute("""INSERT INTO parameter_rule (config_version_id, parameter_id, warn_low, warn_high, crit_low, crit_high)
                        VALUES (%s, %s, %s, %s, %s, %s)""", (cid, pid, a, b, c, d))
    for z in REG.zones:
        conn.execute("INSERT INTO parameter_rule (config_version_id, parameter_id, zone_id, target) VALUES (%s, %s, %s, %s)",
                     (cid, z.parameter_id, z.zone_id, targets()[z.channel]))
    conn.execute("INSERT INTO config_activation (id, config_version_id, effective_at, reason) VALUES (%s, %s, now() - interval '1 s', 't')",
                 (uuid7(), cid))
    conn.commit()


@pytest.fixture
def seeded(database):
    with database.connect() as conn:
        seed(conn)
    return database
