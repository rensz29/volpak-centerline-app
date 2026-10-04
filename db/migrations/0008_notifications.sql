-- 0008 Notifications: routing, deliveries and attempts for the outbox (NOT-01…07), ADR-0023.
--
-- monitor-core writes each logical message to `notification` with its event (NOT-03). The
-- notifier routes it once, by the routing in effect, and freezes what matched in
-- `notification_route`. Each channel × target is a `notification_delivery` carrying the
-- message as sent. It is retried on the schedule (NOT-04/05) with the same dedup key and
-- Message-ID, and every attempt is kept in `delivery_attempt`. Routing versions are written
-- once and take effect through activations, like the rules. A TEST message (NOT-07) is a
-- notification of kind 'test' that the api routes itself, to one target.

-- The message never changes: its status lives in its route and deliveries
ALTER TABLE notification DROP COLUMN status;
ALTER TABLE notification DROP CONSTRAINT notification_kind_check;
ALTER TABLE notification ADD CONSTRAINT notification_kind_check
    CHECK (kind IN ('initial', 'escalated', 'recovery', 'critical_repeat', 'critical_escalation', 'superseded',
                    'changeover', 'system', 'test'));
CREATE INDEX notification_created ON notification (created_at DESC, id DESC);
CREATE TRIGGER notification_append_only BEFORE UPDATE OR DELETE ON notification
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER notification_no_truncate BEFORE TRUNCATE ON notification
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

-- Who gets what: rules of {name, types, channel, targets}, written once per version
CREATE TABLE routing_version (
    id          uuid PRIMARY KEY,
    number      integer NOT NULL UNIQUE CHECK (number > 0),
    based_on_id uuid REFERENCES routing_version (id),
    rules       jsonb NOT NULL CHECK (jsonb_typeof(rules) = 'array'),
    sha256      text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by  text,
    reason      text NOT NULL
);
CREATE TRIGGER routing_version_append_only BEFORE UPDATE OR DELETE ON routing_version
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER routing_version_no_truncate BEFORE TRUNCATE ON routing_version
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

CREATE TABLE routing_activation (
    id                 uuid PRIMARY KEY,
    routing_version_id uuid NOT NULL REFERENCES routing_version (id),
    effective_at       timestamptz NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by         text,
    reason             text NOT NULL,
    cancelled_at       timestamptz,
    cancelled_by       text,
    cancel_reason      text,
    CHECK ((cancelled_at IS NULL) = (cancel_reason IS NULL))
);
CREATE INDEX routing_activation_in_effect ON routing_activation (effective_at DESC, created_at DESC)
    WHERE cancelled_at IS NULL;
CREATE TRIGGER routing_activation_guard BEFORE UPDATE OR DELETE ON routing_activation
    FOR EACH ROW EXECUTE FUNCTION activation_guard();
CREATE TRIGGER routing_activation_no_truncate BEFORE TRUNCATE ON routing_activation
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

CREATE FUNCTION active_routing_version(at_time timestamptz DEFAULT clock_timestamp()) RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT routing_version_id FROM routing_activation
     WHERE cancelled_at IS NULL AND effective_at <= at_time
     ORDER BY effective_at DESC, created_at DESC
     LIMIT 1
$$;

-- How each message was routed, frozen once: the routing snapshot (SDD §8)
CREATE TABLE notification_route (
    notification_id uuid PRIMARY KEY REFERENCES notification (id),
    routed_at       timestamptz NOT NULL DEFAULT clock_timestamp(),
    type            text NOT NULL,       -- hmi_mismatch, actual_warning, actual_critical, …, test
    routing_version integer,             -- the routing in effect; NULL when there was none, and for a TEST
    matched         jsonb NOT NULL,      -- the rules that matched, as they were
    outcome         text NOT NULL CHECK (outcome IN ('routed', 'unrouted', 'expired', 'test'))
);
CREATE TRIGGER notification_route_append_only BEFORE UPDATE OR DELETE ON notification_route
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER notification_route_no_truncate BEFORE TRUNCATE ON notification_route
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

-- One message × channel × target, with its own status (a Teams outage never blocks email)
CREATE TABLE notification_delivery (
    id              uuid PRIMARY KEY,
    notification_id uuid NOT NULL REFERENCES notification (id),
    channel         text NOT NULL CHECK (channel IN ('teams', 'email')),
    target          text NOT NULL CHECK (target <> ''),
    rule            text,                -- the routing rule that chose it; NULL for a TEST
    dedup_key       text NOT NULL UNIQUE,
    message_id      text NOT NULL,       -- the same on every retry: the email Message-ID, and the key in the Teams footer
    content         jsonb NOT NULL,      -- the message as sent: subject, text, the Teams payload
    status          text NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING', 'ATTEMPTING', 'DELIVERED', 'SUBMITTED', 'RETRYING',
                                      'PERMANENT_FAILURE', 'REDRIVEN')),
    attempt_count   integer NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    next_attempt_at timestamptz,
    last_error      text,
    finished_at     timestamptz,
    redrive_of      uuid REFERENCES notification_delivery (id),  -- an Administrator sent it again (NOT-05)
    redriven_by     text,
    redrive_reason  text,
    CHECK ((redrive_of IS NULL) = (redrive_reason IS NULL))
);
CREATE INDEX notification_delivery_due ON notification_delivery (channel, next_attempt_at)
    WHERE status IN ('PENDING', 'RETRYING');
CREATE INDEX notification_delivery_of ON notification_delivery (notification_id);

-- A delivery changes status, never what it is. Once Teams answered 202 or the relay 250, it is
-- never sent again (NOT-06); a permanent failure can only be re-driven.
CREATE FUNCTION delivery_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    moving constant text[] := ARRAY['status', 'attempt_count', 'next_attempt_at', 'last_error', 'finished_at'];
BEGIN
    IF TG_OP = 'UPDATE'
       AND to_jsonb(NEW) - moving = to_jsonb(OLD) - moving
       AND (OLD.status IN ('PENDING', 'ATTEMPTING', 'RETRYING')
            OR (OLD.status = 'PERMANENT_FAILURE' AND NEW.status = 'REDRIVEN'))
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'notification_delivery: only the status of an unfinished delivery can change'
        USING ERRCODE = 'restrict_violation';
END
$$;
CREATE TRIGGER notification_delivery_guard BEFORE UPDATE OR DELETE ON notification_delivery
    FOR EACH ROW EXECUTE FUNCTION delivery_guard();
CREATE TRIGGER notification_delivery_no_truncate BEFORE TRUNCATE ON notification_delivery
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

-- Every attempt, kept
CREATE TABLE delivery_attempt (
    id          uuid PRIMARY KEY,
    delivery_id uuid NOT NULL REFERENCES notification_delivery (id),
    attempt     integer NOT NULL CHECK (attempt > 0),
    started_at  timestamptz NOT NULL,
    ended_at    timestamptz NOT NULL,
    outcome     text NOT NULL CHECK (outcome IN ('delivered', 'submitted', 'failed', 'interrupted')),
    response    text,                    -- what the provider said, trimmed; never a secret
    UNIQUE (delivery_id, attempt)
);
CREATE TRIGGER delivery_attempt_append_only BEFORE UPDATE OR DELETE ON delivery_attempt
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER delivery_attempt_no_truncate BEFORE TRUNCATE ON delivery_attempt
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

CREATE TABLE notifier_heartbeat (
    instance   text PRIMARY KEY,
    started_at timestamptz NOT NULL,
    beat_at    timestamptz NOT NULL,
    status     jsonb NOT NULL
);

-- The services' role (ADR-0020): versions, routes and attempts are added and read; deliveries,
-- activations (cancelling only) and the heartbeat are also updated
GRANT SELECT, INSERT ON routing_version, notification_route, delivery_attempt TO centerline_app;
GRANT SELECT, INSERT, UPDATE ON routing_activation, notification_delivery, notifier_heartbeat TO centerline_app;
