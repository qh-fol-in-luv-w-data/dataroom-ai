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
