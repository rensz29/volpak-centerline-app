"""Monitoring rules endpoints (ADR-0012): versions, activation and SKUs.

SDD §10 names them GET/POST /config/versions and POST /config/versions/{id}/activate.
Managers and Administrators read them, and only Managers change them (ADR-0016).
Versions are addressed by number: Rules v3 is /versions/3.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ..auth.deps import MANAGER_ONLY, PRIVILEGED
from ..database import connect
from .models import ActivateIn, CancelIn, RulesVersionIn, SkuIn, SkuRenameIn

router = APIRouter(prefix="/api/v1/config", tags=["rules"], dependencies=[PRIVILEGED])


def _overview(request: Request, conn) -> dict:
    register = request.app.state.register_store.load(conn)
    return request.app.state.rules_store.overview(conn, register) | {"registerVersion": register.version}


@router.get("/rules", summary="Rules in effect, scheduled activations, every version and the SKUs")
def rules_overview(request: Request, conn=Depends(connect)) -> dict:
    return _overview(request, conn)


@router.get("/rules/proposal", summary="The Phase 0 proposal a first version starts from (ADR-0002, ADR-0010)")
def rules_proposal(request: Request) -> dict:
    return request.app.state.rules_store.proposal()


@router.get("/versions/{number}", summary="One rules version with its SKU readiness")
def get_version(number: int, request: Request, conn=Depends(connect)) -> dict:
    return request.app.state.rules_store.version(conn, number, request.app.state.register_store.load(conn))


@router.post("/versions/check", dependencies=[MANAGER_ONLY], summary="Check a version without saving it")
def check_version(body: RulesVersionIn, request: Request, conn=Depends(connect)) -> dict:
    return request.app.state.rules_store.check(conn, body, request.app.state.register_store.load(conn))


@router.post("/versions", dependencies=[MANAGER_ONLY], status_code=201, summary="Save a new rules version, optionally activating it")
def create_version(body: RulesVersionIn, request: Request, conn=Depends(connect)) -> dict:
    number = request.app.state.rules_store.create(conn, body, request.app.state.register_store.load(conn))
    return {"created": number} | _overview(request, conn)


@router.post("/versions/{number}/activate", dependencies=[MANAGER_ONLY], summary="Activate a version now or at a set time; an older one is a rollback")
def activate_version(number: int, body: ActivateIn, request: Request, conn=Depends(connect)) -> dict:
    request.app.state.rules_store.activate(conn, number, body)
    return _overview(request, conn)


@router.post("/activations/{activation_id}/cancel", dependencies=[MANAGER_ONLY], summary="Cancel an activation that hasn't happened yet")
def cancel_activation(activation_id: UUID, body: CancelIn, request: Request, conn=Depends(connect)) -> dict:
    request.app.state.rules_store.cancel(conn, activation_id, body)
    return _overview(request, conn)


@router.post("/skus", dependencies=[MANAGER_ONLY], status_code=201, summary="Add a SKU as the machine publishes it")
def add_sku(body: SkuIn, request: Request, conn=Depends(connect)) -> dict:
    request.app.state.rules_store.add_sku(conn, body)
    return _overview(request, conn)


@router.put("/skus/{code}", dependencies=[MANAGER_ONLY], summary="Rename a SKU")
def rename_sku(code: str, body: SkuRenameIn, request: Request, conn=Depends(connect)) -> dict:
    request.app.state.rules_store.rename_sku(conn, code, body)
    return _overview(request, conn)


@router.delete("/skus/{code}", dependencies=[MANAGER_ONLY], summary="Remove a SKU no saved version uses")
def delete_sku(code: str, request: Request, reason: str = "", conn=Depends(connect)) -> dict:
    request.app.state.rules_store.delete_sku(conn, code, reason)
    return _overview(request, conn)
