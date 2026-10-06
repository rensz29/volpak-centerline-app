"""Tag mapping endpoints (ADR-0013): where each register tag arrives on MQTT.

SDD §10 has mapping import, browse and activate/rollback for Administrators.
Managers and Administrators read them, and only Administrators change them
(ADR-0016, closing O-13). Versions are addressed by number.
"""

from __future__ import annotations

from uuid import UUID

from centerline_common import mapping as mapping_mod
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from ..auth.deps import ADMIN_ONLY, PRIVILEGED
from ..database import connect
from . import checks
from .models import ActivateIn, CancelIn, DiscoverIn, MappingImportIn, MappingVersionIn

router = APIRouter(prefix="/api/v1/config/mappings", tags=["mappings"], dependencies=[PRIVILEGED])


def _subscriptions(request: Request) -> list[str]:
    return request.app.state.connections.mqtt().get("subscriptions") or []


def _overview(request: Request, conn) -> dict:
    register = request.app.state.register_store.load(conn)
    return request.app.state.mapping_store.overview(conn, register, _subscriptions(request)) | {"registerVersion": register.version}


@router.get("", summary="Mapping in effect, scheduled activations, versions, and the tags monitor-core needs")
def mappings_overview(request: Request, conn=Depends(connect)) -> dict:
    return _overview(request, conn)


@router.get("/versions/{number}", summary="One mapping version, with coverage and warnings")
def get_mapping(number: int, request: Request, conn=Depends(connect)) -> dict:
    register = request.app.state.register_store.load(conn)
    return request.app.state.mapping_store.version(conn, number, register, _subscriptions(request))


@router.get("/versions/{number}/export.csv", summary="A mapping version as tag,topic,field CSV")
def export_mapping(number: int, request: Request, conn=Depends(connect)) -> Response:
    text = request.app.state.mapping_store.export_csv(conn, number)
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="mapping-v{number}.csv"'})


@router.post("/versions/check", dependencies=[ADMIN_ONLY], summary="Check a mapping without saving it")
def check_mapping(body: MappingVersionIn, request: Request, conn=Depends(connect)) -> dict:
    register = request.app.state.register_store.load(conn)
    return request.app.state.mapping_store.check(body, register, _subscriptions(request))


@router.post("/versions", dependencies=[ADMIN_ONLY], status_code=201, summary="Save a new mapping version, optionally activating it")
def create_mapping(body: MappingVersionIn, request: Request, conn=Depends(connect)) -> dict:
    register = request.app.state.register_store.load(conn)
    number = request.app.state.mapping_store.create(conn, body, register, _subscriptions(request))
    return {"created": number} | _overview(request, conn)


@router.post("/versions/{number}/activate", dependencies=[ADMIN_ONLY], summary="Activate a mapping now or at a set time; an older one is a rollback")
def activate_mapping(number: int, body: ActivateIn, request: Request, conn=Depends(connect)) -> dict:
    request.app.state.mapping_store.activate(conn, number, body, request.app.state.register_store.load(conn))
    return _overview(request, conn)


@router.post("/activations/{activation_id}/cancel", dependencies=[ADMIN_ONLY], summary="Cancel a mapping activation that hasn't happened yet")
def cancel_mapping_activation(activation_id: UUID, body: CancelIn, request: Request, conn=Depends(connect)) -> dict:
    request.app.state.mapping_store.cancel(conn, activation_id, body)
    return _overview(request, conn)


@router.post("/import", dependencies=[ADMIN_ONLY], summary="Read a probe topic-map.json or a tag,topic,field CSV into rows (nothing is saved)")
def import_mapping(body: MappingImportIn, request: Request, conn=Depends(connect)) -> dict:
    return request.app.state.mapping_store.import_file(body, request.app.state.register_store.load(conn))


@router.post("/discover", dependencies=[ADMIN_ONLY], summary="Listen on the saved broker and find each tag's place (read-only, nothing is saved)")
def discover_mapping(body: DiscoverIn, request: Request, conn=Depends(connect)) -> dict:
    register = request.app.state.register_store.load(conn)
    store = request.app.state.connections
    if not store.mqtt().get("host"):
        return {"connected": False, "error": "No broker saved yet: set it up on the Connections tab first"}
    result = checks.check_mqtt(store.mqtt_client_config(), register, body.seconds)
    if not result.get("connected"):
        return result
    wanted = {r.tag for r in mapping_mod.required(register)}
    rows = [{"tag": m["tag"], "topic": m["topic"], "field": m["field"]} for m in result["mapped"] if m["tag"] in wanted]
    return {"connected": True, "listenedS": result["listenedS"], "rows": rows,
            "notSeen": sorted(wanted - {r["tag"] for r in rows}),
            "topics": [t["topic"] for t in result["topics"]],
            "fields": {t["topic"]: t["fieldNames"] for t in result["topics"]}, "warnings": result["warnings"]}
