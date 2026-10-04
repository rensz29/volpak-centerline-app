-- 0001 Configuration: audit log, SKUs, register versions and monitoring rules (ADR-0012).
--
-- Configuration history is append-only (DAT-01): every change inserts rows, and
-- triggers refuse UPDATE, DELETE and TRUNCATE. The two exceptions are SKU names
-- (reference data) and cancelling an activation that hasn't happened yet.
-- The application runs at READ COMMITTED, which the audit chain relies on.

CREATE FUNCTION refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END
$$;

-- Audit log -------------------------------------------------------------------
-- Hash-chained (SDD §9): each row's hash covers its content and the previous
-- row's hash, so an edited or missing row breaks the chain (audit_log_verify).

CREATE TABLE audit_log (
    seq       bigint PRIMARY KEY,           -- set by the trigger, in commit order
    id        uuid NOT NULL UNIQUE,
    at        timestamptz NOT NULL,
    actor     text,                         -- NULL until login exists (Phase 1)
    action    text NOT NULL,
    summary   text NOT NULL,
    reason    text,
    details   jsonb NOT NULL DEFAULT '{}'::jsonb,
    prev_hash text,
    hash      text NOT NULL
);

CREATE FUNCTION audit_log_digest(r audit_log) RETURNS text LANGUAGE sql STABLE AS $$
    SELECT encode(sha256(convert_to(concat_ws(E'\n',
        r.seq::text, r.id::text,
        to_char(r.at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        coalesce(r.actor, ''), r.action, r.summary, coalesce(r.reason, ''),
        r.details::text, coalesce(r.prev_hash, '')), 'UTF8')), 'hex')
$$;

CREATE FUNCTION audit_log_chain() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    last_seq  bigint;
    last_hash text;
BEGIN
    -- One writer at a time; held to commit, so the next writer sees this row
    PERFORM pg_advisory_xact_lock(hashtext('centerline.audit_log'));
    SELECT seq, hash INTO last_seq, last_hash FROM audit_log ORDER BY seq DESC LIMIT 1;
    NEW.seq := coalesce(last_seq, 0) + 1;
    NEW.at := coalesce(NEW.at, clock_timestamp());  -- given only when importing older entries
    NEW.prev_hash := last_hash;
    NEW.hash := audit_log_digest(NEW);
    RETURN NEW;
END
$$;

-- The first row whose chain doesn't hold, or NULL when the whole log is intact.
CREATE FUNCTION audit_log_verify() RETURNS bigint LANGUAGE plpgsql STABLE AS $$
DECLARE
    r        audit_log;
    prev     text := NULL;
    expected bigint := 1;
BEGIN
    FOR r IN SELECT * FROM audit_log ORDER BY seq LOOP
        IF r.seq <> expected OR r.prev_hash IS DISTINCT FROM prev OR r.hash <> audit_log_digest(r) THEN
            RETURN r.seq;
        END IF;
        prev := r.hash;
        expected := expected + 1;
    END LOOP;
    RETURN NULL;
END
$$;

CREATE TRIGGER audit_log_chain BEFORE INSERT ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_chain();
CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

-- SKUs ------------------------------------------------------------------------
-- Reference data (SDD §9). The code is what the machine publishes (O-15).

CREATE TABLE sku (
    code       text PRIMARY KEY CHECK (code ~ '^[A-Za-z0-9][A-Za-z0-9._/-]{0,39}$'),
    name       text NOT NULL CHECK (btrim(name) <> '' AND length(name) <= 120),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Parameter register ------------------------------------------------------------
-- Each save on the Tags tab is a new row (ADR-0007, ADR-0011). The latest is current.

CREATE TABLE register_version (
    seq        bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    id         uuid PRIMARY KEY,
    number     text NOT NULL UNIQUE,        -- <Manila date>.<n>, e.g. 2026-09-29.3
    content    jsonb NOT NULL,
    sha256     text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by text,
    reason     text NOT NULL
);

CREATE TRIGGER register_version_append_only BEFORE UPDATE OR DELETE ON register_version
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER register_version_no_truncate BEFORE TRUNCATE ON register_version
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

-- Monitoring rules ----------------------------------------------------------------
-- A version is written once, with its rules, in one transaction; sha256 covers
-- both and is checked on every read. Versions take effect through activations.

CREATE TABLE config_version (
    id                  uuid PRIMARY KEY,
    number              integer NOT NULL UNIQUE CHECK (number > 0),
    based_on_id         uuid REFERENCES config_version (id),
    register_version_id uuid NOT NULL REFERENCES register_version (id),
    settings            jsonb NOT NULL,     -- line-wide: stop pause, default delays and handling
    sha256              text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by          text,
    reason              text NOT NULL
);

-- One row per scope. NULL SKU = every SKU; NULL zone = every zone of the parameter.
-- A NULL field is inherited from a wider scope (centerline_common/rules.py).
CREATE TABLE sku_parameter_rule (
    config_version_id     uuid NOT NULL REFERENCES config_version (id),
    sku_code              text REFERENCES sku (code),
    parameter_id          text NOT NULL,
    zone_id               text,
    target                numeric,
    warn_low              numeric CHECK (warn_low >= 0),   -- offsets around the HMI setpoint (A-02)
    warn_high             numeric CHECK (warn_high >= 0),
    crit_low              numeric CHECK (crit_low >= 0),
    crit_high             numeric CHECK (crit_high >= 0),
    mismatch_delay_s      integer CHECK (mismatch_delay_s BETWEEN 0 AND 3600),
    warning_delay_s       integer CHECK (warning_delay_s BETWEEN 0 AND 3600),  -- also Critical → Warning (ACT-02)
    critical_delay_s      integer CHECK (critical_delay_s BETWEEN 0 AND 3600),
    recovery_delay_s      integer CHECK (recovery_delay_s BETWEEN 0 AND 3600),
    brief_change_mode     text CHECK (brief_change_mode IN ('do_not_record', 'lightweight', 'cleared_before_trigger')),
    warning_notifications boolean,
    CONSTRAINT one_rule_per_scope UNIQUE NULLS NOT DISTINCT (config_version_id, sku_code, parameter_id, zone_id)
);

CREATE TRIGGER config_version_append_only BEFORE UPDATE OR DELETE ON config_version
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER config_version_no_truncate BEFORE TRUNCATE ON config_version
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
CREATE TRIGGER sku_parameter_rule_append_only BEFORE UPDATE OR DELETE ON sku_parameter_rule
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER sku_parameter_rule_no_truncate BEFORE TRUNCATE ON sku_parameter_rule
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

-- Activations: immediate or scheduled (OPC-07). The active version at any time is
-- the latest activation in effect; activating an older version is a rollback.
CREATE TABLE config_activation (
    id                uuid PRIMARY KEY,
    config_version_id uuid NOT NULL REFERENCES config_version (id),
    effective_at      timestamptz NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by        text,
    reason            text NOT NULL,
    cancelled_at      timestamptz,
    cancelled_by      text,
    cancel_reason     text,
    CHECK ((cancelled_at IS NULL) = (cancel_reason IS NULL))
);

CREATE INDEX config_activation_in_effect ON config_activation (effective_at DESC, created_at DESC)
    WHERE cancelled_at IS NULL;

CREATE FUNCTION config_activation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.cancelled_at IS NULL AND NEW.cancelled_at IS NOT NULL
       AND OLD.effective_at > clock_timestamp()
       AND (NEW.id, NEW.config_version_id, NEW.effective_at, NEW.created_at, NEW.created_by, NEW.reason)
           IS NOT DISTINCT FROM (OLD.id, OLD.config_version_id, OLD.effective_at, OLD.created_at, OLD.created_by, OLD.reason)
    THEN
        RETURN NEW;  -- cancelling an activation that is still scheduled
    END IF;
    RAISE EXCEPTION 'config_activation is append-only: only a scheduled activation can be cancelled'
        USING ERRCODE = 'restrict_violation';
END
$$;

CREATE TRIGGER config_activation_guard BEFORE UPDATE OR DELETE ON config_activation
    FOR EACH ROW EXECUTE FUNCTION config_activation_guard();
CREATE TRIGGER config_activation_no_truncate BEFORE TRUNCATE ON config_activation
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

-- The version in effect at a given time; NULL before the first activation.
CREATE FUNCTION active_config_version(at_time timestamptz DEFAULT clock_timestamp()) RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT config_version_id FROM config_activation
     WHERE cancelled_at IS NULL AND effective_at <= at_time
     ORDER BY effective_at DESC, created_at DESC
     LIMIT 1
$$;
