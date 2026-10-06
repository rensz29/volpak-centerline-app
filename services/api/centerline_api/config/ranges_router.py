"""Analytics-valid ranges endpoints (ANA-10/11, ADR-0029). Managers and Administrators read them; only an
Administrator uploads a file, activates or rolls back a version, with a reason (ANA-11, ADR-0016)."""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from ..analytics import ranges as ranges_mod
from ..auth.deps import ADMIN_ONLY, PRIVILEGED
from ..database import connect
from .models import ActivateIn, CancelIn, RangesFileIn, RangesVersionIn

router = APIRouter(prefix="/api/v1/config/analytics-ranges", tags=["analytics ranges"], dependencies=[PRIVILEGED])


def _csv(name: str, data: bytes) -> Response:
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip() or "analytics-ranges.csv"  # the name was typed by someone
    return Response(data, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.get("", summary="The ranges in effect, scheduled activations, every version, the parameters a file needs")
def ranges_overview(request: Request, conn=Depends(connect)) -> dict:
    return request.app.state.ranges_store.overview(conn, request.app.state.register)


@router.get("/template.csv", summary="A file to fill in: every register parameter with its unit")
def ranges_template(request: Request) -> Response:
    return _csv("analytics-ranges.csv", ranges_mod.template(request.app.state.register).encode("utf-8"))


@router.get("/versions/{number}", summary="One version: its rows, the file's hash, and whether it still fits the register")
def get_ranges(number: int, request: Request, conn=Depends(connect)) -> dict:
    return request.app.state.ranges_store.version(conn, number, request.app.state.register)


@router.get("/versions/{number}/original.csv", summary="The file exactly as it was uploaded")
def get_ranges_original(number: int, request: Request, conn=Depends(connect)) -> Response:
    source, data = request.app.state.ranges_store.original(conn, number)
    return _csv(source, data)


@router.post("/versions/check", dependencies=[ADMIN_ONLY], summary="Check a file without saving it")
def check_ranges(body: RangesFileIn, request: Request) -> dict:
    return request.app.state.ranges_store.check(body, request.app.state.register)


@router.post("/versions", dependencies=[ADMIN_ONLY], status_code=201, summary="Save an uploaded file as a new version, optionally activating it")
def create_ranges(body: RangesVersionIn, request: Request, conn=Depends(connect)) -> dict:
    store = request.app.state.ranges_store
    number = store.create(conn, body, request.app.state.register)
    return {"created": number} | store.overview(conn, request.app.state.register)


@router.post("/versions/{number}/activate", dependencies=[ADMIN_ONLY], summary="Activate a version now or at a set time; an older one is a rollback")
def activate_ranges(number: int, body: ActivateIn, request: Request, conn=Depends(connect)) -> dict:
    store = request.app.state.ranges_store
    store.activate(conn, number, body, request.app.state.register)
    return store.overview(conn, request.app.state.register)


@router.post("/activations/{activation_id}/cancel", dependencies=[ADMIN_ONLY], summary="Cancel an activation that hasn't happened yet")
def cancel_ranges_activation(activation_id: UUID, body: CancelIn, request: Request, conn=Depends(connect)) -> dict:
    store = request.app.state.ranges_store
    store.cancel(conn, activation_id, body)
    return store.overview(conn, request.app.state.register)
