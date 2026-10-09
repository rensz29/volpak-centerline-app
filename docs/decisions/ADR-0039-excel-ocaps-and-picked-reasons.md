# ADR-0039: Excel OCAPs, and reasons the operator picks from their rows

- **Status:** Accepted
- **Date:** 2026-10-08
- **Decider:** Szyrelle (system owner), on 2026-10-08: "make a suggestion reason why they need to change it so they
  didn't need to type the reason". Then, of the options put to the owner:
  - the reasons come "From the OCAP file";
  - operators "Pick, or type under Other";
  - after a pick, they see "That reason's OCAP row".
- **Amends:** [ADR-0031](ADR-0031-ocap-library-deterministic-path.md) (PDF and Word only; every reason typed; every
  OCAP step searched)
- **URS:** OCP-01 (PDF and Word: a change request to add Excel), OCP-02, WF-01, LAN-01; SDD §7.1 (the reason was
  free text)

## Context

- **The plant's OCAPs come as an Excel workbook.** `OCAP_Volpak_Digital Copy_Updated (1).xlsx` has two sheets:
  - "OCAP - Filling": three OCAPs (weak seal on the vertical, bottom and top sealers) in blocks of merged rows;
  - "Sealer Troubleshooting": 13 rows, each a phenomenon with its cause, effect, mitigation and escalation, with a
    control note below the table.

  The library took PDF and Word only. Converting the workbook would turn a clean table into page layout, and it
  would have to be repeated after every change.
- **Typing a reason is slow, and typed Taglish searches badly.** The review of 2026-10-08 ran 14 sample Taglish
  reasons through the keyword search. The right section came first 8 times, and OCAP 1 came first for 12 of the 14
  reasons, including the two top-sealer alarms. Tagalog-only words, like "sunog" (burnt), never matched.
- **The workbook already names the reasons.** Each row's phenomenon ("Weak seal or seal separates easily",
  "Film sticks to the sealing jaw") is what an operator would write. Its sealer column says which parameters it
  concerns, and its cause column often says whether the temperature was too low or too high.

## Decision

1. **The library accepts Excel (`.xlsx`).** It's read with the standard library; `.xls` is refused with a request
   to save it as `.xlsx`. Each visible sheet is read as a table:
   - **The header row** is, among a sheet's first ten rows, the one with the most cells.
   - **Each row is a section**, or each block of rows merged in the first column. Its heading is the first column's
     number and the phenomenon; its text is every other column as "Column: value".
   - **Title lines** above the header form a section, as do **notes** below the table's first empty row.
   - **Hidden sheets are skipped.**
   - **Each section's place is its sheet and rows**, not pages. Citations read
     `OCAP-040 v1 · 1. Seal separates easily · Troubleshooting, row 4`.
   - A workbook that unpacks to more than 100 MB, or has more than 2000 rows of text, is refused.
   - A guidance's attachment stays PDF or Word (GDE-01).
2. **A row with a phenomenon is a reason to pick**, for HMI mismatches on some parameters, in one direction or both.
   - **Proposed from the file at upload.** The parameters are those whose distinctive name words the row's sealer,
     area or Centerline-name columns contain: "Top / Bottom / Vertical" gives Vertical, Bottom and Top Temperature.
     The direction is "raised" when its cause says the temperature was too low, "lowered" when it says too high,
     otherwise either.
   - **A Manager checks the proposal** on the version's sheet and changes it with a reason, any time. Each change is
     a row in `ocap_reason_tag`, audited; the latest is in effect. A row tagged with no parameter isn't offered, but
     it's still searched.
   - **Only Active versions offer reasons** (OCP-01).
3. **The operator picks the reason** when the alarm's request has any to offer:
   - The choices are the Active rows tagged for the alarm's parameter, in the alarm's direction (setpoint above the
     target: raised) or either. Those for the direction come first, then each OCAP's rows in order.
   - **Picking one** records its phenomenon as the reason, with an optional note below it, and keeps its section.
   - **Other** keeps today's free text, in English or Filipino.
   - A request with nothing to offer asks for a typed reason as before.
4. **A picked reason offers its own row in the OCAP step**, alone, recorded with the method `reason`. The operator
   reads it in full and chooses it, or "None of these apply" goes to a Manager's guidance (OCP-01: up to three, plus
   none). A typed reason is searched as before.
5. **The follow-up questions stay** as they are. When the AI comes (O-01), it can ask its two questions about the
   picked row instead of the fixed ones (AI-02).

## Consequences

- **An operator answers most alarms in two taps**, and the OCAP step always shows the row they picked: no search
  can rank the wrong OCAP first.
- **What operators pick is countable by row.** The reasons that "Other" collects show what the workbook lacks.
- **The choices are only as good as the tags.** "Seal / Scissor-Cutter" and "Sealing-Bar Contact" name no sealer, so
  they're offered for nothing until a Manager ticks the parameters.
- **The labels are the workbook's words, in English.** Filipino labels (LAN-01) wait for a Filipino version of the
  OCAP, or the AI's translation.
- **The URS says PDF and Word (OCP-01).** Accepting Excel is a change request to raise with the URS's owner, as
  ADR-0027 did for the SKU. The SDD's free-text reason (§7.1) is now picked or typed.
- **The plant's workbook isn't in the repository.** The tests use a workbook laid out like it,
  `ocap_samples.sealer_xlsx()`.

## Tests

- `services/api/tests/test_ocap_units.py`:
  - a workbook read row by row: merged blocks, the title and notes sections, the hidden sheet skipped, the group
    header and number column left out;
  - a workbook too large unpacked, or without text, refused, and `.xls` refused;
  - the proposals for parameters and direction;
  - citations by sheet and rows.
- `services/api/tests/test_ocap_api.py`:
  - an Excel upload's sections, places and proposed tags;
  - a Manager changing a tag, with a reason and only for judged parameters; an operator can't, and a note can't be
    a reason;
  - the operator's choices: none from a Draft, the direction's first, the other direction's never;
  - a pick with a note, then its row offered alone (`reason`);
  - "Other" searched as before;
  - a guidance's Excel attachment refused.
- `tests/acceptance/test_at08_ocap_deterministic.py`: on the simulated line, a reason picked from an Excel OCAP
  offers its row with its exact source, and the event's evidence keeps it (OCP-01, OCP-02, WF-01, AI-01).
- The access, idempotency, roles and migration guards list the new endpoint, table and migration (0015).
- The sample PDFs now carry a fixed creation date. AT-08's scanner test compared two copies made a second apart,
  and failed now and then.
