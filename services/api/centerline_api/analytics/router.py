"""Analytics endpoints (SDD §10). Plain `def` handlers: the Timebase client blocks, so they run in the threadpool."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..auth.deps import PRIVILEGED
from . import service
from .models import AnalyticsQuery

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"], dependencies=[PRIVILEGED])


@router.get("/options", summary="Variables, buckets, groupings, limits and defaults for the Analytics page")
def get_options(request: Request) -> dict:
    return service.options(request.app.state.settings, request.app.state.register)


@router.post("/query", summary="Run one X/Y correlation over Timebase history")
def post_query(query: AnalyticsQuery, request: Request) -> dict:
    return service.run(query, request.app.state.settings, request.app.state.register,
                       client_host=request.client.host if request.client else None)
