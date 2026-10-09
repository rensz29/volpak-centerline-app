"""The AI's opening question (ADR-0042). As soon as an HMI mismatch's request is open, the local model looks at the OCAP
rows offered for its parameter and direction (ADR-0039) and asks the operator why the setpoint changed, naming one or
two likely reasons from them. It runs beside the requests, in the api, so nothing waits for it: until it's written the
chat says it's looking at the OCAP, and when the model can't be used the fixed opening is kept instead."""

from __future__ import annotations

import json
import logging

from centerline_common.db import DatabaseUnavailable
from psycopg import Error as PsycopgError

from ..ocap.choices import direction_of
from ..ocap.store import OcapStore
from . import calls
from .questions import IMPERATIVE, filipino

PROMPT_VERSION = "opening-v2"
FALLBACK = "Why did you change it?"
MAX_LABELS = 12
LOCK = "centerline.ai.opening"

SYSTEM = """You help the operators of a Volpak pouch-filling machine record why they changed a machine setpoint.
An HMI setpoint has just moved off its target. Write the first question to the operator: ask why they changed it.
If the OCAP lists possible reasons, name one or two of the likeliest for this sealer and direction, in the OCAP's own words, inside the question, and leave room for another reason.
Don't repeat the setpoint or target values: they're shown beside your question.
Never give instructions or advice. Never state a fact that isn't in the alarm or the OCAP list.
At most 35 words, plain English, ending with a question mark.
Also write the question in Filipino, as operators at a Philippine plant speak it: everyday Tagalog, keeping technical words in English (seal, jaw, film, sealer, setpoint, OCAP). Same meaning, also ending with a question mark.
Example of the style, for a different machine: {"question": "Why did you raise the glue roller speed: open flaps, weak bonding, or something else?", "question_fil": "Bakit mo itinaas ang speed ng glue roller: may bukas na flaps, mahinang dikit, o iba pa?"}
Reply with JSON only: {"question": "...", "question_fil": "..."}"""

SCHEMA = {"type": "object", "required": ["question", "question_fil"],
          "properties": {"question": {"type": "string"}, "question_fil": {"type": "string"}}}

log = logging.getLogger("centerline.api.ai")


def prompt(alarm: str, labels: list[str]) -> str:
    parts = [alarm]
    if labels:
        parts.append("Possible reasons in the plant's OCAP for this sealer and direction:\n" + "\n".join(f"- {x}" for x in labels[:MAX_LABELS]))
    else:
        parts.append("The OCAP lists no reasons for this.")
    parts.append("Write the first question to the operator.")
    return "\n\n".join(parts)


def validate(raw: str) -> tuple[tuple[str, str | None] | None, str | None]:
    """(English, Filipino or None), or why it can't be asked. Only the English decides."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None, "not JSON"
    q = data.get("question") if isinstance(data, dict) else None
    if not isinstance(q, str):
        return None, "no question"
    q = " ".join(q.split())
    if not 10 <= len(q) <= 300:
        return None, f"a question of {len(q)} characters"
    if not q.endswith("?"):
        return None, f"not a question: {q[:60]!r}"
    if IMPERATIVE.match(q):
        return None, f"an instruction, not a question: {q[:60]!r}"
    return (q, filipino(data.get("question_fil"))), None


def pass_once(app) -> int:
    """An opening question for each open request still waiting for its reason that has none yet. Returns how many.
    One api at a time writes them (an advisory lock); each is committed on its own."""
    settings = app.state.settings
    written = 0
    with settings.database.connect() as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS ok", (LOCK,)).fetchone()["ok"]:
            return 0
        try:
            rows = conn.execute("""SELECT r.id, e.parameter_id, e.zone_id, e.raw_hmi, e.raw_target FROM workflow_request r
                                     JOIN event e ON e.id = r.event_id
                                    WHERE r.status = 'waiting_reason' AND r.created_at > clock_timestamp() - interval '2 hours'
                                      AND NOT EXISTS (SELECT 1 FROM workflow_question q WHERE q.request_id = r.id AND q.ordinal = 0)
                                    ORDER BY r.created_at LIMIT 5""").fetchall()
            names = {}
            if rows:
                names = {z.channel: {"parameterName": z.parameter_name, "zoneName": z.zone_name, "unit": z.unit}
                         for z in app.state.register_store.load(conn).zones}
            conn.commit()
            for r in rows:
                choices = OcapStore.choices(conn, r["parameter_id"], direction_of(r["raw_hmi"], r["raw_target"]))[:MAX_LABELS]
                now = conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]
                q, call_id = calls.run(settings.ai, conn, r["id"], "opening", PROMPT_VERSION, SYSTEM,
                                       prompt(calls.alarm_text(names.get(f"{r['parameter_id']}.{r['zone_id']}", {}), r),
                                              [c["label"] for c in choices]),
                                       SCHEMA, validate, [c["sectionId"] for c in choices], now)
                conn.execute("""INSERT INTO workflow_question (request_id, ordinal, question, question_fil, asked_by, ai_call_id, at)
                                VALUES (%s, 0, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                             (r["id"], q[0] if q else FALLBACK, q[1] if q else None, "ai" if q else "fixed",
                              call_id if q else None, now))
                conn.commit()
                written += 1
        finally:
            conn.rollback()
            conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK,))
            conn.commit()
    return written


def keep_opening(app, stop) -> None:
    """Every `open_every_s`, the opening questions still to write (ADR-0042). Ends with the process."""
    every = max(0.5, app.state.settings.ai.open_every_s)
    while not stop.wait(every):
        try:
            if n := pass_once(app):
                log.info("AI opening question written for %d request(s)", n)
        except (DatabaseUnavailable, PsycopgError) as e:
            log.warning("AI opening questions wait for the database: %s", e)
