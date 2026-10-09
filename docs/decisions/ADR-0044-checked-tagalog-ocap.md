# ADR-0044: The OCAP in Tagalog comes from a checked translation, never the AI

- **Status:** Accepted. [ADR-0045](ADR-0045-ai-translates-the-ocap.md) adds the local AI's translation behind checks;
  this checked translation, once active, is shown instead of it
- **Date:** 2026-10-09
- **Decider:** Szyrelle (system owner), on 2026-10-09: "i want you to translate the OCAP documents response into
  tagalog". Of the options then put to the owner, they chose "Checked Tagalog copy" over "AI translation anyway,
  labelled" and "Keep the OCAP in English for now".
- **Amends:** [ADR-0043](ADR-0043-assistant-in-tagalog.md) (the OCAP's text stayed English)
- **URS:** LAN-01, OCP-02 (the exact authoritative source), AI-02 (never corrective instructions), OCP-03, SEC-01

## Context

- In Tagalog, the operator's chat showed the OCAP rows in English.
- **The trial model translated OCAP rows badly** (the plant's workbook, 2026-10-09):
  - "Clean the jaw if needed" became "Palitan ang jaw" (*replace* the jaw);
  - "Return to the approved centerline and allow stabilization" became "Pumunta sa approved centerline at magbigay ng
    stabilization";
  - "cannot reach or hold the preset" became "hindi makapunta o makatipon";
  - "on both sides" became "sa pare-parehong gilid";
  - one row came back untranslated;
  - OCAP 1 took about a minute.

  A changed instruction is what AI-02 forbids, whatever the label.
- **The workbook is small:** 3 OCAPs and 13 troubleshooting rows, 133 texts in all.

## Decision

1. **The Tagalog OCAP is the plant's own checked translation,** uploaded by a Manager against the OCAP version it
   translates ("Add the Tagalog version" on its sheet).
   - It's scanned (SEC-01) and read like an OCAP (PDF, Word or Excel).
   - It's paired with the version section by section: an Excel workbook by sheet and rows, PDF or Word by order.
   - Every section must have its match, or nothing is saved, and the refusal says which rows don't line up.
2. **A Draft until a Manager activates it**, as for an OCAP (OCP-03): the Manager checks each row's Tagalog under its
   English first. A newer one for the same version supersedes the active one, and it can be withdrawn. It's kept byte
   for byte, every change audited, append-only (migration 0019: `ocap_translation`, its sections and its statuses).
3. **What operators see in Tagalog** (ADR-0043's chat):
   - the reason buttons in the OCAP's Tagalog words, with its English words below;
   - the picked reason in Tagalog, though the record keeps the English;
   - the OCAP row as "Sa Tagalog · sinuri ng plant", followed by "Opisyal na OCAP (English)", the authoritative text
     (OCP-02).

   Without an active Tagalog version, the English is shown, as before.
4. **The first draft is Claude's,** for the plant to check: `Downloads\OCAP\OCAP_Volpak_Tagalog_DRAFT.xlsx`.
   - It's the plant's workbook with its 133 texts in Tagalog, the way operators speak, with technical words in English.
   - Every number and range is kept (checked by script).
   - The column headers are in both languages, e.g. "Posibleng Pangyayari (Possible Phenomenon)", so Centerline still
     finds the phenomenon, sealer and cause columns.
   - It pairs with the English: 18 of 18 sections, 16 reasons.
   - It isn't in the repository: it's the plant's document.

## Consequences

- **No AI writes OCAP instructions in any language.** The AI still writes its questions in Tagalog (ADR-0043), and
  those are questions, not instructions.
- **Someone at the plant has to check the draft.** It's activated only after that, and the Manager's activation is the
  approval.
- **When the English OCAP changes, its Tagalog version must be redone.** A new English version has no translation until
  one is uploaded for it, and operators see the English meanwhile.

## Tests

- `services/api/tests/test_ocap_api.py`, with `ocap_samples.sealer_xlsx_fil()`:
  - a file that doesn't line up is refused, and so is a missing reason;
  - an operator can't upload one;
  - the Draft is shown on the version's sheet but not to operators;
  - once active, operators see the Tagalog label and section text, with the English kept as the section's body;
  - the file is downloadable;
  - a newer one supersedes the older, a withdrawn one isn't shown;
  - the five audit entries.
- The access, idempotency, roles and migration guards list the new endpoints, tables and migration (0019).
- Checked in headless Edge on a scratch stack with the plant's workbook and the draft activated:
  - the operator's chat showed the reasons in Tagalog, the fixed questions in Tagalog, then the OCAP row in Tagalog
    over the English;
  - the Manager's sheet showed the Tagalog version, Active, with Withdraw.
