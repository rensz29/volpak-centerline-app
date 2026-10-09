# ADR-0045: The local AI translates the OCAP into Tagalog, behind checks

- **Status:** Accepted, switched on 2026-10-09 for OCAPs in English
- **Date:** 2026-10-09
- **Decider:** Szyrelle (system owner), on 2026-10-09: "i change my mind lets translate the OCAP response into tagalog
  so no need the file for tagalog". Asked then whether to keep the checked file as an option or remove it, they chose to
  keep it ("ill go with the A"). Shown the measurement below, they first chose "Keep it off for now", then, the same
  day: "let me clear okay once the ocap response by AI its english right then if english translate it into tagalog
  thats it". So it's on, for OCAPs in English.
- **Amends:** [ADR-0044](ADR-0044-checked-tagalog-ocap.md) (the Tagalog OCAP came only from the plant's checked file)
- **URS:** LAN-01 (Filipino), OCP-02 (the exact authoritative source), AI-01 (local model), AI-02 (never corrective
  instructions), DAT-01 (keep the AI's calls)

## Context

- [ADR-0044](ADR-0044-checked-tagalog-ocap.md) showed the OCAP in Tagalog only from a translation the plant checked and
  a Manager activated, because the trial model had changed instructions ("Clean the jaw" became "Palitan ang jaw",
  *replace* the jaw). None was uploaded.
- The owner wants the OCAP in Tagalog without anyone writing a file.
- The risk is unchanged: the trial model (qwen3.5:4b on a 4 GB GPU) can change an instruction, drop a number or leave a
  row in English. A wrong instruction is what AI-02 forbids.

## Decision

1. **The local AI translates each section of the Active OCAPs in English into Tagalog, once, in the background**
   (`services/api/centerline_api/ai/translate.py`, prompt `ocap-fil-v1`). An OCAP uploaded in Filipino is shown as
   written.
   - One section at a time, every `ai.translate_every_s` (20 s), only while no operator is answering (no request has
     waited for a reason or answers in the last 3 minutes), since the model answers one thing at a time.
   - Line by line: the heading, the reason it offers, then each line of the text; the model answers one line for each,
     eight lines to a request (with longer lists it copied them back in English). A batch copied back in English is
     asked once more.
   - With a glossary of the instruction words (clean = linisin, replace = palitan, remove = alisin, stop = itigil,
     isolate = ihiwalay, call Maintenance = tumawag sa Maintenance, return to = ibalik sa, do not = huwag, …) and
     correct examples, technical words kept in English.
   - Its time limit is `ai.translate_timeout_s` (180 s): nobody waits for it.
2. **A translation is shown only if it passes every check;** otherwise that section stays in English:
   - the same number of lines, in the same order;
   - every number kept, each in its own line (the model once shifted a section's lines by one);
   - most sentences actually translated (changed, with Tagalog words);
   - each key word kept: a line that says *clean* must say *linis* (or *clean*: Taglish counts), and likewise *replace*,
     *remove*, *stop*, *isolate*, *call*, *return*, *tighten*, *close*, *open*, *hold*, *set*, *adjust*, *raise*,
     *lower*, *check*, *document*, *record*, *run*, an order not to (*huwag*), a negation (*hindi*), *same*, and the
     labels *cause*, *phenomenon* and *effect*;
   - and none added: *palitan*, *alisin*, *huwag*, *linisin*, *itigil*, *ihiwalay*, *tumawag*, *ibalik*, *isara*,
     *suriin*, *pumunta*, *magkaiba*, *sanhi*, … only where the English says so. Tagalog verbs take infixes (tumawag,
     tumigil, pinalitan), and the checks allow for them.
   - A section longer than 8,000 characters isn't sent.
3. **Every attempt is kept** in `ocap_ai_translation` (migration 0020, append-only): the model, its digest, the prompt
   version, the outcome (used, rejected, failed, timeout), why, its raw answer and how long it took. A failed or timed
   out one is tried again after 30 minutes; a rejected one isn't, until the prompt version changes.
4. **What operators see in Tagalog** is as in ADR-0044, with the AI's translation where the plant has none:
   - the reason buttons in Tagalog, with the OCAP's English words below;
   - the OCAP row under **"Salin ng AI · maaaring may mali, kaya basahin din ang English"** (the AI's translation, it
     may be wrong, so read the English too), followed by "Opisyal na OCAP (English)", the authoritative text (OCP-02).
5. **The plant's checked translation stays optional** (ADR-0044): once a Manager activates one, it's shown instead of
   the AI's, labelled "Sa Tagalog · sinuri ng plant".
6. **The Manager sees how far it got** on the OCAP version's sheet: how many sections are translated, how many stay
   English and why (the check each failed), and how many are still to do.

## Measurement: the plant's workbook with the trial model

`OCAP_Volpak_Digital Copy_Updated (1).xlsx` (18 sections) with qwen3.5:4b on the RTX A500 4 GB, on 2026-10-09:

- **First prompt, whole sections:** 7 of 18 passed the first checks. The model copied most long sections back in
  English, and for one row it wrote its prompt's example sentence ("Itigil ang makina… Linisin ang jaw") in place of
  "Set machine to the approved safe manual condition", an invented instruction, caught by the check.
- **This prompt, eight lines at a time:** 11 of 18 passed the first checks, 20–106 s a section. Reading those 11 line
  by line found what the checks then missed:
  - "Sealers must have same Temp." → "Dapat magkaiba ang Temp ng mga Sealer" (must have *different* temperatures);
  - "Document the procedure" → "Suriin ang proseso" (*check* the procedure);
  - "Run trial pouches" → "Pumunta sa trial pouches" (*go to*);
  - "Record the weak location" → "Ilahad…" (*present*);
  - one section's lines shifted by one, so a Tagalog line sat beside another English line;
  - nonsense words: "hindi nakakataong makabagay sa preset", "pinapayamang", "kalusugan ng jaw" (the jaw's *health*).
- **With the checks above** (each of those cases added): **5 of 18 pass**. They change no instruction that a reader
  found, but some still carry nonsense words and odd labels ("Plano ng Operator para sa Pagpapalago").

So with this model, most of the OCAP stays English, and what's shown in Tagalog still needs the English below it. The
checks catch the kinds of error seen; they can't catch every wrong word.

## Switched on

Deployed first switched off, at the owner's choice after the measurement; switched on the same day
(`ai.translate_every_s` 20 in `deploy/config/api.json` and `deploy/setup.sh`; 0 switches it off). With the trial model
about a third of the plant workbook's sections show in Tagalog and the rest stay English. The plant's checked file
([ADR-0044](ADR-0044-checked-tagalog-ocap.md)), once a Manager activates it, covers every section; the draft of it is
`Downloads\OCAP\OCAP_Volpak_Tagalog_DRAFT.xlsx`. A better model (O-01, a bigger GPU) should be measured on the plant's
workbook again first.

## Consequences

- Operators read the OCAP in Tagalog without anyone writing a file, but **a translation that passed the checks can still
  be wrong** in ways no check catches (a wrong noun, an awkward phrase). That's why it's labelled as the AI's and the
  English is always below it. The plant's checked file remains the way to have it right.
- The checks only know the instruction words in the glossary. An OCAP with other instruction verbs (*adjust*,
  *lubricate*, …) needs them added.
- Translating takes the model 20–106 s a section. An opening question for a mismatch that comes during one waits
  behind it, and may fall back to the fixed question.
- A new OCAP version is translated again; the old version's translations stay with it.

## Tests

- `services/api/tests/test_ai_translate.py`:
  - the checks: a faithful translation is used; "Clean the jaw" as "Palitan ang jaw" is refused, and so is an added
    "Huwag", a lost number, lines that don't pair up, text left in English; infixed verbs count;
  - the job, against a stand-in Ollama: each section of an Active version in English once, a Draft or an OCAP in
    Filipino never; a section that fails a
    check stays English, with why on the version's sheet; operators see the AI's label and section text, with the English
    as the section's body; nothing is sent while an operator is answering; the plant's checked translation, once active,
    is shown instead; a timeout or failure is tried again later, a rejection never; too long a section isn't sent.
  - the trial model's own mistakes on the plant's workbook, each refused: a changed verb (close, tighten, document,
    run), a changed label (phenomenon → *sanhi*), a lost negation, "same" → "magkaiba", shifted lines; and a
    description's "do not" needs *hindi*, not *huwag*;
  - a batch copied back in English is asked once more; a long section goes in batches of eight lines.
- The migration and roles guards list 0020 and `ocap_ai_translation`.
- The measurement above: the saved answers re-checked with the final checks.
