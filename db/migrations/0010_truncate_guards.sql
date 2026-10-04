-- 0010 TRUNCATE guards for the last guarded tables without one (review, 2026-10-01).
--
-- pause_period (0003) and maintenance_window (0005) refuse every UPDATE and DELETE but their one
-- allowed change (ending a pause; extending or ending a window), and app_user (0004) refuses DELETE
-- because the audit log refers to every account. Unlike the other guarded tables they didn't
-- refuse TRUNCATE, which only the owner may run. Now they do (DAT-01, RET-01).
CREATE TRIGGER pause_period_no_truncate BEFORE TRUNCATE ON pause_period
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
CREATE TRIGGER maintenance_window_no_truncate BEFORE TRUNCATE ON maintenance_window
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
CREATE TRIGGER app_user_no_truncate BEFORE TRUNCATE ON app_user
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
