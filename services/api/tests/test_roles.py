"""The services' database role (ADR-0020): exactly the privileges decided, and none that could rewrite history."""

from __future__ import annotations

import uuid
from dataclasses import replace

import psycopg
import pytest

from centerline_api.main import create_app
from centerline_common import migrate, roles
from centerline_common.roles import APP_ROLE

from .conftest import SERVER, make_settings, new_client

ADD_READ = {"SELECT", "INSERT"}
UPDATE = ADD_READ | {"UPDATE"}
EXPECTED = {
    "schema_migration": {"SELECT"},
    # evidence and versions: added and read, never changed (DAT-01)
    **{t: ADD_READ for t in ("audit_log", "register_version", "config_version", "sku_parameter_rule", "mapping_version",
                             "tag_mapping", "event", "event_transition", "lightweight_change", "event_acknowledgment",
                             "notification", "app_user_password", "monitoring_switch", "routing_version", "notification_route",
                             "delivery_attempt", "shift_instance", "workflow_entry", "workflow_settings")},
    # also updated: activations (the triggers allow only cancelling) and the operational rows
    **{t: UPDATE for t in ("config_activation", "mapping_activation", "event_state", "scheduled_action", "pause_period",
                           "monitor_heartbeat", "app_user", "maintenance_window", "routing_activation", "notification_delivery",
                           "notifier_heartbeat", "workflow_request")},
    # also deleted: unused SKUs, ended sessions, an account's sign-in names (rewritten by their trigger)
    "sku": UPDATE | {"DELETE"},
    "app_session": UPDATE | {"DELETE"},
    "app_user_login": ADD_READ | {"DELETE"},
}
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


def test_every_table_gives_the_services_role_exactly_what_was_decided(owner):
    with owner.connect() as conn:
        tables = [r["tablename"] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
        actual = {t: {p for p in PRIVILEGES
                      if conn.execute("SELECT has_table_privilege(%s, %s, %s) AS ok", (APP_ROLE, f"public.{t}", p)).fetchone()["ok"]}
                  for t in tables}
        role = conn.execute("""SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolreplication
                                 FROM pg_roles WHERE rolname = %s""", (APP_ROLE,)).fetchone()
        owned = conn.execute("SELECT count(*) AS n FROM pg_tables WHERE tableowner = %s", (APP_ROLE,)).fetchone()["n"]
    assert actual == EXPECTED  # a new table fails here until its grants are decided and listed
    assert not any(role.values()) and owned == 0


def test_the_services_role_cant_rewrite_history_switch_triggers_off_or_change_the_schema(database):
    assert database.user == APP_ROLE
    with database.connect(autocommit=True) as c:
        for statement in ("UPDATE event_transition SET state = 'OPEN'",
                          "DELETE FROM audit_log",
                          "UPDATE audit_log SET summary = 'rewritten'",
                          "TRUNCATE event",
                          "SET session_replication_role = replica",  # would switch every trigger off
                          "ALTER TABLE event DISABLE TRIGGER USER",
                          "DROP TABLE event_transition",
                          "CREATE TABLE sneaky (x int)",
                          "INSERT INTO schema_migration (version, sha256) VALUES ('9999_x', 'x')",
                          "CREATE ROLE sneaky"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(statement)


def test_a_fresh_database_is_migrated_by_the_owner_then_served_as_the_services_role(db_server, mock_timebase, tmp_path):
    admin, _ = db_server
    name = f"centerline_test_fresh_{uuid.uuid4().hex[:8]}"
    admin.execute(f'CREATE DATABASE "{name}"')
    try:
        app_db = roles.app_database(replace(SERVER, dbname=name))
        c = new_client(create_app(make_settings(mock_timebase[1], tmp_path, app_db)))
        assert c.app.state.db_ready
        with replace(SERVER, dbname=name).connect() as conn:
            assert migrate.status(conn)["pending"] == []  # the owner applied them all, 0006 included
        r = c.post("/api/v1/auth/login", json={"name": "nobody", "password": "not it"})
        assert r.status_code == 401  # answered from the database, as centerline_app
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
