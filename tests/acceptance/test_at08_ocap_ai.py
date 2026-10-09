"""AT-08, its AI part: Ollama's bilingual, grounded help over the top three OCAP sections, the exact source, and the
deterministic fallback with Ollama stopped.

URS v1.1 §13 AT-08 ("Ollama bilingual grounded retrieval, top-three OCAPs, exact source and deterministic fallback"),
with AI-01/02, OCP-01/02, LAN-01 and DAT-01, as built in ADR-0041…0043 and ADR-0046. monitor-core judges each mismatch
on the simulated line; the operator answers through the api, the AI's background jobs run a pass when the test says.

"Running" is a stand-in for Ollama on a local port, speaking its API, that answers each request as a correct model
would, so the run is the same every time; the checks then decide what reaches the operator. To run the same flow
against a real Ollama (on the control-room PC, for O-01's model test), set CENTERLINE_AT08_OLLAMA to its URL (and
CENTERLINE_AT08_MODEL, default qwen3.5:4b): what a real model writes varies, so that run asserts only the guarantees.
"Stopped" is a port nothing listens on.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import replace

import pytest
from centerline_api.ai import ollama, opening, summary
from centerline_api.main import create_app
from centerline_api.settings import AiSettings

from .conftest import AT_THE_LINE, SERVICES, _load, add_account, api, new_client, sign_in
from .test_at05_reason_workflow import REQUESTS, open_mismatch
from .test_at08_ocap_deterministic import OCAPS, activate, samples, upload

fake_ollama = _load("acceptance_fake_ollama", SERVICES / "api" / "tests" / "fake_ollama.py")

MISTAKE = "3.1 HMI setpoint changed by mistake"
REPLACE_TOO = "3.2 Heater element or thermocouple fault"
REASON = "Bagong film roll, tinaas ko yung HMI setpoint by mistake"  # Taglish, as operators write


def stand_in(body: dict) -> dict:
    """A correct model: the opening question, one follow-up, or a summary of section 3.1, each in both languages."""
    system, user = body["messages"][0]["content"], body["messages"][1]["content"]
    if "Write the first question" in system:
        return {"question": "Why did you raise Vertical 1: a new film roll, a trial, or something else?",
                "question_fil": "Bakit mo itinaas ang Vertical 1: bagong film roll, trial, o iba pa?"}
    if "follow-up questions" in system:
        return {"questions": ["Did the shift leader ask for the change for the new film roll?"],
                "questions_fil": ["Hiningi ba ng shift leader ang pagbabago para sa bagong film roll?"]}
    n = next(m[1] for m in re.finditer(r"\[(\d)\] [^\n]*\n([^\n]*)", user) if m[2] == MISTAKE)
    return {"summary": f"[{n}] says to set the vertical heater's HMI setpoint back to its centerline target on the HMI, check "
                       "with the shift leader whether a new film roll or a trial asked for the change, and record the reason "
                       "in Centerline.",
            "summary_fil": f"Ayon sa [{n}], i-set pabalik ang HMI setpoint ng vertical heater sa centerline target nito sa HMI, "
                           "suriin kasama ang shift leader kung may bagong film roll o trial na humingi ng pagbabago, at itala "
                           "ang dahilan sa Centerline.",
            "sections": [int(n)]}


@pytest.fixture
def ai(mock_timebase, tmp_path, database):
    """Clients on an api with the AI on, at the line desk; the stand-in model, or the real one when asked for."""
    fake = fake_ollama.FakeOllama()
    fake.reply = stand_in
    ollama._digests.clear()

    def _make(roles, url: str | None = None, model: str = "qwen3.5:4b"):
        settings = replace(api.make_settings(mock_timebase[1], tmp_path, database, auth=AT_THE_LINE),
                           ai=AiSettings(enabled=True, url=url or fake.url, model=model, timeout_s=30,
                                         open_every_s=3600, summary_every_s=3600))  # their jobs run when the test says
        c = new_client(create_app(settings), "10.0.0.5")
        sign_in(c, add_account(c.app, database, roles))
        return c

    yield _make, fake
    fake.close()
    ollama._digests.clear()


def _calls(database) -> list[dict]:
    with database.connect() as conn:
        return conn.execute("SELECT * FROM ai_call ORDER BY at").fetchall()


def _library(make_client) -> dict:
    manager = make_client(roles=["MANAGER"])
    vertical = activate(manager, upload(manager, samples.vertical_pdf(), "OCAP-017", "Vertical sealing temperature", "017.pdf"))
    activate(manager, upload(manager, samples.bottom_docx(), "OCAP-030", "Bottom sealing temperature", "030.docx"))
    upload(manager, samples.vertical_pdf(), "OCAP-018", "Vertical sealing temperature, the new jaws (draft)", "018.pdf")
    return vertical


@pytest.mark.urs("AI-01", "AI-02", "OCP-01", "OCP-02", "LAN-01", "DAT-01", "WF-01")
def test_with_ollama_running_the_operator_gets_bilingual_questions_and_a_grounded_summary_over_the_exact_source(
        make_client, plant, ai, database):
    client, _ = ai
    owner = make_client()
    vertical = _library(make_client)
    _, event = open_mismatch(owner, plant)  # Vertical 1's HMI setpoint at 222 against 180
    op = client(["OPERATOR"])

    # The AI opens: why the setpoint changed, in English and Tagalog (AI-02, LAN-01)
    (req,) = op.get(REQUESTS).json()["requests"]
    assert req["openingPending"] is True
    assert opening.pass_once(op.app) == 1
    (req,) = op.get(REQUESTS).json()["requests"]
    assert req["opening"] == {"question": "Why did you raise Vertical 1: a new film roll, a trial, or something else?",
                              "questionFil": "Bakit mo itinaas ang Vertical 1: bagong film roll, trial, o iba pa?", "by": "ai"}

    # A Taglish reason, kept as typed; at most two clarifications (AI-02), bilingual
    req = op.post(f"{REQUESTS}/{req['id']}/reason", json={"text": REASON}).json()
    assert req["entries"][0]["body"] == REASON
    assert req["asked"] == [{"question": "Did the shift leader ask for the change for the new film roll?",
                             "questionFil": "Hiningi ba ng shift leader ang pagbabago para sa bagong film roll?", "by": "ai"}]
    req = op.post(f"{REQUESTS}/{req['id']}/answers", json={"answers": ["Oo, para sa bagong roll"]}).json()

    # The top three Active sections (OCP-01), a Draft never
    assert req["next"] == "ocap" and 1 <= len(req["offered"]) <= 3
    assert all(o["status"] == "active" and o["code"] != "OCAP-018" for o in req["offered"])
    assert MISTAKE in [o["heading"] for o in req["offered"]]
    (listed,) = op.get(REQUESTS).json()["requests"]
    assert listed["summaryPending"] is True and listed["summary"] is None

    # The AI's summary, beside the exact source (OCP-02): it cites only sections offered, in both languages
    assert summary.pass_once(op.app) == 1
    (req,) = op.get(REQUESTS).json()["requests"]
    s = req["summary"]
    assert s["text"].endswith("and record the reason in Centerline.") and s["textFil"].startswith("Ayon sa [")
    offered = {o["sectionId"]: o for o in req["offered"]}
    assert [x["sectionId"] for x in s["sections"]] == [next(i for i, o in offered.items() if o["heading"] == MISTAKE)]
    assert all(x["sectionId"] in offered and x["citation"] == offered[x["sectionId"]]["citation"] for x in s["sections"])
    cited = s["sections"][0]["sectionId"]
    section = op.get(f"{OCAPS}/sections/{cited}").json()
    as_read = next(x for x in vertical["sections"] if x["id"] == cited)
    assert (section["heading"], section["body"]) == (as_read["heading"], as_read["body"])  # the exact source, as read

    # Acknowledgment confirms review only (OCP-02)
    op.post(f"{REQUESTS}/{req['id']}/ocap", json={"sectionId": cited})
    done = op.post(f"{REQUESTS}/{req['id']}/acknowledge").json()
    assert done["status"] == "done" and done["summary"]["text"] == s["text"]

    # Every call kept, with the model's digest, the prompt's version and the sections sent (DAT-01)
    calls = _calls(database)
    assert [(c["purpose"], c["outcome"], c["prompt_version"]) for c in calls] == [
        ("opening", "used", "opening-v2"), ("questions", "used", "questions-v3"), ("summary", "used", "summary-v1")]
    assert all(c["model"] == "qwen3.5:4b" and c["model_digest"] == fake_ollama.DIGEST and c["raw_output"] for c in calls)
    assert sorted(map(str, calls[2]["sections"])) == sorted(offered)
    evidence = owner.get(f"/api/v1/events/{event['id']}").json()["requests"][0]
    assert evidence["summary"]["text"] == s["text"]


@pytest.mark.urs("AI-02", "OCP-02")
def test_a_summary_that_cites_or_says_what_the_sections_offered_dont_is_never_shown(make_client, plant, ai, database):
    client, fake = ai
    owner = make_client()
    _library(make_client)
    p, _ = open_mismatch(owner, plant)
    p.line.set("P02.V2", setpoint=230)  # a second mismatch: one wrong summary for each
    p.run(p.t + 31)
    op = client(["OPERATOR"])
    requests = sorted(op.get(REQUESTS).json()["requests"], key=lambda r: r["event"]["zoneId"])
    assert [r["event"]["zoneId"] for r in requests] == ["V1", "V2"]

    for req, wrong, why in (
            (requests[0], lambda n: {"sections": [4]}, "cites a section that wasn't offered: [4]"),
            # 3.2's instruction, said of 3.1
            (requests[1], lambda n: {"summary": f"[{n}] says to replace the faulty part and test-seal ten sachets.", "sections": [n]},
             "an instruction its sections don't have: 'replace'")):
        op.post(f"{REQUESTS}/{req['id']}/reason", json={"text": REASON})
        req = op.post(f"{REQUESTS}/{req['id']}/answers", json={"answers": ["Oo"]}).json()
        n = 1 + [o["heading"] for o in req["offered"]].index(MISTAKE)
        fake.reply = lambda body, wrong=wrong, n=n: stand_in(body) if "Sum up" not in body["messages"][0]["content"] \
            else {**stand_in(body), **wrong(n)}
        assert summary.pass_once(op.app) == 1
        (listed,) = [r for r in op.get(REQUESTS).json()["requests"] if r["id"] == req["id"]]
        assert listed["summary"] is None and listed["offered"] == req["offered"]  # the sections, without a summary
        assert (_calls(database)[-1]["outcome"], _calls(database)[-1]["detail"]) == ("rejected", why)
        fake.reply = stand_in


@pytest.mark.urs("AI-01", "OCP-01", "OCP-02", "WF-01")
def test_with_ollama_stopped_the_same_steps_run_on_the_fixed_questions_and_the_sections_alone(make_client, plant, ai, database):
    client, _ = ai
    owner = make_client()
    _library(make_client)
    open_mismatch(owner, plant)
    op = client(["OPERATOR"], url="http://127.0.0.1:9")  # nothing listens there

    assert opening.pass_once(op.app) == 1
    (req,) = op.get(REQUESTS).json()["requests"]
    assert req["opening"] == {"question": "Why did you change it?", "questionFil": None, "by": "fixed"}
    started = time.monotonic()
    req = op.post(f"{REQUESTS}/{req['id']}/reason", json={"text": REASON}).json()
    assert time.monotonic() - started < 30  # PER-01: an AI result in 30 s, here its absence
    assert [q["by"] for q in req["asked"]] == ["fixed", "fixed"]
    req = op.post(f"{REQUESTS}/{req['id']}/answers", json={"answers": ["Bagong roll", "Hindi"]}).json()
    assert req["next"] == "ocap" and MISTAKE in [o["heading"] for o in req["offered"]]  # the keyword path

    assert summary.pass_once(op.app) == 1
    (req,) = op.get(REQUESTS).json()["requests"]
    assert req["summary"] is None and req["summaryPending"] is False  # the chat stops waiting for it
    top = req["offered"][0]
    op.post(f"{REQUESTS}/{req['id']}/ocap", json={"sectionId": top["sectionId"]})
    assert op.post(f"{REQUESTS}/{req['id']}/acknowledge").json()["status"] == "done"
    calls = _calls(database)
    assert [(c["purpose"], c["outcome"]) for c in calls] == [("opening", "failed"), ("questions", "failed"), ("summary", "failed")]
    assert all("isn't answering" in c["detail"] for c in calls)


@pytest.mark.skipif(not os.environ.get("CENTERLINE_AT08_OLLAMA"), reason="set CENTERLINE_AT08_OLLAMA to a real Ollama's URL")
@pytest.mark.urs("AI-01", "AI-02", "OCP-01", "OCP-02")
def test_with_a_real_ollama_only_grounded_help_reaches_the_operator(make_client, plant, ai, database):
    client, _ = ai
    owner = make_client()
    _library(make_client)
    open_mismatch(owner, plant)
    op = client(["OPERATOR"], url=os.environ["CENTERLINE_AT08_OLLAMA"], model=os.environ.get("CENTERLINE_AT08_MODEL", "qwen3.5:4b"))
    opening.pass_once(op.app)
    (req,) = op.get(REQUESTS).json()["requests"]
    assert req["opening"]["question"].endswith("?")
    req = op.post(f"{REQUESTS}/{req['id']}/reason", json={"text": REASON}).json()
    assert 1 <= len(req["asked"]) <= 2 and all(q["question"].endswith("?") for q in req["asked"])
    req = op.post(f"{REQUESTS}/{req['id']}/answers", json={"answers": ["Oo"] * len(req["asked"])}).json()
    summary.pass_once(op.app)
    (req,) = op.get(REQUESTS).json()["requests"]
    if req["summary"] is not None:
        assert {x["sectionId"] for x in req["summary"]["sections"]} <= {o["sectionId"] for o in req["offered"]}
    for c in _calls(database):
        print(f"\n{c['purpose']}: {c['outcome']} in {c['latency_ms']} ms {c['detail'] or ''}\n{c['raw_output']}")
