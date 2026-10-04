"""What the schema itself guarantees (db/migrations): append-only history, the audit chain, activations."""

from __future__ import annotations

import shutil

import psycopg
import pytest
from psycopg.types.json import Jsonb

from centerline_common import migrate
from centerline_common.db import uuid7


@pytest.fixture
def conn(owner):
    """The schema and its triggers themselves: as the owner, who runs the migrations."""
    with owner.connect() as c:
        yield c


def a_version(conn, number=1):
    rid = uuid7()
    conn.execute("INSERT INTO register_version (id, number, content, sha256, reason) VALUES (%s, %s, '{}', 'x', 'test')",
                 (rid, f"2026-09-30.{number}"))
    vid = uuid7()
    conn.execute("""INSERT INTO config_version (id, number, register_version_id, settings, sha256, reason)
                    VALUES (%s, %s, %s, '{}', 'x', 'test')""", (vid, number, rid))
    conn.execute("INSERT INTO sku_parameter_rule (config_version_id, parameter_id, warn_low) VALUES (%s, 'P02', 2)", (vid,))
    conn.commit()
    return vid


def refused(conn, sql, *args) -> bool:
    try:
        conn.execute(sql, args)
    except psycopg.errors.RestrictViolation:
        conn.rollback()
        return True
    conn.rollback()
    return False


def test_migrations_apply_once_and_refuse_an_edited_file(conn, tmp_path):
    assert migrate.status(conn) == {"applied": ["0001_configuration", "0002_mappings", "0003_monitoring", "0004_accounts", "0005_monitoring_control", "0006_app_role", "0007_sku_placeholder", "0008_notifications", "0009_workflow", "0010_truncate_guards"], "pending": []}
    assert migrate.apply(conn) == []
    edited = tmp_path / "migrations"
    edited.mkdir()
    shutil.copy(migrate.MIGRATIONS / "0001_configuration.sql", edited)
    (edited / "0001_configuration.sql").write_text("-- changed\n", encoding="utf-8")
    with pytest.raises(migrate.MigrationError, match="changed after it was applied"):
        migrate.apply(conn, edited)


def test_every_table_guarded_against_changes_also_refuses_truncate(conn):
    guarded = {r["t"] for r in conn.execute("""
        SELECT DISTINCT c.relname AS t FROM pg_trigger g JOIN pg_class c ON c.oid = g.tgrelid JOIN pg_proc p ON p.oid = g.tgfoid
         WHERE NOT g.tgisinternal AND c.relnamespace = 'public'::regnamespace
           AND (p.proname = 'refuse_change' OR p.proname LIKE '%%\\_guard')
           AND (g.tgtype & 24) <> 0""")}  # row triggers on UPDATE (16) or DELETE (8)
    assert {"event", "pause_period", "maintenance_window", "app_user", "workflow_request", "audit_log"} <= guarded
    for t in sorted(guarded):
        assert refused(conn, f"TRUNCATE {t} CASCADE"), t  # DAT-01: not even the owner empties them


def test_configuration_history_is_append_only(conn):
    vid = a_version(conn)
    for sql in ("UPDATE register_version SET reason = 'x'", "DELETE FROM register_version",
                "UPDATE config_version SET reason = 'x'", "DELETE FROM config_version",
                "UPDATE sku_parameter_rule SET warn_low = 9", "DELETE FROM sku_parameter_rule",
                "TRUNCATE config_version CASCADE", "TRUNCATE sku_parameter_rule"):
        assert refused(conn, sql), sql
    assert conn.execute("SELECT count(*) AS n FROM sku_parameter_rule WHERE config_version_id = %s", (vid,)).fetchone()["n"] == 1


def test_the_audit_chain_notices_an_edit(conn):
    for i in range(3):
        conn.execute("INSERT INTO audit_log (id, action, summary, details) VALUES (%s, 'test', %s, %s)",
                     (uuid7(), f"entry {i}", Jsonb({"n": i})))
    conn.commit()
    assert [r["seq"] for r in conn.execute("SELECT seq FROM audit_log ORDER BY seq")] == [1, 2, 3]
    assert conn.execute("SELECT audit_log_verify() AS bad").fetchone()["bad"] is None
    assert refused(conn, "UPDATE audit_log SET summary = 'edited' WHERE seq = 2")
    assert refused(conn, "DELETE FROM audit_log WHERE seq = 3")
    conn.execute("SET session_replication_role = replica")  # triggers off, as only a superuser can
    conn.execute("UPDATE audit_log SET summary = 'edited' WHERE seq = 2")
    conn.execute("SET session_replication_role = origin")
    assert conn.execute("SELECT audit_log_verify() AS bad").fetchone()["bad"] == 2
    conn.rollback()


def test_only_a_scheduled_activation_can_be_cancelled(conn):
    v1, v2 = a_version(conn, 1), a_version(conn, 2)
    past, future = uuid7(), uuid7()
    conn.execute("INSERT INTO config_activation (id, config_version_id, effective_at, reason) VALUES (%s, %s, now() - interval '1 hour', 'go')", (past, v1))
    conn.execute("INSERT INTO config_activation (id, config_version_id, effective_at, reason) VALUES (%s, %s, now() + interval '1 hour', 'later')", (future, v2))
    conn.commit()
    assert conn.execute("SELECT active_config_version() AS v").fetchone()["v"] == v1
    assert conn.execute("SELECT active_config_version(now() + interval '2 hours') AS v").fetchone()["v"] == v2

    assert refused(conn, "UPDATE config_activation SET cancelled_at = now(), cancel_reason = 'x' WHERE id = %s", past)
    assert refused(conn, "UPDATE config_activation SET effective_at = now() WHERE id = %s", future)
    assert refused(conn, "DELETE FROM config_activation WHERE id = %s", future)
    conn.execute("UPDATE config_activation SET cancelled_at = now(), cancel_reason = 'not needed' WHERE id = %s", (future,))
    conn.commit()
    assert conn.execute("SELECT active_config_version(now() + interval '2 hours') AS v").fetchone()["v"] == v1


def a_mapping(conn, number=1):
    rid = conn.execute("SELECT id FROM register_version LIMIT 1").fetchone()
    if rid is None:
        rid = {"id": uuid7()}
        conn.execute("INSERT INTO register_version (id, number, content, sha256, reason) VALUES (%s, '2026-09-30.9', '{}', 'x', 't')",
                     (rid["id"],))
    vid = uuid7()
    conn.execute("""INSERT INTO mapping_version (id, number, register_version_id, source, sha256, reason)
                    VALUES (%s, %s, %s, 'test', 'x', 'test')""", (vid, number, rid["id"]))
    conn.execute("INSERT INTO tag_mapping (mapping_version_id, tag, topic, field) VALUES (%s, 'SPC.A', 'x/SPC', 'A')", (vid,))
    conn.commit()
    return vid


def test_mappings_are_append_only_and_refuse_wildcards_and_shared_places(conn):
    vid = a_mapping(conn)
    for sql in ("UPDATE mapping_version SET reason = 'x'", "DELETE FROM mapping_version",
                "UPDATE tag_mapping SET topic = 'y'", "DELETE FROM tag_mapping", "TRUNCATE tag_mapping"):
        assert refused(conn, sql), sql
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO tag_mapping (mapping_version_id, tag, topic) VALUES (%s, 'SPC.B', 'x/#')", (vid,))
    conn.rollback()
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO tag_mapping (mapping_version_id, tag, topic, field) VALUES (%s, 'SPC.B', 'x/SPC', 'A')", (vid,))
    conn.rollback()


def test_the_mapping_activation_guard_allows_only_cancelling_a_scheduled_one(conn):
    v1, v2 = a_mapping(conn, 1), a_mapping(conn, 2)
    past, future = uuid7(), uuid7()
    conn.execute("INSERT INTO mapping_activation (id, mapping_version_id, effective_at, reason) VALUES (%s, %s, now() - interval '1 hour', 'go')", (past, v1))
    conn.execute("INSERT INTO mapping_activation (id, mapping_version_id, effective_at, reason) VALUES (%s, %s, now() + interval '1 hour', 'later')", (future, v2))
    conn.commit()
    assert conn.execute("SELECT active_mapping_version() AS v").fetchone()["v"] == v1
    assert refused(conn, "UPDATE mapping_activation SET cancelled_at = now(), cancel_reason = 'x' WHERE id = %s", past)
    assert refused(conn, "UPDATE mapping_activation SET reason = 'edited', cancelled_at = now(), cancel_reason = 'x' WHERE id = %s", future)
    assert refused(conn, "DELETE FROM mapping_activation WHERE id = %s", future)
    conn.execute("UPDATE mapping_activation SET cancelled_at = now(), cancel_reason = 'not needed' WHERE id = %s", (future,))
    conn.commit()
    assert conn.execute("SELECT active_mapping_version(now() + interval '2 hours') AS v").fetchone()["v"] == v1

