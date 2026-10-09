-- 0016 The AI's follow-up questions (AI-01, AI-02, DAT-01, ADR-0041).
--
-- After the reason, the local model (Ollama) may write the request's follow-up questions from the OCAP sections it's
-- given. Every call is kept: the model and its digest, the prompt's version and text, the sections, what came back,
-- and whether it was used. The questions a request asked are kept with it, the AI's or the fixed ones, so its
-- answers always say what they answered. Nothing here is ever changed or deleted.

CREATE TABLE ai_call (
    id             uuid PRIMARY KEY,
    request_id     uuid NOT NULL REFERENCES workflow_request (id),
    purpose        text NOT NULL CHECK (purpose IN ('questions')),
    model          text NOT NULL,
    model_digest   text,
    prompt_version text NOT NULL,
    sections       uuid[] NOT NULL,   -- the OCAP sections it was given
    prompt         text NOT NULL,     -- what was sent, system and user parts
    raw_output     text,              -- what came back, as it came
    outcome        text NOT NULL CHECK (outcome IN ('used', 'rejected', 'failed', 'timeout')),
    detail         text,              -- why it wasn't used
    latency_ms     integer,
    at             timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX ai_call_of ON ai_call (request_id);

-- The follow-up questions a request asked, in order; requests from before 0016 asked the fixed ones in effect
CREATE TABLE workflow_question (
    request_id uuid NOT NULL REFERENCES workflow_request (id),
    ordinal    integer NOT NULL CHECK (ordinal BETWEEN 1 AND 2),  -- at most two (AI-02)
    question   text NOT NULL CHECK (btrim(question) <> ''),
    asked_by   text NOT NULL CHECK (asked_by IN ('ai', 'fixed')),
    ai_call_id uuid REFERENCES ai_call (id),
    at         timestamptz NOT NULL,
    PRIMARY KEY (request_id, ordinal),
    CHECK ((asked_by = 'ai') = (ai_call_id IS NOT NULL))
);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['ai_call', 'workflow_question'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION refuse_change()',
                       t || '_append_only', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION refuse_change()',
                       t || '_no_truncate', t);
    END LOOP;
END
$$;

GRANT SELECT, INSERT ON ai_call, workflow_question TO centerline_app;
