"""The OCAP library and the reason workflow's OCAP steps (OCP-01…03, GDE-01, WF-01, SEC-01, ADR-0031)."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import replace

import psycopg
import pytest

from centerline_api.analytics import service
from centerline_api.main import create_app

from . import ocap_samples as samples
from .conftest import add_account, make_settings, new_client, sign_in
from .ocap_samples import FakeClamd
from .test_workflow_api import REQUESTS, mismatch, operator

OCAPS = "/api/v1/ocaps"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def upload(c, data: bytes, code="OCAP-017", title="Vertical sealing temperature", language="en", name="ocap-017.pdf",
           reason="From the quality binder, 2026 edition"):
    return c.post(OCAPS, json={"code": code, "title": title, "language": language, "source": name, "contentBase64": b64(data),
                               "reason": reason})


def activate(c, vid: str, earlier="supersede", reason="Approved by the QA lead"):
    return c.post(f"{OCAPS}/versions/{vid}/activate", json={"reason": reason, "earlier": earlier})


def search(c, q: str) -> list[dict]:
    return c.get(f"{OCAPS}/search", params={"q": q}).json()["results"]


@pytest.fixture
def clamd():
    fake = FakeClamd()
    yield fake
    fake.close()


@pytest.fixture
def scanned(mock_timebase, tmp_path, database, clamd):
    """A Manager on an api that scans uploads with clamd (the stand-in)."""
    service._tag_cache.clear()
    c = new_client(create_app(replace(make_settings(mock_timebase[1], tmp_path, database), scanner=clamd.settings)))
    sign_in(c, add_account(c.app, database, ["MANAGER"]))
    return c


def test_a_manager_uploads_a_draft_checks_its_sections_and_activates_it_and_then_it_is_searched(make_client, owner):
    manager = make_client(roles=["MANAGER"])
    data = samples.vertical_pdf()
    r = upload(manager, data)
    assert r.status_code == 201, r.text
    draft = r.json()
    assert (draft["number"], draft["status"], draft["pages"], draft["scan"], draft["language"]) == (1, "draft", 4, "not_scanned", "en")
    assert draft["sha256"] == hashlib.sha256(data).hexdigest() and draft["intact"]
    assert [s["heading"] for s in draft["sections"]][4:6] == ["3.1 HMI setpoint changed by mistake",
                                                              "3.2 Heater element or thermocouple fault"]
    assert search(manager, "heater thermocouple") == []  # a draft isn't searched (OCP-01)

    assert activate(manager, draft["id"]).json()["status"] == "active"
    (best, *_) = search(make_client(roles=["OPERATOR"], address="10.0.0.5", auth=_desk()), "heater thermocouple fault")
    assert best["citation"] == "OCAP-017 v1 · 3.2 Heater element or thermocouple fault · p. 3"
    assert "«" in best["excerpt"] and best["code"] == "OCAP-017" and best["version"] == 1
    assert manager.get(f"{OCAPS}/versions/{draft['id']}/original").content == data  # byte for byte
    assert manager.get(f"{OCAPS}/sections/{best['sectionId']}").json()["body"].startswith("If the actual temperature")

    r = upload(manager, samples.bottom_docx(), code="ocap-017", name="other.docx")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "code"  # codes are unique, in any case
    listing = manager.get(OCAPS).json()
    assert (listing["counts"], listing["documents"][0]["active"], listing["scanner"]) == ({"documents": 1, "active": 1}, [1], "none")
    v = manager.get(f"{OCAPS}/versions/{draft['id']}").json()
    assert [h["status"] for h in v["history"]] == ["draft", "active"]
    with owner.connect() as conn, pytest.raises(psycopg.errors.RestrictViolation):
        conn.execute("UPDATE ocap_section SET body = 'rewritten'")  # kept as read, even against the owner


def test_a_new_version_keeps_or_supersedes_the_earlier_one_and_a_version_can_be_suspended(make_client):
    manager = make_client(roles=["MANAGER"])
    v1 = upload(manager, samples.vertical_pdf()).json()
    activate(manager, v1["id"])
    doc = v1["documentId"]
    v2 = manager.post(f"{OCAPS}/{doc}/versions", json={"language": "en", "source": "ocap-017-rev2.docx",
                                                       "contentBase64": b64(samples.bottom_docx()), "reason": "Revision 2"}).json()
    assert (v2["number"], v2["status"]) == (2, "draft")
    assert activate(manager, v2["id"], earlier="keep").status_code == 200
    assert manager.get(OCAPS).json()["documents"][0]["active"] == [2, 1]  # both searched (OCP-03: keep)
    v3 = manager.post(f"{OCAPS}/{doc}/versions", json={"language": "en", "source": "rev3.pdf",
                                                       "contentBase64": b64(samples.vertical_pdf()), "reason": "Revision 3"}).json()
    activate(manager, v3["id"])  # supersede: the earlier active versions retire
    statuses = {v["number"]: v["status"] for v in manager.get(OCAPS).json()["documents"][0]["versions"]}
    assert statuses == {3: "active", 2: "superseded", 1: "superseded"}
    assert manager.post(f"{OCAPS}/versions/{v3['id']}/suspend", json={"reason": "Under review"}).json()["status"] == "suspended"
    assert search(manager, "heater thermocouple") == []
    assert activate(manager, v1["id"]).status_code == 200  # an earlier one can come back
    assert activate(manager, v1["id"]).status_code == 409
    assert manager.post(f"{OCAPS}/versions/{v3['id']}/suspend", json={"reason": "Again"}).status_code == 409
    assert activate(manager, v2["id"], reason="").status_code == 422


def test_uploads_are_scanned_and_an_infected_or_unreadable_file_is_refused_with_nothing_saved(scanned, clamd, database):
    clean = upload(scanned, samples.vertical_pdf()).json()
    assert (clean["scan"], clean["scanDetail"]) == ("clean", "stream: OK")
    r = upload(scanned, samples.infected_docx(), code="OCAP-099", name="bad.docx")
    assert (r.status_code, r.json()["type"]) == (422, "/problems/malware-found") and "Eicar-Signature" in r.json()["detail"]
    for data, why in ((b"\xd0\xcf\x11\xe0 old", "save it as .docx"), (b"%PDF-1.4 broken", "damaged")):
        r = upload(scanned, data, code="OCAP-098")
        assert r.status_code == 422 and why in r.json()["detail"]
    clamd.close()
    r = upload(scanned, samples.bottom_docx(), code="OCAP-097")
    assert (r.status_code, r.json()["type"]) == (503, "/problems/scanner-unavailable")
    with database.connect() as conn:
        assert [d["code"] for d in conn.execute("SELECT code FROM ocap_document")] == ["OCAP-017"]
        refused = conn.execute("SELECT summary FROM audit_log WHERE action = 'upload.refused'").fetchall()
    assert len(refused) == 1 and "OCAP OCAP-099 'bad.docx' refused: malware found (Eicar-Signature)" in refused[0]["summary"]


def test_a_filipino_ocap_is_searched_in_filipino_without_its_function_words(make_client):
    manager = make_client(roles=["MANAGER"])
    v = upload(manager, samples.nozzle_pdf(), code="OCAP-021", title="Presyon ng nozzle", language="fil", name="ocap-021.pdf").json()
    activate(manager, v["id"])
    (best, *_) = search(manager, "barado ang nozzle")
    assert best["heading"] == "2 Mga hakbang kapag barado ang nozzle" and best["language"] == "fil"
    assert search(manager, "ang mga sa ng") == []  # only function words: nothing to match


def _desk():
    from .test_workflow_api import DESK
    return DESK


def _library(manager) -> dict:
    """OCAP-017 (English PDF), OCAP-030 (Word) and OCAP-021 (Filipino), all active."""
    ids = {}
    for data, code, title, lang, name in ((samples.vertical_pdf(), "OCAP-017", "Vertical sealing temperature", "en", "017.pdf"),
                                          (samples.bottom_docx(), "OCAP-030", "Bottom sealing temperature", "en", "030.docx"),
                                          (samples.nozzle_pdf(), "OCAP-021", "Presyon ng nozzle", "fil", "021.pdf")):
        v = upload(manager, data, code=code, title=title, language=lang, name=name).json()
        activate(manager, v["id"])
        ids[code] = v
    return ids


def test_after_the_reason_the_operator_chooses_a_matching_ocap_section_and_acknowledges_it(make_client, database):
    manager = make_client(roles=["MANAGER"])
    library = _library(manager)
    eid, rid = mismatch(database)  # Vertical 1's HMI setpoint at 222 against 180
    op = operator(make_client)
    op.post(f"{REQUESTS}/{rid}/reason", json={"text": "A new film roll, so the HMI setpoint was raised by mistake"})
    req = op.post(f"{REQUESTS}/{rid}/answers", json={"answers": ["Raised it to 222", "No"]}).json()
    assert req["next"] == "ocap" and 1 <= len(req["offered"]) <= 3
    top = req["offered"][0]
    assert top["citation"] == "OCAP-017 v1 · 3.1 HMI setpoint changed by mistake · p. 2" and top["rank"] == 1
    assert top["excerpt"].startswith("If the HMI setpoint of a vertical heater") and "body" not in top

    elsewhere = next(s for s in library["OCAP-030"]["sections"] if s["heading"] == "Bottom heater fault")
    if elsewhere["id"] not in {o["sectionId"] for o in req["offered"]}:
        r = op.post(f"{REQUESTS}/{rid}/ocap", json={"sectionId": elsewhere["id"]})
        assert r.status_code == 422 and r.json()["type"] == "/problems/not-offered"
    chosen = op.post(f"{REQUESTS}/{rid}/ocap", json={"sectionId": top["sectionId"]}).json()
    assert chosen["next"] == "acknowledgment"
    choice = chosen["entries"][-1]
    assert (choice["kind"], choice["body"]) == ("ocap_choice", top["citation"])
    assert choice["section"]["body"].startswith("If the HMI setpoint of a vertical heater differs")  # read in full (OCP-02)
    done = op.post(f"{REQUESTS}/{rid}/acknowledge").json()
    assert done["status"] == "done" and [e["kind"] for e in done["entries"]][-2:] == ["ocap_choice", "acknowledgment"]
    with database.connect() as conn:
        rows = conn.execute("SELECT rank, method, query FROM ocap_recommendation WHERE request_id = %s ORDER BY rank", (rid,)).fetchall()
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1)) and {r["method"] for r in rows} == {"keyword"}
    assert "Vertical 1" in rows[0]["query"] and "film roll" in rows[0]["query"] and "high" in rows[0]["query"]
    evidence = manager.get(f"/api/v1/events/{eid}").json()["requests"][0]
    assert evidence["offered"][0]["sectionId"] == top["sectionId"] and evidence["status"] == "done"


def test_none_of_these_apply_goes_to_a_managers_guidance_with_a_file_and_a_reusable_ocap(make_client, database):
    manager = make_client(roles=["MANAGER"])
    _library(manager)
    _, rid = mismatch(database)
    op = operator(make_client)
    op.post(f"{REQUESTS}/{rid}/reason", json={"text": "Raised the vertical HMI setpoint for a trial film"})
    op.post(f"{REQUESTS}/{rid}/answers", json={"answers": ["For the trial", "No"]})
    assert op.post(f"{REQUESTS}/{rid}/ocap", json={"sectionId": None}).json()["next"] == "guidance"

    taken = manager.post(f"{REQUESTS}/{rid}/guidance", json={"text": "Put it back", "reusable": {"code": "ocap-017", "title": "x"}})
    assert taken.status_code == 422 and taken.json()["errors"] == [{"field": "reusable.code",
                                                                   "message": "ocap-017 already exists: choose another code"}]
    assert op.get(f"{REQUESTS}/{rid}").json()["next"] == "guidance"  # nothing written
    sheet = samples.bottom_docx()
    body = {"text": "Trial films run at 222 °C on Vertical 1 for one shift, then back to 220 °C.",
            "attachment": {"name": "trial-plan.docx", "contentBase64": b64(sheet)},
            "reusable": {"code": "OCAP-050", "title": "Trial films on the verticals", "language": "en"}}
    guided = manager.post(f"{REQUESTS}/{rid}/guidance", json=body).json()
    assert guided["next"] == "acknowledgment"
    attachment = guided["entries"][-1]["attachment"]
    assert (attachment["name"], attachment["scan"], attachment["size"]) == ("trial-plan.docx", "not_scanned", len(sheet))
    assert op.get(f"/api/v1/workflow/attachments/{attachment['id']}").content == sheet
    reusable = next(d for d in manager.get(OCAPS).json()["documents"] if d["code"] == "OCAP-050")
    assert reusable["active"] == [1] and reusable["versions"][0]["source"] == "Written in Centerline"
    assert search(op, "trial films verticals")[0]["code"] == "OCAP-050"  # searched from now on (GDE-01)
    assert op.post(f"{REQUESTS}/{rid}/acknowledge").json()["status"] == "done"


def test_an_infected_attachment_is_refused_and_the_request_still_waits_for_guidance(scanned, make_client, database):
    _, rid = mismatch(database)
    op = operator(make_client)
    op.post(f"{REQUESTS}/{rid}/reason", json={"text": "Changed it"})
    op.post(f"{REQUESTS}/{rid}/answers", json={"answers": ["a", "b"]})  # no OCAP active: straight to guidance
    r = scanned.post(f"{REQUESTS}/{rid}/guidance", json={"text": "Put it back",
                                                        "attachment": {"name": "x.docx", "contentBase64": b64(samples.infected_docx())}})
    assert r.status_code == 422 and r.json()["type"] == "/problems/malware-found"
    assert op.get(f"{REQUESTS}/{rid}").json()["next"] == "guidance"
