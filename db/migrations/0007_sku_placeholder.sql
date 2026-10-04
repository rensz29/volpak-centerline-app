-- 0007 A placeholder SKU in a mapping version, ADR-0022.
--
-- While the machine doesn't publish its SKU (O-15), an Administrator can name a placeholder
-- code in its place. monitor-core then judges the line under that code on actual values only:
-- Warning and Critical against the setpoint, no HMI mismatch, since there are no targets.
-- A version has the machine's SKU field or a placeholder, never both. Existing versions keep
-- neither, and their content hashes don't change.

ALTER TABLE mapping_version
    ADD COLUMN sku_placeholder text
        CHECK (sku_placeholder IS NULL
               OR (sku_topic IS NULL AND sku_placeholder ~ '^[A-Za-z0-9][A-Za-z0-9._/-]{0,39}$'));
