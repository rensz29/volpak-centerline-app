-- 0015 Excel OCAPs and the reasons an operator picks from them (ADR-0039).
--
-- An OCAP can now be an Excel workbook (.xlsx). Each row of a sheet's table, or each block of merged rows, is a
-- section, found by its sheet and rows instead of pages. A row that names a phenomenon is also a reason an operator
-- can pick for an HMI mismatch: for the parameters it applies to and, where it matters, only when the setpoint was
-- raised or lowered. Both are proposed from the file at upload, then checked by a Manager. Every change is a row of
-- its own; the latest is in effect. A reason picked this way leads straight to its section in the OCAP step.

ALTER TABLE ocap_section ADD COLUMN sheet text;         -- an Excel version: the section's sheet
ALTER TABLE ocap_section ADD COLUMN row_from integer;   -- and its rows
ALTER TABLE ocap_section ADD COLUMN row_to integer;
ALTER TABLE ocap_section ADD COLUMN phenomenon text CHECK (phenomenon IS NULL OR btrim(phenomenon) <> '');
ALTER TABLE ocap_section ADD CONSTRAINT ocap_section_rows
    CHECK ((sheet IS NULL) = (row_from IS NULL) AND (row_from IS NULL) = (row_to IS NULL) AND row_to >= row_from);

-- When a section is offered as a reason: the parameters whose HMI mismatches offer it (none: not offered), and the
-- direction of the change (OCP-01 still holds: only Active versions are offered)
CREATE TABLE ocap_reason_tag (
    seq           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    section_id    uuid NOT NULL REFERENCES ocap_section (id),
    parameter_ids text[] NOT NULL,
    direction     text NOT NULL CHECK (direction IN ('raised', 'lowered', 'either')),
    at            timestamptz NOT NULL DEFAULT clock_timestamp(),
    by_user       text,
    reason        text NOT NULL
);
CREATE INDEX ocap_reason_tag_of ON ocap_reason_tag (section_id, seq DESC);

CREATE VIEW ocap_reason_choice AS
    SELECT DISTINCT ON (section_id) section_id, parameter_ids, direction, at, by_user, reason
      FROM ocap_reason_tag ORDER BY section_id, seq DESC;

-- A reason picked from an OCAP keeps its section...
ALTER TABLE workflow_entry DROP CONSTRAINT workflow_entry_ocap_choice;
ALTER TABLE workflow_entry ADD CONSTRAINT workflow_entry_ocap_section
    CHECK (ocap_section_id IS NULL OR kind IN ('reason', 'ocap_choice'));

-- ...which the OCAP step then offers on its own
ALTER TABLE ocap_recommendation DROP CONSTRAINT ocap_recommendation_method_check;
ALTER TABLE ocap_recommendation ADD CONSTRAINT ocap_recommendation_method_check CHECK (method IN ('keyword', 'reason'));

CREATE TRIGGER ocap_reason_tag_append_only BEFORE UPDATE OR DELETE ON ocap_reason_tag
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER ocap_reason_tag_no_truncate BEFORE TRUNCATE ON ocap_reason_tag
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

GRANT SELECT, INSERT ON ocap_reason_tag TO centerline_app;
GRANT SELECT ON ocap_reason_choice TO centerline_app;
