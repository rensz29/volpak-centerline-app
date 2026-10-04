-- 0009 Shifts and the reason workflow (WF-01…03, SES-03), ADR-0025.
--
-- Every HMI mismatch asks that shift's operator for a reason: one request per event per shift.
-- monitor-core writes the request with the event (HMI-02, NOT-03). An operator signing in to a
-- new shift gets a request for each mismatch still open. The operator gives a reason and answers
-- up to two follow-up questions; a Manager gives guidance (GDE-01; OCAP matching comes with
-- Phase 3); the operator acknowledges it. A request still open after 15 min alerts Management
-- once (WF-03, A-05). At the end of its shift an unfinished request closes as not answered, and
-- when its event closes it closes with it.

-- Shifts A, B and C start at 06:00, 14:00 and 22:00 Asia/Manila; the production date is the
-- Manila date a shift starts (A-07). A row is made the first time a shift is needed.
CREATE TABLE shift_instance (
    id              uuid PRIMARY KEY,
    code            text NOT NULL CHECK (code IN ('A', 'B', 'C')),
    starts_at       timestamptz NOT NULL UNIQUE,
    ends_at         timestamptz NOT NULL,
    production_date date NOT NULL,
    CHECK (ends_at > starts_at)
);
CREATE TRIGGER shift_instance_append_only BEFORE UPDATE OR DELETE ON shift_instance
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER shift_instance_no_truncate BEFORE TRUNCATE ON shift_instance
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

CREATE TABLE workflow_request (
    id                uuid PRIMARY KEY,
    event_id          uuid NOT NULL REFERENCES event (id),
    shift_instance_id uuid NOT NULL REFERENCES shift_instance (id),
    created_at        timestamptz NOT NULL,   -- the 15-min escalation clock starts here (A-05)
    status            text NOT NULL DEFAULT 'waiting_reason'
                      CHECK (status IN ('waiting_reason', 'waiting_answers', 'waiting_guidance', 'waiting_acknowledgment',
                                        'done', 'not_answered', 'resolved', 'superseded', 'cancelled')),
    escalated_at      timestamptz,
    closed_at         timestamptz,
    updated_at        timestamptz NOT NULL,
    UNIQUE (event_id, shift_instance_id),
    CHECK ((closed_at IS NULL) = (status IN ('waiting_reason', 'waiting_answers', 'waiting_guidance', 'waiting_acknowledgment')))
);
CREATE INDEX workflow_request_open ON workflow_request (created_at)
    WHERE status IN ('waiting_reason', 'waiting_answers', 'waiting_guidance', 'waiting_acknowledgment');

-- A request moves on, and once closed it stays closed; what it's about never changes
CREATE FUNCTION workflow_request_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    moving constant text[] := ARRAY['status', 'escalated_at', 'closed_at', 'updated_at'];
BEGIN
    IF TG_OP = 'UPDATE' AND to_jsonb(NEW) - moving = to_jsonb(OLD) - moving AND OLD.closed_at IS NULL
       AND (OLD.escalated_at IS NULL OR NEW.escalated_at = OLD.escalated_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'workflow_request: only an open request can move on, and what it is about never changes'
        USING ERRCODE = 'restrict_violation';
END
$$;
CREATE TRIGGER workflow_request_guard BEFORE UPDATE OR DELETE ON workflow_request
    FOR EACH ROW EXECUTE FUNCTION workflow_request_guard();
CREATE TRIGGER workflow_request_no_truncate BEFORE TRUNCATE ON workflow_request
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

-- What people wrote, as they wrote it (English or Filipino), kept for good: the reason, each
-- answer with the question as it was asked, a Manager's guidance, the acknowledgment
CREATE TABLE workflow_entry (
    seq        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id         uuid NOT NULL UNIQUE,
    request_id uuid NOT NULL REFERENCES workflow_request (id),
    kind       text NOT NULL CHECK (kind IN ('reason', 'answer', 'guidance', 'acknowledgment')),
    at         timestamptz NOT NULL,
    by_user    text NOT NULL,
    question   text,
    body       text NOT NULL,
    CHECK ((kind = 'answer') = (question IS NOT NULL)),
    CHECK (kind = 'acknowledgment' OR body <> '')
);
CREATE INDEX workflow_entry_of ON workflow_entry (request_id, seq);
CREATE TRIGGER workflow_entry_append_only BEFORE UPDATE OR DELETE ON workflow_entry
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER workflow_entry_no_truncate BEFORE TRUNCATE ON workflow_entry
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

-- The follow-up questions an operator answers after a reason, until the AI's (Phase 3), which
-- they also stand in for when it's down. Every change is a row; the latest is in effect.
CREATE TABLE workflow_settings (
    seq       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    questions jsonb NOT NULL CHECK (jsonb_typeof(questions) = 'array' AND jsonb_array_length(questions) <= 2),
    at        timestamptz NOT NULL DEFAULT clock_timestamp(),
    by_user   text,
    reason    text NOT NULL
);
CREATE TRIGGER workflow_settings_append_only BEFORE UPDATE OR DELETE ON workflow_settings
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER workflow_settings_no_truncate BEFORE TRUNCATE ON workflow_settings
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
INSERT INTO workflow_settings (questions, reason)
    VALUES ('["What was changed, and why?", "Is the product affected?"]', 'The starting questions (ADR-0025)');

-- A request still open after 15 min is a message to Management (WF-03)
ALTER TABLE notification DROP CONSTRAINT notification_kind_check;
ALTER TABLE notification ADD CONSTRAINT notification_kind_check
    CHECK (kind IN ('initial', 'escalated', 'recovery', 'critical_repeat', 'critical_escalation', 'superseded',
                    'changeover', 'system', 'test', 'workflow_escalation'));

GRANT SELECT, INSERT ON shift_instance, workflow_entry, workflow_settings TO centerline_app;
GRANT SELECT, INSERT, UPDATE ON workflow_request TO centerline_app;
