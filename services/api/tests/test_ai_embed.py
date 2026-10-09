"""The OCAP search by meaning (OCP-01, LAN-01, AI-01, ADR-0048): the Active sections embedded once, a Taglish reason
finding the section that means it, merged with the keyword search; the keyword search alone whenever the embedding
model can't be used."""

from __future__ import annotations

from centerline_api.ai import embed, ollama

from . import ocap_samples as samples
from .fake_ollama import EMBED_DIGEST, idea_vector
from .test_ai_questions import ai_client, fake  # noqa: F401 (fixtures)
from .test_ocap_api import OCAPS, activate, upload
from .test_workflow_api import DESK, REQUESTS, mismatch

BURNT = "sunog yung seal, maitim at marupok"  # Taglish: burnt seal, dark and brittle


def test_a_vector_is_written_as_pgvector_reads_it():
    assert embed.literal([0.5, -1, 1e-9]) == "[0.5,-1,1e-09]"
    assert embed.text_of("2. Burnt or brittle seal", "Temperature too high") == "2. Burnt or brittle seal\nTemperature too high"
    assert idea_vector("Sunog yung seal")[0] == 1.0 and idea_vector("2. Burnt or brittle seal")[0] == 2.0


def _sealer(ai_client, **ai):
    manager = ai_client(["MANAGER"], embed_model="bge-m3", **ai)
    v = upload(manager, samples.sealer_xlsx(), code="OCAP-040", title="Sealer OCAP", name="sealer.xlsx").json()
    return manager, v


def _embedded(database) -> list[dict]:
    with database.connect() as conn:
        return conn.execute("SELECT * FROM ocap_chunk_embedding ORDER BY at").fetchall()


def test_the_active_sections_are_embedded_once_and_a_draft_never(ai_client, database, fake):
    manager, v = _sealer(ai_client)
    assert embed.pass_once(manager.app) == 0 and fake.embeds == []  # a Draft isn't searched
    activate(manager, v["id"])
    total = 0
    while n := embed.pass_once(manager.app):
        total += n
    with database.connect() as conn:
        chunks = conn.execute("""SELECT count(*) AS n FROM ocap_chunk c JOIN ocap_section s ON s.id = c.section_id
                                  WHERE s.version_id = %s""", (v["id"],)).fetchone()["n"]
    rows = _embedded(database)
    assert total == chunks == len(rows) and embed.pass_once(manager.app) == 0  # once each
    assert {(r["model"], r["model_digest"]) for r in rows} == {("bge-m3", EMBED_DIGEST.removeprefix("sha256:"))}
    sent = fake.embeds[0]
    assert sent["model"] == "bge-m3" and sent["options"] == {"num_gpu": 0} and sent["keep_alive"] == "24h"
    assert any(t.startswith("2. Burnt or brittle seal\n") for e in fake.embeds for t in e["input"])  # with its heading


def test_a_taglish_reason_finds_the_section_that_means_it(ai_client, database, fake):
    manager, v = _sealer(ai_client)
    activate(manager, v["id"])
    while embed.pass_once(manager.app):
        pass
    found = manager.get(f"{OCAPS}/search", params={"q": BURNT}).json()["results"]
    assert found[0]["heading"] == "2. Burnt or brittle seal" and found[0]["method"] == "hybrid"
    assert all(r["method"] == "hybrid" for r in found)

    # In the workflow: a typed reason, then its sections offered, the nearest first
    _, rid = mismatch(database)  # Vertical 1 raised
    op = ai_client(["OPERATOR"], address="10.0.0.5", auth=DESK, embed_model="bge-m3")
    op.post(f"{REQUESTS}/{rid}/reason", json={"text": BURNT})
    req = op.post(f"{REQUESTS}/{rid}/answers", json={"answers": ["Kaliwa", "Oo"]}).json()
    assert req["offered"][0]["heading"] == "2. Burnt or brittle seal" and req["offered"][0]["method"] == "hybrid"
    queried = [t for e in fake.embeds for t in e["input"] if BURNT in t]
    assert queried[-1] == f"{BURNT}\nKaliwa\nOo"  # only what was written: the keyword search has the sealer


def test_without_the_embedding_model_the_keyword_search_answers_alone(ai_client, database, fake):
    manager, v = _sealer(ai_client)
    activate(manager, v["id"])
    while embed.pass_once(manager.app):
        pass
    for broken in ("down", "not pulled", "another digest"):
        ollama._digests.clear()  # the installed models are looked up again
        if broken == "down":
            fake.status = 500
        elif broken == "not pulled":
            fake.status, fake.models = 200, fake.models[:1]
        c = ai_client(["MANAGER"], embed_model="bge-m3",
                      **({"embed_model_digest": "sha256:" + "9" * 64} if broken == "another digest" else {}))
        if broken == "another digest":
            fake.models = [*fake.models, {"name": "bge-m3:latest", "model": "bge-m3:latest", "digest": EMBED_DIGEST}]
        found = c.get(f"{OCAPS}/search", params={"q": "brittle seal"}).json()["results"]
        assert found and all(r["method"] == "keyword" for r in found), broken
        assert c.get(f"{OCAPS}/search", params={"q": BURNT}).json()["results"] == [] or all(
            r["method"] == "keyword" for r in c.get(f"{OCAPS}/search", params={"q": BURNT}).json()["results"]), broken
    # With it off, nothing is asked of Ollama
    asked = len(fake.embeds)
    off = ai_client(["MANAGER"])
    assert all(r["method"] == "keyword" for r in off.get(f"{OCAPS}/search", params={"q": "brittle seal"}).json()["results"])
    assert len(fake.embeds) == asked
