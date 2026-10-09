"""OCAP library endpoints (OCP-01…03, ADR-0031). Every role reads and searches the library; any Manager uploads a
draft, activates it without second approval, and keeps or supersedes the earlier version, or suspends one (OCP-03,
ADR-0016). A Manager also says which HMI mismatches offer an Excel row as a reason to pick (ADR-0039)."""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import Field

from ..auth.deps import MANAGER_ONLY, SIGNED_IN
from ..config.models import _Camel
from ..database import connect
from ..problems import Problem
from ..storage import refuse_uploads

router = APIRouter(prefix="/api/v1/ocaps", tags=["ocap"])
BASE64_MAX = 28_000_000  # a 20 MB file


class UploadIn(_Camel):
    language: str = Field("en", description="en or fil")
    source: str = Field("", max_length=200, description="The file's name")
    content_base64: str = Field(max_length=BASE64_MAX)
    reason: str = ""


class OcapIn(UploadIn):
    code: str = Field("", max_length=40, description="As the plant knows it, e.g. OCAP-017")
    title: str = Field("", max_length=200)


class ActivateIn(_Camel):
    reason: str = ""
    earlier: Literal["keep", "supersede"] = Field("supersede", description="The OCAP's other active versions (OCP-03)")


class SuspendIn(_Camel):
    reason: str = ""


class TranslationIn(_Camel):
    language: Literal["fil"] = "fil"
    source: str = Field("", max_length=200, description="The file's name")
    content_base64: str = Field(max_length=BASE64_MAX)
    reason: str = ""


class ReasonTagIn(_Camel):
    parameter_ids: list[str] = Field(default_factory=list, max_length=50,
                                     description="The parameters whose HMI mismatches offer it; empty: none")
    direction: Literal["raised", "lowered", "either"] = "either"
    reason: str = ""


def _store(request: Request):
    return request.app.state.ocap_store


def _register(request: Request, conn):
    return request.app.state.register_store.load(conn)


@router.get("", dependencies=[SIGNED_IN], summary="Every OCAP with its versions and their status")
def listing(request: Request, conn=Depends(connect)) -> dict:
    return _store(request).listing(conn) | {"scanner": request.app.state.settings.scanner.type}


@router.get("/search", dependencies=[SIGNED_IN], summary="The Active versions' sections that best match the words")
def search(request: Request, q: str = Query(min_length=2, max_length=500), limit: int = Query(10, ge=1, le=20),
           conn=Depends(connect)) -> dict:
    return {"query": q, "results": _store(request).search(conn, q, limit)}


@router.post("", dependencies=[MANAGER_ONLY], status_code=201, summary="A new OCAP: its first version, a Draft")
def create(body: OcapIn, request: Request, conn=Depends(connect)) -> dict:
    refuse_uploads(conn)  # protected degraded mode (RES-02)
    store = _store(request)
    register = _register(request, conn)
    return store.version(conn, store.create(conn, body, request.app.state.settings.scanner, register), register)


@router.post("/{document_id}/versions", dependencies=[MANAGER_ONLY], status_code=201, summary="A new Draft version of an OCAP")
def add_version(document_id: UUID, body: UploadIn, request: Request, conn=Depends(connect)) -> dict:
    refuse_uploads(conn)  # protected degraded mode (RES-02)
    store = _store(request)
    register = _register(request, conn)
    return store.version(conn, store.add_version(conn, document_id, body, request.app.state.settings.scanner, register), register)


@router.get("/versions/{version_id}", dependencies=[SIGNED_IN], summary="One version, read into sections with their pages")
def version(version_id: UUID, request: Request, conn=Depends(connect)) -> dict:
    return _store(request).version(conn, version_id, _register(request, conn))


@router.get("/sections/{section_id}", dependencies=[SIGNED_IN], summary="One section in full, with its citation (OCP-02)")
def section(section_id: UUID, request: Request, conn=Depends(connect)) -> dict:
    found = _store(request).sections(conn, [section_id])
    if section_id not in found:
        raise Problem(404, "not-found", "No such section", "Reload the page")
    return found[section_id]


@router.get("/versions/{version_id}/original", dependencies=[SIGNED_IN], summary="The file as it was uploaded")
def original(version_id: UUID, request: Request, conn=Depends(connect)) -> Response:
    name, media_type, data = _store(request).original(conn, version_id)
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip() or "ocap"
    return Response(data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.post("/versions/{version_id}/activate", dependencies=[MANAGER_ONLY], summary="Search it from now on (OCP-01, OCP-03)")
def activate(version_id: UUID, body: ActivateIn, request: Request, conn=Depends(connect)) -> dict:
    store = _store(request)
    store.activate(conn, version_id, body.reason, body.earlier)
    return store.version(conn, version_id, _register(request, conn))


@router.post("/versions/{version_id}/suspend", dependencies=[MANAGER_ONLY], summary="Stop searching it")
def suspend(version_id: UUID, body: SuspendIn, request: Request, conn=Depends(connect)) -> dict:
    store = _store(request)
    store.suspend(conn, version_id, body.reason)
    return store.version(conn, version_id, _register(request, conn))


@router.post("/versions/{version_id}/translations", dependencies=[MANAGER_ONLY], status_code=201,
             summary="The plant's checked Tagalog version of an OCAP version, paired section by section (a Draft, ADR-0044)")
def add_translation(version_id: UUID, body: TranslationIn, request: Request, conn=Depends(connect)) -> dict:
    refuse_uploads(conn)  # protected degraded mode (RES-02)
    request.app.state.translations.add(conn, version_id, body.language, body.source, body.content_base64, body.reason,
                                       request.app.state.settings.scanner)
    return _store(request).version(conn, version_id, _register(request, conn))


@router.post("/translations/{translation_id}/activate", dependencies=[MANAGER_ONLY],
             summary="Show a Tagalog version to operators; an earlier one for the same OCAP version is superseded")
def activate_translation(translation_id: UUID, body: SuspendIn, request: Request, conn=Depends(connect)) -> dict:
    version_id = request.app.state.translations.set_status(conn, translation_id, "active", body.reason)
    return _store(request).version(conn, version_id, _register(request, conn))


@router.post("/translations/{translation_id}/withdraw", dependencies=[MANAGER_ONLY], summary="Stop showing a Tagalog version")
def withdraw_translation(translation_id: UUID, body: SuspendIn, request: Request, conn=Depends(connect)) -> dict:
    version_id = request.app.state.translations.set_status(conn, translation_id, "withdrawn", body.reason)
    return _store(request).version(conn, version_id, _register(request, conn))


@router.get("/translations/{translation_id}/original", dependencies=[SIGNED_IN], summary="A Tagalog version's file as uploaded")
def translation_original(translation_id: UUID, request: Request, conn=Depends(connect)) -> Response:
    name, media_type, data = request.app.state.translations.original(conn, translation_id)
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip() or "translation"
    return Response(data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.post("/sections/{section_id}/reason", dependencies=[MANAGER_ONLY],
             summary="Which HMI mismatches offer an Excel row as a reason to pick (ADR-0039)")
def tag_reason(section_id: UUID, body: ReasonTagIn, request: Request, conn=Depends(connect)) -> dict:
    store, register = _store(request), _register(request, conn)
    store.tag(conn, section_id, body.parameter_ids, body.direction, body.reason, register)
    version_id = conn.execute("SELECT version_id FROM ocap_section WHERE id = %s", (section_id,)).fetchone()["version_id"]
    return store.version(conn, version_id, register)
