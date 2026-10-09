-- 0021 The AI's summary of the OCAP sections offered (OCP-02, AI-02, LAN-01, DAT-01, ADR-0046).
--
-- Once a request's OCAP sections are offered, the local model sums up what they say for this mismatch, in English and
-- Filipino, citing which of them it used. It's shown above the sections, never instead of them, and only if it cites
-- nothing but the sections offered and names no number or instruction the cited sections don't have. The call is
-- kept in ai_call like the others; a summary that passed is kept here, one per request.

ALTER TABLE ai_call DROP CONSTRAINT ai_call_purpose_check;
ALTER TABLE ai_call ADD CONSTRAINT ai_call_purpose_check CHECK (purpose IN ('questions', 'opening', 'summary'));

CREATE TABLE workflow_summary (
    request_id  uuid PRIMARY KEY REFERENCES workflow_request (id),
    summary     text NOT NULL,
    summary_fil text,                    -- its Filipino, when that passed its own checks; else the English shows
    section_ids uuid[] NOT NULL,         -- the sections it cites: some of those offered (ocap_recommendation)
    ai_call_id  uuid NOT NULL REFERENCES ai_call (id),
    at          timestamptz NOT NULL
);

CREATE TRIGGER workflow_summary_append_only BEFORE UPDATE OR DELETE ON workflow_summary
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER workflow_summary_no_truncate BEFORE TRUNCATE ON workflow_summary
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

GRANT SELECT, INSERT ON workflow_summary TO centerline_app;
