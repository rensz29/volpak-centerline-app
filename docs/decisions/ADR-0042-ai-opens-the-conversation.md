# ADR-0042: The AI opens the conversation and asks every question it can

- **Status:** Accepted
- **Date:** 2026-10-09
- **Decider:** Szyrelle (system owner), on 2026-10-09: "i would like to ai ask the question not the exactly created
  questions so the ai will ask and look for the OCAP after detect HMI mismatch"
- **Amends:** [ADR-0041](ADR-0041-local-ai-follow-up-questions.md) (the AI asked only after the reason, and only with
  OCAP sections) and [ADR-0040](ADR-0040-reason-assistant-chat.md) (the chat opened with a fixed "Why did you change
  it?")
- **URS:** AI-01, AI-02, WF-01, DAT-01

## Context

- **After ADR-0041 the AI asked only the follow-up questions,** after the reason, and only when OCAP sections were
  found. Without them, operators got the two fixed questions. The chat always opened with the same fixed question.
- **Its first real questions were weak.** Given the "Burnt, darkened, brittle or excessively thin seal" row, it asked
  about the setpoint values, which are already recorded.
- **The owner wants the AI to lead:** look up the OCAP as soon as the mismatch is detected, and ask.

## Decision

1. **The AI writes the opening question as soon as the request is open.**
   - A background job in the api looks, every 2 s (`ai.open_every_s`), for open requests still waiting for their
     reason with no opening question.
   - For each, it gives the model the alarm and the OCAP rows offered for its parameter and direction (ADR-0039),
     those for the direction first, twelve at most.
   - The model asks why the setpoint changed, naming one or two likely reasons in the OCAP's words, and leaves room
     for another.
   - It's the request's question 0 in `workflow_question`; 1 and 2 stay the follow-ups (AI-02: two clarifications at
     most). One api writes them at a time, under an advisory lock.
2. **Nothing waits for it.**
   - Until it's written, the chat says "Looking at the OCAP for Vertical 3…", for up to 45 s. The list's
     `openingPending` says it's coming, and the reason buttons are there already.
   - If the model can't be used, the fixed opening is kept: "Why did you change it?".
   - Measured on this laptop's GPU: 5 s.
3. **The follow-up questions are the AI's even without OCAP sections.** Without sections, it asks what the operator saw
   and what exactly they did.
4. **Better follow-up questions (prompt `questions-v2`):**
   - they ask about the checks, the signs on the pouch or sealer and the causes the OCAP names, in its words;
   - never about the setpoint or target values;
   - an example of the style is in the prompt.

   The opening prompt is `opening-v1`, with the same rules and checks: one question, ending with a question mark,
   not an instruction.
5. **The fixed questions stay, as the fallback only** (AI-01: monitoring never depends on AI; AT-08's run with Ollama
   stopped). They're used when the AI is off, down, slow, not the pinned model, or answers against the rules. Every
   call is kept in `ai_call` with its purpose: `opening` or `questions`.

## Consequences

- **The operator is asked by the AI from the first message.** On the trial cases from the plant's workbook:
  - for Vertical 2 lowered: "Why did you lower the vertical temperature: burnt seal, melted film, wrinkles, or
    something else?";
  - then: "Did you see burnt film or dark marks on the sealer jaws?" and "Did you clean the sealing surface before
    lowering the temperature?".
- **Every new mismatch costs one call to the model,** even if nobody answers it. On one line that's a few calls an hour.
- **The opening is written once per request,** so a second shift's request for the same mismatch gets its own.
- **The model can still paraphrase the OCAP** ("uneven heating" for "Sealers do not show similar temperature"). The
  OCAP row itself, word for word, is what the operator then reads and acknowledges (OCP-02).

## Tests

- `services/api/tests/test_ai_questions.py`:
  - the opening for a new request: from the rows for a raised Vertical Temperature, never the lowered ones;
  - written once, shown in the list, apart from the follow-ups;
  - the fixed opening when Ollama fails, the call kept as `opening`;
  - the "on its way" flag where the api writes openings;
  - an opening must be one real question;
  - follow-ups with no OCAP sections still asked by the AI;
  - the prompt versions recorded.
- The migration guard lists 0017.
- On the Docker stack (2026-10-09): the open Vertical 3 request got "Why did you raise the temperature: weak seal,
  uneven heating, or something else?" in 4.8 s.
