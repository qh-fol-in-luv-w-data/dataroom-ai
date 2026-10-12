"""Restoring Vietnamese diacritics in a question typed without them.

"Dinh gia noi bo cua Sao Mai la bao nhieu" ranks badly: the reranker and the embeddings understand
accent-free Vietnamese poorly (the answer passage fell to rank 24-31). The accents are restored from
word and word-pair frequencies of the shared documents (site COMMON, readable by every investor),
so the restored question can never reveal wording that only another group's documents contain.
Deterministic: no model, unknown words are left as typed.
"""
from __future__ import annotations

import re
import threading
from collections import Counter, defaultdict

from unidecode import unidecode

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_lock = threading.Lock()
_uni: dict[str, Counter] | None = None          # folded word -> Counter(accented form)
_bi: dict[tuple[str, str], Counter] | None = None


def _fold(w: str) -> str:
    return unidecode(w).lower()


def _build() -> None:
    global _uni, _bi
    from dr.db import pg
    uni: dict[str, Counter] = defaultdict(Counter)
    bi: dict[tuple[str, str], Counter] = defaultdict(Counter)
    with pg.admin() as c:
        rows = c.execute("SELECT c.text FROM chunks c JOIN items i ON i.item_id = c.item_id AND i.ctag = c.ctag "
                         "WHERE i.site_id = 'COMMON'").fetchall()
    for (text,) in rows:
        words = [w.lower() for w in _WORD.findall(text)]
        for a, b in zip([None] + words, words):
            uni[_fold(b)][b] += 1
            if a is not None:
                bi[(_fold(a), _fold(b))][(a, b)] += 1
    _uni, _bi = dict(uni), dict(bi)


def unaccented(text: str) -> bool:
    """Written in Latin letters with no Vietnamese diacritic at all."""
    letters = "".join(_WORD.findall(text))
    return bool(letters) and unidecode(letters) == letters


def restore(text: str, beam: int = 6) -> str:
    """Viterbi over the accented forms of each word: unigram frequency times word-pair frequency
    with both neighbours, so "bao nhieu" -> "bao nhiêu" (not "bảo nhiêu" as in "bảo hiểm")."""
    import math
    with _lock:
        if _uni is None:
            _build()
    matches = list(_WORD.finditer(text))
    if not matches:
        return text
    cands = []
    for m in matches:
        key = m.group(0).lower()
        forms = [f for f, _ in _uni[key].most_common(beam)] if key in _uni else [key]
        cands.append(forms)

    def emit(i, f):
        key = matches[i].group(0).lower()
        n = _uni.get(key, Counter()).get(f, 0)
        total = sum(_uni.get(key, Counter()).values()) or 1
        return math.log((n + 0.1) / (total + 0.1))

    def trans(a, b):
        pair = _bi.get((_fold(a), _fold(b)))
        if not pair:
            return 0.0                               # no evidence: neutral
        total = sum(pair.values())
        return 1.0 * math.log((pair.get((a, b), 0) + 0.05) / (total + 0.05))
    # best[i][f] = (score, back-pointer)
    best = [{f: (emit(0, f), None) for f in cands[0]}]
    for i in range(1, len(cands)):
        row = {}
        for f in cands[i]:
            sc, bp = max(((best[i - 1][g][0] + trans(g, f), g) for g in cands[i - 1]), key=lambda x: x[0])
            row[f] = (sc + emit(i, f), bp)
        best.append(row)
    f = max(best[-1], key=lambda k: best[-1][k][0])
    chosen = [f]
    for i in range(len(cands) - 1, 0, -1):
        f = best[i][f][1]
        chosen.append(f)
    chosen.reverse()
    out, pos = [], 0
    for m, choice in zip(matches, chosen):
        out.append(text[pos:m.start()])
        word = m.group(0)
        if word.isupper() and len(word) > 1:
            choice = choice.upper()
        elif word[:1].isupper():
            choice = choice[:1].upper() + choice[1:]
        out.append(choice)
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def reset() -> None:
    """Forget the frequency tables (tests, or after re-ingesting the shared site)."""
    global _uni, _bi
    with _lock:
        _uni = _bi = None
