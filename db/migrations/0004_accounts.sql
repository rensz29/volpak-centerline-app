-- 0004 Accounts and sessions: who may do what, checked by the api on every call (ADR-0016).
--
-- IAM-01…04, SES-01…04. Passwords are Argon2id hashes; a session's token lives only in the
-- browser's cookie and is stored here as a SHA-256 hash. Accounts are never deleted, only
-- disabled, because the audit log and the events name them. Sessions are server-side (DD-06):
-- deleting a row signs that browser out at its next request.

CREATE TABLE app_user (
    id              uuid PRIMARY KEY,
    username        text NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9][a-z0-9._-]{1,63}$'),
    display_name    text NOT NULL CHECK (btrim(display_name) <> ''),
    email           text,
    employee_id     text,
    -- Manager and Administrator may be combined; an Operator account is only that (SES-01…04 differ)
    roles           text[] NOT NULL CHECK (cardinality(roles) >= 1
                                           AND roles <@ ARRAY['OPERATOR', 'MANAGER', 'ADMINISTRATOR']
                                           AND (NOT 'OPERATOR' = ANY (roles) OR cardinality(roles) = 1)),
    active          boolean NOT NULL DEFAULT true,
    password_hash   text NOT NULL,                  -- Argon2id (IAM-03)
    must_change     boolean NOT NULL DEFAULT true,  -- a temporary password: changed at first sign-in
    temp_expires_at timestamptz,                    -- a temporary password stops working after 24 h
    failed_count    integer NOT NULL DEFAULT 0,     -- failed sign-ins in a row; 5 lock the account for 15 min
    locked_until    timestamptz,
    last_sign_in_at timestamptz,
    created_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at      timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Every name someone can sign in with: the username, the email and the Employee ID, unique
-- case-insensitively across all three, so a name always means one account (IAM-02).
CREATE TABLE app_user_login (
    name    text PRIMARY KEY CHECK (name = lower(name) AND name <> ''),
    user_id uuid NOT NULL REFERENCES app_user (id),
    kind    text NOT NULL CHECK (kind IN ('username', 'email', 'employee_id'))
);

CREATE FUNCTION app_user_logins() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM app_user_login WHERE user_id = NEW.id;
    -- A name used twice by the same account counts once; used by another account, the insert fails
    INSERT INTO app_user_login (name, user_id, kind)
    SELECT DISTINCT ON (n.name) n.name, NEW.id, n.kind
      FROM (VALUES (lower(btrim(NEW.username)), 'username', 1), (lower(btrim(NEW.email)), 'email', 2),
                   (lower(btrim(NEW.employee_id)), 'employee_id', 3)) AS n (name, kind, rank)
     WHERE n.name IS NOT NULL AND n.name <> ''
     ORDER BY n.name, n.rank;
    RETURN NEW;
END
$$;

CREATE TRIGGER app_user_logins AFTER INSERT OR UPDATE OF username, email, employee_id ON app_user
    FOR EACH ROW EXECUTE FUNCTION app_user_logins();

-- The audit log and the events refer to the username, so it never changes
CREATE FUNCTION app_user_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.username <> OLD.username THEN
        RAISE EXCEPTION 'a username never changes: the audit log refers to it' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER app_user_guard BEFORE UPDATE ON app_user FOR EACH ROW EXECUTE FUNCTION app_user_guard();
CREATE TRIGGER app_user_no_delete BEFORE DELETE ON app_user FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- Every password an account has had, so the last five can't be used again (IAM-03)
CREATE TABLE app_user_password (
    user_id uuid NOT NULL REFERENCES app_user (id),
    set_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
    hash    text NOT NULL,
    PRIMARY KEY (user_id, set_at)
);

CREATE TABLE app_session (
    id             uuid PRIMARY KEY,
    token_sha256   text NOT NULL UNIQUE,
    user_id        uuid NOT NULL REFERENCES app_user (id),
    kind           text NOT NULL CHECK (kind IN ('operator', 'privileged')),
    ip             text NOT NULL,                                 -- as the api saw it (behind the proxy: X-Forwarded-For)
    workstation    text,                                          -- the operator workstation's name (SES-04)
    user_agent     text,
    created_at     timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_seen_at   timestamptz NOT NULL DEFAULT clock_timestamp(),  -- any request: the heartbeat (SES-04)
    last_active_at timestamptz NOT NULL DEFAULT clock_timestamp()   -- the person's own activity (SES-02)
);

CREATE INDEX app_session_user ON app_session (user_id);
-- One operator session for the line (SES-01)
CREATE UNIQUE INDEX app_session_one_operator ON app_session (kind) WHERE kind = 'operator';

-- The Critical period an acknowledgment belongs to (the count of the event's Critical
-- transitions when it was given): a new Critical period needs a new one (ACT-04, ADR-0016).
ALTER TABLE event_acknowledgment ADD COLUMN critical_period integer;
