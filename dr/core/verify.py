"""Deterministic answer verification (the hard grounding gate).

A claim survives only if every citation:
  1. points at a passage that was given to the LLM (and therefore passed RLS + live check),
  2. quotes text that actually occurs in that passage (exact after normalisation; fuzzy
     ratio >= 0.9 allowed for OCR passages),
and every number in the claim appears in one of its quotes (Vietnamese number formats).
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

_NUM = re.compile(r"(?<![\w.,])\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?(?![\d])|(?<![\w.,])\d+(?:[.,]\d+)?(?![\d])")


@dataclass
class Citation:
    chunk_id: int
    quote: str


@dataclass
class Claim:
    text: str
    citations: list[Citation] = field(default_factory=list)
    nli: float | None = None


_NUM_SEP = re.compile(r"(?<=\d)[.,](?=\d)")


def norm(s: str) -> str:
    """Word-stream form for verbatim comparison: case, whitespace and punctuation are
    ignored, but every word and every digit (including number separators like 1.250,5)
    must match exactly."""
    s = unicodedata.normalize("NFC", s).lower()
    s = _NUM_SEP.sub(lambda m: "\x00" if m.group(0) == "." else "\x01", s)   # protect 1.250,5
    s = "".join(" " if unicodedata.category(ch).startswith("P") or ch in "|·•" else ch for ch in s)
    s = s.replace("\x00", ".").replace("\x01", ",")
    return re.sub(r"\s+", " ", s).strip()


def _parse_number(tok: str) -> set[Decimal]:
    out: set[Decimal] = set()
    try:
        if "," in tok and "." in tok:
            dec = "," if tok.rfind(",") > tok.rfind(".") else "."
            th = "." if dec == "," else ","
            out.add(Decimal(tok.replace(th, "").replace(dec, ".")))
        elif "." in tok:
            parts = tok.split(".")
            if all(len(p) == 3 for p in parts[1:]):
                out.add(Decimal(tok.replace(".", "")))        # VN thousands: 25.850
            if len(parts) == 2:
                out.add(Decimal(tok))                          # EN decimal: 12.5
        elif "," in tok:
            parts = tok.split(",")
            if len(parts) == 2:
                out.add(Decimal(tok.replace(",", ".")))        # VN decimal: 0,85
            if all(len(p) == 3 for p in parts[1:]):
                out.add(Decimal(tok.replace(",", "")))        # EN thousands: 1,250
        else:
            out.add(Decimal(tok))
    except InvalidOperation:
        pass
    return {d.normalize() for d in out}


def vn_numbers(text: str) -> list[set[Decimal]]:
    """Each number in the text as the set of its plausible values."""
    return [v for v in (_parse_number(m.group(0)) for m in _NUM.finditer(text)) if v]


def quote_found(quote: str, passage: str, fuzzy: bool) -> bool:
    q, p = norm(quote), norm(passage)
    if len(q) < 8:
        return False
    if q in p:
        return True
    if not fuzzy:
        return False
    sm = difflib.SequenceMatcher(None, p, q, autojunk=False)
    best = 0.0
    for blk in sm.get_matching_blocks():
        start = max(0, blk.a - blk.b)
        window = p[start:start + len(q)]
        best = max(best, difflib.SequenceMatcher(None, window, q).ratio())
    return best >= 0.9


def check(raw_claims: list[dict], labels: dict[str, int], passages: dict[int, dict], question: str = ""
          ) -> tuple[list[Claim], list[tuple[dict, str]]]:
    """Numbers that already appear in the question (e.g. the year asked about) are context,
    not facts asserted by the answer, so they need not appear in the quote."""
    q_vals = vn_numbers(question)
    q_union = set().union(*q_vals) if q_vals else set()
    kept: list[Claim] = []
    dropped: list[tuple[dict, str]] = []
    for rc in raw_claims:
        text = (rc.get("text") or "").strip()
        cits = rc.get("citations") or []
        if not text or not cits:
            dropped.append((rc, "không có trích dẫn"))
            continue
        good: list[Citation] = []
        reason = None
        for c in cits:
            cid = labels.get(str(c.get("doc", "")).strip())
            if cid is None or cid not in passages:
                reason = f"trích dẫn tài liệu không được cung cấp ({c.get('doc')})"
                continue
            p = passages[cid]
            if not quote_found(c.get("quote", ""), p["text"], fuzzy=p.get("ocr", False)):
                reason = "câu trích không có nguyên văn trong tài liệu"
                continue
            good.append(Citation(cid, c["quote"].strip()))
        if not good:
            dropped.append((rc, reason or "không có trích dẫn hợp lệ"))
            continue
        quote_vals = [v for g in good for v in vn_numbers(g.quote)]
        quote_union = set().union(*quote_vals) if quote_vals else set()
        missing = [vals for vals in vn_numbers(text) if not (vals & quote_union) and not (vals & q_union)]
        if missing:
            dropped.append((rc, "con số trong câu trả lời không khớp câu trích"))
            continue
        kept.append(Claim(text, good))
    return kept, dropped
