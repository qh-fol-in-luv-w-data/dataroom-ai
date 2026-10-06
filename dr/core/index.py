"""In-memory hybrid search index (BM25 + vectors), partitioned by site.

The index never decides who may see what. Callers pass ``allowed_ids`` — the chunk ids
returned by Postgres under row-level security for the current principal — and the index
only ever scores those ids. BM25 statistics are computed per site partition so that
documents added to one investor group's site cannot change term statistics (and hence
rankings) seen by another group (master plan §5, non-interference).
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass

import math
from collections import Counter

import numpy as np
from unidecode import unidecode

from dr.db import pg

_TOKEN = re.compile(r"[0-9a-z]+(?:[.,][0-9]+)*")


def tokens(text: str) -> list[str]:
    """Accent-folded syllables plus syllable bigrams (Vietnamese words are mostly 1–2 syllables)."""
    syl = _TOKEN.findall(unidecode(text).lower())
    return syl + [f"{a}_{b}" for a, b in zip(syl, syl[1:])]


class BM25:
    """Okapi BM25 with the Lucene idf (always positive, stable on small partitions)."""

    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = np.array([len(d) for d in docs], dtype=np.float64)
        self.avgdl = float(self.len.mean()) if len(docs) else 0.0
        df: Counter = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def get_batch_scores(self, query: list[str], idx: list[int]) -> np.ndarray:
        out = np.zeros(len(idx))
        q = [t for t in set(query) if t in self.idf]
        for j, i in enumerate(idx):
            tf, dl = self.tf[i], self.len[i]
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            out[j] = s
        return out


@dataclass
class _Partition:
    ids: list[int]
    pos: dict[int, int]
    bm25: BM25


class SearchIndex:
    def __init__(self, embedder=None):
        self._lock = threading.RLock()
        self.embedder = embedder
        self.parts: dict[str, _Partition] = {}
        self.vecs: dict[int, np.ndarray] = {}
        self.site_of: dict[int, str] = {}
        self.item_of: dict[int, str] = {}

    # -------------------------------------------------------------- loading
    def refresh(self) -> int:
        """Reload all current chunks (admin connection: the index is the search engine,
        access control happens through allowed_ids)."""
        with pg.admin() as c:
            rows = c.execute("SELECT chunk_id, item_id, site_id, text, embedding FROM chunks "
                             "WHERE is_current ORDER BY chunk_id").fetchall()
        return self.build(rows)

    def build(self, rows) -> int:
        by_site: dict[str, list[tuple[int, list[str]]]] = {}
        vecs, site_of, item_of = {}, {}, {}
        for cid, item_id, site, text, emb in rows:
            by_site.setdefault(site, []).append((cid, tokens(text)))
            site_of[cid], item_of[cid] = site, item_id
            if emb is not None:
                vecs[cid] = np.asarray(emb, dtype=np.float32)
        parts = {}
        for site, docs in by_site.items():
            ids = [d[0] for d in docs]
            parts[site] = _Partition(ids, {cid: i for i, cid in enumerate(ids)},
                                     BM25([d[1] or ["_"] for d in docs]))
        with self._lock:
            self.parts, self.vecs, self.site_of, self.item_of = parts, vecs, site_of, item_of
        return len(rows)

    # -------------------------------------------------------------- search
    def search(self, allowed_ids: set[int], query: str, qvec: np.ndarray | None = None,
               k: int = 40, rrf_k: int = 60) -> list[tuple[int, float]]:
        with self._lock:
            qtok = tokens(query)
            ranked_lists: list[list[int]] = []
            # BM25: statistics per partition, one ranked list merged by score.
            bm: list[tuple[float, int]] = []
            for site, part in self.parts.items():
                idx = [part.pos[c] for c in part.ids if c in allowed_ids]
                if not idx or not qtok:
                    continue
                scores = part.bm25.get_batch_scores(qtok, idx)
                for i in np.argsort(-scores)[:k]:
                    if scores[i] > 0:
                        bm.append((float(scores[i]), part.ids[idx[i]]))
            if bm:
                ranked_lists.append([cid for _, cid in sorted(bm, key=lambda x: -x[0])[:k]])
            if qvec is not None:
                cand = [c for c in allowed_ids if c in self.vecs]
                if cand:
                    m = np.stack([self.vecs[c] for c in cand])
                    sims = m @ qvec
                    order = np.argsort(-sims)[:k]
                    ranked_lists.append([cand[i] for i in order])
            fused: dict[int, float] = {}
            for lst in ranked_lists:
                for rank, cid in enumerate(lst):
                    if cid in allowed_ids:  # defensive: never return a non-allowed id
                        fused[cid] = fused.get(cid, 0.0) + 1.0 / (rrf_k + rank + 1)
            return sorted(fused.items(), key=lambda x: -x[1])[:k]

    def stats(self) -> dict:
        with self._lock:
            return {"chunks": len(self.site_of), "partitions": {s: len(p.ids) for s, p in self.parts.items()}}
