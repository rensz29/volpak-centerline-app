-- 0012 Idempotency keys (SDD §11, ADR-0028).
--
-- Every POST that creates a record carries an Idempotency-Key. The api claims the key before the request
-- runs and keeps the answer, so a repeat (a retry after a lost answer, a second click) gets the same answer
-- instead of making a second record. A key is one session's: another browser can't replay it.
--
-- Not evidence: a row is kept 24 h and then removed, so the services' role may update and delete it.

CREATE TABLE idempotency_key (
    session_hash text NOT NULL,                 -- the session's app_session.token_sha256
    key          text NOT NULL CHECK (length(key) BETWEEN 1 AND 255),
    fingerprint  text NOT NULL,                 -- SHA-256 of the method, path, query and body
    created_at   timestamptz NOT NULL DEFAULT now(),
    status       integer,                       -- NULL while the first request is running
    content_type text,
    body         bytea,                         -- NULL too when the answer held a temporary password
    PRIMARY KEY (session_hash, key)
);
CREATE INDEX idempotency_key_created ON idempotency_key (created_at);

GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_key TO centerline_app;
