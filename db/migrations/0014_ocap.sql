-- 0014 The OCAP library and the reason workflow's OCAP steps (OCP-01…03, GDE-01, WF-01, ADR-0031).
--
-- A Manager uploads an OCAP as a PDF or Word file: each upload is a version of its document, kept as uploaded and
-- read into sections with their pages, then split into chunks for the search. Only Active versions are searched.
-- Every change of status is a row of its own. Nothing here is ever changed or deleted.

CREATE TABLE ocap_document (
    id         uuid PRIMARY KEY,
    code       text NOT NULL CHECK (btrim(code) <> ''),   -- as the plant knows it, e.g. OCAP-017
    title      text NOT NULL CHECK (btrim(title) <> ''),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by text
);
CREATE UNIQUE INDEX ocap_document_code ON ocap_document (lower(code));

CREATE TABLE ocap_version (
    id          uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES ocap_document (id),
    number      integer NOT NULL CHECK (number > 0),
    language    text NOT NULL CHECK (language IN ('en', 'fil')),
    source      text NOT NULL,          -- the file's name, or "Written in Centerline"
    media_type  text NOT NULL,
    original    bytea,                  -- the file as uploaded; NULL for a version written in Centerline
    sha256      text NOT NULL,          -- of the file, or of the text written
    scan        text NOT NULL CHECK (scan IN ('clean', 'not_scanned', 'written')),  -- SEC-01
    scan_detail text,                   -- the scanner's answer
    pages       integer,
    created_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by  text,
    reason      text NOT NULL,
    UNIQUE (document_id, number),
    CHECK ((original IS NULL) = (scan = 'written'))
);

-- The version read into sections: a heading (NULL for the text before the first), its pages, its text
CREATE TABLE ocap_section (
    id         uuid PRIMARY KEY,
    version_id uuid NOT NULL REFERENCES ocap_version (id),
    ordinal    integer NOT NULL CHECK (ordinal > 0),
    heading    text,
    level      integer NOT NULL DEFAULT 1 CHECK (level BETWEEN 1 AND 6),
    page_from  integer,
    page_to    integer,
    body       text NOT NULL,
    UNIQUE (version_id, ordinal)
);

-- What the search reads: a section in pieces, the document's title and the heading weighing more than the text
CREATE TABLE ocap_chunk (
    id         uuid PRIMARY KEY,
    section_id uuid NOT NULL REFERENCES ocap_section (id),
    ordinal    integer NOT NULL CHECK (ordinal > 0),
    body       text NOT NULL,
    tsv        tsvector NOT NULL,
    UNIQUE (section_id, ordinal)
);
CREATE INDEX ocap_chunk_tsv ON ocap_chunk USING gin (tsv);

-- Draft → Active; an Active version Suspended (and activated again) or Superseded by a newer one (OCP-03)
CREATE TABLE ocap_status (
    seq        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version_id uuid NOT NULL REFERENCES ocap_version (id),
    status     text NOT NULL CHECK (status IN ('draft', 'active', 'suspended', 'superseded')),
    at         timestamptz NOT NULL DEFAULT clock_timestamp(),
    by_user    text,
    reason     text NOT NULL
);
CREATE INDEX ocap_status_of ON ocap_status (version_id, seq DESC);

CREATE VIEW ocap_version_status AS
    SELECT DISTINCT ON (version_id) version_id, status, at, by_user, reason
      FROM ocap_status ORDER BY version_id, seq DESC;

-- The reason workflow: a step for the operator to choose an OCAP, and what was offered
ALTER TABLE workflow_request DROP CONSTRAINT workflow_request_status_check;
ALTER TABLE workflow_request ADD CONSTRAINT workflow_request_status_check
    CHECK (status IN ('waiting_reason', 'waiting_answers', 'waiting_ocap', 'waiting_guidance', 'waiting_acknowledgment',
                      'done', 'not_answered', 'resolved', 'superseded', 'cancelled'));
ALTER TABLE workflow_request DROP CONSTRAINT workflow_request_check;
ALTER TABLE workflow_request ADD CONSTRAINT workflow_request_check
    CHECK ((closed_at IS NULL) = (status IN ('waiting_reason', 'waiting_answers', 'waiting_ocap', 'waiting_guidance',
                                             'waiting_acknowledgment')));
DROP INDEX workflow_request_open;
CREATE INDEX workflow_request_open ON workflow_request (created_at)
    WHERE status IN ('waiting_reason', 'waiting_answers', 'waiting_ocap', 'waiting_guidance', 'waiting_acknowledgment');

-- The operator's choice: a section, or "none" when none of them applies
ALTER TABLE workflow_entry DROP CONSTRAINT workflow_entry_kind_check;
ALTER TABLE workflow_entry ADD CONSTRAINT workflow_entry_kind_check
    CHECK (kind IN ('reason', 'answer', 'ocap_choice', 'guidance', 'acknowledgment'));
ALTER TABLE workflow_entry ADD COLUMN ocap_section_id uuid REFERENCES ocap_section (id);
ALTER TABLE workflow_entry ADD CONSTRAINT workflow_entry_ocap_choice CHECK (ocap_section_id IS NULL OR kind = 'ocap_choice');

CREATE TABLE ocap_recommendation (
    request_id uuid NOT NULL REFERENCES workflow_request (id),
    rank       integer NOT NULL CHECK (rank BETWEEN 1 AND 3),
    section_id uuid NOT NULL REFERENCES ocap_section (id),
    score      double precision NOT NULL,
    method     text NOT NULL CHECK (method IN ('keyword')),  -- the AI's search joins it later
    query      text NOT NULL,                                -- what was searched for
    at         timestamptz NOT NULL,
    PRIMARY KEY (request_id, rank)
);

-- A Manager's guidance may carry one PDF or Word file (GDE-01), scanned like an OCAP
CREATE TABLE workflow_attachment (
    id         uuid PRIMARY KEY,
    entry_id   uuid NOT NULL UNIQUE REFERENCES workflow_entry (id),
    name       text NOT NULL,
    media_type text NOT NULL,
    content    bytea NOT NULL,
    sha256     text NOT NULL,
    scan       text NOT NULL CHECK (scan IN ('clean', 'not_scanned')),
    scan_detail text,
    at         timestamptz NOT NULL
);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['ocap_document', 'ocap_version', 'ocap_section', 'ocap_chunk', 'ocap_status',
                             'ocap_recommendation', 'workflow_attachment'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION refuse_change()',
                       t || '_append_only', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION refuse_change()',
                       t || '_no_truncate', t);
    END LOOP;
END
$$;

GRANT SELECT, INSERT ON ocap_document, ocap_version, ocap_section, ocap_chunk, ocap_status, ocap_recommendation,
                        workflow_attachment TO centerline_app;
GRANT SELECT ON ocap_version_status TO centerline_app;
