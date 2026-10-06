"""Configuration endpoints: connections, historian tags and the register (ADR-0011, ADR-0012).

No login exists yet (Phase 1), so these, like the rest of the api, must stay on
127.0.0.1. Once login arrives they are Administrator-only (SDD §10). Saves need
the database, for the register and for the audit log.
"""

from __future__ import annotations

from dataclasses import replace

from centerline_common.channels import Email
from centerline_common.historian import TimebaseClient, TimebaseError
from centerline_common import isotime
from fastapi import APIRouter, Depends, Request

from ..auth.deps import ADMIN_ONLY, PRIVILEGED
from ..database import connect
from ..problems import Problem
from . import audit, checks
from .models import HistorianIn, MqttIn, MqttTestIn, NotificationsConnectionIn, ParameterIn, TagsIn

router = APIRouter(prefix="/api/v1/config", tags=["configuration"], dependencies=[PRIVILEGED])


def _historian_client(request: Request) -> TimebaseClient:
    return TimebaseClient(request.app.state.settings.timebase)


# -- connections ---------------------------------------------------------------


@router.get("/connections", summary="MQTT broker and historian settings (secrets are never returned)")
def get_connections(request: Request) -> dict:
    return request.app.state.connections.public()


@router.put("/connections/historian", dependencies=[ADMIN_ONLY], summary="Save the historian connection")
def put_historian(body: HistorianIn, request: Request, conn=Depends(connect)) -> dict:
    store = request.app.state.connections
    stored = store.build_historian(body)
    store.save_historian(stored, body.reason, conn)
    conn.commit()
    # Analytics picks the new connection up with its next query
    request.app.state.settings = replace(request.app.state.settings, timebase=store.historian_client_config(stored))
    return store.public()


@router.post("/connections/historian/test", dependencies=[ADMIN_ONLY], summary="Test historian settings before saving them")
def test_historian(body: HistorianIn, request: Request) -> dict:
    """Uses what's on the form; a secret not typed again comes from the saved settings. Nothing is stored."""
    store = request.app.state.connections
    saved = store.historian().get("auth") or {}
    auth: dict = {"type": body.auth_type}
    if body.auth_type == "bearer":
        auth["token"] = body.token or store.read_secret(saved.get("token_file"))
        if not auth["token"]:
            return {"ok": False, "error": "Enter the bearer token"}
    elif body.auth_type == "basic":
        auth |= {"username": body.username, "password": body.password or store.read_secret(saved.get("password_file"))}
        if not auth["password"]:
            return {"ok": False, "error": "Enter the password"}
    cfg = {"base_url": body.base_url.rstrip("/"), "dataset": body.dataset, "timeout_s": body.timeout_s,
           "verify_tls": body.verify_tls, "auth": auth}
    return checks.check_historian(cfg, request.app.state.register.namespace)


@router.put("/connections/mqtt", dependencies=[ADMIN_ONLY], summary="Save the MQTT broker connection")
def put_mqtt(body: MqttIn, request: Request, conn=Depends(connect)) -> dict:
    store = request.app.state.connections
    store.save_mqtt(store.build_mqtt(body), body.reason, conn)
    conn.commit()
    return store.public()


@router.put("/connections/notifications", dependencies=[ADMIN_ONLY], summary="Save the Teams flow and the SMTP relay (ADR-0023)")
def put_notifications(body: NotificationsConnectionIn, request: Request, conn=Depends(connect)) -> dict:
    store = request.app.state.connections
    store.save_notifications(store.build_notifications(body), body.reason, conn)
    conn.commit()
    return store.public()


@router.post("/connections/notifications/email-test", dependencies=[ADMIN_ONLY],
             summary="Connect to the SMTP relay and sign in, without sending anything")
def test_email(body: NotificationsConnectionIn, request: Request) -> dict:
    """Uses what's on the form; a password not typed again comes from the saved settings. Nothing is stored or sent."""
    if not body.smtp_host.strip():
        return {"ok": False, "response": "Enter the relay's host name"}
    outcome = Email(request.app.state.connections.email_check_config(body)).check()
    return {"ok": outcome.ok, "response": outcome.response}


@router.post("/connections/mqtt/test", dependencies=[ADMIN_ONLY], summary="Connect, subscribe and listen a few seconds (read-only)")
def test_mqtt(body: MqttTestIn, request: Request) -> dict:
    """Uses what's on the form; secrets not typed again come from the saved settings. Nothing is stored."""
    store = request.app.state.connections
    old = store.mqtt()
    cfg = {"host": body.host, "port": body.port, "protocol": body.protocol,
           "tls": {"enabled": body.tls_enabled, "verify_hostname": body.verify_hostname,
                   "ca_file": None if body.clear_ca else (old.get("tls") or {}).get("ca_file")},
           "username": body.username, "password_file": None if body.clear_password else old.get("password_file"),
           "client_id": body.client_id, "keepalive_s": body.keepalive_s, "subscriptions": body.subscriptions}
    client_cfg = store.mqtt_client_config(cfg, password=body.password or None)
    if body.ca_pem:
        client_cfg["tls"]["ca_pem"] = body.ca_pem
    return checks.check_mqtt(client_cfg, request.app.state.register, body.seconds)


# -- historian tags --------------------------------------------------------------


@router.get("/historian/tags", summary="Browse Timebase tags under this machine")
def browse_tags(request: Request, q: str = "", limit: int = 200) -> dict:
    reg = request.app.state.register
    ns = reg.namespace
    client = _historian_client(request)
    try:
        types = client.tag_types(contains=ns)
    except TimebaseError as e:
        raise Problem(502, "historian-unavailable", "Timebase isn't answering", str(e)) from None
    finally:
        client.close()
    used = {}
    for p in reg.parameters:
        for z in p.get("zones", []):
            for kind in ("setpoint", "actual"):
                if z.get(kind):
                    used[f"{ns}.{z[kind]}"] = f"{p['id']} {p['name']} · {z['name']} {kind}"
    for name, tag in reg.context.items():
        used.setdefault(tag, f"context: {name}")
    needle = q.strip().lower()
    rows = []
    for full, kind in sorted(types.items()):
        rel = full[len(ns) + 1:] if full.startswith(ns + ".") else full
        if needle and needle not in rel.lower():
            continue
        if rel.rsplit(".", 1)[-1].startswith("_") or kind in ("System.String", "System.Boolean") and not needle:
            continue  # message metadata and text fields aren't process values
        rows.append({"tag": rel, "area": rel.split(".", 1)[0], "type": (kind or "").replace("System.", ""),
                     "usedBy": used.get(full)})
    return {"namespace": ns, "total": len(rows), "tags": rows[:max(1, min(limit, 500))]}


@router.post("/historian/latest", summary="Latest value of up to 100 tags")
def latest_values(body: TagsIn, request: Request) -> dict:
    ns = request.app.state.register.namespace
    full = [t if t.startswith(ns + ".") else f"{ns}.{t}" for t in body.tags]
    client = _historian_client(request)
    try:
        known = client.tag_names(contains=ns)
        present = [t for t in dict.fromkeys(full) if t in known]
        out = {t[len(ns) + 1:]: None for t in full}
        for i in range(0, len(present), 20):  # one unknown tag fails a whole request, so only known ones
            for tag, pts in client.read(present[i:i + 20]).items():
                p = pts[-1] if pts else None
                out[tag[len(ns) + 1:]] = None if p is None else {
                    "value": p.v, "quality": p.q, "at": isotime.iso(p.t)}
        return {"values": out, "missing": [t[len(ns) + 1:] for t in full if t not in known]}
    except TimebaseError as e:
        raise Problem(502, "historian-unavailable", "Timebase isn't answering", str(e)) from None
    finally:
        client.close()


# -- parameter register -------------------------------------------------------------


def _register_view(request: Request, conn) -> dict:
    raw = request.app.state.register_store.raw(conn)
    return {
        "version": raw.get("version"),
        "namespace": raw["namespace"],
        "line": raw.get("line"),
        "parameters": [{"id": p["id"], "name": p["name"], "unit": p.get("unit"), "status": p.get("status"),
                        "note": p.get("note"), "review": p.get("tag_review") or p.get("hmi_match_review"),
                        "candidateTags": p.get("candidate_tags", []),
                        "zones": [{"id": z["id"], "name": z["name"], "setpoint": z.get("setpoint"),
                                   "actual": z.get("actual")} for z in p.get("zones", [])]}
                       for p in raw["parameters"]],
        "audit": audit.tail(conn),
        "fileWarning": request.app.state.register_file_warning,
    }


@router.get("/register", summary="The parameter register, with recent changes")
def get_register(request: Request, conn=Depends(connect)) -> dict:
    return _register_view(request, conn)


@router.put("/register/parameters/{pid}", dependencies=[ADMIN_ONLY], summary="Replace a parameter's zones and status (versioned, audited)")
def put_parameter(pid: str, body: ParameterIn, request: Request, conn=Depends(connect)) -> dict:
    reg = request.app.state.register
    client = _historian_client(request)
    try:
        known = client.tag_names(contains=reg.namespace)
    except TimebaseError as e:
        raise Problem(502, "historian-unavailable", "Can't check the tags: Timebase isn't answering", str(e)) from None
    finally:
        client.close()
    request.app.state.register = request.app.state.register_store.update_parameter(conn, pid, body, known)
    request.app.state.register_file_warning = None  # the file was just rewritten from the database
    return _register_view(request, conn)
