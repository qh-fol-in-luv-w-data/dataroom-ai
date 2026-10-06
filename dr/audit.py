"""Append-only, hash-chained audit log (master plan §6.4).

Appends go through the SECURITY DEFINER function audit_append(), which serialises
writers with an advisory lock and computes row_hash = sha256(prev_hash | ts | oid | kind | payload).
"""
from __future__ import annotations

import json

import psycopg

from dr.config import settings
from dr.db import pg

RECOMPUTE = """
SELECT seq, prev_hash, row_hash,
       encode(sha256(convert_to(prev_hash || '|' || to_char(ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US')
              || '|' || COALESCE(oid, '') || '|' || kind || '|' || payload::text, 'UTF8')), 'hex') AS recomputed,
       COALESCE(lag(row_hash) OVER (ORDER BY seq), repeat('0', 64)) AS expected_prev
FROM audit ORDER BY seq"""


def append(oid: str | None, kind: str, payload: dict) -> int:
    with psycopg.connect(settings.dsn("app_query"), autocommit=True) as c:
        return c.execute("SELECT audit_append(%s, %s, %s::jsonb)",
                         (oid, kind, json.dumps(payload, ensure_ascii=False, default=str))).fetchone()[0]


def verify() -> dict:
    with pg.admin() as c:
        rows = c.execute(RECOMPUTE).fetchall()
    for seq, prev, row_hash, recomputed, expected_prev in rows:
        if row_hash != recomputed or prev != expected_prev:
            return {"ok": False, "rows": len(rows), "first_bad_seq": seq}
    return {"ok": True, "rows": len(rows), "first_bad_seq": None, "head": rows[-1][2] if rows else None}


def recent(limit: int = 50) -> list[dict]:
    with pg.admin() as c:
        rows = c.execute("SELECT seq, ts, oid, kind, payload, row_hash FROM audit ORDER BY seq DESC LIMIT %s",
                         (limit,)).fetchall()
    return [{"seq": r[0], "ts": r[1].isoformat(), "oid": r[2], "kind": r[3], "payload": r[4], "hash": r[5][:16]}
            for r in rows]
