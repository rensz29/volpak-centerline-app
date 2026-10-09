-- 0022 The OCAP search by meaning (OCP-01, LAN-01, AI-01, ADR-0048).
--
-- The embedding model turns each chunk of the Active OCAP versions into a vector, once, in the background; a search
-- embeds what the operator wrote (English, Filipino or Taglish) and finds the chunks nearest in meaning. That ranking
-- is merged with the keyword search's; with the model off or slow, the keyword search answers alone. A chunk is
-- embedded again only for another model or digest. The vectors have the model's own length (bge-m3: 1024), so the
-- column takes any; a search compares only those of the model in use.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE ocap_chunk_embedding (
    chunk_id     uuid NOT NULL REFERENCES ocap_chunk (id),
    model        text NOT NULL,
    model_digest text NOT NULL,
    embedding    vector NOT NULL,
    at           timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (chunk_id, model, model_digest)
);

CREATE TRIGGER ocap_chunk_embedding_append_only BEFORE UPDATE OR DELETE ON ocap_chunk_embedding
    FOR EACH ROW EXECUTE FUNCTION refuse_change();
CREATE TRIGGER ocap_chunk_embedding_no_truncate BEFORE TRUNCATE ON ocap_chunk_embedding
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();

GRANT SELECT, INSERT ON ocap_chunk_embedding TO centerline_app;

-- The sections offered: found by keywords and meaning together
ALTER TABLE ocap_recommendation DROP CONSTRAINT ocap_recommendation_method_check;
ALTER TABLE ocap_recommendation ADD CONSTRAINT ocap_recommendation_method_check CHECK (method IN ('keyword', 'reason', 'hybrid'));
