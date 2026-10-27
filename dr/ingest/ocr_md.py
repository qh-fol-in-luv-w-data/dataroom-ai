"""Markdown instead of OCR: a scanned PDF or an image that has a `.md` in settings.ocr_md_dir is read from it.

The Markdown comes from inference_ocr/ocr_infer.py (PaddleOCR-VL-1.6 on a GPU server) or from
scripts/export_md.py (the whole data room as already indexed here). The tree mirrors the data room (`<folder>/<file name>.md`). Files that went through the SharePoint copy
have shortened folder or file names (`MẶT BẰ~`, scripts/sp_upload.py MAX_PATH): a segment ending in `~` matches
the real one it is the start of. Names are compared in NFC (macOS file names are often NFD).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from dr.config import settings
from dr.ingest.parsers import Block, ParsedDoc

CONVERTER = "PaddleOCR-VL-1.6 (inference_ocr)"
_index: dict[tuple[str, ...], Path] | None = None
_SECTION = re.compile(r"^## (.+?)\s*$", re.M)        # '## Trang 3', '## Trang 1 – Trang 2', '## Ảnh'
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_LABEL = re.compile(r"^Chữ trong ảnh \(OCR toàn ảnh\):\s*$", re.M)
_NO_TEXT = re.compile(r"^_\((ảnh không có chữ, bỏ qua|không đọc được chữ)\)_\s*$", re.M)


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _load() -> dict[tuple[str, ...], Path]:
    global _index
    if _index is None:
        root = Path(settings.ocr_md_dir)
        _index = {tuple(_nfc(s) for s in p.relative_to(root).parts): p for p in root.rglob("*.md")} if root.is_dir() else {}
    return _index


def _same(md: str, real: str) -> bool:
    return md == real or (md.endswith("~") and real.startswith(md[:-1]))


def _same_file(md: str, real: str) -> bool:
    """'abc~.jpg' (stem shortened, extension kept) matches 'abcdef.jpg'."""
    (ms, _, me), (rs, _, re_) = md.rpartition("."), real.rpartition(".")
    return md == real or (me == re_ and _same(ms, rs))


def find(path: str, name: str) -> Path | None:
    """The Markdown of the file `name` in the folder `path`, or None."""
    if not settings.ocr_md_dir:
        return None
    idx = _load()
    want = tuple(_nfc(s) for s in path.strip("/").split("/") if s) + (_nfc(name) + ".md",)
    if want in idx:
        return idx[want]
    hits = [p for k, p in idx.items() if len(k) == len(want)
            and all(_same(a, b) for a, b in zip(k[:-1], want[:-1]))
            and _same_file(k[-1].removesuffix(".md"), want[-1].removesuffix(".md"))]
    return hits[0] if len(hits) == 1 else None


_READER = re.compile(r"<!--\s*đọc bằng:\s*(.+?)\s*-->")


def is_ocr(md: str) -> bool:
    """Whether the Markdown is OCR output. The GPU server's Markdown carries no reader note; scripts/export_md.py
    writes '<!-- đọc bằng: … -->'. A file whose text came from the PDF's own text layer ('pdfium-text', also
    'pdfium-text+…' with some scanned pages) is read from the original instead: typed text is not OCR, must not
    be tone-corrected as OCR, and is what ocr_accents learns from."""
    m = _READER.search(md[:500])
    return not m or not m.group(1).startswith("pdfium")


def parse(md: str, image: bool) -> ParsedDoc:
    """Blocks of the Markdown: one section per place ('## Trang n' / '## <locator>'), paragraphs split on
    blank lines; the section heading is the block's locator ('Ảnh' for a one-page image). The text is cleaned
    with every other format when it is chunked (clean.py: LaTeX units, reader loops, tables as records)."""
    blocks: list[Block] = []
    parts = _SECTION.split(_COMMENT.sub("", md))
    for i in range(1, len(parts) - 1, 2):
        body = _LABEL.sub("", _NO_TEXT.sub("", parts[i + 1]))
        where = "Ảnh" if image and parts[i] == "Trang 1" else parts[i]
        for para in re.split(r"\n\s*\n", body):
            text = para.strip()
            if not text:
                continue
            lines = text.splitlines()
            kind = "table" if sum(" | " in ln for ln in lines) >= max(2, len(lines) // 2) else "text"
            blocks.append(Block(text, where, kind, ocr=True))
    return ParsedDoc(blocks, CONVERTER)
