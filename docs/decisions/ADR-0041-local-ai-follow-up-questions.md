# ADR-0041: The local AI writes the follow-up questions, through Ollama

- **Status:** Accepted
- **Date:** 2026-10-08
- **Decider:** Szyrelle (system owner), on 2026-10-08. The owner first proposed OpenClaw ("for my ai preferably to use
  a openclaw so create me a container for this one and i use it to my chatbot"). Given its risks, they chose "Ollama
  only" of the options put to them (below).
- **Amends:** [ADR-0031](ADR-0031-ocap-library-deterministic-path.md) (the AI waited for O-01) and
  [ADR-0040](ADR-0040-reason-assistant-chat.md) (the chat asked the fixed questions). O-01 stays open: the model
  here is a trial choice until the model test.
- **URS:** AI-01, AI-02, DAT-01, PER-01; SDD §7.2

## Context

- **The chat asks the operator two fixed questions** after the reason ([ADR-0040](ADR-0040-reason-assistant-chat.md)).
  The owner wants the AI to ask, from the OCAP.
- **The owner first asked for OpenClaw.** OpenClaw isn't a model: it's an agent gateway that gives a model chat
  channels, a shell and files, and still needs a model behind it.
  - With a cloud model, the OCAP text and the operators' reasons leave the plant; AI-01 requires Ollama on premises.
  - Its API credential is "full operator access", and tools run for its chat requests.
  - It had a severe security year: CVE-2026-25253 (one link stole the token and ran code), over 135,000 instances
    found open on the internet, hundreds of malicious skills in its marketplace.

  On the control-room PC, beside the plant's database, that is a risk the chat doesn't need.
- **The options put to the owner:** "Ollama only" (recommended), "OpenClaw in front of Ollama, locked down", or
  "OpenClaw with a cloud model". The owner chose Ollama only.

## Decision

1. **An `ollama` container in the stack**, on its network only: nothing outside the stack reaches it.
   - It keeps its models in the `ollama` volume, stays loaded for 24 h, and answers one question at a time.
   - It runs on the CPU. `deploy/compose.gpu.yaml` gives it an NVIDIA GPU where Docker can reach one.
   - It needs the internet only to pull the model. The offline kit carries the model ([ADR-0037](ADR-0037-offline-install-kit.md)).
   - Ollama is pinned to 0.40.1, its cloud models are off (`OLLAMA_NO_CLOUD`), and its context is 4096 tokens, as the
     api asks: a different size would reload the model.
2. **The trial model is `qwen3.5:4b`**, about 3.3 GB: it fits a 4 GB GPU, and its family covers 200+ languages,
   Taglish included.
   - `api.json`'s `ai` block names it. `model_digest` pins it: a model whose digest differs isn't used. Ollama lists
     digests without "sha256:", so they're compared without it.
   - The model test (O-01) on real OCAPs and reasons decides the go-live model.
3. **The api asks it, right after the reason.**
   - It sends the alarm (zone, setpoint against target, raised or lowered), the reason as written, and the OCAP
     sections for it: the picked row, or the three sections a typed reason finds.
   - It asks for at most two questions as JSON (held to a schema), at temperature 0, without the model's thinking.
     The system prompt forbids instructions, advice and facts that aren't in the alarm, the reason or the sections.
4. **Checked before they're asked** (AI-02):
   - one or two questions, each 8–220 characters, ending with a question mark;
   - not starting like an instruction ("Set", "Replace", "Check", "Please"…);
   - not the same question twice.

   Anything else is rejected.
5. **The fixed questions whenever the AI can't be used** (AI-01):
   - the AI is off or has no model;
   - no OCAP section is found;
   - Ollama is down, or the model isn't pulled or isn't the pinned one;
   - there's no answer within 25 s (PER-01 gives 30 s);
   - the answer is rejected.

   Monitoring never waits for it, and the operator always gets questions.
6. **Everything is kept** (DAT-01), append-only:
   - `ai_call`: each call's model and digest, the prompt's version and full text, the sections' ids, the raw answer,
     whether it was used and why not, and how long it took;
   - `workflow_question`: each request's questions in order, the AI's or the fixed ones, so its answers always say
     what they answer.
7. **Kept loaded and warm:** every minute (`warm_every_s`) the api checks that the model is in memory, and if it isn't
   (after a restart), loads it and runs a tiny question. On this laptop the first question after a restart took 78 s
   (40 s reading the model, 35 s warming the GPU), which would have missed the 25 s.
8. **Seen as such:** the chat and the Reasons page mark the AI's questions "Asked by the AI, from the OCAP". The
   System health page grades the AI model: off, Ollama down, model missing or not pinned, or last questions unused
   (all warnings, since the fixed questions stand in).

## Consequences

- **The questions follow the OCAP row the operator picked,** e.g. which side of the pouch had the weak seal.
- **The trial model is small,** so its questions can be plain. The model test decides the go-live model and its
  hardware (the control-room PC's GPU, and the VM question in ARCHITECTURE §3).
- **Each reason with OCAP sections waits for the model,** 25 s at most. Measured on this laptop (RTX A500, 4 GB: 14 of
  the model's 33 layers fit on it, the rest runs on the CPU), with the plant's workbook and Taglish reasons, warm:
  6 s for one OCAP row, 15 s for a typed reason with two sections (reading 1030 tokens takes 12 s). The chat shows
  "Reading the OCAP for your next questions…". A GPU with 8 GB or more would hold the whole model.
- **Its questions were apt** in all three trial cases, e.g. for a weak seal on Vertical 3: "What was the actual
  temperature measured on Vertical 3 when you raised the setpoint?" and "Did you verify that the sealer reached
  operating temperature before running trial pouches?".
- **The model's thinking must stay off:** with it on, one answer took over 5 minutes on this laptop.
- **Still to come:** the summary beside the OCAP section (OCP-02), translation (LAN-01), embedding search, and AT-08's
  run with Ollama up and stopped.
- **OpenClaw isn't used.** If it's wanted later, it needs an ADR of its own.

## Tests

- `services/api/tests/test_ai_questions.py`, with `fake_ollama.FakeOllama` standing in for Ollama:
  - the checks: good answers, then not JSON, none, three, no question mark, instructions, duplicates, too short;
  - the prompt: the alarm, the reason as written, three sections at most, each cut to 2500 characters;
  - from a picked row: the model's two questions asked, its request (model, schema, temperature 0, no thinking, the
    rules), the answers stored against those questions, its row then offered, and the call kept with the digest;
  - an instruction, a timeout, a 500 and an unpinned model each give the fixed questions, the call saying why;
  - with no OCAP sections or the AI off, nothing is sent.
- The warmer: it loads and warms a model that isn't in memory, and leaves a loaded one alone; a digest listed without
  "sha256:" matches its pin.
- `services/api/tests/test_health_unit.py`: the AI model's states.
- On the Docker stack (2026-10-08): Ollama 0.40.1 found the GPU; `qwen3.5:4b` pulled (digest d8b0f5e9…), pinned, and
  asked the three trial cases through the api's own code; after `restart ollama` the warmer reloaded it in 9 s.
- The roles and migration guards list `ai_call`, `workflow_question` and migration 0016.
