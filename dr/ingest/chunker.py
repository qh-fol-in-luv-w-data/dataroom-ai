"""Split parsed blocks into retrieval chunks and flag likely prompt injections."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from unidecode import unidecode

from dr.ingest.parsers import Block

INJECTION_PATTERNS = [
    r"bỏ qua (mọi|tất cả|các) (hướng dẫn|chỉ dẫn|chỉ thị|quy tắc)",
    r"không tuân theo (hướng dẫn|quy tắc)",
    r"liệt kê toàn bộ (nội dung|tài liệu)",
    r"ignore (all |any )?(previous|prior|above) (instructions|rules)",
    r"disregard (all |the )?(previous|above)",
    r"system prompt|lời nhắc hệ thống",
    r"bạn (bây giờ )?là (một )?(trợ lý|ai) (không|mới)",
    r"<\s*/?\s*(system|assistant|untrusted_document)",
]
_INJ = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


@dataclass
class Chunk:
    text: str
    locator: str
    kind: str
    ordinal: int
    ocr: bool
    injection_flag: bool


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ")
    text = re.sub(r"[​-‏⁠﻿]", "", text)  # zero-width / invisible
    return re.sub(r"[ \t]+", " ", text).strip()


def fold(text: str) -> str:
    """Accent-folded lowercase form for unaccented queries."""
    return unidecode(text).lower()


def is_injection(text: str) -> bool:
    return bool(_INJ.search(text))


def _split(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?;:])\s+|\n+", text):
        if not sent:
            continue
        if len(cur) + len(sent) + 1 > max_chars and cur:
            parts.append(cur.strip())
            cur = ""
        while len(sent) > max_chars:
            parts.append(sent[:max_chars])
            sent = sent[max_chars:]
        cur += sent + " "
    if cur.strip():
        parts.append(cur.strip())
    return parts


def chunk(blocks: list[Block], max_chars: int = 800) -> list[Chunk]:
    out: list[Chunk] = []
    buf: list[Block] = []

    def flush():
        if not buf:
            return
        text = "\n".join(b.text for b in buf)
        loc = buf[0].locator if buf[0].locator == buf[-1].locator else f"{buf[0].locator} – {buf[-1].locator}"
        for piece in _split(text, max_chars):
            out.append(Chunk(piece, loc, buf[0].kind, len(out), any(b.ocr for b in buf), is_injection(piece)))
        buf.clear()

    for b in blocks:
        t = normalize(b.text)
        if not t:
            continue
        b = Block(t, b.locator, b.kind, b.ocr, b.meta)
        if b.kind in ("table", "sheet", "slide", "email_header"):
            flush()
            for piece in _split(t, max_chars * 2 if b.kind in ("table", "sheet") else max_chars):
                out.append(Chunk(piece, b.locator, b.kind, len(out), b.ocr, is_injection(piece)))
            continue
        cur_len = sum(len(x.text) for x in buf)
        if buf and (cur_len + len(t) > max_chars or buf[0].locator.split(" ›")[0] != b.locator.split(" ›")[0]):
            flush()
        buf.append(b)
    flush()
    for i, c in enumerate(out):
        c.ordinal = i
    return out
