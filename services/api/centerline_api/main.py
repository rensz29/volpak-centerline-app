"""api service entry point.

    uvicorn centerline_api.main:create_app --factory --host 127.0.0.1 --port 8000

Built so far: Analytics & Correlation (ADR-0008), the Configuration page (ADR-0011…0013),
the Digital Centerline page's data (ADR-0015), accounts, sign-in and roles (ADR-0016), and the
Notifications log with its routing and channels (ADR-0023).
Every endpoint but signing in and /api/v1/health/live needs a signed-in account. Until the
production proxy (Caddy, HTTPS) is in place, keep binding to 127.0.0.1.
"""

from __future__ import annotations

import time
from dataclasses import replace

from centerline_common.db import DatabaseUnavailable
from centerline_common.historian import TimebaseClient, TimebaseError
from centerline_common import isotime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from . import database, problems
from .analytics.router import router as analytics_router
from .auth.deps import ADMIN_ONLY, CSRF_HEADER, CsrfGuard
from .auth.passwords import Passwords
from .auth.router import router as auth_router
from .auth.users import router as users_router
from .config.mapping_router import router as mapping_router
from .config.mapping_store import MappingStore
from .config.register_store import RegisterStore
from .config.router import router as config_router
from .config.ranges_router import router as ranges_router
from .config.ranges_store import RangesStore
from .config.routing_router import router as routing_router
from .config.routing_store import RoutingStore
from .config.rules_router import router as rules_router
from .config.rules_store import RulesStore
from .idempotency import HEADER as IDEMPOTENCY_HEADER, Idempotency
from .config.store import ConnectionsStore
from .monitoring.control import router as control_router
from .monitoring.router import router as monitoring_router
from .notifications.router import router as notifications_router
from .workflow.router import router as workflow_router
from .settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="Centerline api", version="0.1.0", docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.register_store = RegisterStore(settings.register_path)
    app.state.rules_store = RulesStore()
    app.state.mapping_store = MappingStore()
    app.state.routing_store = RoutingStore()
    app.state.ranges_store = RangesStore()
    app.state.passwords = Passwords(settings.auth)
    database.start(app)  # loads app.state.register, from the database or, without it, from the file
    connections = ConnectionsStore(settings.config_dir, settings.timebase, app.state.register.namespace)
    app.state.connections = connections
    # Historian settings saved on the Configuration page win over the api config file.
    app.state.settings = replace(settings, timebase=connections.historian_client_config())
    app.add_middleware(Idempotency)  # inside GZip: it keeps answers uncompressed
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(CsrfGuard)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                           allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type", CSRF_HEADER, IDEMPOTENCY_HEADER])
    problems.install(app)

    @app.get("/api/v1/health/live", tags=["health"], summary="The api answers: for container health checks, no sign-in")
    def live() -> dict:
        return {"status": "ok"}

    @app.get("/api/v1/health", tags=["health"], dependencies=[ADMIN_ONLY],
             summary="Service, database, monitor-core, notifier and Timebase status (Administrator)")
    def health(request: Request) -> dict:
        reg = request.app.state.register
        try:
            with request.app.state.settings.database.connect() as conn:
                broken = conn.execute("SELECT audit_log_verify() AS seq").fetchone()["seq"]
                beat = conn.execute("""SELECT instance, beat_at, status, extract(epoch FROM clock_timestamp() - beat_at) AS age
                                         FROM monitor_heartbeat ORDER BY beat_at DESC LIMIT 1""").fetchone()
                db = {"reachable": True, "ready": request.app.state.db_ready,
                      "activeRules": request.app.state.rules_store.active_number(conn),
                      "activeMapping": request.app.state.mapping_store.active_number(conn),
                      "auditChain": "intact" if broken is None else f"broken at entry {broken}"}
                # monitor-core beats every 2 s; stale after 60 s (guide §6.7)
                monitor = None if beat is None else {
                    "instance": beat["instance"], "beatAt": isotime.iso(beat["beat_at"]), "ageS": round(float(beat["age"]), 1),
                    "alive": float(beat["age"]) < 60, "judging": beat["status"].get("judging"),
                    "reasons": beat["status"].get("reasons"),
                    "clockSkewS": beat["status"].get("clockSkewS"), "clockSkewWarning": beat["status"].get("clockSkewWarning")}
                # the notifier beats every 2 s too (ADR-0023)
                nb = conn.execute("""SELECT instance, beat_at, status, extract(epoch FROM clock_timestamp() - beat_at) AS age
                                       FROM notifier_heartbeat ORDER BY beat_at DESC LIMIT 1""").fetchone()
                notifier = None if nb is None else {
                    "instance": nb["instance"], "beatAt": isotime.iso(nb["beat_at"]), "ageS": round(float(nb["age"]), 1),
                    "alive": float(nb["age"]) < 60, "lanes": nb["status"].get("lanes"), "backlog": nb["status"].get("backlog")}
                db["activeRouting"] = request.app.state.routing_store.active_rules(conn)[0]
        except DatabaseUnavailable as e:
            db, monitor, notifier = {"reachable": False, "error": str(e)}, None, None
        client = TimebaseClient({**request.app.state.settings.timebase, "timeout_s": 5})
        t0 = time.monotonic()
        try:
            client.datasets()
            timebase = {"reachable": True, "latencyMs": round((time.monotonic() - t0) * 1000),
                        "clockOffsetS": None if client.last_server_date is None
                        else round(client.last_server_date - time.time(), 1)}
        except TimebaseError as e:
            timebase = {"reachable": False, "error": str(e)}
        finally:
            client.close()
        return {"status": "ok", "registerVersion": reg.version,
                "registerSource": "database" if request.app.state.db_ready else "file (read-only)",
                "registerFileWarning": request.app.state.register_file_warning, "database": db, "monitor": monitor,
                "notifier": notifier, "timebase": timebase}

    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(analytics_router)
    app.include_router(config_router)
    app.include_router(rules_router)
    app.include_router(mapping_router)
    app.include_router(routing_router)
    app.include_router(ranges_router)
    app.include_router(notifications_router)
    app.include_router(workflow_router)
    app.include_router(monitoring_router)
    app.include_router(control_router)
    return app
