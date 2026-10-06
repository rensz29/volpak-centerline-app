# ADR-0031: Phase 3 begins with the OCAP library and the deterministic path, before the AI model is chosen

- **Status:** Accepted
- **Date:** 2026-10-06
- **Decider:** Szyrelle (system owner), on 2026-10-06: "lets dive in to your recommendation". Phase 3 starts with
  the OCAP library, its search without AI, the OCAP steps of the reason workflow and the Manager's attachments and
  reusable OCAPs. The AI waits for its model (O-01, gate G0c).
- **Amends:** [ADR-0005](ADR-0005-split-gate-g0.md) (G0c gated all of Phase 3; it now gates the AI only), and
  [ADR-0025](ADR-0025-shifts-and-reasons.md) (every request went to a Manager's guidance)
- **URS:** OCP-01…03, GDE-01, WF-01, SEC-01 (scanned uploads), AI-01 ("monitoring never depends on AI"); AT-08, its
  deterministic part

## Context

- **Phase 3's gate G0c** asks for the AI models to be benchmarked and pinned (O-01), and the owner deferred that.
- **The plan needs a path without AI anyway.** The SDD's deterministic fallback (§7.2): keyword search, the exact
  sections, template questions, no summary. It runs whenever Ollama is down or slow, and AT-08 must pass with
  Ollama stopped.
- **That path is useful by itself:** operators get their plant's OCAP sections for a mismatch, and Managers keep
  their guidance as reusable OCAPs.

## Decision

1. **The OCAP library** (OCP-01, OCP-03), on its own page, for every role to read.
   - A Manager uploads an OCAP, a PDF or a Word `.docx` up to 20 MB. It gets a code as the plant knows it (for
     example `OCAP-017`), a title and a language (English or Filipino).
   - Each upload is a numbered version of its document, kept byte for byte with its SHA-256, the reason and who saved
     it. Nothing is changed or deleted.
   - A version is **Draft** until a Manager activates it, with no second approval. Only **Active** versions are
     searched.
   - On activation, the Manager keeps the earlier active version or retires it (**Superseded**). An active version
     can also be **Suspended** and activated again. Every change of status is a row of its own, audited.
   - The URS's "keep or suspend the prior active version" (OCP-03) is the choice at activation. A prior version
     taken out of use there is marked Superseded, the SDD's status for a version a newer one replaced. Suspended is
     for an active version taken out of use with nothing replacing it. Neither is searched, and either can be
     activated again.
2. **Malware scanning before anything is stored** (SEC-01). The api streams each upload to ClamAV (clamd); a
   `clamav` container joins the Docker stack.
   - An infected file is refused and the refusal audited.
   - With no scanner reachable, the upload is refused.
   - A development PC may say `"scanner": {"type": "none"}`: its versions are marked *not scanned*, and the page shows
     it.
3. **The text is read into sections with their pages:**
   - **PDF** (pdfplumber): headings by their size, weight or numbering; each page's repeated headers, footers and
     "Page n of m" dropped.
   - **Word** (python-docx): headings by their styles; the pages from the breaks Word recorded when it last laid
     the document out, so they're approximate.

   The Manager checks the sections on the draft before activating it: that's the URS's "validate". In this slice
   the api reads the files. The ai-worker takes reading and embedding over when it comes.
4. **The search, without AI** (OCP-01): PostgreSQL full-text search over the Active versions' sections.
   - English uses the `english` configuration; Filipino uses `simple`, with Filipino function words dropped.
   - The query is the event's context (the parameter, the zone, the setpoint above or below its target) with the
     operator's reason and answers. A section's heading and its document's title weigh more than its body.
   - Each result is a section with its exact citation: code, title, version, heading and pages.
5. **The workflow gets its OCAP steps** (WF-01, OCP-01/02):
   - after the reason and answers, the request waits for the operator to choose among up to three matches, or "None
     of these apply";
   - a match chosen: the operator reads the full section with its citation and acknowledges it, which records review
     only;
   - none chosen, or no match at all: the Manager's guidance, as before.

   The three matches are stored with the request: what was offered, its score, how it was found (`keyword`).
6. **A Manager's guidance** (GDE-01) can carry one PDF or Word attachment, scanned and kept like an OCAP file. It can
   also be saved as a reusable OCAP: a new document, active at once, its version written in Centerline.
7. **Not in this slice:**
   - **The AI:** clarification questions, summaries beside the source, translation, embedding search. It comes with
     the ai-worker and ollama once O-01 closes. Until then the follow-up questions stay the Administrator's two fixed
     ones.
   - **The Filipino interface (LAN-01).** Filipino OCAPs and text typed in Filipino work now; the screens follow in a
     later slice, translated by someone fluent.

## Consequences

- **G3 is not met by this slice.** AT-08 needs the AI's bilingual grounded retrieval too. Its deterministic part
  (top three matches, the exact source, the fallback) is tested now.
- **Keyword search finds sections that share words with the event and the reason.** A reason written in Filipino
  matches English OCAPs only through the event's own words, the parameter and the zone. Translation and embeddings
  come with the AI.
- **The plant's real OCAPs are needed.** The parser is built and tested on generated documents. The owner's sample
  OCAPs, English and Filipino, PDF and Word, are needed before G3.
- **ClamAV on the plant network** needs its signatures kept up to date without the internet (O-24).
- **OCAP files live in the database,** so the database backup carries them.
- **Checked on 2026-10-06:**
  - the parser, on generated PDF and Word OCAPs;
  - the scanner, against a real clamd (`clamav/clamav:stable`). It finds the EICAR test file hidden inside a Word
    file, but not one written after a PDF header, since EICAR counts only at the start of a file. The tests use the
    Word file;
  - AT-08's deterministic part, in `tests/acceptance/`;
  - the pages in a browser, from a Manager's upload to the operator's acknowledgment.
