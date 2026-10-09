"""The OCAP search by meaning (OCP-01, LAN-01, AI-01, ADR-0048).

The embedding model (bge-m3: multilingual, so Tagalog and Taglish land near the English that means the same) turns
each chunk of the Active OCAP versions into a vector, once, in the background, with its section's heading. A search
embeds what the operator wrote and ranks the sections by their nearest chunk (OcapStore.search merges that with the
keyword ranking). It runs on the CPU, beside the chat model on the GPU. Off, not pulled, not the pinned digest, slow
or down: the keyword search answers alone, and nothing waits.
"""

from __future__ import annotations

import logging

from centerline_common.db import DatabaseUnavailable
from psycopg import Error as PsycopgError

from . import calls, ollama

BATCH = 16  # chunks a request
LOCK = "centerline.ai.embed"

log = logging.getLogger("centerline.api.ai")


def model_of(settings) -> tuple[str, str] | None:
    """(the embedding model, its digest), when it's set, pulled and the pinned one; else None. Raises AiUnavailable."""
    if not settings.enabled or not settings.embed_model:
        return None
    found = ollama.digest(settings, settings.embed_model)
    if found is None:
        return None
    if settings.embed_model_digest and calls.bare(found) != calls.bare(settings.embed_model_digest):
        return None
    return settings.embed_model, calls.bare(found)


def literal(vector: list[float]) -> str:
    """A vector as pgvector reads it."""
    return "[" + ",".join(format(float(x), ".7g") for x in vector) + "]"


def text_of(heading: str | None, body: str) -> str:
    return f"{heading}\n{body}" if heading else body


def query(settings, text: str) -> tuple[str, str, str] | None:
    """(model, digest, the text's vector) for a search, or None: the keyword search answers alone."""
    try:
        model = model_of(settings)
        if model is None:
            return None
        (vector,) = ollama.embed(settings, [text], settings.embed_timeout_s)
    except ollama.AiUnavailable as e:
        log.warning("OCAP search by keywords only: %s", e)
        return None
    return model[0], model[1], literal(vector)


def pass_once(app) -> int:
    """Embed up to BATCH chunks of the Active versions not embedded yet with this model. Returns how many."""
    settings = app.state.settings
    try:
        model = model_of(settings.ai)
    except ollama.AiUnavailable:
        return 0
    if model is None:
        return 0
    with settings.database.connect() as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS ok", (LOCK,)).fetchone()["ok"]:
            return 0
        try:
            rows = conn.execute("""SELECT c.id, c.body, s.heading FROM ocap_chunk c JOIN ocap_section s ON s.id = c.section_id
                                     JOIN ocap_version_status st ON st.version_id = s.version_id AND st.status = 'active'
                                    WHERE NOT EXISTS (SELECT 1 FROM ocap_chunk_embedding e WHERE e.chunk_id = c.id
                                                         AND e.model = %s AND e.model_digest = %s)
                                    ORDER BY s.version_id, s.ordinal, c.ordinal LIMIT %s""", (*model, BATCH)).fetchall()
            conn.commit()
            if not rows:
                return 0
            try:
                vectors = ollama.embed(settings.ai, [text_of(r["heading"], r["body"]) for r in rows], settings.ai.translate_timeout_s)
            except ollama.AiUnavailable as e:
                log.warning("OCAP sections not embedded yet: %s", e)
                return 0
            for r, v in zip(rows, vectors):
                conn.execute("""INSERT INTO ocap_chunk_embedding (chunk_id, model, model_digest, embedding)
                                VALUES (%s, %s, %s, %s::vector) ON CONFLICT DO NOTHING""", (r["id"], *model, literal(v)))
            conn.commit()
            return len(rows)
        finally:
            conn.rollback()
            conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK,))
            conn.commit()


def keep_embedding(app, stop) -> None:
    """Every `embed_every_s`, the chunks still to embed (ADR-0048). Ends with the process."""
    every = max(1.0, app.state.settings.ai.embed_every_s)
    while not stop.wait(every):
        try:
            while n := pass_once(app):
                log.info("OCAP search by meaning: %d chunk(s) embedded", n)
                if stop.is_set():
                    return
        except (DatabaseUnavailable, PsycopgError) as e:
            log.warning("OCAP embeddings wait for the database: %s", e)
