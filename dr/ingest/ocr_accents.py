"""Tone marks of OCR text, corrected from how the same words are written in the typed documents.

The OCR reader gets a Vietnamese word right but its tone mark wrong ('CẢN HỘ' for 'CĂN HỘ', 'XẤY DỰNG',
'TẢNG 17'). Word and word-pair counts are taken from the chunks that were NOT OCR-ed (Word, Excel,
PowerPoint, PDFs with a text layer: typed text, 14,179 chunks in the CT Group room). An OCR word is replaced by
another spelling of the same letters (same text once the accents are removed) only when the typed documents
use that spelling far more often next to the same neighbours ('cản hộ' -> 'căn hộ', while 'cản trở' stays).

Only tone marks and vowel hats change: the result is checked to equal the input once accents are removed, so a
number, a code or a letter is never changed. No model, deterministic, a few seconds to learn from the room.
"""
from __future__ import annotations

import re
import threading
from collections import Counter, defaultdict

from unidecode import unidecode

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_lock = threading.Lock()
_uni: dict[str, Counter] | None = None
_bi: Counter | None = None
MIN_COUNT = 5          # the better spelling must be seen at least this often in the typed documents
RATIO = 5.0            # … and this many times more than the OCR spelling, in the same context
RARE = 0.05            # the OCR spelling must itself be rare in typed text (< 5% of the better one): a word
                       # typed often ('thuế', 'số', 'Nguyên') is a real word, not a misreading
MIN_PAIR = 3           # the better spelling must be seen at least this often next to one of the neighbours


def _fold(w: str) -> str:
    return unidecode(w).lower()


def learn(texts) -> None:
    """Counts from typed text: folded word -> spellings, and (word, word) pairs as written."""
    global _uni, _bi
    uni: dict[str, Counter] = defaultdict(Counter)
    bi: Counter = Counter()
    for text in texts:
        words = [w.lower() for w in _WORD.findall(text)]
        for i, w in enumerate(words):
            uni[_fold(w)][w] += 1
            if i:
                bi[(words[i - 1], w)] += 1
    _uni, _bi = dict(uni), bi


def _load() -> None:
    if _uni is not None:
        return
    with _lock:
        if _uni is not None:
            return
        from dr.db import pg
        with pg.admin() as c:
            rows = c.execute("SELECT text FROM chunks WHERE is_current AND NOT ocr").fetchall()
        learn(r[0] for r in rows)


def _right(w: str, nxt: str | None) -> int | None:
    """Pairs of `w` with the next word in typed text, the next word in any of its spellings: it may be misread
    too and is corrected after this one ('HỘP ĐÔNG': 'hợp đồng' is typed, 'hợp đông' is not)."""
    if not nxt:
        return None
    return max([_bi[(w, nxt)], *(_bi[(w, s)] for s in _uni.get(_fold(nxt), ()))])


def _score(prev: str | None, w: str, nxt: str | None) -> float:
    """How well the typed documents support spelling `w` here: its pairs with both neighbours first."""
    pairs = (_bi[(prev, w)] if prev else 0) + (_right(w, nxt) or 0)
    return pairs * 10 + _uni[_fold(w)][w] * 0.01


def _cased(src: str, word: str) -> str:
    return word.upper() if src.isupper() else word.capitalize() if src[:1].isupper() else word


def fix(text: str) -> str:
    _load()
    tokens = list(_WORD.finditer(text))
    if not tokens:
        return text
    low = [m.group(0).lower() for m in tokens]
    out, last = [], 0
    for i, m in enumerate(tokens):
        w = low[i]
        spellings = _uni.get(_fold(w))
        best = w
        if spellings and (len(spellings) > 1 or w not in spellings):     # 'xấy' is never typed: 'xây' is
            prev = low[i - 1] if i else None
            nxt = low[i + 1] if i + 1 < len(low) else None
            # a spelling with marks never becomes one without (unaccented forms in typed text are codes, names)
            options = [s for s in spellings if s != _fold(s) or w == _fold(w)]
            cand = max(options, key=lambda s: _score(prev, s, nxt)) if options else w
            # both neighbours must be seen next to the new spelling in typed text ('tạm dừng' stays: 'tạm dụng'
            # is never typed, although 'dụng' is far commoner than 'dừng'), one of them at least MIN_PAIR times
            left, right = (_bi[(prev, cand)] if prev else None), _right(cand, nxt)
            sides = [s for s in (left, right) if s is not None]
            if (cand != w and spellings[cand] >= MIN_COUNT and spellings[w] < RARE * spellings[cand]
                    and sides and min(sides) >= 1 and max(sides) >= MIN_PAIR
                    and _score(prev, cand, nxt) >= RATIO * max(_score(prev, w, nxt), 0.1)):
                best = cand
        out.append(text[last:m.start()])
        out.append(_cased(m.group(0), best) if best != w else m.group(0))
        low[i] = best                 # the next word is judged next to the corrected one ('HỘP ĐÔNG' -> 'HỢP ĐỒNG')
        last = m.end()
    out.append(text[last:])
    fixed = "".join(out)
    return fixed if _fold(fixed) == _fold(text) else text       # only tone marks may change


def reset() -> None:
    global _uni, _bi
    _uni = _bi = None
