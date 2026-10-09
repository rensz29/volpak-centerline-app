"""The AI's follow-up questions (AI-02, ADR-0041, ADR-0042): at most two, after the reason, about what the OCAP
sections for it say to check or look for, or, with none found, about what the operator saw and did. Checked before
they're asked; anything off (Ollama down or slow, a pinned digest that differs, an answer that breaks a rule) and the
caller asks the fixed questions instead. Every call is kept in `ai_call` (DAT-01)."""

from __future__ import annotations

import json
import re

from . import calls

PROMPT_VERSION = "questions-v3"
SECTION_CHARS = 2500  # of each section's text in the prompt
MAX_SECTIONS = 3

SYSTEM = """You help the operators of a Volpak pouch-filling machine record why they changed a machine setpoint.
After the operator's reason, you write follow-up questions only: one or two, short, in plain English an operator understands.
If OCAP sections are given, ask about what they name for this situation: the checks to do, the signs on the pouch or the sealer, the causes to rule out. Use the OCAP's own words for those things.
If no OCAP section is given, ask what the operator saw and what exactly they did.
Don't ask about the setpoint or target values: they're already recorded. Don't ask for what the operator already wrote.
Never give instructions, advice or answers. Never state a fact that isn't in the alarm, the reason or the sections.
Each question is one sentence of at most 25 words, ends with a question mark, and can be answered in a few words.
Also write each question in Filipino, as operators at a Philippine plant speak it: everyday Tagalog, keeping technical words in English (seal, jaw, film, sealer, setpoint, OCAP). Same meaning, same order, also ending with a question mark.
Example of the style, for a different machine: {"questions": ["Did you see glue on the rollers before you changed it?", "Was the belt tension within its marks?"], "questions_fil": ["May nakita ka bang glue sa rollers bago mo ito binago?", "Nasa tamang marka ba ang tension ng belt?"]}
Reply with JSON only: {"questions": ["...", "..."], "questions_fil": ["...", "..."]}"""

SCHEMA = {"type": "object", "required": ["questions", "questions_fil"],
          "properties": {"questions": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string"}},
                         "questions_fil": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string"}}}}

# A question that starts like an instruction is one (AI-02: never corrective instructions)
IMPERATIVE = re.compile(r"^(please|set|turn|raise|lower|increase|decrease|reduce|replace|call|stop|start|clean|tighten|"
                        r"adjust|change|put|return|go|make|use|run|keep|ensure|verify|check|inform|document|don'?t|do not|"
                        r"never|always)\b", re.I)


def prompt(alarm: str, reason: str, sections: list[dict]) -> str:
    parts = [alarm, f'The operator\'s reason, as they wrote it (it may mix English and Tagalog): "{reason}"']
    if sections:
        parts.append("The OCAP sections for this reason:")
        for i, s in enumerate(sections[:MAX_SECTIONS], start=1):
            parts.append(f"[{i}] {s['citation']}\n{s['body'][:SECTION_CHARS]}")
    else:
        parts.append("No OCAP section was found for this reason.")
    parts.append("Write one or two follow-up questions for the operator.")
    return "\n\n".join(parts)


def checked(q: object, out: list[str]) -> tuple[str | None, str | None]:
    """One question tidied, or why it can't be asked."""
    if not isinstance(q, str):
        return None, "a question that isn't text"
    q = " ".join(q.split())
    if not 8 <= len(q) <= 220:
        return None, f"a question of {len(q)} characters"
    if not q.endswith("?"):
        return None, f"not a question: {q[:60]!r}"
    if IMPERATIVE.match(q):
        return None, f"an instruction, not a question: {q[:60]!r}"
    if q.lower() in (x.lower() for x in out):
        return None, "the same question twice"
    return q, None


def filipino(q: object) -> str | None:
    """The Filipino text of a question, or None when it can't be shown (the English is, instead)."""
    if not isinstance(q, str):
        return None
    q = " ".join(q.split())
    return q if 6 <= len(q) <= 260 and q.endswith("?") else None


def validate(raw: str) -> tuple[list[tuple[str, str | None]], str | None]:
    """The questions as (English, Filipino or None), or why the answer can't be used. Only the English decides."""
    try:
        data = json.loads(raw)
    except ValueError:
        return [], "not JSON"
    items = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return [], "no questions"
    if len(items) > 2:
        return [], f"{len(items)} questions: two at most (AI-02)"
    out: list[str] = []
    for item in items:
        q, problem = checked(item, out)
        if q is None:
            return [], problem
        out.append(q)
    fil = data.get("questions_fil")
    fil = [filipino(x) for x in fil] if isinstance(fil, list) and len(fil) == len(out) else [None] * len(out)
    return list(zip(out, fil)), None


def ask(settings, conn, request_id, alarm: str, reason: str, sections: list[dict], now) -> tuple[list[tuple[str, str | None]], object]:
    """The model's questions as (English, Filipino or None) and its call's id; ([], id or None) when they can't be used.
    The caller commits."""
    if not settings.enabled or not settings.model:
        return [], None
    questions, call_id = calls.run(settings, conn, request_id, "questions", PROMPT_VERSION, SYSTEM,
                                   prompt(alarm, reason, sections), SCHEMA, validate,
                                   [s["sectionId"] for s in sections[:MAX_SECTIONS]], now)
    return questions or [], call_id
