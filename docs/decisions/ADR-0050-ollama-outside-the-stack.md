# ADR-0050: Ollama runs outside Centerline's stack; deploy/.env names its URL

- **Status:** Accepted
- **Date:** 2026-10-09
- **Decider:** Szyrelle (system owner), on 2026-10-09: "i forgot to say that the ollama will use is on another container
  so not include the ollama during installation so instead i will provide it into .env the url of ollama"
- **Amends:** [ADR-0049](ADR-0049-production-runs-the-laptops-stack.md) (Ollama was a container of the stack, its GPU
  file applied by `deploy/compose.sh`), [ADR-0041](ADR-0041-local-ai-follow-up-questions.md) (the `ollama` service in
  `deploy/compose.yaml`), [ADR-0037](ADR-0037-offline-install-kit.md) (the kit carried the models)
- **URS:** AI-01 (Ollama on premises, models pinned; monitoring never depends on AI), DEP-01

## Context

- Since ADR-0041 the stack had its own `ollama` container, reached by the api as `ollama:11434` on the stack's network.
- In production, the Ollama Centerline uses is another container, provided apart from Centerline's installation.

## Decision

1. **Centerline's stack has no Ollama**: seven containers (the proxy, api, monitor-core, notifier, PostgreSQL, ClamAV,
   the backup agent).
2. **`CENTERLINE_OLLAMA_URL` in `deploy/.env` names the Ollama the api asks**, passed into the api container; it wins
   over `ai.url` in `deploy/config/api.json`. Empty: no Ollama, and the AI's work falls back as ever (the fixed
   questions, no summary, keywords only). `setup.sh` adds the line, empty.
   - **Another machine:** `http://<its address>:11434`, its firewall letting in only Centerline's server.
   - **This machine, another container:** `http://host.docker.internal:<port>`. The api resolves that name to the host
     on Linux as on Docker Desktop (`host-gateway`). Publish Ollama's port where the LAN can't reach it: 127.0.0.1 on
     Docker Desktop, the Docker bridge (172.17.0.1) on Linux. Ollama has no password.
3. **That Ollama needs what Centerline asks of it**: the models `qwen3.5:4b` and `bge-m3` (pinned in `api.json` by
   their full digests), 4096 tokens of context, both models kept loaded (`OLLAMA_MAX_LOADED_MODELS` 2, `OLLAMA_KEEP_ALIVE`
   24h), one request at a time, cloud models off, and a GPU for speed.
4. **`deploy/ollama/` runs one where none runs yet**: its own Compose project (`ollama`), with those settings, the
   GPU file, and its port only where `deploy/ollama/.env` says (127.0.0.1 by default).
5. **The GPU is the Ollama's business**: `deploy/compose.sh` no longer has a GPU setting (`CENTERLINE_GPU` is gone), and
   the kit no longer carries models. System health still says how much of the model is on the GPU, wherever Ollama runs,
   and now also when no URL is set.

## On this laptop (2026-10-09)

- Its Ollama moved out of the stack into `deploy/ollama/` (project `ollama`), on the same model volume
  (`centerline_ollama`, so nothing was downloaded again), on the GPU, published on **127.0.0.1:11435**:
  11434 was taken by a separate Ollama installed natively in WSL (other models; left alone), and 11436 by another
  project's llama.cpp container.
- `deploy/.env`: `CENTERLINE_OLLAMA_URL=http://host.docker.internal:11435`. System health: "qwen3.5:4b ready on the GPU
  (56% of it)".

## Consequences

- Installing Centerline no longer installs, downloads or updates Ollama or its models; whoever provides the Ollama
  does, with the settings above.
- The network path from the api to Ollama is part of the installation: the health page shows when it isn't answering.
- An Ollama shared with other applications answers them too: Centerline's 30 s budget (PER-01) holds only while it
  isn't busy with theirs.

## Tests

- `services/api/tests/test_settings_ollama.py`: the URL from the environment wins; an empty one leaves `api.json`'s.
- `services/api/tests/test_health_unit.py`: "No Ollama to ask" when no URL is set.
- On this laptop: the api reached the new Ollama by `host.docker.internal`, the pinned digest matched, the warmer loaded
  the model onto the GPU.
