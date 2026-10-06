-- 0011 No SKU (ADR-0027).
--
-- The owner took the SKU out of Centerline on 2026-10-05: the rules give each zone its limits and its
-- target, a mapping names only tags, and nothing is judged per product. What was recorded before
-- about SKUs (rule rows, mapping fields and placeholders, the SKU on events and brief changes) stays as
-- history, in columns renamed legacy_*. Nothing reads them to judge, nothing writes them any more, and
-- the checks below refuse them from now on (NOT VALID: earlier rows keep what they hold).

-- The SKU list goes, and with it the rule rows' link to it (the codes they hold stay, as written)
DROP TABLE sku CASCADE;

-- The rules table is named for what it holds
ALTER TABLE sku_parameter_rule RENAME TO parameter_rule;
ALTER TRIGGER sku_parameter_rule_append_only ON parameter_rule RENAME TO parameter_rule_append_only;
ALTER TRIGGER sku_parameter_rule_no_truncate ON parameter_rule RENAME TO parameter_rule_no_truncate;

ALTER TABLE parameter_rule RENAME COLUMN sku_code TO legacy_sku_code;
ALTER TABLE parameter_rule ADD CONSTRAINT parameter_rule_no_sku CHECK (legacy_sku_code IS NULL) NOT VALID;

ALTER TABLE mapping_version RENAME COLUMN sku_topic TO legacy_sku_topic;
ALTER TABLE mapping_version RENAME COLUMN sku_field TO legacy_sku_field;
ALTER TABLE mapping_version RENAME COLUMN sku_placeholder TO legacy_sku_placeholder;
ALTER TABLE mapping_version ADD CONSTRAINT mapping_version_no_sku
    CHECK (legacy_sku_topic IS NULL AND legacy_sku_field IS NULL AND legacy_sku_placeholder IS NULL) NOT VALID;

ALTER TABLE event RENAME COLUMN sku_code TO legacy_sku_code;
ALTER TABLE event ALTER COLUMN legacy_sku_code DROP NOT NULL;
ALTER TABLE event ADD CONSTRAINT event_no_sku CHECK (legacy_sku_code IS NULL) NOT VALID;

ALTER TABLE lightweight_change RENAME COLUMN sku_code TO legacy_sku_code;
ALTER TABLE lightweight_change ALTER COLUMN legacy_sku_code DROP NOT NULL;
ALTER TABLE lightweight_change ADD CONSTRAINT lightweight_change_no_sku CHECK (legacy_sku_code IS NULL) NOT VALID;

-- Nothing closes an event or sends a message for a product change any more
ALTER TABLE event_transition ADD CONSTRAINT event_transition_no_changeover CHECK (state <> 'CLOSED_SKU_CHANGEOVER') NOT VALID;
ALTER TABLE notification ADD CONSTRAINT notification_no_changeover CHECK (kind <> 'changeover') NOT VALID;
