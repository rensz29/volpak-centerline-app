"""api service entry point.

    uvicorn centerline_api.main:create_app --factory --host 127.0.0.1 --port 8000

Built so far: Analytics & Correlation (ADR-0008), the Configuration page (ADR-0011…0013),
the Digital Centerline page's data (ADR-0015), accounts, sign-in and roles (ADR-0016), and the
Notifications log with its routing and channels (ADR-0023).
Every endpoint but signing in and /api/v1/health/live needs a signed-in account. Until the
production proxy (Caddy, HTTPS) is in place, keep binding to 127.0.0.1.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone

from centerline_common.db import DatabaseUnavailable
from centerline_common.historian import TimebaseClient, TimebaseError
from centerline_common import connections as saved_connections
from centerline_common import isotime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from . import database, problems
from . import health as health_mod
from .ai import ollama as ai_ollama
from .ai import opening as ai_opening
from .ai import embed as ai_embed
from .ai import summary as ai_summary
from .ai import translate as ai_translate
from .ocap import scan
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
from .ocap.router import router as ocap_router
from .ocap.store import OcapStore
from .ocap.translations import Translations
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
    app.state.ocap_store = OcapStore(ai_translates=settings.ai.enabled and bool(settings.ai.model) and settings.ai.translate_every_s > 0,
                                     ai=settings.ai)
    app.state.translations = Translations()
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
    app.state.ai_stop = threading.Event()
    if settings.ai.enabled and settings.ai.model and settings.ai.warm_every_s > 0:
        # The model stays loaded and warm (ADR-0041): a background thread, which ends with the process
        threading.Thread(target=ai_ollama.keep_warm, args=(settings.ai, app.state.ai_stop), name="ai-warm", daemon=True).start()
    if settings.ai.enabled and settings.ai.model and settings.ai.open_every_s > 0:
        # The AI's opening question for each new request (ADR-0042)
        threading.Thread(target=ai_opening.keep_opening, args=(app, app.state.ai_stop), name="ai-opening", daemon=True).start()
    if settings.ai.enabled and settings.ai.embed_model and settings.ai.embed_every_s > 0:
        # The Active OCAPs' sections embedded for the search by meaning (ADR-0048)
        threading.Thread(target=ai_embed.keep_embedding, args=(app, app.state.ai_stop), name="ai-embed", daemon=True).start()
    if settings.ai.enabled and settings.ai.model and settings.ai.summary_every_s > 0:
        # The AI's summary of the OCAP sections each request is offered (ADR-0046)
        threading.Thread(target=ai_summary.keep_summarising, args=(app, app.state.ai_stop), name="ai-summary", daemon=True).start()
    if settings.ai.enabled and settings.ai.model and settings.ai.translate_every_s > 0:
        # The OCAP's Tagalog, one section at a time, while no operator is answering (ADR-0045)
        threading.Thread(target=ai_translate.keep_translating, args=(app, app.state.ai_stop), name="ai-translate", daemon=True).start()

    @app.get("/api/v1/health/live", tags=["health"], summary="The api answers: for container health checks, no sign-in")
    def live() -> dict:
        return {"status": "ok"}

    @app.get("/api/v1/health", tags=["health"], dependencies=[ADMIN_ONLY],
             summary="Every part of Centerline, graded OK, warning or critical, for the System health page (Administrator)")
    def health(request: Request) -> dict:
        settings = request.app.state.settings
        reg = request.app.state.register
        beat_sql = """SELECT instance, started_at, beat_at, status, extract(epoch FROM clock_timestamp() - beat_at) AS age
                        FROM {} ORDER BY beat_at DESC LIMIT 1"""
        mb = nb = last_ai = embedded = None
        outbox: dict = {}
        try:
            with settings.database.connect() as conn:
                broken = conn.execute("SELECT audit_log_verify() AS seq").fetchone()["seq"]
                mb = conn.execute(beat_sql.format("monitor_heartbeat")).fetchone()
                nb = conn.execute(beat_sql.format("notifier_heartbeat")).fetchone()
                db = {"reachable": True, "ready": request.app.state.db_ready,
                      "activeRules": request.app.state.rules_store.active_number(conn),
                      "activeMapping": request.app.state.mapping_store.active_number(conn),
                      "auditChain": "intact" if broken is None else f"broken at entry {broken}",
                      "size": conn.execute("SELECT pg_size_pretty(pg_database_size(current_database())) AS s").fetchone()["s"]}
                db["activeRouting"] = request.app.state.routing_store.active_rules(conn)[0]
                o = conn.execute("""SELECT count(*) FILTER (WHERE d.status IN ('PENDING', 'ATTEMPTING', 'RETRYING')) AS waiting,
                                           count(*) FILTER (WHERE d.status = 'PERMANENT_FAILURE') AS failed,
                                           min(n.created_at) FILTER (WHERE d.status IN ('PENDING', 'ATTEMPTING', 'RETRYING')) AS oldest
                                      FROM notification_delivery d JOIN notification n ON n.id = d.notification_id""").fetchone()
                outbox = {"waiting": o["waiting"], "failed": o["failed"], "oldestWaitingAt": isotime.iso(o["oldest"])}
                last_ai = conn.execute("SELECT outcome, detail, latency_ms, at FROM ai_call ORDER BY at DESC LIMIT 1").fetchone()
                embedded = conn.execute("""SELECT count(*) AS total, count(*) FILTER (WHERE EXISTS (
                                                  SELECT 1 FROM ocap_chunk_embedding e WHERE e.chunk_id = c.id AND e.model = %s)) AS done
                                             FROM ocap_chunk c JOIN ocap_section s ON s.id = c.section_id
                                             JOIN ocap_version_status st ON st.version_id = s.version_id AND st.status = 'active'""",
                                        (settings.ai.embed_model,)).fetchone()
        except DatabaseUnavailable as e:
            db = {"reachable": False, "error": str(e)}

        def beat(row) -> dict | None:
            return None if row is None else {"instance": row["instance"], "beatAt": isotime.iso(row["beat_at"]),
                                             "ageS": round(float(row["age"]), 1), "status": row["status"]}

        # As before ADR-0038, for the callers that read these
        monitor = None if mb is None else {
            "instance": mb["instance"], "beatAt": isotime.iso(mb["beat_at"]), "ageS": round(float(mb["age"]), 1),
            "alive": float(mb["age"]) < 60, "judging": mb["status"].get("judging"), "reasons": mb["status"].get("reasons"),
            "clockSkewS": mb["status"].get("clockSkewS"), "clockSkewWarning": mb["status"].get("clockSkewWarning")}
        notifier = None if nb is None else {
            "instance": nb["instance"], "beatAt": isotime.iso(nb["beat_at"]), "ageS": round(float(nb["age"]), 1),
            "alive": float(nb["age"]) < 60, "lanes": nb["status"].get("lanes"), "backlog": nb["status"].get("backlog")}

        client = TimebaseClient({**settings.timebase, "timeout_s": 5})
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

        if settings.scanner.type == "none":
            scanner = {"type": "none"}
        else:
            try:
                scanner = {"type": settings.scanner.type, "version": scan.version(settings.scanner)}
            except scan.ScannerUnavailable as e:
                scanner = {"type": settings.scanner.type, "error": str(e)}
        backup = None
        if settings.backup_status is not None:
            try:
                backup = json.loads(settings.backup_status.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                backup = None
        ai = {"enabled": settings.ai.enabled and bool(settings.ai.model), "model": settings.ai.model,
              "pinned": settings.ai.model_digest,
              "last": None if last_ai is None else {"outcome": last_ai["outcome"], "detail": last_ai["detail"],
                                                    "latencyMs": last_ai["latency_ms"], "at": isotime.iso(last_ai["at"])}}
        if ai["enabled"] and settings.ai.embed_model:
            # The OCAP search by meaning (ADR-0048): its model, and how much of the Active OCAPs it has embedded
            ai["embed"] = {"model": settings.ai.embed_model, "pinned": settings.ai.embed_model_digest,
                           "total": embedded["total"] if embedded else None, "done": embedded["done"] if embedded else None}
        if ai["enabled"]:
            try:
                ai.update(reachable=True, digest=ai_ollama.digest(settings.ai), gpu=ai_ollama.on_gpu(settings.ai))
                if "embed" in ai:
                    ai["embed"]["digest"] = ai_ollama.digest(settings.ai, settings.ai.embed_model)
            except ai_ollama.AiUnavailable as e:
                ai.update(reachable=False, error=str(e))
        freshness = (saved_connections.load(settings.config_dir).get("mqtt") or {}).get("freshness_s") or {}
        report = health_mod.grade({"monitor": beat(mb), "notifier": beat(nb), "outbox": outbox, "freshness": freshness,
                                   "backup": backup, "backupConfigured": settings.backup_status is not None,
                                   "database": db, "scanner": scanner, "timebase": timebase, "ai": ai})
        return {"status": "ok", "registerVersion": reg.version,
                "registerSource": "database" if request.app.state.db_ready else "file (read-only)",
                "registerFileWarning": request.app.state.register_file_warning, "database": db, "monitor": monitor,
                "notifier": notifier, "timebase": timebase, "scanner": scanner, "backup": backup,
                "checkedAt": isotime.iso(datetime.now(timezone.utc)), **report}

    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(analytics_router)
    app.include_router(config_router)
    app.include_router(rules_router)
    app.include_router(mapping_router)
    app.include_router(routing_router)
    app.include_router(ranges_router)
    app.include_router(ocap_router)
    app.include_router(notifications_router)
    app.include_router(workflow_router)
    app.include_router(monitoring_router)
    app.include_router(control_router)
    return app
