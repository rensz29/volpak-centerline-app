# ADR-0047: The interface stays English; Tagalog only in the operator's chat and the OCAP

- **Status:** Accepted
- **Date:** 2026-10-09
- **Decider:** Szyrelle (system owner), on 2026-10-09: "no need tagalog for the interface okay lets remove to our
  plan", after being shown what a Filipino interface would change (menus, page titles, buttons, labels, messages)
- **Amends:** the plan's Phase 3 and gate G3 (Architecture §16), and the gap analysis's "Language" row (§15)
- **URS:** LAN-01. See the change request below.

## Context

- LAN-01 asks for "English and Filipino/Tagalog UI, clarification, summary, translation and optional voice", with
  external notifications in English.
- Built so far in Filipino: the operator's chat, Tagalog by default with an English switch, and the AI's questions in
  both languages ([ADR-0043](ADR-0043-assistant-in-tagalog.md)); the OCAP in Tagalog
  ([ADR-0044](ADR-0044-checked-tagalog-ocap.md), [ADR-0045](ADR-0045-ai-translates-the-ocap.md)); the AI's summary in
  both ([ADR-0046](ADR-0046-ai-summary-of-the-ocap.md)). Every other screen is English.
- The plan listed "the Filipino interface beyond the operator's chat" as still needed for G3.
- Operators at the plant work with English screens and speak Taglish.

## Decision

1. **The interface stays English**: menus, page titles, buttons, labels and messages, on every page.
2. **Filipino stays where it is:** the operator's chat (its words, the AI's questions and summary, with its Tagalog /
   English switch) and the OCAP in Tagalog. Operators may type in English, Filipino or Taglish anywhere, as now.
3. **It's out of the plan:** G3 no longer needs a Filipino interface. No i18n framework is added.

## Consequences

- No translation layer to keep in step with every new screen; the screens stay as they are.
- An operator who reads Tagalog better than English gets it where the decision is made (the chat and the OCAP), not on
  the alarm and line pages.
- If the plant later wants Tagalog screens, that's a new decision; the chat's words (`assistantText.ts`) show the
  pattern.

## URS change request (owner to raise)

| URS | Today (v1.1) | Proposed |
|---|---|---|
| LAN-01 | "Support English and Filipino/Tagalog UI, clarification, summary, translation and optional voice; external notifications remain English." | Support English and Filipino/Tagalog in the operator's reason assistant (its messages, clarification and summary) and in the OCAP's text (translation), and optional voice; the rest of the user interface and external notifications remain English. |

AT-08's "bilingual" is unchanged: it concerns the AI's clarification, retrieval and summary, which stay bilingual.

## Tests

None: nothing in the code changes. The plan (Architecture §15, §16) no longer lists a Filipino interface.
