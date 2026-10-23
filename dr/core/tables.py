"""Deterministic answers over spreadsheet rows (the parser writes each row as 'column: value; …').

A 7B model asked "which agency is cheapest" over a whole sheet copied the right figure but put the
wrong row's name next to it. Smallest/largest is arithmetic, so it is done here: the rows of the
sheet the user can read are parsed, the column the question names is chosen by its words, and the
answer cites the row itself (verbatim, so the normal verifier still checks it).
"""
from __future__ import annotations

import re
from decimal import Decimal

from unidecode import unidecode

from dr.core import intent
from dr.core.verify import vn_numbers

MIN_Q = re.compile(r"\b(thap nhat|re nhat|nho nhat|it nhat|ngan nhat|lowest|cheapest|smallest|least|minimum)\b")
MAX_Q = re.compile(r"\b(cao nhat|dat nhat|lon nhat|nhieu nhat|dai nhat|highest|largest|most expensive|maximum)\b")
_KEY_SKIP = re.compile(r"^(stt|no|tt|#)$", re.I)


def _cells(line: str) -> list[tuple[str, str]]:
    out = []
    for part in line.split("; "):
        name, sep, val = part.partition(": ")
        out.append((name.strip(), val.strip()) if sep else ("", part.strip()))
    return out


def _number(val: str) -> Decimal | None:
    vals = vn_numbers(val)
    if len(vals) != 1:                       # "15–20 ngày", ranges and notes are not a single figure
        return None
    return max(vals[0])


def _label(cells: list[tuple[str, str]]) -> tuple[str, str] | None:
    """The cell that names the row: the first short non-numeric value (TÊN: GJDC, Mã căn: SH09)."""
    for name, val in cells[:4]:
        if val and len(val) <= 60 and not _KEY_SKIP.match(name) and _number(val) is None:
            return name, val
    return None


def _rows(passages: list[dict]) -> list[tuple]:
    rows = []                                 # (label, column, value, value text, line, chunk_id)
    for p in passages:
        for line in p["text"].split("\n"):
            cells = _cells(line)
            lab = _label(cells)
            if not lab or len(cells) < 3:
                continue
            for name, val in cells:
                num = _number(val) if name else None
                if num is not None:
                    rows.append((lab, name, num, val, line, p["chunk_id"]))
    return rows


def _column(question: str, rows: list[tuple], min_labels: int = 2) -> str | None:
    """The numeric column whose header words best match the question."""
    q_terms = intent.key_terms(question)
    by_col: dict[str, set] = {}
    for r in rows:
        by_col.setdefault(r[1], set()).add(r[0][1])
    scored = []
    for col, labels in by_col.items():
        if len(labels) < min_labels:
            continue
        terms = intent.key_terms(col)
        hit = len(q_terms & terms)
        if hit:
            scored.append((hit / max(1, len(terms)) + hit, col))
    return max(scored)[1] if scored else None


def compare(question: str, passages: list[dict]) -> tuple[dict, dict] | None:
    """A question naming two or more rows of the sheet (BNF và MIX MEDIA): the asked column of each
    named row, one claim per row citing that row. None if fewer than two named rows have the column."""
    rows = _rows(passages)
    q = f" {unidecode(question).lower()} "
    named = {r[0][1] for r in rows if f" {unidecode(r[0][1]).lower()} " in q}
    if len(named) < 2:
        return None
    col = _column(question, [r for r in rows if r[0][1] in named])
    if not col:
        return None
    picked: dict[str, tuple] = {}
    for r in rows:
        if r[0][1] in named and r[1] == col:
            picked.setdefault(r[0][1], r)
    if len(picked) < 2:
        return None
    claims, labels = [], {}
    for k, ((lab_name, lab_val), _, _, val, line, cid) in enumerate(picked.values(), 1):
        claims.append({"text": f"{lab_name or 'Dòng'} {lab_val}: {col} là {val}.",
                       "citations": [{"doc": f"T{k}", "quote": line}]})
        labels[f"T{k}"] = cid
    return {"claims": claims, "no_answer": False}, labels


def extreme(question: str, passages: list[dict]) -> tuple[dict, dict] | None:
    """(raw claims, labels) in the LLM output shape, or None when the question is not a
    smallest/largest question over rows or no column fits it. passages: [{chunk_id, text}]."""
    q = unidecode(question).lower()
    lowest = bool(MIN_Q.search(q))
    if not lowest and not MAX_Q.search(q):
        return None
    rows = _rows(passages)
    col = _column(question, rows) if rows else None
    if not col:
        return None
    best: dict[str, tuple] = {}
    for r in (r for r in rows if r[1] == col):  # one value per row (a long row may come in several pieces)
        best.setdefault(r[0][1], r)
    pick = (min if lowest else max)(best.values(), key=lambda r: r[2])
    (lab_name, lab_val), _, _, val, line, cid = pick
    word = "thấp nhất" if lowest else "cao nhất"
    text = f"{lab_name or 'Dòng'} {lab_val} có {col} {word} trong bảng: {val}."
    return ({"claims": [{"text": text, "citations": [{"doc": "T1", "quote": line}]}], "no_answer": False},
            {"T1": cid})
