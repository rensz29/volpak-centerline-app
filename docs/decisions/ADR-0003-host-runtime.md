# ADR-0003 — Host runtime: Hyper-V Linux VM with Docker Engine

- **Status:** Accepted, conditional on the Phase 0 test below passing on the control-room PC
- **Date:** 2026-09-28
- **Decider:** Szyrelle (system owner)
- **Closes:** O-02 (runtime part)
- **URS:** DEP-01, DEP-05, SES-04, AVL-01

## Decision

Run the core on a **Hyper-V Generation 2 Ubuntu Server 24.04 LTS VM** with
**Docker Engine** (not Docker Desktop), on an **external** virtual switch,
set to start automatically with Windows.

| Option | Verdict |
|---|---|
| **A. Hyper-V VM + Docker Engine** | **Chosen.** Starts without login, has its own LAN IP (real client IPs), no Desktop licence |
| B. WSL2 + Docker Engine via boot task | Fallback, only if A fails the test |
| Docker Desktop | Rejected: needs an interactive login (breaks DEP-05) and a paid licence at company size |

**Development** stays on WSL2 on the dev laptop. That's fine because the
containers are the same; only the production host differs.

## Acceptance test (Phase 0)

Follow [`deploy/host-check/README.md`](../../deploy/host-check/README.md) on the **control-room PC**:

| # | Check | Result |
|---|---|---|
| 1 | `Test-CenterlineHost.ps1`: no FAIL | _tbd_ |
| 2 | Boot log shows PASS after a normal restart with nobody logged in | _tbd_ |
| 3 | Boot log shows PASS after a Windows Update restart | _tbd_ |
| 4 | `whoami` from the backup workstation shows that workstation's own IP | _tbd_ |
| 5 | VM has a static IP / DHCP reservation, recorded here: _tbd_ | _tbd_ |

If all pass, remove "conditional" from the status. If 2–4 fail and can't be
fixed, switch to option B and re-run the test with a week-long soak.

## Consequences

- GPU access for Ollama inside a Hyper-V VM is limited. ~~If the O-01 model needs a
  GPU, run Ollama on the Windows host, reachable only from the VM, and record a
  DEP-01 deviation.~~ Since [ADR-0050](ADR-0050-ollama-outside-the-stack.md), Ollama is another container,
  provided apart from Centerline and named by URL in `deploy/.env`: the GPU is wherever that Ollama runs, and this
  host needs none. (The dev laptop's RTX A500 has 4 GB VRAM. That's enough to
  benchmark small models, not to size production.)
- The Windows host must be Windows 11 Pro/Enterprise or LTSC; Windows 10 is out
  of support.
- Windows Update restarts must be scheduled outside production or covered by the
  availability budget. Agree the update policy with IT.
