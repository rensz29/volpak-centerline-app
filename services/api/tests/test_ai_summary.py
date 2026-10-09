"""The AI's summary of the OCAP sections offered (OCP-02, AI-02, LAN-01, DAT-01, ADR-0046): shown only when it cites
nothing but the sections offered and names no number or instruction they don't have; kept with its call."""

from __future__ import annotations

import json

from centerline_api.ai import summary

from . import ocap_samples as samples
from .fake_ollama import DIGEST
from .test_ai_questions import _another, _calls, ai_client, fake  # noqa: F401 (fixtures)
from .test_ocap_api import activate, upload
from .test_workflow_api import DESK, REQUESTS, mismatch

ALARM = ("The alarm: HMI mismatch on Vertical 1 (Vertical Temperature). The HMI setpoint is 222 °C; its target is 180 °C: "
         "the setpoint was raised.")
SECTIONS = [
    {"citation": "OCAP-040 v1 · 1. Seal separates easily · Sealer Troubleshooting, row 4", "heading": "1. Seal separates easily",
     "body": "Possible Cause: Temperature too low; heater not warm yet\nOperator Mitigation: Hold the pouches and let the heaters "
             "reach their preset.\nCall Maintenance if it isn't at 200 - 220 within 15 min."},
    {"citation": "OCAP-040 v1 · 2. Burnt or brittle seal · Sealer Troubleshooting, row 5", "heading": "2. Burnt or brittle seal",
     "body": "Possible Cause: Temperature too high\nOperator Mitigation: Return to the centerline and let it settle."}]
GOOD = {"summary": "[1] says a seal that separates easily comes from a temperature too low, the heater not warm yet: hold the "
                   "pouches and let the heaters reach their preset. Call Maintenance if it isn't at 200 - 220 within 15 min.",
        "summary_fil": "Ayon sa [1], ang seal na madaling matanggal ay dahil masyadong mababa ang temperature at hindi pa mainit "
                       "ang heater: i-hold ang mga pouch at hayaang maabot ng mga heater ang preset. Tumawag sa Maintenance kung "
                       "hindi pa ito 200 - 220 sa loob ng 15 min.",
        "sections": [1]}


def check(**change):
    return summary.validate(json.dumps({**GOOD, **change}), SECTIONS, ALARM)


def test_a_summary_grounded_in_the_sections_it_cites_is_shown_in_both_languages():
    assert check() == ((GOOD["summary"], GOOD["summary_fil"], [0]), None)
    # The alarm's own words count: the setpoint was raised
    text = "The setpoint was raised. " + GOOD["summary"]
    assert check(summary=text)[0][0] == text
    # Citing both, it may use both
    both = GOOD["summary"] + " [2] says to return to the centerline and let it settle."
    assert check(summary=both, sections=[1, 2])[0][2] == [0, 1]


def test_a_citation_outside_the_sections_offered_shows_no_summary():
    assert check(sections=[3]) == (None, "cites a section that wasn't offered: [3]")
    assert check(summary=GOOD["summary"] + " See also [4].") == (None, "cites a section that wasn't offered: [4]")
    assert check(sections=[]) == (None, "cites no section")


def test_a_number_or_an_instruction_its_sections_dont_have_shows_no_summary():
    assert check(summary=GOOD["summary"].replace("200 - 220", "200 - 230")) == (None, "a number its sections don't have: 230")
    assert check(summary=GOOD["summary"] + " Replace the Teflon tape.") == (None, "an instruction its sections don't have: 'Replace'")
    # [2]'s instruction, while citing only [1]
    assert check(summary=GOOD["summary"] + " Then return to the centerline.") == (
        None, "an instruction its sections don't have: 'return'")
    assert check(summary=GOOD["summary"] + " Never run it hotter.") == (None, "an instruction its sections don't have: 'run'")
    assert check(summary=GOOD["summary"] + " Never let them cool.") == (None, "an instruction its sections don't have: 'Never'")


def test_a_filipino_that_fails_its_checks_leaves_the_english():
    changed = GOOD["summary_fil"].replace("i-hold ang mga pouch", "palitan ang mga pouch")  # replace, not hold
    assert check(summary_fil=changed) == ((GOOD["summary"], None, [0]), None)
    assert check(summary_fil=GOOD["summary"]) == ((GOOD["summary"], None, [0]), None)  # the English copied back
    assert check(summary_fil="") == ((GOOD["summary"], None, [0]), None)


def test_a_filipino_that_says_an_instruction_more_often_than_the_english_leaves_the_english():
    # The trial model's: "palitan" where the English said to tighten, then again for the real "replace"
    en = "[1] says to tighten the bars if needed. Call the mechanic if that fails, and replace any deteriorated parts."
    fil = ("Ayon sa [1], palitan ang mga parts kung hindi matitiyak. Tumawag sa mechanic kung hindi makakapag-tighten, at "
           "palitan ang anumang sirang parts.")
    sections = [{"citation": "c", "heading": "Tightening", "body": "Tighten the bars if needed. Call the mechanic if that fails. "
                                                                   "Replace any deteriorated parts."}]
    assert summary.validate(json.dumps({"summary": en, "summary_fil": fil, "sections": [1]}), sections, ALARM) == ((en, None, [0]), None)


def test_an_english_summary_written_in_tagalog_shows_none():
    text = ("Section [1] ang mga hakbang na kailangan gawin: suriin ang temperature sa HMI, at tumawag sa Maintenance kung "
            "hindi gumagana.")
    assert check(summary=text) == (None, "its English summary isn't in English")


def test_an_answer_that_isnt_a_summary_shows_none():
    assert summary.validate("not json", SECTIONS, ALARM) == (None, "not JSON")
    assert summary.validate('{"sections": [1]}', SECTIONS, ALARM) == (None, "no summary")
    assert check(summary="Hold them.") == (None, "a summary of 10 characters")


# -- the job, against a stand-in for Ollama ------------------------------------------------------------------------------

LIVE = {"summary": "[1] says a seal that separates easily comes from a temperature too low, the heater not warm yet: hold the "
                   "pouches and let the heaters reach their preset.",
        "summary_fil": "Ayon sa [1], ang seal na madaling matanggal ay dahil masyadong mababa ang temperature at hindi pa mainit "
                       "ang heater: i-hold ang mga pouch at hayaang maabot ng mga heater ang preset.",
        "sections": [1]}


def _to_the_ocap_step(ai_client, database, fake, **ai) -> tuple:
    """A mismatch whose operator picked "Seal separates easily" and answered the AI's two questions."""
    manager = ai_client(["MANAGER"])
    activate(manager, upload(manager, samples.sealer_xlsx(), code="OCAP-040", title="Sealer OCAP", name="sealer.xlsx").json()["id"])
    _, rid = mismatch(database)  # Vertical 1 raised: 222 against 180
    op = ai_client(["OPERATOR"], address="10.0.0.5", auth=DESK, **ai)
    (req,) = op.get(REQUESTS).json()["requests"]
    picked = next(c for c in req["choices"] if c["label"] == "Seal separates easily")
    op.post(f"{REQUESTS}/{rid}/reason", json={"sectionId": picked["sectionId"], "note": "kanina pa"})
    req = op.post(f"{REQUESTS}/{rid}/answers", json={"answers": ["Left side", "Not yet"]}).json()
    assert req["next"] == "ocap" and [o["sectionId"] for o in req["offered"]] == [picked["sectionId"]]
    return op, rid, picked


def test_once_the_sections_are_offered_the_ai_sums_them_up_and_the_summary_is_kept_with_its_call(ai_client, database, fake):
    op, rid, picked = _to_the_ocap_step(ai_client, database, fake, summary_every_s=3600)  # its writer waits an hour first
    (req,) = op.get(REQUESTS).json()["requests"]
    assert req["summary"] is None and req["summaryTried"] is False and req["summaryPending"] is True

    fake.reply = LIVE
    assert summary.pass_once(op.app) == 1 and summary.pass_once(op.app) == 0  # once per request
    system, user = fake.chats[-1]["messages"][0]["content"], fake.chats[-1]["messages"][1]["content"]
    assert "Use only what the sections say" in system and "HMI mismatch on Vertical 1 (Vertical Temperature)" in user
    assert 'The operator\'s reason, as they wrote it: "Seal separates easily\nkanina pa"' in user
    assert 'Asked "Which side of the pouch had the weak seal?", they answered: "Left side"' in user
    assert "[1] OCAP-040 v1" in user and "Hold the pouches and let the heaters reach their preset." in user

    (req,) = op.get(REQUESTS).json()["requests"]
    assert req["summaryPending"] is False and req["summaryTried"] is True
    assert req["summary"]["text"] == LIVE["summary"] and req["summary"]["textFil"] == LIVE["summary_fil"]
    assert [s["sectionId"] for s in req["summary"]["sections"]] == [picked["sectionId"]]
    assert req["summary"]["sections"][0]["citation"] == req["offered"][0]["citation"]
    call = _calls(database)[-1]
    assert (call["purpose"], call["outcome"], call["prompt_version"], call["model_digest"]) == ("summary", "used", "summary-v1", DIGEST)
    assert [str(s) for s in call["sections"]] == [picked["sectionId"]]

    # The operator still reads the section and chooses it: the summary changes nothing in the steps
    req = op.post(f"{REQUESTS}/{rid}/ocap", json={"sectionId": picked["sectionId"]}).json()
    assert req["next"] == "acknowledgment" and req["summary"]["text"] == LIVE["summary"]


def test_a_summary_that_fails_its_checks_or_a_model_thats_down_leaves_the_sections_alone(ai_client, database, fake):
    op, rid, _ = _to_the_ocap_step(ai_client, database, fake, summary_every_s=3600)
    fake.reply = {**LIVE, "sections": [2]}  # only one section was offered
    assert summary.pass_once(op.app) == 1
    (req,) = op.get(REQUESTS).json()["requests"]
    assert req["summary"] is None and req["summaryPending"] is False and len(req["offered"]) == 1
    call = _calls(database)[-1]
    assert (call["purpose"], call["outcome"], call["detail"]) == ("summary", "rejected", "cites a section that wasn't offered: [2]")
    assert summary.pass_once(op.app) == 0  # not asked again

    rid2 = _another(database, "V2", 230)  # Vertical 2 raised
    (r2,) = [r for r in op.get(REQUESTS).json()["requests"] if r["id"] == rid2]
    fake.reply = {"questions": ["Which side had it?"]}
    op.post(f"{REQUESTS}/{rid2}/reason", json={"sectionId": r2["choices"][0]["sectionId"], "note": ""})
    assert op.post(f"{REQUESTS}/{rid2}/answers", json={"answers": ["Left"]}).json()["next"] == "ocap"
    fake.status = 500
    assert summary.pass_once(op.app) == 1
    (r2,) = [r for r in op.get(REQUESTS).json()["requests"] if r["id"] == rid2]
    assert r2["summary"] is None and r2["summaryPending"] is False and r2["next"] == "ocap" and r2["offered"]
    assert _calls(database)[-1]["outcome"] == "failed"


def test_with_summaries_off_nothing_is_pending(ai_client, database, fake):
    op, _, _ = _to_the_ocap_step(ai_client, database, fake)
    (req,) = op.get(REQUESTS).json()["requests"]
    assert req["summaryPending"] is False and req["summary"] is None
