# ADR-0048: The OCAP search goes by meaning too, so a Taglish reason finds its section

- **Status:** Accepted; built and deployed, waiting for its model: bge-m3 couldn't be downloaded on 2026-10-09 (see
  below), so the search goes by keywords until it is
- **Date:** 2026-10-09
- **Decider:** Szyrelle (system owner), on 2026-10-09: "go ahead", after the OCAP search that understands Taglish
  reasons was proposed as the next step for G3
- **URS:** OCP-01 (index the Active versions, present up to three matches), LAN-01 (Filipino and Tagalog), AI-01 (the
  embedding model pinned; monitoring never depends on AI), PER-01 (an OCAP search in 10 s); the plan's §7.2 Index and
  Query
- **Builds on:** [ADR-0031](ADR-0031-ocap-library-deterministic-path.md) (the keyword search, kept as the fallback)

## Context

- The OCAP sections are found by PostgreSQL's keyword search. Operators write Taglish ("sunog yung seal, maitim"), and
  the OCAP is English: on 14 made-up Taglish reasons for the plant's workbook, the right row came first for 8 (the
  alarm's own words outvote the reason).
- The plan (§7.2) has the chunks embedded with a pinned embedding model into pgvector, a search merging the vector and
  keyword results, top three. bge-m3 was its first candidate: multilingual (Tagalog among its languages), 1.2 GB.

## Decision

1. **The embedding model is bge-m3 in the stack's Ollama** (`ai.embed_model`), pinned by digest like the chat model
   (`ai.embed_model_digest`), **on the CPU**: the GPU is the chat model's, and a short text takes a fraction of a second
   there. Ollama keeps both loaded (`OLLAMA_MAX_LOADED_MODELS` 2).
2. **The Active OCAPs' chunks are embedded once, in the background** (`services/api/centerline_api/ai/embed.py`, every
   `ai.embed_every_s`, 10 s), each with its section's heading, into `ocap_chunk_embedding` (migration 0022, pgvector,
   append-only). A chunk is embedded again only for another model or digest; a Draft never.
3. **A search ranks the sections both ways and merges the two** (`OcapStore.search`):
   - by keywords, as before (with the sealer and the direction of the change in the query);
   - by meaning: the nearest chunk to **what the operator wrote, alone** (the reason and the answers; the sealer would
     outweigh the reason here, as it does in the keyword search), those less similar than `ai.min_similarity` (0.45)
     left out;
   - merged by reciprocal rank fusion (each ranking's 10 best; a section ranked well by both comes first); the top three
     are offered, kept with the request as method `hybrid`.
4. **Keywords alone whenever the meaning can't be used**: no embedding model set, not pulled, not the pinned digest,
   Ollama down, or the search's own embedding slower than `ai.embed_timeout_s` (5 s, within PER-01's 10 s). Nothing
   waits for it, and the offered sections say `keyword`.
5. **The same search serves** the workflow's sections (for the AI's questions and the three offered) and the OCAP
   library's search box.
6. **System health shows it**: "OCAP search by meaning": ready, how many of the Active OCAPs' parts are embedded, or
   why it's keywords only.

## The model couldn't be downloaded yet

On 2026-10-09 every pull of bge-m3 failed: `registry.ollama.ai` and `ollama.com` reset the connection during the TLS
handshake, from this laptop and from Docker, while other sites (huggingface.co, google.com) answered. Hours earlier
the chat model had downloaded from the same registry. Whether it's Ollama's side or this network blocking it, the model
wasn't fetched from anywhere else. Once the registry answers:

```bash
docker compose -f deploy/compose.yaml exec ollama ollama pull bge-m3
docker compose -f deploy/compose.yaml exec ollama ollama list     # its digest, for ai.embed_model_digest in deploy/config/api.json
```

The api notices within a minute and embeds the Active OCAPs; then the search measurement below is to be run (the 14
Taglish reasons, keywords alone against both), and `min_similarity` set from it.

## Consequences

- A Taglish or Tagalog reason can find the English section that means it; keywords still decide when the meaning
  doesn't help.
- 1.2 GB more in the Ollama volume and in the offline kit, and about 1.2 GB of RAM while it's loaded.
- The similarity threshold is a placeholder until it's measured on the plant's OCAP.
- Translating the reason for the search (the plan's other half of Query) isn't built: a multilingual embedding compares
  the Taglish as written, with no call to the chat model on the operator's path.

## Tests

- `services/api/tests/test_ai_embed.py`, against a stand-in Ollama whose embeddings place a Tagalog word and its English
  alike: the Active sections embedded once (with their heading, on the CPU, kept loaded), a Draft never; a Taglish reason
  ("sunog yung seal, maitim at marupok") finds "Burnt or brittle seal" first, in the library's search and among the
  sections a request is offered, comparing only what was written; the model down, not pulled or not the pinned one,
  or off: keywords alone, and nothing asked of Ollama when it's off.
- `services/api/tests/test_health_unit.py`: the "OCAP search by meaning" check's states.
- The migration and roles guards list 0022 and `ocap_chunk_embedding`.
