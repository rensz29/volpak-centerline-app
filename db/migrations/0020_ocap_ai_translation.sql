-- 0020 The AI's Tagalog translation of OCAP sections (LAN-01, AI-02, DAT-01, ADR-0045).
--
-- The local model translates each section of the Active OCAP versions once, in the background, line by line. Its
-- answer is used only if it passes the checks (every line translated, every number kept, the instruction words kept:
-- clean stays "linisin", never "palitan"); otherwise the section stays English. Every attempt is kept, used or not.

CREATE TABLE ocap_ai_translation (
    id             uuid PRIMARY KEY,
    section_id     uuid NOT NULL REFERENCES ocap_section (id),
    language       text NOT NULL CHECK (language IN ('fil')),
    prompt_version text NOT NULL,
    model          text NOT NULL,
    model_digest   text,
    outcome        text NOT NULL CHECK (outcome IN ('used', 'rejected', 'failed', 'timeout')),
    detail         text,              -- why it isn't used
    heading        text,
    label          text,              -- the phenomenon, the reason it offers
    body           text,
    raw_output     text,
    latency_ms     integer,
    at             timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((outcome = 'used') = (body IS NOT NULL))
);
CREATE INDEX ocap_ai_translation_of ON ocap_ai_translation (section_id, at DESC);

CREATE TRIGGER ocap_ai_translation_append_only BEFORE UPDATE OR DELETE ON ocap_ai_translation
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER ocap_ai_translation_no_truncate BEFORE TRUNCATE ON ocap_ai_translation
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

GRANT SELECT, INSERT ON ocap_ai_translation TO centerline_app;
