"""Notification routing endpoints (ADR-0023): who gets which messages. Managers and Administrators read
them, and only Administrators change them, like the other connection settings (ADR-0016)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ..auth.deps import ADMIN_ONLY, PRIVILEGED
from ..database import connect
from .models import ActivateIn, CancelIn, RoutingVersionIn

router = APIRouter(prefix="/api/v1/config/routing", tags=["routing"], dependencies=[PRIVILEGED])


@router.get("", summary="Routing in effect, scheduled activations, every version, the kinds of message and channels")
def routing_overview(request: Request, conn=Depends(connect)) -> dict:
    return request.app.state.routing_store.overview(conn)


@router.get("/proposal", summary="The Phase 2 proposal a first version starts from (ADR-0023)")
def routing_proposal(request: Request) -> dict:
    return request.app.state.routing_store.proposal()


@router.get("/versions/{number}", summary="One routing version, with its warnings")
def get_routing(number: int, request: Request, conn=Depends(connect)) -> dict:
    return request.app.state.routing_store.version(conn, number)


@router.post("/versions/check", dependencies=[ADMIN_ONLY], summary="Check a routing without saving it")
def check_routing(body: RoutingVersionIn, request: Request) -> dict:
    return request.app.state.routing_store.check(body)


@router.post("/versions", dependencies=[ADMIN_ONLY], status_code=201, summary="Save a new routing version, optionally activating it")
def create_routing(body: RoutingVersionIn, request: Request, conn=Depends(connect)) -> dict:
    number = request.app.state.routing_store.create(conn, body)
    return {"created": number} | request.app.state.routing_store.overview(conn)


@router.post("/versions/{number}/activate", dependencies=[ADMIN_ONLY], summary="Activate a routing now or at a set time; an older one is a rollback")
def activate_routing(number: int, body: ActivateIn, request: Request, conn=Depends(connect)) -> dict:
    request.app.state.routing_store.activate(conn, number, body)
    return request.app.state.routing_store.overview(conn)


@router.post("/activations/{activation_id}/cancel", dependencies=[ADMIN_ONLY], summary="Cancel a routing activation that hasn't happened yet")
def cancel_routing_activation(activation_id: UUID, body: CancelIn, request: Request, conn=Depends(connect)) -> dict:
    request.app.state.routing_store.cancel(conn, activation_id, body)
    return request.app.state.routing_store.overview(conn)
