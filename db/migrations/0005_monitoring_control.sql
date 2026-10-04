-- 0005 Monitoring control: switching zones off (MON-01) and maintenance windows (MNT-01), ADR-0017.
--
-- A Manager switches a zone's monitoring off or on again; every switch is a row, so the history
-- is kept and the latest row per zone is its state. Switching off closes the zone's open event
-- as "Monitoring disabled" with no recovery notice. An Administrator opens, extends and ends
-- maintenance windows for the whole line or chosen zones; judging stops inside them.

-- Every switch, off or on again. A zone is off while its latest row says so.
CREATE TABLE monitoring_switch (
    seq      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id       uuid NOT NULL UNIQUE,
    channel  text NOT NULL,                              -- P02.V3: a zone of the register
    enabled  boolean NOT NULL,                           -- false: monitoring switched off
    at       timestamptz NOT NULL DEFAULT clock_timestamp(),
    by_user  text NOT NULL,
    reason   text,
    CONSTRAINT a_reason_to_switch_off CHECK (enabled OR btrim(coalesce(reason, '')) <> '')
);

CREATE INDEX monitoring_switch_latest ON monitoring_switch (channel, seq DESC);
CREATE TRIGGER monitoring_switch_append_only BEFORE UPDATE OR DELETE ON monitoring_switch
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER monitoring_switch_no_truncate BEFORE TRUNCATE ON monitoring_switch
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

-- Maintenance windows. One is in force from its planned start until it's ended. Past its planned
-- end it stays in force as overdue (the work may not be done) until an Administrator ends it.
CREATE TABLE maintenance_window (
    id            uuid PRIMARY KEY,
    scope         text NOT NULL CHECK (scope IN ('line', 'zones')),
    channels      text[] NOT NULL DEFAULT '{}',          -- the zones, when the scope is zones
    reason        text NOT NULL CHECK (btrim(reason) <> ''),
    planned_start timestamptz NOT NULL,
    planned_end   timestamptz NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by    text NOT NULL,
    ended_at      timestamptz,                            -- before the planned start: cancelled
    ended_by      text,
    CONSTRAINT window_has_zones CHECK (scope = 'line' OR cardinality(channels) > 0),
    CONSTRAINT window_ends_after_it_starts CHECK (planned_end > planned_start)
);

CREATE INDEX maintenance_window_open ON maintenance_window (planned_start) WHERE ended_at IS NULL;

-- Only the planned end may move, and only while the window is open; ending happens once.
-- Every change is also in the audit log, with who and why.
CREATE FUNCTION maintenance_window_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.ended_at IS NULL
       AND to_jsonb(NEW) - 'planned_end' - 'ended_at' - 'ended_by' = to_jsonb(OLD) - 'planned_end' - 'ended_at' - 'ended_by'
       AND (NEW.ended_at IS NULL) = (NEW.ended_by IS NULL) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'maintenance_window: only an open window can be extended or ended'
        USING ERRCODE = 'restrict_violation';
END
$$;

CREATE TRIGGER maintenance_window_guard BEFORE UPDATE OR DELETE ON maintenance_window
    FOR EACH ROW EXECUTE FUNCTION maintenance_window_guard();

-- Switching a zone off closes its open event as "Monitoring disabled" (MON-01)
ALTER TABLE event_transition DROP CONSTRAINT event_transition_state_check;
ALTER TABLE event_transition ADD CONSTRAINT event_transition_state_check
    CHECK (state IN ('OPEN', 'WARNING', 'CRITICAL', 'RESOLVED', 'SUPERSEDED', 'CLOSED_SKU_CHANGEOVER',
                     'CLOSED_MONITORING_DISABLED', 'ACKNOWLEDGED'));
