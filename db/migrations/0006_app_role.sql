-- 0006 The services' database role (ADR-0020): least privilege for the api and monitor-core.
--
-- They connect as centerline_app. It isn't a superuser, so it can't switch triggers off
-- (session_replication_role), and it owns nothing, so it can't change the schema or truncate.
-- On evidence it may only add and read; the append-only triggers stay a second line. Only
-- operational rows (projections, timers, sessions, accounts, windows) may be updated, and only
-- sessions, sign-in names and unused SKUs deleted. The migrations keep running as the owner.
-- The role is the cluster's, so it's made once; its password is set from a secret file by
-- `python -m centerline_common.roles` (never in a migration).

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'centerline_app') THEN
        CREATE ROLE centerline_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO centerline_app', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO centerline_app;
GRANT SELECT ON schema_migration TO centerline_app;

-- Evidence and versions: added and read, never changed (DAT-01)
GRANT SELECT, INSERT ON audit_log, register_version, config_version, sku_parameter_rule, mapping_version, tag_mapping,
                        event, event_transition, lightweight_change, event_acknowledgment, notification,
                        app_user_password, monitoring_switch
    TO centerline_app;

-- Also updated: activations (only cancelling, the triggers say) and the operational rows
GRANT SELECT, INSERT, UPDATE ON config_activation, mapping_activation, event_state, scheduled_action, pause_period,
                                monitor_heartbeat, app_user, maintenance_window
    TO centerline_app;

-- Also deleted: a SKU no version uses, a session ended, an account's sign-in names (rewritten by their trigger)
GRANT SELECT, INSERT, UPDATE, DELETE ON sku, app_session TO centerline_app;
GRANT SELECT, INSERT, DELETE ON app_user_login TO centerline_app;

GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO centerline_app;
