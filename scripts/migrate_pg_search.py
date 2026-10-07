"""Backfill the in-database search columns (emb halfvec, tsv, tlen) for chunks ingested
before the switch to pgvector, then compute BM25 statistics.
Usage: .venv/bin/python scripts/migrate_pg_search.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dr.core.pgindex import PgSearchIndex, tsv_literal  # noqa: E402
from dr.db import pg  # noqa: E402


def main() -> int:
    pg.ensure_cluster()
    with pg.admin() as c:
        c.execute("UPDATE chunks SET emb = embedding::vector::halfvec WHERE emb IS NULL AND embedding IS NOT NULL")
        rows = c.execute("SELECT chunk_id, text FROM chunks WHERE tsv IS NULL").fetchall()
        with c.cursor() as cur:
            cur.executemany("UPDATE chunks SET tsv = %s::tsvector, tlen = %s WHERE chunk_id = %s",
                            [(*tsv_literal(t), cid) for cid, t in rows])
        c.commit()
    n = PgSearchIndex().refresh()
    print(f"Đã bổ sung {len(rows)} đoạn; thống kê BM25 trên {n} đoạn hiện hành.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
