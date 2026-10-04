-- 0003 Monitoring: events and their evidence, timers, pauses, the notification outbox (ADR-0014).
--
-- Evidence is append-only (DAT-01): event headers, transitions, brief-change records and
-- acknowledgments are inserted once. event_state is a projection that can be rebuilt from
-- the transitions; scheduled_action, the heartbeat and outbox statuses are operational.
-- Every event is pinned to the rules, mapping and register versions it was judged under (OPC-07).

CREATE TABLE event (
    id                  uuid PRIMARY KEY,                -- UUIDv7, made by monitor-core
    kind                text NOT NULL CHECK (kind IN ('HMI_MISMATCH', 'ACTUAL')),
    parameter_id        text NOT NULL,
    zone_id             text NOT NULL,
    sku_code            text NOT NULL,
    opened_at           timestamptz NOT NULL,            -- when the delay ended (DEP-06: UTC)
    severity            text CHECK (severity IN ('WARNING', 'CRITICAL')),
    raw_target          numeric,                         -- raw decimals as evidence (HMI-01)
    raw_hmi             numeric,
    raw_actual          numeric,
    config_version_id   uuid NOT NULL REFERENCES config_version (id),
    mapping_version_id  uuid NOT NULL REFERENCES mapping_version (id),
    register_version_id uuid NOT NULL REFERENCES register_version (id),
    supersedes_event_id uuid REFERENCES event (id),     -- HMI-03
    rule                jsonb NOT NULL,                  -- the resolved rule it is judged by until it closes
    CHECK ((kind = 'ACTUAL') = (severity IS NOT NULL))
);

CREATE INDEX event_zone ON event (parameter_id, zone_id, opened_at DESC);

CREATE TABLE event_transition (
    id       uuid NOT NULL UNIQUE,                       -- so a replayed write lands once (RES-01)
    event_id uuid NOT NULL REFERENCES event (id),
    seq      integer NOT NULL CHECK (seq > 0),
    at       timestamptz NOT NULL,
    state    text NOT NULL CHECK (state IN ('OPEN', 'WARNING', 'CRITICAL', 'RESOLVED', 'SUPERSEDED',
                                            'CLOSED_SKU_CHANGEOVER', 'ACKNOWLEDGED')),
    inputs   jsonb NOT NULL DEFAULT '{}'::jsonb,         -- the values that caused it
    PRIMARY KEY (event_id, seq)
);

-- The current state of each event, kept in step with its transitions
CREATE TABLE event_state (
    event_id        uuid PRIMARY KEY REFERENCES event (id),
    state           text NOT NULL,
    severity        text,
    open            boolean NOT NULL,
    updated_at      timestamptz NOT NULL,
    closed_at       timestamptz,
    acknowledged_at timestamptz
);

CREATE INDEX event_state_open ON event_state (open) WHERE open;

-- A setpoint back on target before the mismatch delay ended (HMI-05)
CREATE TABLE lightweight_change (
    id                 uuid PRIMARY KEY,
    parameter_id       text NOT NULL,
    zone_id            text NOT NULL,
    sku_code           text NOT NULL,
    mode               text NOT NULL CHECK (mode IN ('lightweight', 'cleared_before_trigger')),
    started_at         timestamptz NOT NULL,
    ended_at           timestamptz NOT NULL,
    raw_target         numeric,
    raw_hmi            numeric,
    config_version_id  uuid NOT NULL REFERENCES config_version (id),
    mapping_version_id uuid NOT NULL REFERENCES mapping_version (id),
    evidence           jsonb                              -- full evidence, cleared-before-trigger only (A-04)
);

-- A Manager's acknowledgment stops a Critical's repeats (ACT-04); written by the api, read by monitor-core
CREATE TABLE event_acknowledgment (
    seq      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id       uuid NOT NULL UNIQUE,
    event_id uuid NOT NULL REFERENCES event (id),
    at       timestamptz NOT NULL DEFAULT clock_timestamp(),
    by_user  text,                                       -- NULL until login exists
    note     text
);

CREATE TRIGGER event_append_only BEFORE UPDATE OR DELETE ON event
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER event_transition_append_only BEFORE UPDATE OR DELETE ON event_transition
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER lightweight_change_append_only BEFORE UPDATE OR DELETE ON lightweight_change
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER event_acknowledgment_append_only BEFORE UPDATE OR DELETE ON event_acknowledgment
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER event_no_truncate BEFORE TRUNCATE ON event
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
CREATE TRIGGER event_transition_no_truncate BEFORE TRUNCATE ON event_transition
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
CREATE TRIGGER lightweight_change_no_truncate BEFORE TRUNCATE ON lightweight_change
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
CREATE TRIGGER event_acknowledgment_no_truncate BEFORE TRUNCATE ON event_acknowledgment
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

-- Every delay, repeat and escalation, mirrored from monitor-core's scheduler. After a
-- restart, pending ones are marked abandoned: incomplete timers restart from zero (MNT-02).
CREATE TABLE scheduled_action (
    id          uuid PRIMARY KEY,
    key         text NOT NULL,                           -- e.g. P02.V1:hmi:delay
    kind        text NOT NULL,
    event_id    uuid REFERENCES event (id),
    due_at      timestamptz NOT NULL,
    created_at  timestamptz NOT NULL,
    status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'cancelled', 'abandoned')),
    finished_at timestamptz
);

CREATE UNIQUE INDEX scheduled_action_one_pending ON scheduled_action (key) WHERE status = 'pending';

-- When monitoring stopped judging, and why (OPC-03, OPC-08, ADR-0010)
CREATE TABLE pause_period (
    id         uuid PRIMARY KEY,
    scope      text NOT NULL CHECK (scope IN ('line', 'actual')),  -- line: the snapshot gate; actual: machine stopped
    started_at timestamptz NOT NULL,
    ended_at   timestamptz,
    reasons    jsonb NOT NULL,
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE FUNCTION pause_period_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.ended_at IS NULL AND NEW.ended_at IS NOT NULL
       AND to_jsonb(NEW) - 'ended_at' = to_jsonb(OLD) - 'ended_at' THEN
        RETURN NEW;  -- closing a pause that is still open
    END IF;
    RAISE EXCEPTION 'pause_period is append-only: only an open pause can be ended'
        USING ERRCODE = 'restrict_violation';
END
$$;

CREATE TRIGGER pause_period_guard BEFORE UPDATE OR DELETE ON pause_period
    FOR EACH ROW EXECUTE FUNCTION pause_period_guard();

-- The outbox (NOT-03): written in the same transaction as the event change. The notifier
-- (Phase 2) delivers it; the dedup key blocks duplicate notifications after a restart (MNT-02).
CREATE TABLE notification (
    id         uuid PRIMARY KEY,
    dedup_key  text NOT NULL UNIQUE,
    kind       text NOT NULL CHECK (kind IN ('initial', 'escalated', 'recovery', 'critical_repeat',
                                             'critical_escalation', 'superseded', 'changeover', 'system')),
    event_id   uuid REFERENCES event (id),
    created_at timestamptz NOT NULL,
    payload    jsonb NOT NULL,
    status     text NOT NULL DEFAULT 'pending'
);

CREATE TABLE monitor_heartbeat (
    instance   text PRIMARY KEY,
    started_at timestamptz NOT NULL,
    beat_at    timestamptz NOT NULL,
    status     jsonb NOT NULL
);
