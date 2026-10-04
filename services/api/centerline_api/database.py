"""The api's use of PostgreSQL (ADR-0012): start-up steps and a connection per request.

Analytics needs only the register, so the api also starts without the database:
it then reads config/parameter-register.json, and the configuration endpoints
answer 503 until the database is back. The first request that reaches it
finishes the start-up steps.
"""

from __future__ import annotations

import logging
import threading

from centerline_common import migrate, roles
from centerline_common import register as register_mod
from centerline_common.db import DatabaseUnavailable
from fastapi import FastAPI, Request

from .config import audit
from .problems import Problem

log = logging.getLogger("centerline.api")
_lock = threading.Lock()


def bootstrap(app: FastAPI) -> list[str]:
    return migrate_as_owner(app.state.settings)


def migrate_as_owner(settings) -> list[str]:
    """As the owner, when one is configured (ADR-0020): the migrations, then the services' role password from its
    secret file, so that the api can connect as centerline_app. Returns the migrations applied. The api runs it at
    start, and the accounts command line before it signs anyone up."""
    if settings.migrate_database is None or not settings.migrate_on_start:
        return []
    with settings.migrate_database.connect() as owner:
        applied = migrate.apply(owner)
        owner.commit()
        if settings.database.user == roles.APP_ROLE and settings.database.password_file:
            roles.ensure_password(owner, settings.database.password_file)
    return applied


def prepare(app: FastAPI, conn, applied: list[str] | None = None) -> None:
    """Migrate (unless the owner did), import the register file and the old change history (first start only),
    then load the register."""
    settings, store = app.state.settings, app.state.register_store
    if applied is None:
        applied = migrate.apply(conn) if settings.migrate_on_start and settings.migrate_database is None else []
    imported = audit.import_legacy(conn, settings.config_dir)  # older entries first, so the chain follows time
    seeded = store.seed(conn)
    conn.commit()
    app.state.register = store.load(conn)
    app.state.register_file_warning = store.file_status(conn)
    app.state.db_ready = True
    app.state.db_error = None
    for what, done in (("migrations applied", applied), ("register imported", seeded), ("history entries imported", imported)):
        if done:
            log.info("database: %s: %s", what, done)


def start(app: FastAPI) -> None:
    app.state.db_ready = False
    app.state.register_file_warning = None
    try:
        applied = bootstrap(app)
        with app.state.settings.database.connect() as conn:
            prepare(app, conn, applied)
    except DatabaseUnavailable as e:
        app.state.db_error = str(e)
        app.state.register = register_mod.load(app.state.settings.register_path)
        log.warning("database unavailable, using %s read-only: %s", app.state.settings.register_path, e)


def connect(request: Request):
    """FastAPI dependency: one connection per request, rolled back unless the handler commits."""
    app = request.app
    try:
        if not app.state.db_ready:
            with _lock:
                if not app.state.db_ready:
                    bootstrap(app)  # the database came up after the api: the role may be new
        conn = app.state.settings.database.connect()
    except DatabaseUnavailable as e:
        app.state.db_error = str(e)
        raise Problem(503, "database-unavailable", "The Centerline database isn't reachable",
                      f"{e}. Start it with: docker compose -f deploy/dev/compose.yaml up -d") from None
    try:
        if not app.state.db_ready:
            with _lock:
                if not app.state.db_ready:
                    prepare(app, conn)
        yield conn
    finally:
        conn.close()
