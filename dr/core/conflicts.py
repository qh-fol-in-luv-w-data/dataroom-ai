"""Documents that disagree, document dates, and how much a source is trusted.

A data room holds several versions of the same thing: two floor plans of apartment B4 (52.55 m² and 52.88 m²
usable area), a price list counting penthouse PD2 over two floors (326.18 m²) and a plan giving one floor
(163.09 m²). The verifier only checks that a quoted number is in its document, so the answer took one value as
if it were the only one. Here, after the answer is verified:

- `find(...)`: for a numeric answer about a named unit or code (B4, S-08, PS1, SH09 …), the other retrieved
  passages the user may read are searched for the same unit and the same measure ("thông thủy", "xây dựng" …)
  with another number. Each such value is added to the answer as its own cited line, so the reader sees every
  value with its source and date instead of one picked silently.
- `doc_date(name)`: the date written in a file name (23.03.2018, 20220623, 07062023 …), shown with the source
  and used to say which version is newer. 730 of the CT Group files carry one.
- `source_weight(path, name)`: a rejected or old version ranks lower, a signed / approved / legal document
  higher (the reranker score is multiplied by it).
- `older_versions(names)`: files whose names differ only by a date or a version mark (Bảng giá 01.03.2023 /
  Bảng giá 15.06.2024, v1 / v2): all but the latest, which rank a little lower.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from unidecode import unidecode

from dr.core import verify

_CODE = re.compile(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z]{1,3}-?\d{1,3}[A-Z]?\b")   # B4, S-08, PS1, SH09, A6
_DATES = [
    (re.compile(r"(?<!\d)(\d{1,2})[._\-/](\d{1,2})[._\-/](20\d{2}|\d{2})(?!\d)"), "dmy"),
    (re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)"), "ymd"),
    (re.compile(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)"), "dmy"),
]
_LOW = re.compile(r"reject|kh[oô]ng duy[eệ]t|\bold\b|b[aả]n c[uũ]|\bcu\b|nh[aá]p|draft|h[uủ]y b[oỏ]", re.I)
_HIGH = re.compile(r"\[signed\]|đ[aã] k[yý]|approved|đ[aã] duy[eệ]t|\bduyet\b|^03\. ", re.I)
_MEASURE = re.compile(r"([^\d\n:|;]{3,40}?)\s*[:|]?\s*$")


def doc_date(name: str) -> date | None:
    """The date written in a file name, if it is a real date."""
    for rx, order in _DATES:
        for m in rx.finditer(name):
            a, b, c = (int(x) for x in m.groups())
            y, mo, d = (a, b, c) if order == "ymd" else (c + 2000 if c < 100 else c, b, a)
            try:
                if 2000 <= y <= 2035:
                    return date(y, mo, d)
            except ValueError:
                continue
    return None


def source_weight(path: str, name: str) -> float:
    if _LOW.search(name) or _LOW.search(path.rsplit("/", 1)[-1] if path else ""):
        return 0.5
    if _HIGH.search(name) or _HIGH.search(path or ""):
        return 1.1
    return 1.0


def _fold(s: str) -> str:
    return re.sub(r"\s+", " ", unidecode(s).lower()).strip()


def _values(text: str) -> set:
    return {v for vs in verify.vn_numbers(text) for v in vs}


@dataclass
class Conflict:
    chunk_id: int
    quote: str           # the line of the other passage, verbatim
    value: str           # the number it gives


def _measure(quote: str, number: str) -> str:
    """The words just before the number in the quote: what is measured ('Diện tích thông thủy')."""
    at = quote.find(number)
    m = _MEASURE.search(quote[:at]) if at > 0 else None
    words = re.findall(r"[^\W\d_]+", m.group(1)) if m else []
    return _fold(" ".join(words[-3:])) if len(words) >= 1 else ""


def find(question: str, claim_text: str, claim_quotes: list[str], cited: set[int],
         candidates: dict[int, dict], limit: int = 3) -> list[Conflict]:
    """Lines of other passages that give another number for the same unit and measure as the claim."""
    codes = set(_CODE.findall(question)) | set(_CODE.findall(" ".join(claim_quotes)))
    codes = {c for c in codes if c in question or c in claim_text}
    nums = [m.group(0) for m in verify._NUM.finditer(claim_text)]
    if not codes or not nums:
        return []
    claim_vals = _values(claim_text)
    # only what the question asks about: an answer quoting 'Phòng ngủ 01 10.03 m²' to a usable-area question
    # must not raise a conflict about bedrooms
    fq = _fold(question)
    measures = {m for q in claim_quotes for n in nums if (m := _measure(q, n)) and m in fq}
    if not measures:
        return []
    out: list[Conflict] = []
    seen: set = set()
    for cid, p in candidates.items():
        if cid in cited:
            continue
        in_passage = set(_CODE.findall(p["text"]))
        if not in_passage & codes:
            continue
        for ln in (x for x in p["text"].split("\n") if x.strip()):
            in_line = set(_CODE.findall(ln))
            # the line is about the unit: it names it, or names no unit in a passage about this unit only
            if not (in_line & codes or (not in_line and in_passage <= codes)):
                continue
            fl = _fold(ln)
            at = next((fl.find(m) + len(m) for m in measures if m in fl), -1)
            if at < 0:
                continue
            # the value is the first number after the measure that is not an ordinal ('Phòng ngủ 01')
            first = next((m for m in verify._NUM.finditer(ln[at:]) if not re.fullmatch(r"0\d", m.group(0))), None)
            if not first:
                continue
            vals = _values(first.group(0))
            if not vals or vals & claim_vals or frozenset(vals) in seen:
                continue
            seen.add(frozenset(vals))
            out.append(Conflict(cid, ln.strip(), first.group(0)))
            if len(out) >= limit:
                return out
    return out


_VERSION = re.compile(r"(?<![a-z0-9])(?:v|ver|version|rev|lan|ban)\s?(\d{1,2})(?![0-9])")
_NOISE = re.compile(r"\b(?:final|updated?|cap nhat|moi nhat|new|copy|ban sao|chinh sua|sua|edit|revised)\b|\(\d+\)")


def _stem(name: str) -> str:
    """The file name without extension, dates and version marks: what two versions of a file share."""
    s = _fold(re.sub(r"\.[A-Za-z0-9]{2,5}$", "", name))
    for rx, _ in _DATES:
        s = rx.sub(" ", s)
    s = _NOISE.sub(" ", _VERSION.sub(" ", s))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _version(name: str) -> tuple:
    """(date in the name, version number); None when the name says neither."""
    d = doc_date(name)
    v = _VERSION.search(_fold(name))
    if not d and not v:
        return None
    return (d or date.min, int(v.group(1)) if v else 0)


def older_versions(names: dict[str, str]) -> set[str]:
    """item_id -> name: the items that an item of the same stem with a later date or version supersedes."""
    groups: dict[str, list[tuple[tuple, str]]] = {}
    for it, name in names.items():
        stem, ver = _stem(name), _version(name)
        if len(stem) >= 4 and ver:
            groups.setdefault(stem, []).append((ver, it))
    out: set[str] = set()
    for vs in groups.values():
        latest = max(v for v, _ in vs)
        out |= {it for v, it in vs if v < latest}
    return out
