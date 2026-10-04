# ADR-0005 — Split gate G0 so Phase 1 isn't blocked by the AI model decision

- **Status:** Accepted. G0b amended by [ADR-0021](ADR-0021-g0b-revised.md) (2026-10-01): it no longer needs
  the SKU field or controls M1–M5
- **Date:** 2026-09-28
- **Decider:** Szyrelle (system owner)
- **Changes:** SDD §15 roadmap (G0)

## Context

The SDD puts one gate (G0) before Phase 1, requiring URS approval, the host
runtime, the acquisition security controls (then OPC UA None/None, now MQTT per
ADR-0006) **and** the AI models (O-01). The AI models are
first used in Phase 3. Tying Phase 1 to them delays the monitoring core for no
technical reason.

## Decision

| Gate | Requires | Unlocks |
|---|---|---|
| **G0a** | URS v1.1 approved by the owner · ADR-0001 accepted (O-09) · ADR-0002 at least Proposed with placeholders (O-08) · ADR-0003 accepted (O-02 runtime) · ADR-0006 and ADR-0007 accepted (MQTT acquisition, register) | Phase 1 against the simulated MQTT publisher (`tools/mqtt-sim`) |
| **G0b** | ADR-0002 Accepted with measured values · ADR-0003 test passed on the control-room PC · ADR-0006 M1–M5 and M7 verified · SKU field published (O-15, ADR-0007) | Connecting Phase 1 to the real broker; exit gate G1 |
| **G0c** | O-01 closed: Ollama models benchmarked on real OCAPs (EN + FIL), pinned by digest, hardware and licensing confirmed | Phase 3 |

The Ollama benchmark runs in parallel with Phases 1–2.

*Amended by [ADR-0021](ADR-0021-g0b-revised.md) on 2026-10-01:* G0b now needs ADR-0002 accepted (done
that day), the ADR-0003 test passed and M7 confirmed, unless the owner takes M7 out. The SKU field
is deferred until its tag is ready, and the broker's security (M1–M5) is accepted as it is for now.

## Consequences

- Phase 1 can start once G0a is met.
- G1 (AT-01…03) still needs G0b, so real delays and the real host are proven
  before the monitoring core is signed off.
- If the O-01 benchmark shows no acceptable local model, Phase 3 falls back to
  the deterministic path (keyword search, exact sections, template questions).
  That path is required anyway (AT-08), so Phases 1–2 aren't affected.
