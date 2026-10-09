# ADR-0043: The operator's chat in Tagalog by default, switchable to English

- **Status:** Accepted
- **Date:** 2026-10-09
- **Decider:** Szyrelle (system owner), on 2026-10-09: "now the default for the operator is tagalog language then it
  can translate it to english by clicking on the chat to set either english or tagalog"
- **Amends:** [ADR-0040](ADR-0040-reason-assistant-chat.md), [ADR-0041](ADR-0041-local-ai-follow-up-questions.md),
  [ADR-0042](ADR-0042-ai-opens-the-conversation.md)
- **URS:** LAN-01 (English and Filipino UI, clarification and translation; notifications stay English), AI-02, DAT-01

## Context

- Operators speak Tagalog and write Taglish. The chat ([ADR-0040](ADR-0040-reason-assistant-chat.md)) and the AI's
  questions ([ADR-0041](ADR-0041-local-ai-follow-up-questions.md), [ADR-0042](ADR-0042-ai-opens-the-conversation.md))
  were in English.
- **The trial model's Tagalog is understandable but not polished.** On the plant's workbook it wrote, for example:
  - "Bakit mo itaas…" for "Bakit mo itinaas…";
  - "mahina na seal" for "mahinang seal";
  - once, "maputol na seal" (a cut seal) for a weak seal.

  One correct example in its instructions helped. Writing both languages adds about 2–3 s.

## Decision

1. **The chat opens in Tagalog** for operators. A Tagalog | English switch in its header changes it at once. The
   choice is kept in that browser, the shared operator desk's (a convenience, nothing stored on the server).
2. **The chat's own words are written in Filipino** (`client/src/components/workflow/assistantText.ts`): its messages,
   buttons and placeholders. Technical words stay English, as operators say them: setpoint, target, seal, OCAP, Manager.
   So do the fixed opening and the two fixed questions as they come out of the box. A fixed question an Administrator
   writes shows as written.
3. **The model writes each question in English and Filipino at once** (prompts `opening-v2` and `questions-v3`), in
   everyday Tagalog with technical words in English, with one correct example. So switching never waits.
   - Only the English is checked against AI-02's rules and decides whether the call is used.
   - A Filipino text that isn't a question, or doesn't pair up with the English, is left out, and that question
     shows in English.
   - It's kept beside the English in `workflow_question.question_fil` (migration 0018).
4. **The record stays in English.**
   - The answers keep the English question, and the Reasons page and Managers read English.
   - The OCAP's text is shown as written: it's the authoritative source (OCP-02).
   - The reason choices are the OCAP's own words.
   - Notifications stay English (LAN-01).
5. **The AI's time limit is 30 s**, PER-01's, up from 25 s, since the answer is longer.

## Consequences

- An operator reads the chat in Tagalog and answers in whatever they write: Taglish is kept as typed.
- **The AI's Tagalog needs a native speaker's eye.** The model test (O-01) should judge Tagalog as well as English. A
  bigger model on a bigger GPU writes it better.
- **The rest of the interface is still English** (LAN-01's Filipino UI beyond the chat isn't done). Since
  [ADR-0047](ADR-0047-interface-stays-english.md) it stays English.

## Tests

- `services/api/tests/test_ai_questions.py`:
  - the Filipino kept beside the English and shown in the request's questions and opening;
  - a Filipino text that isn't a question is left out, and so is a list that doesn't pair up;
  - the prompt versions.
- Checked in headless Edge on a scratch stack with the plant's workbook:
  - the chat opened in Tagalog, with a seeded bilingual AI opening;
  - after a reason and a note, the next question came in Tagalog;
  - English switched everything at once;
  - Tagalog stayed after a reload.
- The migration guard lists 0018.
