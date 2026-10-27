"""Clean-up of extracted text before it is chunked, embedded and read by the LLM — every format goes through it.

What it removes or rewrites (counts from the CT Group data room, 52,083 chunks before clean-up):
- control characters and lines of a broken PDF font (`$¤1+2£$`, 1.1%);
- HTML / Markdown left by the readers (`<br>`, `<td>`, `**`, 0.3%), LaTeX units from PaddleOCR-VL (ocr.clean_math);
- runs of the same character in blank forms (`Số: ..........`, `-----`, `0000000000`, 1.8%) and phrases a reader
  repeated over and over (2.4%);
- page headers / footers repeated on most pages of a document (`Page30`, the company letterhead);
- OCR tables: a '|' table whose first row is a header becomes one record per row, `Header: value; …`, the form
  the Excel rows already have (a small LLM read `| PS1 | 303.09 m² | 321.56 m² |` without knowing which column
  was which);
- OCR text only: tone marks the reader got wrong, corrected from the typed documents of the room
  (ocr_accents.py: `CẢN HỘ` -> `CĂN HỘ`, `HỘP ĐÔNG` -> `HỢP ĐỒNG`), and a label and its value read onto two lines
  joined (`GIẢI NHẤT` / `1 lượng vàng 9999` -> `GIẢI NHẤT: 1 lượng vàng 9999`).
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from dr.ingest.ocr import clean_math

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏⁠﻿]")
_HTML = re.compile(r"</?(?:br|p|div|span|td|th|tr|table|tbody|thead|b|i|u|strong|em|sup|sub)\b[^>]*>", re.I)
_RUN = re.compile(r"([.\-_=*~·…])\1{3,}|(\d)\2{9,}")
_LOOP = re.compile(r"(\S.{3,80}?)(?:\s*\1){4,}")
_WEIRD = re.compile(r"[^\w\s.,;:!?%()\[\]/\\'\"“”‘’&@#+\-=*<>|°²³±×÷€$₫–—…·•✓→←↑↓]")


def _garbage(line: str) -> bool:
    """A line of a broken font: mostly symbols that are neither letters, digits nor punctuation."""
    s = line.strip()
    return len(s) >= 4 and len(_WEIRD.findall(s)) > 0.3 * len(s)


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace(" ", " ")
    text = _CONTROL.sub(" ", text)
    text = _HTML.sub(lambda m: "\n" if m.group(0).lower().startswith(("<br", "<p", "<div", "<tr")) else " ", text)
    text = re.sub(r"\*\*|__", "", clean_math(text))
    text = _RUN.sub(lambda m: (m.group(1) * 3) if m.group(1) else m.group(2) * 3 + "…", text)
    text = _LOOP.sub(lambda m: f"{m.group(1)} {m.group(1)} …", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if not _garbage(ln)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def join_label_lines(text: str) -> str:
    """OCR of a poster or a plan puts a label and its value on two lines ('GIẢI NHẤT' / '1 lượng vàng 9999',
    'CĂN S-08' / '28.4 m²/31.2 m²'): one line 'label: value', so the sentence the reader keeps has both."""
    lines = text.split("\n")
    out: list[str] = []
    for ln in lines:
        prev = out[-1].strip() if out else ""
        if (prev and 2 <= len(prev) <= 30 and not re.search(r"[:.;,!?|]$", prev) and "|" not in ln
                and re.match(r"\s*\d", ln) and len(ln.strip()) <= 60):
            out[-1] = f"{prev}: {ln.strip()}"
        else:
            out.append(ln)
    return "\n".join(out)


def _cells(line: str) -> list[str]:
    """Cells of a '|' row. Only a Markdown frame ('| a | b |') is taken off: ' | PS1 | 303.09' keeps its empty
    first cell, which is what lines it up with the header."""
    s = line.strip()
    if s.startswith("|") and s.endswith("|") and len(s) > 1:
        s = s[1:-1]
    return [c.strip() for c in s.split("|")]


def _is_header(cells: list[str]) -> bool:
    named = [c for c in cells if c]
    return (len(named) >= 2 and len(named) >= len(cells) - 1
            and sum(bool(re.search(r"\d", c)) for c in named) <= len(named) // 3)


def table_records(text: str) -> str:
    """'H1 | H2 | H3' then rows 'a | b | c'  ->  'H1: a; H2: b; H3: c' per row. A row the reader gave another
    width (a cell lost) stays as it is. Left as it is when the first row is not a header, fewer than two rows,
    or most rows do not have the header's width."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    rows = [ln for ln in lines if "|" in ln]
    if len(rows) < 3 or len(rows) < len(lines) - 2:
        return text
    head_at = lines.index(rows[0])
    head = _cells(rows[0])
    fit = [len(_cells(r)) == len(head) for r in rows[1:]]
    if lines[head_at:head_at + len(rows)] != rows or not _is_header(head) or sum(fit) * 2 < len(fit):
        return text
    out = lines[:head_at]
    for r, ok in zip(rows[1:], fit):
        pairs = [f"{h}: {v}" for h, v in zip(head, _cells(r)) if v and h] if ok else []
        if pairs or not ok:
            out.append("; ".join(pairs) if ok else r)
    out += lines[head_at + len(rows):]
    return "\n".join(out)


def drop_repeated_lines(pages: dict[str, list[str]], min_pages: int = 3, share: float = 0.5) -> set[str]:
    """Lines (header / footer / letterhead) found on at least `share` of the pages of a document with at least
    `min_pages` pages: the set of such lines, to be kept on their first page only."""
    if len(pages) < min_pages:
        return set()
    seen = Counter(ln for lines in pages.values() for ln in {x.strip() for x in lines if 3 <= len(x.strip()) <= 120})
    return {ln for ln, n in seen.items() if n >= max(min_pages, share * len(pages))}
