"""Errors as RFC 9457 problem details (SDD §10 conventions)."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

MEDIA_TYPE = "application/problem+json"


class Problem(Exception):
    """Raise anywhere in a request to answer with a problem document."""

    def __init__(self, status: int, slug: str, title: str, detail: str, **extra: Any):
        super().__init__(detail)
        self.status, self.slug, self.title, self.detail, self.extra = status, slug, title, detail, extra

    def body(self, instance: str | None = None) -> dict:
        doc = {"type": f"/problems/{self.slug}", "title": self.title, "status": self.status, "detail": self.detail}
        if instance:
            doc["instance"] = instance
        return doc | self.extra


def _response(status: int, body: dict) -> JSONResponse:
    return JSONResponse(body, status_code=status, media_type=MEDIA_TYPE)


def _field(loc) -> str:
    """("body", "rules", 3, "warnLow") → "rules[3].warnLow", the form the api's own checks use."""
    out = ""
    for part in loc:
        if part == "body":
            continue
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def install(app) -> None:
    @app.exception_handler(Problem)
    async def _problem(request: Request, exc: Problem):
        return _response(exc.status, exc.body(request.url.path))

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError):
        errors = [{"field": _field(e["loc"]), "message": e["msg"]} for e in exc.errors()]
        body = Problem(422, "invalid-request", "The request is invalid",
                       "; ".join(f"{e['field']}: {e['message']}" for e in errors), errors=errors).body(request.url.path)
        return _response(422, body)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return _response(exc.status_code, {"type": "about:blank", "title": str(exc.detail), "status": exc.status_code,
                                           "instance": request.url.path})
