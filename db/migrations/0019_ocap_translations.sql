-- 0019 A checked Tagalog version of an OCAP version (LAN-01, OCP-02, ADR-0044).
--
-- The plant's own translation, never the AI's: a Manager uploads it against the OCAP version it translates, and it's
-- read and paired with that version section by section (an Excel workbook by sheet and rows, a PDF or Word file by
-- order). It's shown to operators only once a Manager activates it, and always beside the English, which stays the
-- authoritative text. Every change is a row of its own. Nothing here is ever changed or deleted.

CREATE TABLE ocap_translation (
    id          uuid PRIMARY KEY,
    version_id  uuid NOT NULL REFERENCES ocap_version (id),  -- the OCAP version it translates
    language    text NOT NULL CHECK (language IN ('fil')),
    source      text NOT NULL,          -- the file's name
    media_type  text NOT NULL,
    original    bytea NOT NULL,         -- the file as uploaded
    sha256      text NOT NULL,
    scan        text NOT NULL CHECK (scan IN ('clean', 'not_scanned')),  -- SEC-01
    scan_detail text,
    created_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by  text,
    reason      text NOT NULL
);
CREATE INDEX ocap_translation_of ON ocap_translation (version_id);

-- Each section of the version, as the translation has it
CREATE TABLE ocap_translation_section (
    translation_id uuid NOT NULL REFERENCES ocap_translation (id),
    section_id     uuid NOT NULL REFERENCES ocap_section (id),
    heading        text,
    body           text NOT NULL,
    phenomenon     text,                -- the reason it offers, in the translation's words
    PRIMARY KEY (translation_id, section_id)
);

-- Draft → Active (shown to operators); Withdrawn, or Superseded by a newer one for the same version and language
CREATE TABLE ocap_translation_status (
    seq            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    translation_id uuid NOT NULL REFERENCES ocap_translation (id),
    status         text NOT NULL CHECK (status IN ('draft', 'active', 'withdrawn', 'superseded')),
    at             timestamptz NOT NULL DEFAULT clock_timestamp(),
    by_user        text,
    reason         text NOT NULL
);
CREATE INDEX ocap_translation_status_of ON ocap_translation_status (translation_id, seq DESC);

CREATE VIEW ocap_translation_current AS
    SELECT DISTINCT ON (translation_id) translation_id, status, at, by_user, reason
      FROM ocap_translation_status ORDER BY translation_id, seq DESC;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['ocap_translation', 'ocap_translation_section', 'ocap_translation_status'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION refuse_change()',
                       t || '_append_only', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION refuse_change()',
                       t || '_no_truncate', t);
    END LOOP;
END
$$;

GRANT SELECT, INSERT ON ocap_translation, ocap_translation_section, ocap_translation_status TO centerline_app;
GRANT SELECT ON ocap_translation_current TO centerline_app;
