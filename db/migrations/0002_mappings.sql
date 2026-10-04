-- 0002 Tag mappings: where each register tag arrives on MQTT (OPC-06, OPC-07, ADR-0013).
--
-- The same pattern as the rules in 0001: a version is written once with its rows,
-- activations are appended, and history can't be changed or removed.

CREATE TABLE mapping_version (
    id                  uuid PRIMARY KEY,
    number              integer NOT NULL UNIQUE CHECK (number > 0),
    based_on_id         uuid REFERENCES mapping_version (id),
    register_version_id uuid NOT NULL REFERENCES register_version (id),
    sku_topic           text,                -- where the running SKU arrives, once the edge team adds it (O-15)
    sku_field           text,
    source              text NOT NULL,       -- where the rows came from: the broker, a file, by hand
    sha256              text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by          text,
    reason              text NOT NULL,
    CHECK ((sku_topic IS NULL) = (sku_field IS NULL))
);

-- One row per register tag. field NULL: the whole payload is the value.
CREATE TABLE tag_mapping (
    mapping_version_id uuid NOT NULL REFERENCES mapping_version (id),
    tag                text NOT NULL,        -- relative to the namespace, e.g. SPC.SetPointTemperatureVertical1
    topic              text NOT NULL CHECK (topic <> '' AND topic !~ '[+#]'),
    field              text CHECK (field <> ''),
    PRIMARY KEY (mapping_version_id, tag),
    CONSTRAINT one_tag_per_place UNIQUE NULLS NOT DISTINCT (mapping_version_id, topic, field)
);

CREATE TRIGGER mapping_version_append_only BEFORE UPDATE OR DELETE ON mapping_version
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER mapping_version_no_truncate BEFORE TRUNCATE ON mapping_version
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
CREATE TRIGGER tag_mapping_append_only BEFORE UPDATE OR DELETE ON tag_mapping
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER tag_mapping_no_truncate BEFORE TRUNCATE ON tag_mapping
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

CREATE TABLE mapping_activation (
    id                 uuid PRIMARY KEY,
    mapping_version_id uuid NOT NULL REFERENCES mapping_version (id),
    effective_at       timestamptz NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by         text,
    reason             text NOT NULL,
    cancelled_at       timestamptz,
    cancelled_by       text,
    cancel_reason      text,
    CHECK ((cancelled_at IS NULL) = (cancel_reason IS NULL))
);

CREATE INDEX mapping_activation_in_effect ON mapping_activation (effective_at DESC, created_at DESC)
    WHERE cancelled_at IS NULL;

-- Any activation table: rows are append-only, except cancelling one that is still scheduled.
CREATE FUNCTION activation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    cancel_columns constant text[] := ARRAY['cancelled_at', 'cancelled_by', 'cancel_reason'];
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.cancelled_at IS NULL AND NEW.cancelled_at IS NOT NULL
       AND OLD.effective_at > clock_timestamp()
       AND to_jsonb(NEW) - cancel_columns = to_jsonb(OLD) - cancel_columns
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION '% is append-only: only a scheduled activation can be cancelled', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

CREATE TRIGGER mapping_activation_guard BEFORE UPDATE OR DELETE ON mapping_activation
    FOR EACH ROW EXECUTE FUNCTION activation_guard();
CREATE TRIGGER mapping_activation_no_truncate BEFORE TRUNCATE ON mapping_activation
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

CREATE FUNCTION active_mapping_version(at_time timestamptz DEFAULT clock_timestamp()) RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT mapping_version_id FROM mapping_activation
     WHERE cancelled_at IS NULL AND effective_at <= at_time
     ORDER BY effective_at DESC, created_at DESC
     LIMIT 1
$$;
