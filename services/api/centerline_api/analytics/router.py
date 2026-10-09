"""Analytics endpoints (SDD §10). Plain `def` handlers: the Timebase client blocks, so they run in the threadpool."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends, Request

from ..auth.deps import PRIVILEGED
from ..database import connect
from ..storage import degraded
from . import ranges, service
from .models import AnalyticsQuery

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"], dependencies=[PRIVILEGED])


def _ranges(request: Request, conn) -> ranges.RangeCheck:
    """The Analytics-valid ranges in effect (ANA-10/11); the transaction ends before Timebase is read."""
    found = ranges.active(conn, request.app.state.register)
    conn.rollback()
    return found


@router.get("/options", summary="Variables, buckets, groupings, limits and defaults for the Analytics page")
def get_options(request: Request, conn=Depends(connect)) -> dict:
    return service.options(request.app.state.settings, request.app.state.register, _ranges(request, conn))


@router.post("/query", summary="Run one X/Y correlation over Timebase history")
def post_query(query: AnalyticsQuery, request: Request, conn=Depends(connect)) -> dict:
    principal = getattr(request.state, "principal", None)
    settings = request.app.state.settings
    if settings.audit_log and degraded(conn):
        settings = replace(settings, audit_log=None)  # the query log stops in protected degraded mode (RES-02)
    return service.run(query, settings, request.app.state.register, _ranges(request, conn),
                       client_host=request.client.host if request.client else None,
                       user=principal.username if principal else None)
