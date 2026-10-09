"""The AI's questions (AI-01, AI-02, DAT-01, ADR-0041, ADR-0042): the opening question as soon as a mismatch's request
is open, from the OCAP rows for it, and the follow-up questions after the reason, from the OCAP sections for that;
checked, kept with the request; the fixed questions whenever the model is off, slow or wrong."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from centerline_common import workflow as workflow_mod

import threading
import time

from centerline_api.ai import ollama
from centerline_api.ai import opening
from centerline_api.ai.questions import prompt, validate
from centerline_api.analytics import service
from centerline_api.main import create_app
from centerline_api.settings import AiSettings

from . import ocap_samples as samples
from .conftest import FAST_AUTH, add_account, make_settings, new_client, sign_in
from .fake_ollama import DIGEST, FakeOllama
from .test_monitoring_api import event
from .test_ocap_api import activate, upload
from .test_workflow_api import DESK, REQUESTS, mismatch

FIXED = ["What was changed, and why?", "Is the product affected?"]
SECTION = {"sectionId": "s1", "citation": "OCAP-040 v1 · 1. Seal separates easily · Troubleshooting, row 4",
           "body": "x" * 3000}


def test_an_answer_is_used_only_as_one_or_two_real_questions():
    assert validate(json.dumps({"questions": ["Which side had the weak seal?"]})) == ([("Which side had the weak seal?", None)], None)
    assert validate('{"questions": ["  Which   side   had it?  ", "Was the heater at its preset?"]}')[0] == [
        ("Which side had it?", None), ("Was the heater at its preset?", None)]
    # The Filipino rides along; one that isn't a question, or a list that doesn't pair up, is left out (the English shows)
    both = {"questions": ["Which side had the weak seal?", "Was the heater at its preset?"],
            "questions_fil": ["Saang  gilid ang mahinang seal?", "Nasa preset na ba ang heater."]}
    assert validate(json.dumps(both))[0] == [("Which side had the weak seal?", "Saang gilid ang mahinang seal?"),
                                             ("Was the heater at its preset?", None)]
    assert validate(json.dumps({**both, "questions_fil": ["Saang gilid?"]}))[0][0][1] is None
    for raw, why in (("Sure! Here you go", "not JSON"), ('{"questions": []}', "no questions"),
                     ('{"questions": ["A?", "B is it?", "C is it?"]}', "two at most"),
                     ('{"questions": ["Which side had the weak seal"]}', "not a question"),
                     ('{"questions": ["Set the heater back to 180 °C?"]}', "an instruction"),
                     ('{"questions": ["Please clean the jaw, okay?"]}', "an instruction"),
                     ('{"questions": ["Which side was it?", "which side was it?"]}', "twice"),
                     ('{"questions": ["Ok?"]}', "characters")):
        questions, problem = validate(raw)
        assert questions == [] and why in problem, raw


def test_the_prompt_holds_the_alarm_the_reason_as_written_and_the_sections_cut_to_size():
    text = prompt("The alarm: HMI mismatch on Vertical 1.", "tinaas ko kasi weak seal", [SECTION] * 4)
    assert text.startswith("The alarm: HMI mismatch on Vertical 1.")
    assert '"tinaas ko kasi weak seal"' in text and text.count("[1] OCAP-040 v1") == 1
    assert "[3]" in text and "[4]" not in text  # three sections at most
    assert "x" * 2500 in text and "x" * 2501 not in text
    assert "No OCAP section was found for this reason." in prompt("The alarm.", "kasi", [])


@pytest.fixture
def fake():
    f = FakeOllama()
    ollama._digests.clear()
    yield f
    f.close()
    ollama._digests.clear()


@pytest.fixture
def ai_client(mock_timebase, tmp_path, database, fake):
    service._tag_cache.clear()

    def _make(roles, address="127.0.0.1", auth=FAST_AUTH, **ai):
        settings = replace(make_settings(mock_timebase[1], tmp_path, database, auth=auth),
                           ai=AiSettings(**{"enabled": True, "url": fake.url, "model": "qwen3.5:4b", "timeout_s": 1.5, **ai}))
        c = new_client(create_app(settings), address)
        sign_in(c, add_account(c.app, database, roles))
        return c

    return _make


def _another(database, zone: str, hmi: int) -> str:
    """One more open mismatch on Vertical Temperature (target 180), with its request."""
    with database.connect() as conn:
        v = conn.execute("SELECT config_version_id, mapping_version_id, register_version_id FROM event LIMIT 1").fetchone()
        eid = event(conn, tuple(v.values()), "HMI_MISMATCH", "P02", zone, "OPEN", hmi=hmi)
        workflow_mod.open_request(conn, eid, conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"])
        conn.commit()
        return str(conn.execute("SELECT id FROM workflow_request WHERE event_id = %s", (eid,)).fetchone()["id"])


def _calls(database) -> list[dict]:
    with database.connect() as conn:
        return conn.execute("SELECT * FROM ai_call ORDER BY at").fetchall()


def test_the_models_questions_are_asked_from_the_picked_row_and_kept_with_their_call(ai_client, database, fake):
    manager = ai_client(["MANAGER"])
    sealer = upload(manager, samples.sealer_xlsx(), code="OCAP-040", title="Sealer OCAP", name="sealer.xlsx").json()
    activate(manager, sealer["id"])
    _, rid = mismatch(database)  # Vertical 1 raised: 222 against 180
    op = ai_client(["OPERATOR"], address="10.0.0.5", auth=DESK)
    (req,) = op.get(REQUESTS).json()["requests"]
    assert req["asked"] is None  # nothing asked before the reason
    picked = next(c for c in req["choices"] if c["label"] == "Seal separates easily")
    req = op.post(f"{REQUESTS}/{rid}/reason", json={"sectionId": picked["sectionId"], "note": "kanina pa"}).json()
    assert req["next"] == "answers" and req["asked"] == [
        {"question": "Which side of the pouch had the weak seal?", "questionFil": None, "by": "ai"},
        {"question": "Had the heater reached its preset when it happened?", "questionFil": None, "by": "ai"}]

    (sent,) = fake.chats
    assert (sent["model"], sent["stream"], sent["think"], sent["options"]["temperature"]) == ("qwen3.5:4b", False, False, 0)
    assert sent["format"]["properties"]["questions"]["maxItems"] == 2
    user = sent["messages"][1]["content"]
    assert "HMI mismatch on Vertical 1 (Vertical Temperature)" in user and "222 °C; its target is 180 °C: the setpoint was raised" in user
    assert '"Seal separates easily\nkanina pa"' in user and "Hold the pouches and let the heaters reach their preset." in user
    assert "Never give instructions" in sent["messages"][0]["content"]

    assert op.post(f"{REQUESTS}/{rid}/answers", json={"answers": ["Left side"]}).status_code == 422  # both questions
    req = op.post(f"{REQUESTS}/{rid}/answers", json={"answers": ["Left side", "Not yet"]}).json()
    answers = [(e["question"], e["body"]) for e in req["entries"] if e["kind"] == "answer"]
    assert answers == [("Which side of the pouch had the weak seal?", "Left side"),
                       ("Had the heater reached its preset when it happened?", "Not yet")]
    assert [o["sectionId"] for o in req["offered"]] == [picked["sectionId"]]
    (call,) = _calls(database)
    assert (call["outcome"], call["model"], call["model_digest"], call["prompt_version"]) == ("used", "qwen3.5:4b", DIGEST, "questions-v3")
    assert [str(s) for s in call["sections"]] == [picked["sectionId"]] and "Never give instructions" in call["prompt"]
    assert json.loads(call["raw_output"])["questions"][0] == "Which side of the pouch had the weak seal?"


def test_off_slow_wrong_or_not_pinned_the_fixed_questions_are_asked_and_the_call_says_why(ai_client, database, fake):
    manager = ai_client(["MANAGER"])
    activate(manager, upload(manager, samples.sealer_xlsx(), code="OCAP-040", title="Sealer OCAP", name="sealer.xlsx").json()["id"])
    _, first = mismatch(database)
    op = ai_client(["OPERATOR"], address="10.0.0.5", auth=DESK)

    def explain(rid: str) -> dict:
        req = next(r for r in op.get(REQUESTS).json()["requests"] if r["id"] == rid)
        return op.post(f"{REQUESTS}/{rid}/reason", json={"sectionId": req["choices"][0]["sectionId"], "note": ""}).json()

    fake.reply = {"questions": ["Set the heater to 180 °C now?"]}  # an instruction
    assert [q["by"] for q in explain(first)["asked"]] == ["fixed", "fixed"]
    fake.reply, fake.delay = {"questions": ["Which side was it?"]}, 3  # slower than the 1.5 s allowed
    req = explain(_another(database, "V2", 222))
    assert [q["question"] for q in req["asked"]] == FIXED
    fake.delay, fake.status = 0, 500
    assert [q["by"] for q in explain(_another(database, "V3", 222))["asked"]] == ["fixed", "fixed"]
    calls = _calls(database)
    assert [c["outcome"] for c in calls] == ["rejected", "timeout", "failed"]
    assert "an instruction" in calls[0]["detail"] and calls[1]["latency_ms"] >= 1400 and "500" in calls[2]["detail"]

    same = ai_client(["OPERATOR"], address="10.0.0.5", auth=DESK, model_digest=DIGEST.removeprefix("sha256:"))  # listed bare
    fake.status = 200
    rid = _another(database, "V5", 222)
    req = next(r for r in same.get(REQUESTS).json()["requests"] if r["id"] == rid)
    assert [q["by"] for q in same.post(f"{REQUESTS}/{rid}/reason", json={"sectionId": req["choices"][0]["sectionId"], "note": ""}).json()["asked"]] == ["ai"]
    pinned = ai_client(["OPERATOR"], address="10.0.0.5", auth=DESK, model_digest="sha256:" + "f" * 64)
    fake.status = 200
    rid = _another(database, "V4", 222)
    req = next(r for r in pinned.get(REQUESTS).json()["requests"] if r["id"] == rid)
    req = pinned.post(f"{REQUESTS}/{rid}/reason", json={"sectionId": req["choices"][0]["sectionId"], "note": ""}).json()
    assert [q["by"] for q in req["asked"]] == ["fixed", "fixed"] and "isn't the pinned one" in _calls(database)[-1]["detail"]
    assert len(fake.chats) == 4  # the unpinned model was never asked


def test_without_ocap_sections_the_ai_still_asks_and_with_it_off_nothing_is_sent(ai_client, make_client, database, fake):
    op = ai_client(["OPERATOR"], address="10.0.0.5", auth=DESK)  # its first start imports the register
    _, rid = mismatch(database)  # no OCAP in the library
    req = op.post(f"{REQUESTS}/{rid}/reason", json={"text": "Pinalitan para sa bagong film"}).json()
    assert [q["by"] for q in req["asked"]] == ["ai", "ai"]
    (sent,) = fake.chats
    assert "No OCAP section was found for this reason." in sent["messages"][1]["content"]
    (call,) = _calls(database)
    assert call["sections"] == [] and call["outcome"] == "used"
    fake.chats.clear()
    off = make_client(roles=["OPERATOR"], address="10.0.0.5", auth=DESK)  # the default: no AI
    rid2 = _another(database, "V2", 222)
    assert [q["by"] for q in off.post(f"{REQUESTS}/{rid2}/reason", json={"text": "x y z"}).json()["asked"]] == ["fixed", "fixed"]


def test_the_model_is_loaded_and_warmed_when_it_isnt_in_memory_and_left_alone_when_it_is(fake):
    settings = AiSettings(enabled=True, url=fake.url, model="qwen3.5:4b", warm_every_s=60)
    stop = threading.Event()
    threading.Thread(target=ollama.keep_warm, args=(settings, stop), daemon=True).start()
    for _ in range(100):
        if fake.chats:
            break
        time.sleep(0.1)
    stop.set()
    (warm,) = fake.chats
    assert (warm["model"], warm["keep_alive"], warm["options"]["num_ctx"], warm["options"]["num_predict"]) == ("qwen3.5:4b", "24h", 4096, 8)
    fake.chats.clear()
    fake.running = [{"name": "qwen3.5:4b", "model": "qwen3.5:4b"}]
    stop = threading.Event()
    threading.Thread(target=ollama.keep_warm, args=(settings, stop), daemon=True).start()
    time.sleep(6)
    stop.set()
    assert fake.chats == []  # loaded already: nothing sent


def test_the_ai_opens_each_new_request_from_the_ocap_rows_for_it_and_the_fixed_opening_stands_in(ai_client, database, fake):
    manager = ai_client(["MANAGER"])
    activate(manager, upload(manager, samples.sealer_xlsx(), code="OCAP-040", title="Sealer OCAP", name="sealer.xlsx").json()["id"])
    _, rid = mismatch(database)  # Vertical 1 raised: 222 against 180
    op = ai_client(["OPERATOR"], address="10.0.0.5", auth=DESK)
    listing = op.get(REQUESTS).json()
    assert listing["aiOpening"] is False and listing["requests"][0]["opening"] is None  # this app writes none by itself

    fake.reply = {"question": "Why did you raise Vertical 1: a seal that separates easily, a weak vertical seal, or something else?",
                  "question_fil": "Bakit mo itinaas ang Vertical 1: madaling matanggal ang seal, mahinang vertical seal, o iba pa?"}
    assert opening.pass_once(op.app) == 1 and opening.pass_once(op.app) == 0  # once per request
    (sent,) = fake.chats
    system, user = sent["messages"][0]["content"], sent["messages"][1]["content"]
    assert "Write the first question to the operator" in system and "HMI mismatch on Vertical 1 (Vertical Temperature)" in user
    assert "- Seal separates easily\n- Weak seal on the vertical side" in user and "Burnt or brittle seal" not in user  # raised only
    req = op.get(REQUESTS).json()["requests"][0]
    assert req["opening"] == {"question": fake.reply["question"], "questionFil": fake.reply["question_fil"], "by": "ai"}
    assert req["asked"] is None

    fake.reply = {"questions": ["Which side of the pouch had the weak seal?", "Had the heater reached its preset?"],
                  "questions_fil": ["Saang gilid ng pouch ang mahinang seal?", "Naabot na ba ng heater ang preset nito?"]}
    req = op.post(f"{REQUESTS}/{rid}/reason", json={"sectionId": req["choices"][0]["sectionId"], "note": ""}).json()
    assert req["opening"]["by"] == "ai" and [q["by"] for q in req["asked"]] == ["ai", "ai"]  # the follow-ups, apart
    assert [q["questionFil"] for q in req["asked"]] == fake.reply["questions_fil"]
    calls = _calls(database)
    assert [(c["purpose"], c["prompt_version"]) for c in calls] == [("opening", "opening-v2"), ("questions", "questions-v3")]
    assert len(calls[0]["sections"]) == 3  # the rows offered for a raised Vertical Temperature

    fake.status = 500
    rid2 = _another(database, "V2", 170)
    assert opening.pass_once(op.app) == 1
    req = next(r for r in op.get(REQUESTS).json()["requests"] if r["id"] == rid2)
    assert req["opening"] == {"question": "Why did you change it?", "questionFil": None, "by": "fixed"}
    assert _calls(database)[-1]["purpose"] == "opening" and _calls(database)[-1]["outcome"] == "failed"


def test_an_opening_question_must_be_one_real_question():
    assert opening.validate('{"question": "Why did you lower it:  wrinkles,   or something else?", "question_fil": "Bakit mo ibinaba?"}') == (
        ("Why did you lower it: wrinkles, or something else?", "Bakit mo ibinaba?"), None)
    assert opening.validate('{"question": "Why did you lower it: wrinkles?", "question_fil": "Bakit"}')[0][1] is None
    for raw, why in (("hello", "not JSON"), ('{"questions": ["x?"]}', "no question"), ('{"question": "Lower it now."}', "not a question"),
                     ('{"question": "Set it back to 180, okay?"}', "an instruction"), ('{"question": "Why?"}', "characters")):
        q, problem = opening.validate(raw)
        assert q is None and why in problem, raw


def test_where_the_ai_opens_requests_a_fresh_one_says_its_question_is_on_its_way(ai_client, database, fake):
    op = ai_client(["OPERATOR"], address="10.0.0.5", auth=DESK, open_every_s=3600)  # its writer waits an hour first
    _, rid = mismatch(database)
    listing = op.get(REQUESTS).json()
    (req,) = listing["requests"]
    assert listing["aiOpening"] is True and req["opening"] is None and req["openingPending"] is True
    fake.reply = {"question": "Why did you raise Vertical 1: a weak seal, or something else?"}
    opening.pass_once(op.app)
    (req,) = op.get(REQUESTS).json()["requests"]
    assert req["opening"]["by"] == "ai" and req["openingPending"] is False
