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

from dr.config import settings

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


def numbers_with_digits(text: str) -> list[tuple[str, set[Decimal]]]:
    """Each number as (the number as written, its plausible values)."""
    out = []
    for m in _NUM.finditer(text):
        vals = _parse_number(m.group(0))
        if vals:
            out.append((m.group(0), vals))
    return out


def _same_digits(a: str, b: str) -> bool:
    """Same digits, separators aside; a decimal written with fewer trailing zeros (2.786,9 / 2.786,90) too,
    but not when a last group of exactly three digits makes it a thousands group ('4.000' is not '4.0')."""
    da, db = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
    if da == db:
        return True
    last = [re.split(r"[.,]", x)[-1] for x in (a, b)]
    return (da.rstrip("0") == db.rstrip("0") and all(re.search(r"[.,]", x) for x in (a, b))
            and all(len(g) != 3 for g in last))


def number_supported(written: str, vals: set[Decimal], sources: list[tuple[str, set[Decimal]]]) -> bool:
    """A number of the answer is supported by a source number with the same value AND the same digits.
    Value alone is not enough: '4.000' (four thousand, or 4.000 read as a decimal) equals '4.0' of
    'CYBER SALE 4.0' as a decimal, and an invented '4.000 USD' passed. Digits alone are not enough either:
    '1.250' and '12,50' share them."""
    return any(v & vals and _same_digits(written, w) for w, v in sources)


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
    q_nums = numbers_with_digits(question)
    kept: list[Claim] = []
    dropped: list[tuple[dict, str]] = []
    given = norm(" ".join(p["text"] for p in passages.values()))
    given_words = set(given.split())
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
        sources = [n for g in good for n in numbers_with_digits(g.quote)] + q_nums
        missing = [d for d, vals in numbers_with_digits(text) if not number_supported(d, vals, sources)]
        if missing:
            dropped.append((rc, "con số trong câu trả lời không khớp câu trích"))
            continue
        if settings.binding:
            wrong_kind = unbound(text, [g.quote for g in good], q_nums)
            if wrong_kind:
                dropped.append((rc, f"con số gắn sai nghĩa: câu trả lời ghi {wrong_kind[0]}, câu trích ghi {wrong_kind[1]}"))
                continue
        # a name the answer gives (an agency, a unit code) must be in its own quotes when the documents
        # use it: a figure copied from one table row under another row's name passes the number check
        quoted = norm(" ".join(g.quote for g in good))
        # a code the question names (SH09, GJDC) that the documents use: the answer must come from a passage
        # about it, not a figure from another unit's contract that happens to fit the sentence
        named = [t for t in _CODES.findall(question) if t not in _CODE_STOP and norm(t) in given_words]
        if named and not any(norm(t) in norm(passages[g.chunk_id]["text"]).split() for t in named for g in good):
            dropped.append((rc, f"câu trích không thuộc tài liệu về {', '.join(named)}"))
            continue
        asked = norm(question).split()        # the subject the user named (SH09) may be left out of the quote
        # a scanned table names its units and columns (MW, COD) once, in its header row: a claim read
        # from one row may use them although the row itself does not
        header = norm(" ".join(passages[g.chunk_id]["text"].split("\n", 1)[0] for g in good
                               if passages[g.chunk_id].get("kind") == "table")).split()
        wrong = [t for t in _CODES.findall(text) if t not in _CODE_STOP and norm(t) in given_words
                 and norm(t) not in quoted.split() and norm(t) not in asked and norm(t) not in header]
        if wrong:
            dropped.append((rc, f"tên trong câu trả lời không có trong câu trích ({', '.join(wrong)})"))
            continue
        kept.append(Claim(text, good))
    return kept, dropped


_CODES = re.compile(r"\b(?=[A-Z0-9-]*[A-Z])[A-Z][A-Z0-9-]{1,}\b")       # EZ, GJDC, BNF, SH09, CTG-01
_CODE_STOP = {"VAT", "VND", "USD", "CGI", "PR", "KOL", "KOLS", "IPO", "TP", "HCM", "SMS", "LCD", "OOH", "TVC", "BOD",
              "NT", "HĐ", "CT", "QĐ", "TT", "PCCC", "MEP", "CEO", "FB", "GĐ", "KH", "DA", "PDF", "AI", "ID", "OK"}


# ------------------------------------------------------------------ number meaning (DR_BINDING)
# What a figure is, from the words right before it. Two different meanings never stand for each other: the
# "ngân sách 600 triệu" of a campaign is not the price of a flat, a lease's "cam kết thuê 3.000 USD" is no salary.
# Words in no class ("chi phí", "tổng cộng") say nothing, and an unknown side never drops a claim.
MEANINGS = {
    "giá": ("giá", "giá bán", "đơn giá", "giá trị", "báo giá", "giá niêm yết", "chỉ từ"),
    "ngân sách": ("ngân sách", "dự toán", "kinh phí", "phân bổ"),
    "diện tích": ("diện tích", "thông thủy", "tim tường", "dtxd", "dttt", "dtsd"),
    "thu nhập": ("thu nhập", "lương", "hoa hồng", "thưởng"),
    "tiền thuê": ("thuê", "cam kết", "đặt cọc", "cọc"),
    "thuế": ("thuế", "vat", "gtgt", "mst"),
}
_PHRASES = sorted(((tuple(w.split()), m) for m, ws in MEANINGS.items() for w in ws), key=lambda x: -len(x[0]))
_STOP = re.compile(r"[.;!?\n]")


def meanings_before(text: str, start: int, window: int = 8) -> set[str]:
    """Meanings named by the words before position start: back to the previous number or the sentence start,
    at most `window` words."""
    head = _STOP.split(text[:start])[-1]
    prev = list(_NUM.finditer(head))
    if prev:
        head = head[prev[-1].end():]
    words = norm(head).split()[-window:]
    found = set()
    for i in range(len(words)):
        for ph, m in _PHRASES:
            if tuple(words[i:i + len(ph)]) == ph:
                found.add(m)
    return found


def unbound(claim: str, quotes: list[str], q_nums: list[tuple[str, set[Decimal]]]) -> tuple[str, str] | None:
    """(claim's meaning, quote's meaning) for the first figure of the claim whose meaning differs from what every
    quote says of the same figure; None when they agree or either side does not say."""
    for m in _NUM.finditer(claim):
        vals = _parse_number(m.group(0))
        if not vals or number_supported(m.group(0), vals, q_nums):
            continue
        said = meanings_before(claim, m.start())
        if not said:
            continue
        theirs: set[str] = set()
        for q in quotes:
            for n in _NUM.finditer(q):
                if _parse_number(n.group(0)) & vals and _same_digits(m.group(0), n.group(0)):
                    found = meanings_before(q, n.start())
                    if not found or found & said:
                        return None           # a quote leaves it open or agrees
                    theirs |= found
        if theirs:
            return ", ".join(sorted(said)), ", ".join(sorted(theirs))
    return None
