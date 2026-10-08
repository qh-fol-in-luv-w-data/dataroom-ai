-- Schema for the Data Room AI demo. Idempotent: safe to run on every start.
-- dr_admin (cluster superuser) owns everything; app_query is the only role the
-- answer path uses and it can never bypass row-level security.

CREATE TABLE IF NOT EXISTS sites (
    site_id   text PRIMARY KEY,
    name      text NOT NULL,
    rac_groups text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS items (
    item_id     text PRIMARY KEY,
    site_id     text NOT NULL,
    path        text NOT NULL,
    name        text NOT NULL,
    ext         text NOT NULL,
    ctag        text NOT NULL,
    etag        text NOT NULL,
    ai_use      text NOT NULL DEFAULT 'Excluded',
    label       text,
    encrypted   boolean NOT NULL DEFAULT false,
    malware     boolean NOT NULL DEFAULT false,
    size        bigint NOT NULL DEFAULT 0,
    status      text NOT NULL DEFAULT 'pending',   -- pending | indexed | skipped | error
    reason      text,
    ingested_ctag text,
    chunk_count integer NOT NULL DEFAULT 0,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id       bigserial PRIMARY KEY,
    item_id        text NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
    site_id        text NOT NULL,
    ctag           text NOT NULL,
    is_current     boolean NOT NULL DEFAULT true,
    ordinal        integer NOT NULL,
    locator        text NOT NULL,
    kind           text NOT NULL DEFAULT 'text',
    text           text NOT NULL,
    text_folded    text NOT NULL,
    injection_flag boolean NOT NULL DEFAULT false,
    ocr            boolean NOT NULL DEFAULT false,
    converter      text NOT NULL,
    embedding      real[]
);
CREATE INDEX IF NOT EXISTS chunks_item_idx ON chunks(item_id);

-- Mirror of SharePoint grants (resolved per item) and Entra memberships.
CREATE TABLE IF NOT EXISTS grants (
    item_id        text NOT NULL,
    principal_kind text NOT NULL,   -- group | user | link_specific | link_anyone | link_org
    principal_id   text NOT NULL,
    source         text NOT NULL,   -- inherited:<path> | unique
    PRIMARY KEY (item_id, principal_kind, principal_id)
);
CREATE TABLE IF NOT EXISTS memberships (
    group_id text NOT NULL,
    oid      text NOT NULL,
    PRIMARY KEY (group_id, oid)
);
CREATE TABLE IF NOT EXISTS user_roles (
    oid  text NOT NULL,
    role text NOT NULL,
    PRIMARY KEY (oid, role)
);
CREATE TABLE IF NOT EXISTS users_mirror (
    oid     text PRIMARY KEY,
    enabled boolean NOT NULL
);
-- Per-(oid, group) revocation set: grant paths through these groups are ignored
-- until SharePoint is known to have applied the change.
CREATE TABLE IF NOT EXISTS revocations (
    oid        text NOT NULL,
    group_id   text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    until      timestamptz NOT NULL,
    PRIMARY KEY (oid, group_id)
);
CREATE TABLE IF NOT EXISTS deny_list (
    oid        text PRIMARY KEY,
    reason     text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS feed_status (
    feed    text PRIMARY KEY,
    last_ok timestamptz NOT NULL,
    detail  text
);
-- Effective readers (the RLS source). Rebuilt by the connector.
CREATE TABLE IF NOT EXISTS item_reader (
    item_id  text NOT NULL,
    oid      text NOT NULL,
    via_kind text NOT NULL,
    via_id   text NOT NULL,
    PRIMARY KEY (item_id, oid, via_kind, via_id)
);
CREATE INDEX IF NOT EXISTS item_reader_oid_idx ON item_reader(oid);

CREATE TABLE IF NOT EXISTS audit (
    seq       bigserial PRIMARY KEY,
    ts        timestamptz NOT NULL DEFAULT clock_timestamp(),
    oid       text,
    kind      text NOT NULL,
    payload   jsonb NOT NULL,
    prev_hash text NOT NULL,
    row_hash  text NOT NULL
);

-- ---------------------------------------------------------------- roles / grants
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_query') THEN
        CREATE ROLE app_query LOGIN NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM app_query;
GRANT USAGE ON SCHEMA public TO app_query;
GRANT SELECT ON sites, items, chunks, item_reader TO app_query;

ALTER TABLE items       ENABLE ROW LEVEL SECURITY;
ALTER TABLE items       FORCE ROW LEVEL SECURITY;
ALTER TABLE chunks      ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks      FORCE ROW LEVEL SECURITY;
ALTER TABLE item_reader ENABLE ROW LEVEL SECURITY;
ALTER TABLE item_reader FORCE ROW LEVEL SECURITY;
ALTER TABLE sites       ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sites_all ON sites;
CREATE POLICY sites_all ON sites FOR SELECT TO app_query USING (true);

-- The admin (owner) path needs to see everything; FORCE would otherwise apply to it too.
DROP POLICY IF EXISTS items_admin ON items;
CREATE POLICY items_admin ON items TO dr_admin USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS chunks_admin ON chunks;
CREATE POLICY chunks_admin ON chunks TO dr_admin USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS reader_admin ON item_reader;
CREATE POLICY reader_admin ON item_reader TO dr_admin USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS reader_self ON item_reader;
CREATE POLICY reader_self ON item_reader FOR SELECT TO app_query
    USING (oid = current_setting('app.principal_oid', true));

DROP POLICY IF EXISTS items_readable ON items;
CREATE POLICY items_readable ON items FOR SELECT TO app_query
    USING (EXISTS (SELECT 1 FROM item_reader r
                   WHERE r.item_id = items.item_id
                     AND r.oid = current_setting('app.principal_oid', true)));

DROP POLICY IF EXISTS chunks_readable ON chunks;
CREATE POLICY chunks_readable ON chunks FOR SELECT TO app_query
    USING (chunks.is_current
           AND EXISTS (SELECT 1 FROM items i
                       WHERE i.item_id = chunks.item_id
                         AND i.ctag = chunks.ctag
                         AND i.ai_use IN ('Allowed', 'OnPremOnly')
                         AND NOT i.encrypted
                         AND NOT i.malware));
-- items_readable already applies to the items sub-select above (policies are
-- evaluated for referenced tables as the invoking role), so a chunk is visible
-- only if its item is readable by the principal.

-- ---------------------------------------------------------------- definer helpers
CREATE OR REPLACE FUNCTION me_denied() RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT EXISTS (SELECT 1 FROM deny_list WHERE oid = current_setting('app.principal_oid', true))
        OR NOT COALESCE((SELECT enabled FROM users_mirror
                         WHERE oid = current_setting('app.principal_oid', true)), false);
$$;

CREATE OR REPLACE FUNCTION me_has_role(r text) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT EXISTS (SELECT 1 FROM user_roles
                   WHERE oid = current_setting('app.principal_oid', true) AND role = r);
$$;

CREATE OR REPLACE FUNCTION feed_age(f text) RETURNS double precision
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT COALESCE(EXTRACT(EPOCH FROM clock_timestamp() - last_ok), 1e9)::double precision
    FROM (SELECT max(last_ok) AS last_ok FROM feed_status WHERE feed = f) s;
$$;

CREATE OR REPLACE FUNCTION audit_append(p_oid text, p_kind text, p_payload jsonb) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_prev text;
    v_ts   timestamptz := clock_timestamp();
    v_hash text;
    v_seq  bigint;
BEGIN
    PERFORM pg_advisory_xact_lock(424242);
    SELECT row_hash INTO v_prev FROM audit ORDER BY seq DESC LIMIT 1;
    v_prev := COALESCE(v_prev, repeat('0', 64));
    v_hash := encode(sha256(convert_to(
        v_prev || '|' || to_char(v_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US') || '|'
        || COALESCE(p_oid, '') || '|' || p_kind || '|' || p_payload::text, 'UTF8')), 'hex');
    INSERT INTO audit(ts, oid, kind, payload, prev_hash, row_hash)
    VALUES (v_ts, p_oid, p_kind, p_payload, v_prev, v_hash)
    RETURNING seq INTO v_seq;
    RETURN v_seq;
END $$;

REVOKE ALL ON FUNCTION audit_append(text, text, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION me_denied(), me_has_role(text), feed_age(text),
                          audit_append(text, text, jsonb) TO app_query;

-- ---------------------------------------------------------------- in-database search (pgvector + BM25)
-- Retrieval runs as app_query, so row-level security filters candidates inside the
-- search query itself: no list of allowed ids is ever materialised in the app.
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS emb  halfvec(1024);  -- bge-m3, unit length → inner product
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv  tsvector;       -- same tokens as the BM25 tokenizer, with positions
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tlen integer;        -- token count (BM25 length normalisation)
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS ocr_doubt text[];    -- OCR numbers not confirmed by the second reader
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS ocr_page  text;      -- <sha1>/p<n>: cleaned page image for crops
CREATE INDEX IF NOT EXISTS chunks_emb_hnsw ON chunks USING hnsw (emb halfvec_ip_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin  ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_site_idx ON chunks (site_id);

-- BM25 statistics per site partition (non-interference: one group's documents never change
-- the term statistics used to rank another group's documents).
CREATE TABLE IF NOT EXISTS site_stats (
    site_id text PRIMARY KEY,
    n       bigint NOT NULL,
    avgdl   double precision NOT NULL
);
CREATE TABLE IF NOT EXISTS term_stats (
    site_id text NOT NULL,
    term    text NOT NULL,
    df      bigint NOT NULL,
    idf     double precision NOT NULL,
    PRIMARY KEY (site_id, term)
);
CREATE INDEX IF NOT EXISTS term_stats_term_idx ON term_stats (term);
GRANT SELECT ON site_stats, term_stats TO app_query;
-- Answer-path queries are short; LLVM JIT compilation costs more (≈1 s) than it saves.
ALTER ROLE app_query SET jit = off;

CREATE OR REPLACE FUNCTION refresh_term_stats() RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE site_stats, term_stats;
    INSERT INTO site_stats
        SELECT site_id, count(*), COALESCE(avg(tlen), 1) FROM chunks
        WHERE is_current AND tsv IS NOT NULL GROUP BY site_id;
    INSERT INTO term_stats
        SELECT c.site_id, u.lexeme, count(*) AS df,
               ln(1 + (s.n - count(*) + 0.5) / (count(*) + 0.5))   -- Lucene idf, always > 0
        FROM chunks c CROSS JOIN LATERAL unnest(c.tsv) u
        JOIN site_stats s ON s.site_id = c.site_id
        WHERE c.is_current AND c.tsv IS NOT NULL
        GROUP BY c.site_id, u.lexeme, s.n;
END $$;

-- Under RLS, Postgres may not use the GIN index for `tsv @@ query` (ts_match_vq is not
-- LEAKPROOF), so every row would be permission-checked first. This definer function only
-- returns candidate ids from the index; the caller's query runs as app_query, so RLS still
-- filters them, and ids the principal cannot read never leave the SQL statement.
CREATE OR REPLACE FUNCTION fts_candidates(q tsquery, cap integer) RETURNS SETOF bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT chunk_id FROM chunks WHERE tsv @@ q AND is_current LIMIT cap;
$$;
REVOKE ALL ON FUNCTION fts_candidates(tsquery, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fts_candidates(tsquery, integer) TO app_query;

-- Sensitive-question review (BRD BR-08): answers held as drafts until a reviewer decides.
-- Only the gateway (admin connection) touches this table; the reviewer's own SharePoint
-- access to every cited file is checked in code before a draft is shown or decided.
CREATE TABLE IF NOT EXISTS review_drafts (
    draft_id    bigserial PRIMARY KEY,
    oid         text NOT NULL,
    question    text NOT NULL,
    lang        text NOT NULL DEFAULT 'vi',
    topics      text[] NOT NULL,
    answer      jsonb NOT NULL,
    cited_items text[] NOT NULL,
    status      text NOT NULL DEFAULT 'pending',     -- pending | approved | rejected
    reviewer    text,
    note        text,
    edited      boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    decided_at  timestamptz
);
CREATE INDEX IF NOT EXISTS review_drafts_oid_idx ON review_drafts (oid);
