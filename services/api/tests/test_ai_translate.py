"""The checks on the AI's Tagalog translation of an OCAP section (ADR-0045): only a faithful one is shown."""

import json
import re

from centerline_api.ai import translate
from centerline_api.settings import AiSettings

from . import ocap_samples as samples
from .fake_ollama import DIGEST
from .test_ai_questions import ai_client, fake  # noqa: F401 (fixtures)
from .test_ocap_api import OCAPS, activate, b64, upload
from .test_workflow_api import DESK, REQUESTS, mismatch

SECTION = {"heading": "Weak seal", "phenomenon": "Weak seal on the pouch",
           "body": "Operator Mitigation Plan: Stop and isolate affected pouches.\nClean the jaw with a damp cloth.\n"
                   "- Must be 6mm on both sides (Vertical)\nCall Maintenance if the temperature does not reach 180 C."}
GOOD = ["Mahinang seal", "Mahinang seal sa pouch",
        "Plano ng Operator: Itigil at ihiwalay ang mga apektadong pouch.", "Linisin ang jaw gamit ang mamasa-masang tela.",
        "- Dapat 6mm sa magkabilang gilid (Vertical)", "Tumawag sa Maintenance kung hindi maabot ng temperature ang 180 C."]


def run(lines):
    return translate.check(json.dumps({"lines": lines}), translate.lines_of(SECTION))


def test_a_faithful_translation_is_used():
    out, problem = run(GOOD)
    assert problem is None
    assert out == {"heading": "Mahinang seal", "label": "Mahinang seal sa pouch", "body": "\n".join(GOOD[2:])}


def test_clean_turned_into_replace_is_refused():
    # What the trial model did: "Clean the jaw" → "Palitan ang jaw" (replace)
    out, problem = run([*GOOD[:3], "Palitan ang jaw gamit ang mamasa-masang tela.", *GOOD[4:]])
    assert out is None and "line 4 lost 'Clean'" in problem


def test_an_added_instruction_is_refused():
    out, problem = run([*GOOD[:4], "- Huwag gawing 6mm sa magkabilang gilid (Vertical)", *GOOD[5:]])
    assert out is None and "line 5 added 'Huwag'" in problem


def test_a_lost_number_is_refused():
    out, problem = run([*GOOD[:5], "Tumawag sa Maintenance kung hindi maabot ng temperature ang preset."])
    assert out is None and problem == "numbers lost: 180"
    # Lines shifted by one: every number is there, each in the wrong line
    shifted = [GOOD[0], GOOD[1], GOOD[2], GOOD[3], GOOD[5], GOOD[4]]
    assert run(shifted)[1].startswith("line 5 doesn't match its English")


def test_lines_must_pair_up():
    assert run(GOOD[:-1]) == (None, "5 lines for 6")
    assert run([*GOOD, "Dagdag na linya"]) == (None, "7 lines for 6")
    assert translate.check("not json", translate.lines_of(SECTION)) == (None, "not JSON")
    assert translate.check(json.dumps({"lines": "Mahinang seal"}), translate.lines_of(SECTION))[1] == "no lines for 6"


def test_text_left_in_english_is_refused():
    english = translate.lines_of(SECTION)
    out, problem = run([GOOD[0], GOOD[1], *english[2:]])
    assert out is None and problem.startswith("not translated")


def test_a_short_line_may_stay_as_written():
    section = {**SECTION, "body": "HMI\nClean the jaw with a damp cloth."}
    lines = ["Mahinang seal", "Mahinang seal sa pouch", "HMI", "Linisin ang jaw gamit ang mamasa-masang tela."]
    out, problem = translate.check(json.dumps({"lines": lines}), translate.lines_of(section))
    assert problem is None and out["body"] == "HMI\nLinisin ang jaw gamit ang mamasa-masang tela."


def test_infixed_verbs_count():
    # The root takes an infix: tumawag (call), tumigil (stop), pinalitan (replace)
    section = {"heading": "", "phenomenon": "", "body": "Call Maintenance and stop the machine.\nReplace the Teflon tape on the jaw."}
    lines = ["", "", "Tumawag sa Maintenance at tumigil ang makina.", "Pinalitan ang Teflon tape sa jaw."]
    assert translate.check(json.dumps({"lines": lines}), translate.lines_of(section)) == (
        {"heading": None, "label": None, "body": "\n".join(lines[2:])}, None)
    lines[3] = "Pinalitan ang Teflon tape sa jaw, saka tumawag."
    section["body"] = "Call Maintenance and stop the machine.\nClean the Teflon tape on the jaw."
    assert "lost 'Clean'" in translate.check(json.dumps({"lines": lines}), translate.lines_of(section))[1]


# -- the background job, against a stand-in for Ollama ------------------------------------------------------------------

GLOSSARY = [(r"\bClean\b", "Linisin"), (r"\bclean\b", "linisin"), (r"\bReturn to\b", "Ibalik sa"), (r"\bCheck\b", "Suriin"),
            (r"\bStop\b", "Itigil"), (r"\bCall\b", "Tumawag"), (r"\bReplace\b", "Palitan"), (r"\bnot\b", "hindi")]


def translator(bad: str | None = None):
    """A stand-in model: "Sa Tagalog:" before each line, the glossary's words swapped in. A section whose text has `bad`
    gets "Palitan" (replace) for "Ibalik" (return), as the trial model did with "clean"."""
    def reply(body: dict) -> dict:
        lines = json.loads(body["messages"][1]["content"].split("\n", 1)[1])["lines"]
        out = []
        for line in lines:
            for en, fil in GLOSSARY:
                line = re.sub(en, fil, line)
            out.append("Sa Tagalog: " + line if line.strip() else line)
        if bad and any(bad in x for x in lines):
            out = [x.replace("Ibalik", "Palitan") for x in out]
        return {"lines": out}
    return reply


def _attempts(database) -> list[dict]:
    with database.connect() as conn:
        return conn.execute("SELECT * FROM ocap_ai_translation ORDER BY at").fetchall()


def test_the_ai_translates_each_section_of_an_active_ocap_once_and_one_that_fails_a_check_stays_english(ai_client, database, fake):
    manager = ai_client(["MANAGER"])
    v = upload(manager, samples.sealer_xlsx(), code="OCAP-040", title="Sealer OCAP", name="sealer.xlsx").json()
    fake.reply = translator(bad="Return to")
    assert translate.pass_once(manager.app) is None and fake.chats == []  # a Draft isn't translated
    activate(manager, v["id"])
    outcomes = []
    while (outcome := translate.pass_once(manager.app)) is not None:
        outcomes.append(outcome)
    n = len(v["sections"])
    assert len(outcomes) == n and outcomes.count("rejected") == 1 and outcomes.count("used") == n - 1  # once each
    # An OCAP in Filipino stays as written
    fil = upload(manager, samples.sealer_xlsx(), code="OCAP-050", title="Sealer OCAP (Filipino)", language="fil", name="sealer-fil.xlsx").json()
    activate(manager, fil["id"])
    asked = len(fake.chats)  # nobody is answering yet
    assert translate.pass_once(manager.app) is None and len(fake.chats) == asked
    system, user = fake.chats[0]["messages"][0]["content"], fake.chats[0]["messages"][1]["content"]
    ask, lines = user.split("\n", 1)
    assert "clean = linisin" in system and ask == "Translate these lines into Tagalog:"
    assert json.loads(lines)["lines"][:2] == ["1. Weak seal on the vertical side", "Weak seal on the vertical side"]  # heading, reason
    assert fake.chats[0]["options"]["temperature"] == 0

    view = manager.get(f"{OCAPS}/versions/{v['id']}").json()
    assert view["aiTagalog"] == {"on": False, "translated": n - 1, "english": 1, "waiting": 0}  # its job isn't started here
    burnt = next(s for s in view["sections"] if s["phenomenon"] == "Burnt or brittle seal")
    assert burnt["fil"] is None and "lost 'Return'" in burnt["filNote"]
    first = next(s for s in view["sections"] if s["phenomenon"] == "Seal separates easily")
    assert first["fil"]["by"] == "ai" and first["fil"]["phenomenon"] == "Sa Tagalog: Seal separates easily"
    assert first["filNote"] is None
    attempts = _attempts(database)
    assert len(attempts) == n and {a["prompt_version"] for a in attempts} == {"ocap-fil-v1"}
    assert all(a["model_digest"] == DIGEST and a["raw_output"] for a in attempts)

    _, rid = mismatch(database)  # Vertical 1 raised: an operator is answering
    op = ai_client(["OPERATOR"], address="10.0.0.5", auth=DESK)
    (req,) = op.get(REQUESTS).json()["requests"]
    picked = next(c for c in req["choices"] if c["label"] == "Seal separates easily")
    assert picked["labelFil"] == "Sa Tagalog: Seal separates easily"
    section = op.get(f"{OCAPS}/sections/{picked['sectionId']}").json()
    assert section["body"].startswith("Sealer / Area: Top / Bottom / Vertical")  # the English stays the source (OCP-02)
    assert section["fil"]["by"] == "ai" and "Sa Tagalog: Possible Cause: Temperature too low" in section["fil"]["body"]

    # While an operator answers, the model is theirs: a new version waits
    v2 = upload(manager, samples.sealer_xlsx(), code="OCAP-041", title="Sealer OCAP, line 2", name="sealer2.xlsx").json()
    activate(manager, v2["id"])
    asked = len(fake.chats)
    assert translate.pass_once(manager.app) is None and len(fake.chats) == asked

    # The plant's checked translation, once active, is shown instead (ADR-0044)
    t = manager.post(f"{OCAPS}/versions/{v['id']}/translations", json={
        "language": "fil", "source": "tagalog.xlsx", "contentBase64": b64(samples.sealer_xlsx_fil()), "reason": "Checked"}).json()
    manager.post(f"{OCAPS}/translations/{t['translations'][0]['id']}/activate", json={"reason": "Checked and approved"})
    (req,) = op.get(REQUESTS).json()["requests"]
    assert next(c for c in req["choices"] if c["label"] == "Seal separates easily")["labelFil"] == "Madaling matanggal ang seal"
    assert op.get(f"{OCAPS}/sections/{picked['sectionId']}").json()["fil"]["by"] == "plant"


def test_a_slow_or_absent_model_is_tried_again_later_and_a_rejection_never(ai_client, database, fake):
    manager = ai_client(["MANAGER"], translate_timeout_s=0.3)
    v = upload(manager, samples.sealer_xlsx(), code="OCAP-040", title="Sealer OCAP", name="sealer.xlsx").json()
    activate(manager, v["id"])
    fake.reply, fake.delay = translator(), 1.0
    assert translate.pass_once(manager.app) == "timeout"
    fake.delay, fake.status = 0, 500
    assert translate.pass_once(manager.app) == "failed"
    fake.status, fake.reply = 200, {"lines": ["too few"]}
    while translate.pass_once(manager.app) is not None:
        pass
    attempts = _attempts(database)
    assert [a["outcome"] for a in attempts[:2]] == ["timeout", "failed"]
    assert {a["outcome"] for a in attempts[2:]} == {"rejected"} and len(attempts) == len(v["sections"])
    assert attempts[0]["section_id"] != attempts[1]["section_id"]  # the timed-out one waits half an hour
    assert translate.pass_once(manager.app) is None  # nothing left before then
    view = manager.get(f"{OCAPS}/versions/{v['id']}").json()
    assert view["aiTagalog"] == {"on": False, "translated": 0, "english": len(v["sections"]) - 2, "waiting": 2}


def test_too_long_a_section_stays_english_without_asking(fake):
    settings = AiSettings(enabled=True, url=fake.url, model="qwen3.5:4b")
    result, record = translate.translate(settings, {"heading": "Long", "phenomenon": None, "body": "Check the jaw. " * 600})
    assert result is None and record["outcome"] == "rejected" and "too long" in record["detail"] and fake.chats == []


def test_the_trial_models_mistakes_on_the_plant_workbook_are_refused():
    # Each from qwen3.5:4b on the plant's OCAP (2026-10-09): a changed verb, a changed label, a lost negation
    for en, fil, why in (
            ("Operator Mitigation Plan: Set machine to the approved safe manual condition. Close sealers.",
             "Plano ng Operator: I-set ang makina sa ligtas na kondisyon. Itigil at i-hold ang sealers.", "lost 'Close'"),
            ("2. Try to tighten, if cannot be tighten - call the mechanic",
             "2. Subukang itigil kung hindi makapag-adjust - tumawag sa mechanic.", "lost 'tighten'"),
            ("Possible Phenomenon: Actual temperature does not reach the preset",
             "Posibleng Sanhi: Ang actual temperature ay hindi umaabot sa preset", "lost 'Phenomenon'"),
            ("Possible Cause: Temperature too low; sealer not yet at operating temperature",
             "Posibleng Sanhi: Masyadong mababa ang temperature; nasa operating temperature na ang sealer", "lost 'not'"),
            ("- Sealers must have same Temp.", "- Dapat magkaiba ang Temp ng mga Sealer.", "lost 'same'"),
            ("- Document the procedure (Before and After) - Thru BuildApp", "- Suriin ang proseso (Bago at Pagkatapos) - Thru BuildApp",
             "lost 'Document'"),
            ("- Record the result", "- Suriin ang resulta at itala", "added 'Suriin'"),
            ("Run trial pouches.", "Pumunta sa trial pouches.", "lost 'Run'")):
        section = {"heading": "", "phenomenon": "", "body": en}
        out, problem = translate.check(json.dumps({"lines": ["", "", fil]}), translate.lines_of(section))
        assert out is None and why in problem, (en, problem)
    # A description isn't an order: "do not" there needs "hindi", not "huwag"
    section = {"heading": "4. Sealers do not show similar temperature", "phenomenon": "Sealers do not show similar temperature", "body": ""}
    lines = ["4. Hindi magkapareho ang temperature ng sealers", "Hindi magkapareho ang temperature ng sealers", ""]
    assert translate.check(json.dumps({"lines": lines}), translate.lines_of(section))[1] is None


def test_a_batch_copied_back_in_english_is_asked_once_more(fake):
    settings = AiSettings(enabled=True, url=fake.url, model="qwen3.5:4b")
    fake.reply = lambda body: {"lines": json.loads(body["messages"][1]["content"].split("\n", 1)[1])["lines"]}  # copies it back
    result, record = translate.translate(settings, SECTION)
    assert result is None and record["outcome"] == "rejected" and record["detail"].startswith("not translated")
    assert len(fake.chats) == 2 and "Last time they came back in English" in fake.chats[1]["messages"][1]["content"]
    assert len(json.loads(record["raw"])) == 2
    fake.chats.clear()
    fake.reply = translator()
    result, record = translate.translate(settings, {**SECTION, "body": "\n".join(["Check the jaw on both sides now."] * 9)})
    assert record["outcome"] == "used" and len(fake.chats) == 2  # 11 lines: two batches of up to 8


def test_the_version_says_whether_the_ai_translates(ai_client):
    manager = ai_client(["MANAGER"], translate_every_s=3600)  # its job waits an hour first
    v = upload(manager, samples.sealer_xlsx(), code="OCAP-040", title="Sealer OCAP", name="sealer.xlsx").json()
    assert v["aiTagalog"] == {"on": True, "translated": 0, "english": 0, "waiting": len(v["sections"])}
