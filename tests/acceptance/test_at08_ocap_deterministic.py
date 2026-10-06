"""AT-08, its deterministic part: the OCAP library, the top three sections with their exact source, and the path
without AI.

URS v1.1 §7 (OCP-01…03, GDE-01), WF-01, SEC-01 and AI-01, as built in ADR-0031. monitor-core judges each mismatch on
the simulated line; the Manager and the operator act through the api. Nothing here runs a model: this is the path
the plan keeps for when Ollama is down or slow, and the only one until O-01 closes. AT-08's AI part (grounded
summaries, translation, embedding search) comes with the ai-worker, and G3 waits for it.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import replace

import pytest
from centerline_api.main import create_app

from .conftest import SERVICES, _load, add_account, api, new_client, sign_in
from .test_at05_reason_workflow import REQUESTS, open_mismatch, operator

samples = _load("acceptance_ocap_samples", SERVICES / "api" / "tests" / "ocap_samples.py")
OCAPS = "/api/v1/ocaps"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def upload(manager, data: bytes, code: str, title: str, name: str, language: str = "en") -> dict:
    r = manager.post(OCAPS, json={"code": code, "title": title, "language": language, "source": name, "contentBase64": b64(data),
                                  "reason": "From the quality binder"})
    assert r.status_code == 201, r.text
    return r.json()


def activate(manager, version: dict, earlier: str = "supersede") -> dict:
    r = manager.post(f"{OCAPS}/versions/{version['id']}/activate", json={"reason": "Approved by the QA lead", "earlier": earlier})
    assert r.status_code == 200, r.text
    return r.json()


def explain(op, rid: str, reason: str, answers=("Raised it to 222", "No")) -> dict:
    op.post(f"{REQUESTS}/{rid}/reason", json={"text": reason})
    return op.post(f"{REQUESTS}/{rid}/answers", json={"answers": list(answers)}).json()


@pytest.fixture
def clamd():
    fake = samples.FakeClamd()
    yield fake
    fake.close()


@pytest.fixture
def scanned(mock_timebase, tmp_path, database, clamd):
    """A Manager on an api that scans every upload with clamd (its stand-in, speaking clamd's protocol)."""
    settings = api.make_settings(mock_timebase[1], tmp_path, database)
    c = new_client(create_app(replace(settings, scanner=clamd.settings)))
    sign_in(c, add_account(c.app, database, ["MANAGER"]))
    return c


@pytest.mark.urs("OCP-01", "OCP-02", "WF-01", "AI-01")
def test_a_mismatch_is_offered_the_three_best_active_sections_with_their_exact_source_without_any_ai(make_client, plant):
    owner = make_client()
    manager = make_client(roles=["MANAGER"])
    vertical = activate(manager, upload(manager, samples.vertical_pdf(), "OCAP-017", "Vertical sealing temperature", "017.pdf"))
    activate(manager, upload(manager, samples.bottom_docx(), "OCAP-030", "Bottom sealing temperature", "030.docx"))
    draft = upload(manager, samples.vertical_pdf(), "OCAP-018", "Vertical sealing temperature, the new jaws (draft)", "018.pdf")

    _, event = open_mismatch(owner, plant)  # Vertical 1's HMI setpoint at 222 against 180
    op = operator(make_client)
    (req,) = op.get(REQUESTS).json()["requests"]
    req = explain(op, req["id"], "A new film roll, so the HMI setpoint was raised by mistake")
    assert req["status"] == "waiting_ocap" and 1 <= len(req["offered"]) <= 3
    assert [o["rank"] for o in req["offered"]] == list(range(1, len(req["offered"]) + 1))
    assert all(o["status"] == "active" and o["versionId"] != draft["id"] for o in req["offered"])  # a Draft isn't searched
    top = req["offered"][0]
    assert top["citation"] == "OCAP-017 v1 · 3.1 HMI setpoint changed by mistake · p. 2"

    # the operator reads the exact section, as it was read from the file, and its file byte for byte (OCP-02)
    section = op.get(f"{OCAPS}/sections/{top['sectionId']}").json()
    as_read = next(s for s in vertical["sections"] if s["id"] == top["sectionId"])
    assert (section["heading"], section["body"], section["pageFrom"]) == (as_read["heading"], as_read["body"], 2)
    assert hashlib.sha256(op.get(f"{OCAPS}/versions/{vertical['id']}/original").content).hexdigest() == vertical["sha256"]

    chosen = op.post(f"{REQUESTS}/{req['id']}/ocap", json={"sectionId": top["sectionId"]}).json()
    assert chosen["next"] == "acknowledgment" and chosen["entries"][-1]["section"]["body"] == as_read["body"]
    done = op.post(f"{REQUESTS}/{req['id']}/acknowledge").json()
    assert done["status"] == "done"
    assert [e["kind"] for e in done["entries"]] == ["reason", "answer", "answer", "ocap_choice", "acknowledgment"]
    # the event's evidence keeps what was offered and what was chosen
    evidence = owner.get(f"/api/v1/events/{event['id']}").json()["requests"][0]
    assert [o["sectionId"] for o in evidence["offered"]] == [o["sectionId"] for o in req["offered"]]


@pytest.mark.urs("OCP-03")
def test_a_manager_uploads_versions_activates_them_without_a_second_approval_and_keeps_or_retires_the_earlier(make_client, owner):
    manager = make_client(roles=["MANAGER"])
    v1 = upload(manager, samples.vertical_pdf(), "OCAP-017", "Vertical sealing temperature", "017.pdf")
    assert (v1["status"], v1["pages"], len(v1["sections"])) == ("draft", 4, 7)  # checked by the Manager before activating
    activate(manager, v1)
    doc = v1["documentId"]
    new = lambda name, data: manager.post(f"{OCAPS}/{doc}/versions", json={"language": "en", "source": name, "contentBase64": b64(data),
                                                                          "reason": "Revised"}).json()
    v2 = activate(manager, new("017-rev2.docx", samples.bottom_docx()), earlier="keep")
    assert manager.get(OCAPS).json()["documents"][0]["active"] == [2, 1]
    activate(manager, new("017-rev3.pdf", samples.vertical_pdf()))
    statuses = {v["number"]: v["status"] for v in manager.get(OCAPS).json()["documents"][0]["versions"]}
    assert statuses == {3: "active", 2: "superseded", 1: "superseded"}
    assert manager.post(f"{OCAPS}/versions/{v2['id']}/suspend", json={"reason": "Under review"}).status_code == 409  # not active
    with owner.connect() as conn:
        actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log WHERE action LIKE 'ocap.%' ORDER BY seq")]
    assert actions == ["ocap.version", "ocap.activate", "ocap.version", "ocap.activate", "ocap.version", "ocap.activate"]


@pytest.mark.urs("GDE-01", "WF-01")
def test_when_none_apply_a_manager_guides_with_a_file_and_the_guidance_is_offered_next_time(make_client, plant):
    owner = make_client()
    manager = make_client(roles=["MANAGER"])
    activate(manager, upload(manager, samples.bottom_docx(), "OCAP-030", "Bottom sealing temperature", "030.docx"))
    p, _ = open_mismatch(owner, plant)
    op = operator(make_client)
    (req,) = op.get(REQUESTS).json()["requests"]
    req = explain(op, req["id"], "Raised for a trial film", answers=("For the trial", "No"))
    if req["next"] == "ocap":
        req = op.post(f"{REQUESTS}/{req['id']}/ocap", json={"sectionId": None}).json()  # none of these apply
    assert req["next"] == "guidance"

    plan = samples.bottom_docx()
    guided = manager.post(f"{REQUESTS}/{req['id']}/guidance", json={
        "text": "Trial films run at 222 °C on Vertical 1 for one shift, then back to 180 °C.",
        "attachment": {"name": "trial-plan.docx", "contentBase64": b64(plan)},
        "reusable": {"code": "OCAP-050", "title": "Trial films on the verticals", "language": "en"}}).json()
    attachment = guided["entries"][-1]["attachment"]
    assert op.get(f"/api/v1/workflow/attachments/{attachment['id']}").content == plan
    assert op.post(f"{REQUESTS}/{req['id']}/acknowledge").json()["status"] == "done"

    # the next mismatch with those words is offered the Manager's guidance, as an OCAP of its own
    p.line.set("P02.V2", setpoint=222)
    p.run(p.t + 31)
    (second,) = [r for r in op.get(REQUESTS).json()["requests"] if r["status"] == "waiting_reason"]
    second = explain(op, second["id"], "Trial film again", answers=("For the trial", "No"))
    assert second["next"] == "ocap" and second["offered"][0]["citation"] == "OCAP-050 v1 · Trial films on the verticals"


@pytest.mark.urs("SEC-01")
def test_every_upload_is_scanned_and_an_infected_file_or_a_silent_scanner_saves_nothing(scanned, clamd, make_client, plant, database):
    clean = upload(scanned, samples.vertical_pdf(), "OCAP-017", "Vertical sealing temperature", "017.pdf")
    assert (clean["scan"], clean["scanDetail"]) == ("clean", "stream: OK") and clamd.scanned[-1] == samples.vertical_pdf()
    r = scanned.post(OCAPS, json={"code": "OCAP-099", "title": "Sent by mail", "language": "en", "source": "bad.docx",
                                  "contentBase64": b64(samples.infected_docx()), "reason": "From a supplier's email"})
    assert (r.status_code, r.json()["type"]) == (422, "/problems/malware-found")

    owner = make_client()
    open_mismatch(owner, plant)
    op = operator(make_client)
    (req,) = op.get(REQUESTS).json()["requests"]
    explain(op, req["id"], "Changed it")  # no Active OCAP: straight to a Manager
    r = scanned.post(f"{REQUESTS}/{req['id']}/guidance", json={"text": "Put it back",
                                                               "attachment": {"name": "x.docx", "contentBase64": b64(samples.infected_docx())}})
    assert (r.status_code, r.json()["type"]) == (422, "/problems/malware-found")
    clamd.close()
    r = scanned.post(f"{REQUESTS}/{req['id']}/guidance", json={"text": "Put it back",
                                                               "attachment": {"name": "plan.docx", "contentBase64": b64(samples.bottom_docx())}})
    assert (r.status_code, r.json()["type"]) == (503, "/problems/scanner-unavailable")
    assert op.get(f"{REQUESTS}/{req['id']}").json()["next"] == "guidance"  # still waiting: nothing was written
    with database.connect() as conn:
        assert [d["code"] for d in conn.execute("SELECT code FROM ocap_document")] == ["OCAP-017"]
        assert conn.execute("SELECT count(*) AS n FROM workflow_attachment").fetchone()["n"] == 0
        refused = conn.execute("SELECT count(*) AS n FROM audit_log WHERE action = 'upload.refused'").fetchone()["n"]
    assert refused == 2
