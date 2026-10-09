# ADR-0049: Production runs this laptop's stack: Ollama in its own container, on the GPU

- **Status:** Accepted
- **Date:** 2026-10-09
- **Decider:** Szyrelle (system owner), on 2026-10-09: "imagine this my loptop is a production so my ollama is totally
  installed on the different container so thats the production setup so i want you to prefere on this once this
  project transfer into server"
- **Amends:** [ADR-0003](ADR-0003-host-runtime.md) (its fallback of Ollama on the Windows host, for the GPU, is
  dropped), [ADR-0041](ADR-0041-local-ai-follow-up-questions.md) (how the GPU file is applied)
- **URS:** DEP-01 (the containers on the host), AI-01 (Ollama on premises), PER-01 (an AI result in 30 s)

## Context

- This laptop runs the Docker stack at :6040 as production does: postgres, the api, monitor-core, the notifier, the
  backup agent, ClamAV, the proxy, and **Ollama in its own container**, with its models in its volume, reachable only
  on the stack's network, on the laptop's NVIDIA GPU through `deploy/compose.gpu.yaml`. Away from the plant it also
  runs the simulated line.
- The plan put the server's Docker in a Hyper-V VM, where a GPU is hard to reach, and so planned Ollama on the Windows
  host for the GPU, as a DEP-01 deviation (ADR-0003, Architecture §3).
- The GPU came from adding `-f deploy/compose.gpu.yaml` to each command by hand: a restart without it brings Ollama
  back on the CPU, slower, and nothing said so.

## Decision

1. **This laptop's stack is the production setup**: the same containers and compose files on the server, Ollama its
   own container in the stack with its models in its volume. Ollama is never installed on the host.
2. **The server's Docker must reach an NVIDIA GPU**: on Linux, the NVIDIA driver and the NVIDIA Container Toolkit; on
   Windows, WSL2 with the NVIDIA driver; in a Hyper-V VM, only with the GPU passed through to it. If the host ADR-0003
   chose can't give Docker the GPU, the host changes, not where Ollama runs; ADR-0003's host test gains that check.
3. **`deploy/compose.sh` runs the stack as the PC is set up**, from `deploy/.env`:
   - `CENTERLINE_GPU=nvidia` adds `deploy/compose.gpu.yaml`; `none` leaves Ollama on the CPU. `deploy/setup.sh` checks
     once whether Docker reaches a GPU (a container given one lists it with `nvidia-smi -L`) and writes it.
   - `CENTERLINE_SIMULATOR=on` adds `deploy/compose.sim.yaml`: away from the plant only; `off` on the server.
   - Every command goes through it, so no restart drops the GPU or brings the simulator onto the line.
4. **The offline kit carries it**: the images (Ollama's among them), Ollama's models, and restore steps that set up the
   GPU, run `setup.sh` and start with `deploy/compose.sh`.
5. **System health shows where the model runs**: "qwen3.5:4b ready on the GPU (56% of it)", or a warning when none of
   it is on the GPU, with what to do.

## Consequences

- Moving to the server is the kit, a backup set, the GPU's driver (and toolkit), `setup.sh` and `deploy/compose.sh up
  -d`, and the health page confirms the GPU.
- The server needs an NVIDIA GPU: 4 GB holds about half of qwen3.5:4b (this laptop's), 8 GB or more holds it whole and
  answers faster. The embedding model (ADR-0048) runs on the CPU either way.
- The laptop runs Docker Desktop; the server runs Docker Engine (ADR-0003). The containers are the same.
- Commands in older notes written as `docker compose -f deploy/compose.yaml …` still work, but leave the GPU file out:
  `deploy/compose.sh` is the one to use.

## Tests

- `services/api/tests/test_health_unit.py`: the AI model check says how much of the model is on the GPU, and warns when
  none of it is.
- On this laptop, 2026-10-09: `deploy/compose.sh config` includes the GPU reservation and the simulator, and
  `deploy/compose.sh ps` addresses the running `centerline` stack; `docker run --rm --gpus all pgvector/pgvector:pg17
  nvidia-smi -L` lists the RTX A500, as `setup.sh` checks; System health reads "on the GPU" after the api's update.
