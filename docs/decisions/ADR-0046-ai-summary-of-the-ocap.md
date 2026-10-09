# ADR-0046: The AI sums up the OCAP sections offered, only from what they say

- **Status:** Accepted
- **Date:** 2026-10-09
- **Decider:** Szyrelle (system owner), on 2026-10-09: "okay go ahead to my suggestion and do what is next", after the
  suggestion to build the AI summary with citation checking and AT-08 with Ollama running and stopped next
- **URS:** OCP-02 ("Show an AI summary plus the exact authoritative source section and citation"), AI-02 (never invent
  facts or corrective instructions), LAN-01 (summary in Filipino), DAT-01, PER-01 (an AI result in 30 s), AI-01 (monitoring
  never depends on AI); AT-08 ("Ollama bilingual grounded retrieval, top-three OCAPs, exact source and deterministic
  fallback")
- **Builds on:** [ADR-0031](ADR-0031-ocap-library-deterministic-path.md) (the sections offered),
  [ADR-0041](ADR-0041-local-ai-follow-up-questions.md)…[ADR-0043](ADR-0043-assistant-in-tagalog.md) (the AI's questions),
  [ADR-0045](ADR-0045-ai-translates-the-ocap.md) (what the trial model gets wrong, and the checks for it)

## Context

- After the reason and the answers, the operator is offered up to three OCAP sections (OCP-01) and reads them in full.
  OCP-02 also wants an AI summary beside them; the plan's "Generate" and "Verify" steps (Architecture §7.2) weren't
  built.
- The trial model (qwen3.5:4b) invents and swaps instructions when it rewrites OCAP text (ADR-0045's measurement).

## Decision

1. **Once a request's sections are offered, the local model sums them up** (`services/api/centerline_api/ai/summary.py`,
   prompt `summary-v1`). It runs in the api beside the requests, every `ai.summary_every_s` (2 s), like the opening
   question: the operator reads the sections meanwhile.
   - It's given the alarm, the operator's reason and answers as written, and the sections offered, numbered [1]–[3]
     (2,500 characters of each).
   - It writes two to four sentences on what they say for this situation, in the OCAP's words, naming each point's
     section, in English and Filipino, and lists the sections it used.
   - One attempt per request; nothing waits for it.
2. **It's shown only if it passes every check** (the plan's "Verify"); otherwise there's no summary and the sections
   are shown alone:
   - it cites at least one section, and only sections offered (in its list and in its text);
   - every number in it is in the sections it cites, or in the alarm;
   - every instruction verb in it (clean, replace, remove, stop, isolate, call, return, tighten, hold, set, adjust,
     raise, lower, run, document, record, do not, …) is in the sections it cites, or in the alarm ("raised");
   - its English is English.
3. **Its Filipino is shown only if it passes the OCAP translation's checks** against the English (ADR-0045: every
   number and key word kept, both ways) **and says each instruction as many times as the English**. Otherwise the
   English summary is shown in the Tagalog chat too.
4. **In the chat** (OCP-02): "Buod ng AI mula sa OCAP" (AI summary of the OCAP) above the sections, the sections it
   cites by number and citation, and "Basahin pa rin ang OCAP sa ibaba bago pumili" (still read the OCAP below before
   you choose). While it's written: "Binubuod ng AI ang OCAP…", for at most 60 s. The operator still opens a section
   in full before choosing it, and acknowledges review only. Managers see the summary on the Reasons page and in the
   event's evidence.
5. **Kept** (DAT-01): every call in `ai_call` (purpose `summary`: model, digest, prompt version, sections sent, raw
   answer, outcome and why); a summary that passed in `workflow_summary` (migration 0021, append-only), with the
   sections it cites.
6. **The OCAP translation (ADR-0045) also pauses during the OCAP step**, so the summary doesn't wait behind it.

## Measurement: the plant's workbook with the trial model

Each of the 18 sections of `OCAP_Volpak_Digital Copy_Updated (1).xlsx`, as the one section offered for a raised
Vertical 1, with qwen3.5:4b on the RTX A500 4 GB, on 2026-10-09:

- **13 of 18 summaries pass**, in 9–22 s each. Reading them: they keep the OCAP's checks, causes and actions in its
  words. One joins two parts of a row ("replace any deteriorated parts … before changing the centerline"), which is why
  the label says to read the OCAP too.
- **Refused:** three invented an instruction ("replace", "stop", "lower"), one wrote "do not change the temperature" for
  "Stop changing temperature" (refused, though it means the same), and one wrote its "English" in Tagalog.
- **4 of the 13 pass with Filipino.** One Filipino said "palitan … kung hindi matitiyak" (replace if it can't be
  verified) where the English said to tighten: it had every key word, so counting them (decision 3) was added. The
  Filipino that passes still has typos and odd words ("Suruin", "lekwis").

## Consequences

- OCP-02 is met with the AI running; with it stopped, slow or wrong, the sections are shown alone, as before (AI-01).
- A summary is a reading aid, never the instruction: the operator still reads and chooses the section, and the label
  says so.
- The checks know the instruction verbs listed; an OCAP that uses others (lubricate, purge, …) needs them added.
- **Not built yet** (G3): embedding search and translating a Taglish reason for the search (OCP-01's retrieval is
  still keyword search, ADR-0031), and the model choice itself (O-01).

## Tests

- `services/api/tests/test_ai_summary.py`: a grounded summary is shown in both languages; a citation outside those
  offered, a number or an instruction the cited sections don't have, an English written in Tagalog, each shows none; a
  Filipino that fails its checks, or says an instruction more often than the English (the trial model's own case),
  leaves the English; the job sums up once per request, kept with its call; a rejected answer or a model that's down
  leaves the sections alone; with summaries off, nothing is pending.
- `tests/acceptance/test_at08_ocap_ai.py`, AT-08's AI part: monitor-core judges a mismatch on the simulated line;
  - **Ollama running** (a stand-in on a local port answering as a correct model would): the AI's bilingual opening, a
    Taglish reason kept as typed, one bilingual clarification, the top three Active sections, the bilingual summary
    citing only sections offered, the exact source as read, acknowledgment, and every call kept with its digest and
    prompt version;
  - a summary citing a section not offered, or saying another section's instruction, is never shown;
  - **Ollama stopped:** the fixed opening and questions, the sections alone, no summary, every step done;
  - **a real Ollama:** the same flow when `CENTERLINE_AT08_OLLAMA` names it, asserting only the guarantees.
- The migration and roles guards list 0021 and `workflow_summary`.
- The measurement above.
