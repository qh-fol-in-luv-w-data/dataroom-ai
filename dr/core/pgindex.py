"""In-database hybrid search: pgvector HNSW + BM25 over tsvector, under row-level security.

Same ranking recipe as the in-memory SearchIndex (same tokenizer, Lucene-idf BM25 with
statistics per site partition, inner product on bge-m3 vectors, reciprocal rank fusion),
but every candidate comes from SQL run as app_query. Row-level security therefore removes
what the principal may not read *inside* the search query, and the app never materialises
a list of allowed ids — which is what lets this scale to millions of chunks.

Plan per question, chosen from how much the principal can read:
- exact:  the principal's readable chunks fit in EXACT_LIMIT → exact scan over their items
          (small, selective permission sets would starve an approximate index);
- hnsw:   otherwise HNSW with iterative scan (pgvector ≥ 0.8), so post-filtering by RLS
          keeps searching until enough rows survive.
"""
from __future__ import annotations

import time
from collections import defaultdict

import numpy as np

from dr.core.index import tokens
from dr.db import pg

EXACT_LIMIT = 20_000     # readable chunks at or below this → exact search
CAND_TARGET = 1_500      # rarest query terms are used to pick candidates until ~this many matches
CAND_CAP = 20_000        # hard cap on index candidates (before the permission filter)
SCORE_CAP = 4_000        # readable candidates scored per question
AI_ITEMS = ("i.status = 'indexed' AND i.ai_use IN ('Allowed','OnPremOnly') "
            "AND NOT i.encrypted AND NOT i.malware")


def tsv_literal(text: str) -> tuple[str, int]:
    """tsvector literal ('term':1,5 ...) with the BM25 tokenizer's tokens, and the token count."""
    toks = tokens(text)
    pos: dict[str, list[int]] = defaultdict(list)
    for i, t in enumerate(toks[:16_000], 1):          # tsvector positions are capped at 16383
        if len(pos[t]) < 256:                         # and at 256 positions per lexeme
            pos[t].append(i)
    return " ".join(f"'{t}':{','.join(map(str, p))}" for t, p in pos.items()), len(toks)


def vec_literal(v) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in np.asarray(v, dtype=np.float32)) + "]"


class PgSearchIndex:
    in_db = True

    def refresh(self) -> int:
        """Recompute per-site BM25 statistics (vectors and postings live in the table)."""
        with pg.admin() as c:
            c.execute("SELECT refresh_term_stats()")
            c.commit()
            return c.execute("SELECT COALESCE(sum(n), 0) FROM site_stats").fetchone()[0]

    def stats(self) -> dict:
        with pg.admin() as c:
            parts = {r[0]: r[1] for r in c.execute("SELECT site_id, n FROM site_stats ORDER BY site_id")}
        return {"chunks": sum(parts.values()), "partitions": parts, "backend": "postgres (pgvector HNSW + BM25)"}

    # ------------------------------------------------------------------ scope
    @staticmethod
    def _scope_sql(site: str | None) -> tuple[str, tuple]:
        return (AI_ITEMS + (" AND i.site_id = %s" if site else "")), ((site,) if site else ())

    def allowed_scope(self, oid: str, site: str | None = None) -> tuple[int, int]:
        """(files, chunks) the principal may use with AI — counted under RLS on items."""
        where, args = self._scope_sql(site)
        with pg.as_principal(oid) as cur:
            n, c = cur.execute(f"SELECT count(*), COALESCE(sum(i.chunk_count), 0) FROM items i WHERE {where}",
                               args).fetchone()
        return int(n), int(c)

    # ------------------------------------------------------------------ search
    def search_as(self, oid: str, query: str, qvec=None, k: int = 40, site: str | None = None,
                  rrf_k: int = 60) -> tuple[list[tuple[int, float]], dict]:
        info: dict = {}
        where, args = self._scope_sql(site)
        with pg.as_principal(oid) as cur:
            n_chunks = cur.execute(f"SELECT COALESCE(sum(i.chunk_count), 0) FROM items i WHERE {where}",
                                   args).fetchone()[0]
            exact = n_chunks <= EXACT_LIMIT
            items = [r[0] for r in cur.execute(f"SELECT i.item_id FROM items i WHERE {where}", args)] if exact else None
            info["plan"] = "exact" if exact else "hnsw"
            ranked: list[list[int]] = []

            t0 = time.perf_counter()
            bm = self._bm25(cur, query, k, items, site)
            info["bm25_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            if bm:
                ranked.append(bm)

            if qvec is not None:
                t0 = time.perf_counter()
                ranked.append(self._vector(cur, qvec, k, items, site))
                info["vector_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        fused: dict[int, float] = {}
        for lst in ranked:
            for rank, cid in enumerate(lst):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (rrf_k + rank + 1)
        return sorted(fused.items(), key=lambda x: -x[1])[:k], info

    @staticmethod
    def _filters(items, site) -> tuple[str, list]:
        sql, args = "", []
        if items is not None:
            sql += " AND c.item_id = ANY(%s)"
            args.append(items)
        if site:
            sql += " AND c.site_id = %s"
            args.append(site)
        return sql, args

    def _vector(self, cur, qvec, k, items, site) -> list[int]:
        fsql, fargs = self._filters(items, site)
        v = vec_literal(qvec)
        if items is not None:
            # "+ 0" keeps the planner off the HNSW index: exact distances over the item index.
            rows = cur.execute(f"SELECT c.chunk_id FROM chunks c WHERE c.emb IS NOT NULL{fsql} "
                               f"ORDER BY (c.emb <#> %s::halfvec) + 0 LIMIT %s", (*fargs, v, k)).fetchall()
            return [r[0] for r in rows]
        cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
        cur.execute("SET LOCAL hnsw.ef_search = 200")
        rows = cur.execute(
            f"WITH r AS MATERIALIZED (SELECT c.chunk_id, c.emb <#> %s::halfvec AS d FROM chunks c "
            f"WHERE c.emb IS NOT NULL{fsql} ORDER BY c.emb <#> %s::halfvec LIMIT %s) "
            f"SELECT chunk_id FROM r ORDER BY d", (v, *fargs, v, k)).fetchall()
        return [r[0] for r in rows]

    def _bm25(self, cur, query, k, items, site) -> list[int]:
        terms = list(dict.fromkeys(tokens(query)))
        if not terms:
            return []
        stats = cur.execute("SELECT term, sum(df) FROM term_stats WHERE term = ANY(%s) GROUP BY term ORDER BY 2",
                            (terms,)).fetchall()
        if not stats:
            return []
        # Rarest terms first: they carry the most information and have the shortest posting
        # lists. Common terms still contribute to the score of every candidate below.
        pick, est = [], 0
        for t, df in stats:
            if pick and est + df > CAND_TARGET:
                break
            pick.append(t)
            est += df
        tsq = " | ".join(f"'{t}'" for t in pick)
        fsql, fargs = self._filters(items, site)
        rows = cur.execute(
            f"""WITH cand AS MATERIALIZED (
                    SELECT c.chunk_id, c.site_id, c.tsv, c.tlen FROM chunks c
                    WHERE c.chunk_id IN (SELECT fts_candidates(%s::tsquery, %s)){fsql} LIMIT %s)
                SELECT cand.chunk_id,
                       sum(ts.idf * u.tf * 2.2 / (u.tf + 1.2 * (0.25 + 0.75 * cand.tlen / ss.avgdl))) AS score
                FROM cand
                CROSS JOIN LATERAL (SELECT lexeme, cardinality(positions) AS tf FROM unnest(cand.tsv)) u
                JOIN term_stats ts ON ts.site_id = cand.site_id AND ts.term = u.lexeme
                JOIN site_stats ss ON ss.site_id = cand.site_id
                WHERE u.lexeme = ANY(%s)
                GROUP BY cand.chunk_id ORDER BY score DESC LIMIT %s""",
            (tsq, CAND_CAP, *fargs, SCORE_CAP, terms, k)).fetchall()
        return [r[0] for r in rows]


def make_index():
    """The search engine selected by DR_SEARCH (default: in Postgres)."""
    from dr.config import settings
    from dr.core.index import SearchIndex
    return PgSearchIndex() if settings.search_backend == "pg" else SearchIndex()
