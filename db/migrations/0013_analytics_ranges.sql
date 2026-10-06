-- 0013 Analytics-valid ranges, versioned (ANA-10/11, SDD §9.3, ADR-0029).
--
-- An Administrator uploads the ranges CSV: one row per register parameter, accepted or rejected as a
-- whole. Each accepted file is a version, kept as uploaded with its SHA-256 and the reason, and takes
-- effect through an activation like the rules, mappings and routing. Activating an older one is a
-- rollback. Nothing here is ever changed or deleted.

CREATE TABLE analytics_range_version (
    id                  uuid PRIMARY KEY,
    number              integer NOT NULL UNIQUE CHECK (number > 0),
    register_version_id uuid NOT NULL REFERENCES register_version (id),  -- what its units were checked against
    source              text NOT NULL,     -- the file's name as uploaded
    original            bytea NOT NULL,    -- the file exactly as uploaded (ANA-11)
    sha256              text NOT NULL,     -- of `original`
    created_at          timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by          text,
    reason              text NOT NULL
);
CREATE TRIGGER analytics_range_version_append_only BEFORE UPDATE OR DELETE ON analytics_range_version
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER analytics_range_version_no_truncate BEFORE TRUNCATE ON analytics_range_version
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

-- The file's rows, as read from it: what queries use
CREATE TABLE analytics_range (
    version_id   uuid NOT NULL REFERENCES analytics_range_version (id),
    parameter_id text NOT NULL,
    unit         text,
    valid_min    double precision NOT NULL,
    valid_max    double precision NOT NULL CHECK (valid_min < valid_max),
    PRIMARY KEY (version_id, parameter_id)
);
CREATE TRIGGER analytics_range_append_only BEFORE UPDATE OR DELETE ON analytics_range
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER analytics_range_no_truncate BEFORE TRUNCATE ON analytics_range
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

CREATE TABLE analytics_range_activation (
    id                         uuid PRIMARY KEY,
    analytics_range_version_id uuid NOT NULL REFERENCES analytics_range_version (id),
    effective_at               timestamptz NOT NULL,
    created_at                 timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by                 text,
    reason                     text NOT NULL,
    cancelled_at               timestamptz,
    cancelled_by               text,
    cancel_reason              text,
    CHECK ((cancelled_at IS NULL) = (cancel_reason IS NULL))
);
CREATE INDEX analytics_range_activation_in_effect ON analytics_range_activation (effective_at DESC, created_at DESC)
    WHERE cancelled_at IS NULL;
CREATE TRIGGER analytics_range_activation_guard BEFORE UPDATE OR DELETE ON analytics_range_activation
    FOR EACH ROW EXECUTE FUNCTION activation_guard();
CREATE TRIGGER analytics_range_activation_no_truncate BEFORE TRUNCATE ON analytics_range_activation
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

CREATE FUNCTION active_analytics_range_version(at_time timestamptz DEFAULT clock_timestamp()) RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT analytics_range_version_id FROM analytics_range_activation
     WHERE cancelled_at IS NULL AND effective_at <= at_time
     ORDER BY effective_at DESC, created_at DESC
     LIMIT 1
$$;

GRANT SELECT, INSERT ON analytics_range_version, analytics_range TO centerline_app;
GRANT SELECT, INSERT, UPDATE ON analytics_range_activation TO centerline_app;
