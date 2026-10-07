"""Load test for the in-database search (pgvector HNSW + BM25 under row-level security).

Builds a separate database (dataroom_scale) with N synthetic chunks derived from the real
demo chunks (text lightly mutated, vectors = real bge-m3 vector + noise), a realistic site
layout and five principals with very different reach, then measures retrieval latency and
HNSW recall against exact search.

  .venv/bin/python scripts/scale_test.py load --n 200000          # (re)build with N chunks
  .venv/bin/python scripts/scale_test.py load --n 800000 --append # add N more chunks
  .venv/bin/python scripts/scale_test.py bench                    # latency + recall report

The demo database is only read (source texts, vectors and questions).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from multiprocessing import Pool
from pathlib import Path

os.environ["DR_PG_DB"] = "dataroom_scale"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402

from dr.config import settings  # noqa: E402
from dr.core.pgindex import PgSearchIndex, tsv_literal  # noqa: E402
from dr.db import pg  # noqa: E402
from dr.ingest.chunker import fold  # noqa: E402

GROUPS = [f"G{i:02d}" for i in range(1, 21)]
# share of all chunks per site: a big common site, an internal site, 20 investor-group sites
SITES = {"COMMON": 0.35, "INTERNAL": 0.10, **{g: 0.55 / len(GROUPS) for g in GROUPS}}
PERSONAS = {                       # who can read what (item_reader rows)
    "staff": "all sites (≈100%)",
    "big": "COMMON + G01 (≈38%)",
    "mid": "G02–G05 (≈11%)",
    "small": "G07 only (≈2.75%)",
    "tiny": "5 shared files in G09 (a few dozen chunks)",
}
OUT = ROOT / "logs" / "scale_test.json"
_BASE: list = []


def _demo_dsn() -> str:
    return settings.dsn("dr_admin").replace("dbname=dataroom_scale", "dbname=dataroom")


def _readers(site: str, item_no: int) -> list[str]:
    r = ["staff"]
    if site in ("COMMON", "G01"):
        r.append("big")
    if site in ("G02", "G03", "G04", "G05"):
        r.append("mid")
    if site == "G07":
        r.append("small")
    if site == "G09" and item_no % 1000 < 5:
        r.append("tiny")
    return r


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def _init(base):
    global _BASE
    _BASE = base


def _rows(job) -> bytes:
    """COPY text lines for one batch of chunks (runs in a worker process)."""
    seed, specs = job
    rng = np.random.default_rng(seed)
    r = random.Random(seed)
    out = []
    for item_id, site, ordinal in specs:
        # Blend two real chunks (text halves and vectors) so the vector space is a continuum
        # like a real corpus, not hundreds of near-copies of each source chunk.
        (t1, e1), (t2, e2) = _BASE[r.randrange(len(_BASE))], _BASE[r.randrange(len(_BASE))]
        w1, w2 = t1.split(), t2.split()
        words = w1[: max(1, len(w1) * 2 // 3)] + w2[len(w2) // 2:]
        for _ in range(max(1, len(words) // 25)):        # light mutation: every chunk is unique
            words[r.randrange(len(words))] = f"{r.choice(['HĐ', 'PL', 'BB', 'TK'])}-{r.randrange(10**5):05d}"
        text = " ".join(words) + f" Số {r.randrange(10**6)}/{2020 + r.randrange(7)}."
        a = r.uniform(0.55, 0.95)
        v = a * e1 + (1 - a) * e2 + rng.normal(0, 0.01, e1.shape).astype(np.float32)
        v /= np.linalg.norm(v)
        tsv, tlen = tsv_literal(text)
        vec = "[" + ",".join(f"{x:.4f}" for x in v) + "]"
        out.append("\t".join([item_id, site, "c1", str(ordinal), f"Đoạn {ordinal + 1}", _esc(text), _esc(fold(text)),
                              "synthetic", vec, _esc(tsv), str(tlen)]) + "\n")
    return "".join(out).encode()


def load(n: int, append: bool, workers: int) -> None:
    t_all = time.time()
    pg.ensure_cluster()
    with psycopg.connect(_demo_dsn()) as d:
        base = [(t, np.asarray(e, dtype=np.float32)) for t, e in
                d.execute("SELECT text, embedding FROM chunks WHERE is_current AND embedding IS NOT NULL")]
    print(f"{len(base)} đoạn gốc làm mẫu")
    with pg.admin() as c:
        if not append:
            pg.reset_all()
            c.execute("INSERT INTO sites(site_id, name) SELECT unnest(%s::text[]), unnest(%s::text[])",
                      (list(SITES), list(SITES)))
        c.execute("DROP INDEX IF EXISTS chunks_emb_hnsw")
        c.execute("DROP INDEX IF EXISTS chunks_tsv_gin")
        c.commit()
        start = c.execute("SELECT count(*) FROM items").fetchone()[0]

    # items: ~10 chunks each, spread over sites by share
    r = random.Random(7 + start)
    specs, items, readers = [], [], []
    made, k = 0, start
    while made < n:
        site = r.choices(list(SITES), weights=list(SITES.values()))[0]
        cnt = min(n - made, r.randint(1, 20))
        iid = f"it-{k:07d}"
        items.append((iid, site, f"/{site}", f"{iid}.docx", "docx", "c1", "e1", "Allowed", "indexed", cnt))
        readers += [(iid, p, "group", "synthetic") for p in _readers(site, k)]
        specs += [(iid, site, o) for o in range(cnt)]
        made += cnt
        k += 1
    with pg.admin() as c:
        with c.cursor() as cur:
            with cur.copy("COPY items(item_id, site_id, path, name, ext, ctag, etag, ai_use, status, chunk_count) "
                          "FROM STDIN") as cp:
                for row in items:
                    cp.write_row(row)
            with cur.copy("COPY item_reader(item_id, oid, via_kind, via_id) FROM STDIN") as cp:
                for row in readers:
                    cp.write_row(row)
        c.commit()
    print(f"{len(items)} file, {len(readers)} dòng quyền đọc")

    batch = 5000
    jobs = [(start * 1000 + i, specs[i:i + batch]) for i in range(0, len(specs), batch)]
    t0 = time.time()
    done = 0
    with pg.admin() as c, Pool(workers, initializer=_init, initargs=(base,)) as pool:
        with c.cursor() as cur, cur.copy("COPY chunks(item_id, site_id, ctag, ordinal, locator, text, text_folded, "
                                         "converter, emb, tsv, tlen) FROM STDIN") as cp:
            for blob in pool.imap(_rows, jobs):
                cp.write(blob)
                done += batch
                if done % 100_000 < batch:
                    print(f"  nạp {min(done, n):>9,} đoạn  {time.time() - t0:6.0f}s", flush=True)
        c.commit()
    t_copy = time.time() - t0

    timings = {}
    with pg.admin() as c:
        c.autocommit = True
        c.execute("SET maintenance_work_mem = '4GB'")
        c.execute("SET max_parallel_maintenance_workers = 7")
        for name, sql in [("gin", "CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv)"),
                          ("hnsw", "CREATE INDEX chunks_emb_hnsw ON chunks USING hnsw (emb halfvec_ip_ops) "
                                   "WITH (m = 16, ef_construction = 64)"),
                          ("bm25_stats", "SELECT refresh_term_stats()"),
                          ("analyze", "ANALYZE")]:
            t0 = time.time()
            c.execute(sql)
            timings[name] = round(time.time() - t0, 1)
            print(f"  {name}: {timings[name]}s", flush=True)
        total, size, hnsw, gin = c.execute(
            "SELECT count(*), pg_size_pretty(pg_total_relation_size('chunks')), "
            "pg_size_pretty(pg_relation_size('chunks_emb_hnsw')), pg_size_pretty(pg_relation_size('chunks_tsv_gin')) "
            "FROM chunks").fetchone()
    print(f"Xong: {total:,} đoạn, bảng {size} (HNSW {hnsw}, GIN {gin}); nạp {t_copy:.0f}s, tổng {time.time() - t_all:.0f}s")
    _save({"load": {"chunks": total, "table_size": size, "hnsw_size": hnsw, "gin_size": gin,
                    "copy_s": round(t_copy), **{f"{k}_s": v for k, v in timings.items()}}})


def _save(part: dict) -> None:
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    n = None
    with pg.admin() as c:
        n = c.execute("SELECT count(*) FROM chunks").fetchone()[0]
    data.setdefault(str(n), {}).update(part)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1))


def bench(rounds: int) -> None:
    from dr.models.embed import embed_texts
    facts = json.loads((settings.tenant_dir / "facts.json").read_text(encoding="utf-8"))["facts"]
    questions = [f["question"] for f in facts]
    qvecs = embed_texts(questions)
    ix = PgSearchIndex()
    report = {}
    for who in PERSONAS:
        files, chunks = ix.allowed_scope(who)
        lat, bm, vec, recall, plans = [], [], [], [], set()
        for _ in range(rounds):
            for q, qv in zip(questions, qvecs):
                t0 = time.perf_counter()
                hits, info = ix.search_as(who, q, qv, k=40)
                lat.append((time.perf_counter() - t0) * 1000)
                bm.append(info.get("bm25_ms", 0))
                vec.append(info.get("vector_ms", 0))
                plans.add(info["plan"])
        tol = []
        for q, qv in list(zip(questions, qvecs))[:8]:          # recall of the vector leg vs exact search
            with pg.as_principal(who) as cur:
                approx = ix._vector(cur, qv, 40, None if chunks > 20_000 else
                                    [r[0] for r in cur.execute("SELECT item_id FROM items")], None)
                v = "[" + ",".join(f"{x:.6f}" for x in qv) + "]"
                exact = cur.execute("SELECT c.chunk_id, c.emb <#> %s::halfvec FROM chunks c WHERE c.emb IS NOT NULL "
                                    "ORDER BY (c.emb <#> %s::halfvec) + 0 LIMIT 40", (v, v)).fetchall()
                dist = dict(cur.execute("SELECT chunk_id, emb <#> %s::halfvec FROM chunks WHERE chunk_id = ANY(%s)",
                                        (v, approx)).fetchall())
            recall.append(len(set(approx) & {r[0] for r in exact}) / max(1, len(exact)))
            # near-duplicates make the exact top-40 order arbitrary: also count results that are
            # as close as the exact 40th neighbour (within 0.005 inner product)
            kth = exact[-1][1] if exact else 0
            tol.append(sum(dist[c] <= kth + 0.005 for c in approx) / max(1, len(exact)))
        p = lambda xs, q: round(statistics.quantiles(xs, n=100)[q - 1], 1) if len(xs) > 1 else round(xs[0], 1)
        report[who] = {"reach": PERSONAS[who], "files": files, "chunks": chunks, "plan": sorted(plans),
                       "search_p50_ms": p(lat, 50), "search_p95_ms": p(lat, 95),
                       "bm25_p50_ms": p(bm, 50), "vector_p50_ms": p(vec, 50),
                       "vector_recall_at_40": round(statistics.mean(recall), 3),
                       "vector_recall_tol": round(statistics.mean(tol), 3)}
        print(f"{who:<6} {chunks:>9,} đoạn  {'/'.join(sorted(plans)):<6} tìm p50 {report[who]['search_p50_ms']:>7} ms  "
              f"p95 {report[who]['search_p95_ms']:>7} ms  (BM25 {report[who]['bm25_p50_ms']}, vector "
              f"{report[who]['vector_p50_ms']})  recall@40 {report[who]['vector_recall_at_40']} "
              f"(dung sai {report[who]['vector_recall_tol']})", flush=True)
    _save({"bench": report})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    lp = sub.add_parser("load")
    lp.add_argument("--n", type=int, default=200_000)
    lp.add_argument("--append", action="store_true")
    lp.add_argument("--workers", type=int, default=8)
    bp = sub.add_parser("bench")
    bp.add_argument("--rounds", type=int, default=2)
    a = ap.parse_args(argv)
    if a.cmd == "load":
        load(a.n, a.append, a.workers)
    else:
        bench(a.rounds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
