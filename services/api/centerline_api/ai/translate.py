"""The AI's Tagalog translation of OCAP sections (LAN-01, AI-02, DAT-01, ADR-0045).

The local model translates each section of the Active OCAP versions in English once, in the background, line by line, eight lines
to a request (it copies longer lists back in English, and is asked once more when it does), with a glossary of the
instruction words. A translation is shown only when every check passes, otherwise the section stays
English:
- every line translated, in the same order (the model answers one line for each line it's given);
- every number kept, each in its own line (the model once shifted a section's lines by one);
- the instruction words kept both ways: a line that says "clean" must say "linis", and one that says "palitan"
  (replace) must have said replace. The trial model turned "Clean the jaw" into "Palitan ang jaw", "Close sealers" into
  "Itigil" (stop), and "Possible Phenomenon" into "Posibleng Sanhi" (cause); negations ("not") must keep "hindi".

It runs only while no operator is answering, since the model answers one thing at a time. Every attempt is kept in
`ocap_ai_translation`. A checked translation from the plant (ADR-0044), when one is active, is shown instead.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from dataclasses import replace

from centerline_common.db import DatabaseUnavailable, uuid7
from psycopg import Error as PsycopgError

from . import calls, ollama

PROMPT_VERSION = "ocap-fil-v1"
MAX_CHARS = 8000  # of a section's text: past that, a section is left in English rather than hold the model for minutes
TAGALOG_MARKERS = {"ang", "ng", "sa", "na", "mga", "kung", "at", "ay", "o", "para", "kapag", "hindi", "huwag", "dapat"}

SYSTEM = """You translate lines of a factory's troubleshooting guide from English into Filipino (Tagalog), the way operators at a Philippine plant talk: everyday Tagalog sentences, with technical words and part names kept in English (seal, sealer, jaw, film, pouch, sealing bar, preset, setpoint, temperature, HMI, OCAP, Maintenance, Cell Lead, centerline, BuildApp, Teflon, probe, cutter, bolt, shaft, rod spring).
Every line must come back in Tagalog. A line copied back in English is wrong; only a line that is just a name, a code or a number stays as it is.
Translate faithfully: don't add, drop or change any instruction, and never add a sentence that isn't in the line. Keep every number, unit and range exactly. Keep numbering, dashes and the label before a colon (translate the label too).
Words to use: clean = linisin; replace = palitan; remove = alisin; stop = itigil; hold = i-hold; isolate = ihiwalay; call = tumawag sa; return to = ibalik sa; close = isara; open = buksan; tighten = higpitan; set = i-set; adjust = i-adjust; do not = huwag; check / inspect = suriin; verify / confirm = tiyakin; allow / let = hayaan; cause = sanhi; phenomenon = pangyayari; effect = epekto; both sides = magkabilang gilid.
Examples, from a bottling line:
"Possible Cause: Glue too cold; belt not yet at speed." = "Posibleng Sanhi: Masyadong malamig ang glue; hindi pa nasa tamang bilis ang belt."
"Operator Plan: Stop the conveyor and remove the jammed bottles. Check the belt tension." = "Plano ng Operator: Itigil ang conveyor at alisin ang mga naipit na bote. Suriin ang tension ng belt."
"- Labels do not stick on both sides" = "- Hindi dumidikit ang labels sa magkabilang gilid"
Reply with JSON only: {"lines": [...]}, one Tagalog line for each line given, in the same order."""
BATCH_LINES = 8  # lines per request: the model copies long lists back in English

# A word in the English → what a faithful Tagalog line must have (the English word itself counts: operators speak
# Taglish). Tagalog verbs take infixes (tumawag, tumigil, bumalik, pinalitan), so a root is matched with or without one.
KEEP = [(re.compile(e, re.I), re.compile(t, re.I)) for e, t in (
    (r"\bclean(ed)?\b", r"linis|clean"),
    (r"\breplaced?\b", r"p(in)?alit|replace"),
    (r"\bremove\b", r"alis|tanggal|remove"),
    (r"\bstop\b", r"t(um|in)?igil|h(um|in)?into|stop"),
    (r"\b(isolate|segregate)\b", r"hiwalay|isolate|segregate"),
    (r"\bcall\b", r"t(um|in)?awag|call"),
    (r"\breturn\b", r"b(um|in)?alik|return"),
    (r"\btighten\b", r"h(in)?igpit|tighten"),
    (r"\bloosen\b", r"luwag|loosen"),
    (r"\bclose\b", r"sara|close"),
    (r"\bopen\b", r"buks|bukas|open"),
    (r"\bhold\b", r"hold|panatili|pigil|hawak"),
    (r"\bset\b", r"\bset\b|takda"),
    (r"\badjust\w*", r"adjust|ayusin|iayos|inayos"),
    (r"\b(raise|increase)\b", r"taas|dagdag|raise|increase"),
    (r"\b(lower|decrease|reduce)\b", r"baba|bawas|lower|decrease|reduce"),
    (r"\b(check|inspect|verify|confirm|ensure)\w*", r"suri|tingn|tiyak|sigurad|kumpirm|alamin|check|inspect|verify|confirm|ensure"),
    (r"(^|[:;.!]\s*|^[-\d.\s]*)(do not|don't|never)\b", r"huwag|hindi dapat"),  # an order not to
    (r"\b(not|never|cannot)\b|n't\b", r"\b(hindi|di|huwag|wala|walang)\b"),  # a negation, kept
    (r"\bcause\w*", r"sanhi|dahilan|cause"),
    (r"\bphenomen\w*", r"pangyayari|nangyayari|phenomen"),
    (r"\beffect\b", r"epekto|effect"),
    (r"\b(same|equal|similar|uniform)\b", r"pareho|parehas|pantay|same|equal|similar|uniform"),  # "same" became "magkaiba"
    (r"\bdocument(ed)?\b", r"document|dokument|itala|isulat|tala\b|record"),
    (r"\brecord\b", r"record|itala|isulat|tala\b|document"),
    (r"\brun\b", r"\brun\b|i-run|takbo|paandar"),
)]
# A word in the Tagalog → what the English must have said for it to be there
NEVER = [(re.compile(t, re.I), re.compile(e, re.I)) for t, e in (
    (r"p(in)?alit", r"\b(replace|change|swap|switch)"),
    (r"\b(alisin|inalis|naalis|tanggalin|tinanggal)\b", r"\b(remove|clear|take|discard|eliminate)"),
    (r"huwag", r"\b(do not|don't|never|not|avoid)\b"),
    (r"linis", r"\bclean|sanit"),
    (r"t(um|in)?igil|ihinto|huminto", r"\b(stop|halt|pause|shut)"),
    (r"hiwalay", r"\b(isolate|separat|segregat)"),
    (r"t(um|in)?awag", r"\b(call|contact|notify)"),
    (r"b(um|in)?alik", r"\b(return|back|restore|revert)"),
    (r"h(in)?igpit", r"\btighten"),
    (r"\b(isara|isinara|sarhan|sinarhan)\b", r"\b(close|shut)"),
    (r"\b(itaas|itinaas|taasan|tinaasan|dagdagan|dinagdagan)\b", r"\b(raise|increase|higher|add|up)"),
    (r"\b(bawasan|binawasan)\b", r"\b(lower|decrease|reduce)"),
    (r"\bsanhi\b", r"\bcause"),
    (r"\bepekto\b", r"\b(effect|affect|impact)"),
    (r"pangyayari", r"\b(phenomen|event|happen|occur)"),
    (r"\b(suriin|sinuri|sinusuri)\b", r"\b(check|inspect|verify|confirm|ensure|review|examine|look|test)"),  # "Document" became "Suriin"
    (r"\b(pumunta|pupunta|pumupunta)\b", r"\b(go|proceed|move)"),  # "Run trial pouches" became "Pumunta sa"
    (r"\b(magkaiba|magkakaiba|naiiba)\b", r"\b(differ|different|vary|varies|uneven|inconsistent)"),
)]
NUMBER = re.compile(r"\d+(?:\.\d+)?")
WORDS = re.compile(r"[A-Za-z][A-Za-z'-]+")

log = logging.getLogger("centerline.api.ai")


def lines_of(section: dict) -> list[str]:
    """What the model translates: the heading, the reason it offers, then the text, line by line."""
    return [section.get("heading") or "", section.get("phenomenon") or "", *(section.get("body") or "").split("\n")]


def check(raw: str, source: list[str]) -> tuple[dict | None, str | None]:
    """The translated heading, label and text, or why it can't be shown (then the section stays English)."""
    try:
        out = json.loads(raw).get("lines")
    except (ValueError, AttributeError):
        return None, "not JSON"
    if not isinstance(out, list) or len(out) != len(source) or not all(isinstance(x, str) for x in out):
        return None, f"{len(out) if isinstance(out, list) else 'no'} lines for {len(source)}"
    out = [x.rstrip() for x in out]
    missing = Counter(NUMBER.findall("\n".join(source))) - Counter(NUMBER.findall("\n".join(out)))
    if missing:
        return None, f"numbers lost: {', '.join(sorted(missing))}"
    for i, (en, fil) in enumerate(zip(source, out)):  # each line its own: the model can shift lines
        if Counter(NUMBER.findall(en)) != Counter(NUMBER.findall(fil)):
            return None, f"line {i + 1} doesn't match its English (its numbers differ): {fil[:60]!r}"
    sentences = [(en, fil) for en, fil in zip(source, out) if len(WORDS.findall(en)) >= 4]
    changed = sum(1 for en, fil in sentences if en.strip() != fil.strip())
    markers = sum(1 for w in WORDS.findall(" ".join(out).lower()) if w in TAGALOG_MARKERS)
    if sentences and (changed < 0.6 * len(sentences) or markers < 2):
        return None, f"not translated: {len(sentences) - changed} of {len(sentences)} sentences left in English"
    for i, (en, fil) in enumerate(zip(source, out)):
        for word, needed in KEEP:
            if word.search(en) and not needed.search(fil):
                return None, f"line {i + 1} lost {word.search(en).group(0).strip(' :;.!-')!r}: {en[:60]!r}"
        for word, said in NEVER:
            if word.search(fil) and not said.search(en):
                return None, f"line {i + 1} added {word.search(fil).group(0)!r}: {fil[:60]!r}"
    return {"heading": out[0] or None, "label": out[1] or None, "body": "\n".join(out[2:])}, None


def _copied(part: list[str], lines: list[str]) -> bool:
    """Most of these sentences came back as they went: the model copied them instead of translating."""
    sentences = [(en, fil) for en, fil in zip(part, lines) if len(WORDS.findall(en)) >= 4]
    return bool(sentences) and sum(1 for en, fil in sentences if en.strip() == fil.strip()) * 2 >= len(sentences)


def _batch(settings, part: list[str], raws: list[str]) -> list[str] | None:
    """One batch's lines in Tagalog, asked again once if they came back in English; None when the answer can't be read."""
    schema = {"type": "object", "required": ["lines"],
              "properties": {"lines": {"type": "array", "minItems": len(part), "maxItems": len(part), "items": {"type": "string"}}}}
    lines = None
    for ask in ("Translate these lines into Tagalog:\n",
                "Translate these lines into Tagalog. Last time they came back in English: every sentence must be in Tagalog.\n"):
        raws.append(ollama.chat(settings, SYSTEM, ask + json.dumps({"lines": part}, ensure_ascii=False), schema))
        try:
            lines = json.loads(raws[-1]).get("lines")
        except (ValueError, AttributeError):
            return None
        if not isinstance(lines, list) or len(lines) != len(part) or not all(isinstance(x, str) for x in lines):
            return None
        if not _copied(part, lines):
            break
    return lines


def translate(settings, section: dict) -> tuple[dict | None, dict]:
    """(the checked translation or None, what to keep of the attempt)."""
    source = lines_of(section)
    record = {"digest": None, "raw": None, "outcome": "failed", "detail": None}
    result = None
    started = time.monotonic()
    try:
        size = sum(len(x) for x in source)
        if size > MAX_CHARS:
            record["outcome"], record["detail"] = "rejected", f"too long to translate ({size} characters)"
            return None, {**record, "latency": 0}
        record["digest"] = ollama.digest(settings)
        if record["digest"] is None:
            record["detail"] = f"the model {settings.model} isn't pulled on this host"
        elif settings.model_digest and calls.bare(record["digest"]) != calls.bare(settings.model_digest):
            record["detail"] = f"the installed {settings.model} isn't the pinned one"
        else:
            slow = replace(settings, timeout_s=settings.translate_timeout_s)
            raws: list[str] = []
            out: list[str] = []
            try:
                for k in range(0, len(source), BATCH_LINES):
                    lines = _batch(slow, source[k:k + BATCH_LINES], raws)
                    if lines is None:
                        record["outcome"], record["detail"] = "rejected", f"lines {k + 1}–{k + BATCH_LINES}: an answer that isn't the lines asked for"
                        break
                    out += lines
                else:
                    result, problem = check(json.dumps({"lines": out}, ensure_ascii=False), source)
                    record["outcome"], record["detail"] = ("used", None) if result else ("rejected", problem)
            finally:
                record["raw"] = json.dumps(raws, ensure_ascii=False)  # every answer, as given
    except ollama.AiTimeout as e:
        record["outcome"], record["detail"] = "timeout", str(e)
    except ollama.AiUnavailable as e:
        record["detail"] = str(e)
    record["latency"] = round((time.monotonic() - started) * 1000)
    return result, record


def pass_once(app) -> str | None:
    """Translate one section still waiting, while no operator is answering. Returns its outcome, if one was tried."""
    settings = app.state.settings
    with settings.database.connect() as conn:
        busy = conn.execute("""SELECT EXISTS (SELECT 1 FROM workflow_request WHERE status IN ('waiting_reason', 'waiting_answers', 'waiting_ocap')
                                                 AND updated_at > clock_timestamp() - interval '3 minutes') AS b""").fetchone()["b"]
        if busy:
            return None
        s = conn.execute("""SELECT s.id, s.heading, s.phenomenon, s.body FROM ocap_section s
                              JOIN ocap_version v ON v.id = s.version_id AND v.language = 'en'  -- an OCAP in Filipino stays as written
                              JOIN ocap_version_status st ON st.version_id = s.version_id AND st.status = 'active'
                             WHERE NOT EXISTS (SELECT 1 FROM ocap_translation_section ts
                                                 JOIN ocap_translation_current c ON c.translation_id = ts.translation_id
                                                WHERE ts.section_id = s.id AND c.status = 'active')
                               AND NOT EXISTS (SELECT 1 FROM ocap_ai_translation a WHERE a.section_id = s.id AND a.prompt_version = %s
                                                  AND (a.outcome IN ('used', 'rejected') OR a.at > clock_timestamp() - interval '30 minutes'))
                             ORDER BY s.phenomenon IS NULL, s.version_id, s.ordinal LIMIT 1""", (PROMPT_VERSION,)).fetchone()
        conn.commit()
        if s is None:
            return None
        result, rec = translate(settings.ai, s)
        conn.execute("""INSERT INTO ocap_ai_translation (id, section_id, language, prompt_version, model, model_digest, outcome, detail,
                                                         heading, label, body, raw_output, latency_ms)
                        VALUES (%s, %s, 'fil', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                     (uuid7(), s["id"], PROMPT_VERSION, settings.ai.model, rec["digest"], rec["outcome"], rec["detail"],
                      result and result["heading"], result and result["label"], result and result["body"], rec["raw"], rec["latency"]))
        conn.commit()
        log.info("OCAP section %s translated to Tagalog: %s%s", s["heading"], rec["outcome"], f" ({rec['detail']})" if rec["detail"] else "")
        return rec["outcome"]


def keep_translating(app, stop) -> None:
    """Every `translate_every_s`, one section more (ADR-0045). Ends with the process."""
    every = max(1.0, app.state.settings.ai.translate_every_s)
    log.info("the Active English OCAPs are translated into Tagalog, a section every %g s while no operator is answering", every)
    while not stop.wait(every):
        try:
            pass_once(app)
        except (DatabaseUnavailable, PsycopgError) as e:
            log.warning("OCAP translation waits for the database: %s", e)
