# ADR-0040: The reason assistant, a chat that opens by itself for the operator

- **Status:** Accepted (its sound changed on 2026-10-09, decision 1)
- **Date:** 2026-10-08
- **Decider:** Szyrelle (system owner), on 2026-10-08: "need to pop up the message like a chatbot the ai will ask him
  immediately". Then, of the options put to the owner:
  - "Chat panel that opens itself";
  - "Build now, AI joins later";
  - "Yes, a short alert sound".
- **Amends:** [ADR-0025](ADR-0025-shifts-and-reasons.md) (the operator's pop-up was a notice in the corner)
- **URS:** WF-01, PER-01 (the pop-up within 3 s), AI-02 (at most two questions, later the AI's), OCP-01/02

## Context

- **When a mismatch needed a reason, the operator got a small notice** in the corner for 15 s ("HMI mismatch on
  Vertical 3: give your reason") with no button. They then had to open the Reasons page and answer there.
- **Nothing showed for requests already waiting** when the operator opened the page or signed in: only the count on
  Reasons and on the bell. A busy operator could miss it.
- **The owner wants the assistant to ask right away,** like a chat. The AI model isn't chosen yet (O-01).

## Decision

1. **A chat panel, "Centerline assistant", on every page for operators.** It opens by itself, with a short two-note
   sound, when:
   - a new mismatch needs the operator's reason (within 3 s: the operator's browser asks every 2 s);
   - a Manager's guidance arrives for a request that waited for it;
   - the page opens or the operator signs in with requests already waiting.

   It stays on the request in hand while that one still waits for the operator. Minimised, it's a bubble with the
   number of reasons to give, and the next call opens it again. The sound plays once the operator has clicked or typed
   on the page (signing in does).
   - **Since 2026-10-09, the plant's own sound**, at the owner's request ("on the sound when message is pop up i want to
     use this"): `client/src/assets/sounds/popup-message-alert.mp3` (from `Popup_message_alert.mpeg`, an MP3, 13.8 s).
     It stops at the operator's first click, touch or key on the page, and a new call starts it again. If it can't
     play, the two-note tone made in the browser stands in (`client/src/utils/chime.ts`).
2. **One thing at a time, in the request's own steps.** The chat writes nothing of its own: it shows the request's
   record as a conversation and posts the same steps as the Reasons page.
   - First the mismatch: zone, setpoint against target, raised or lowered, since when.
   - "Why did you change it?": the OCAP reasons offered (ADR-0039) as buttons, and Other to type. A picked reason can
     carry a note.
   - The follow-up questions, one by one; both answers are sent together after the last.
   - The OCAP row of a picked reason, shown in full, or the sections a typed reason matches: "This one applies", or
     "ask a Manager".
   - The acknowledgment: "I've read it", review only (OCP-02).
   - When it waits for a Manager, the chat says so and comes back when the guidance arrives.
   - When the request closes, it says how: recorded, back on target, replaced by a newer change, or the shift ended.
     Then on to the next one waiting.
3. **The Reasons page stays** for the whole shift's list, and for Managers and Administrators. The corner notice is
   gone: the chat replaces it.
4. **The questions are the fixed ones until the AI model is chosen** (O-01). The AI then asks its two questions and
   writes its summary inside the same chat, within AI-02 and OCP-02.

## Consequences

- **The operator answers where they are,** without leaving the live view. Every answer is the same record as before,
  in the same order, audited the same way.
- **It's hard to miss:** it opens on its own and makes a sound. It doesn't cover the page, so the line can still be
  watched while answering.
- **It's in English,** like the rest of the interface, until LAN-01's Filipino interface. (Since
  [ADR-0043](ADR-0043-assistant-in-tagalog.md) the chat is Tagalog by default; the rest stays English, [ADR-0047](ADR-0047-interface-stays-english.md).)
- **Browsers can still mute it.** A page opened without any click or key press stays silent until the operator
  interacts with it. The panel opens anyway.

## Tests

- No new server code: the chat posts the same steps the workflow tests cover (`services/api/tests/test_workflow_api.py`,
  `test_ocap_api.py`, AT-05 and AT-08).
- Checked in headless Edge on a scratch stack, with the plant's workbook and seeded mismatches:
  - the chat opened after sign-in for a waiting mismatch, and the operator went through it: reason with a note, the
    two questions, the OCAP row, "I've read it", "Recorded";
  - after closing it, a new mismatch opened it again by itself;
  - minimised, it showed "1 reason to give";
  - at 400 px wide it fits, with no sideways scrolling.
