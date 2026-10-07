"""OCR / document structure with PaddleOCR.

Primary engine: PaddleOCR-VL-1.6 (layout detection PP-DocLayoutV3 + 0.9B VLM recogniser),
with the VLM served by mlx-vlm on the Apple GPU (``make ocr-server``). It reads
Vietnamese diacritics, tables and seals far better than the latin PP-OCR models.
Fallback engine: PP-OCRv5 (det) + latin_PP-OCRv5_mobile_rec — used if the VL server is
not reachable, so ingestion never silently skips scanned pages.

Every page is cleaned up first (preprocess.py: perspective, lighting, fax noise, upscaling,
orientation, skew). The latin PP-OCRv5 reader then reads the same cleaned page as an
independent second opinion: a number the VLM produced that the second reader does not
see is recorded as *doubtful*, and answers quoting it are marked "chưa chắc".
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field

import hashlib
import json
import re
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from dr.config import settings

log = logging.getLogger("ocr")
_lock = threading.Lock()
_vl = None


@dataclass
class OcrBlock:
    label: str   # text | table | seal | title | ...
    text: str


@dataclass
class OcrPage:
    page: int
    blocks: list[OcrBlock] = field(default_factory=list)
    engine: str = ""
    steps: list[str] = field(default_factory=list)      # clean-up applied to the page
    doubt: list[str] = field(default_factory=list)      # numbers the second reader did not confirm
    numbers: int = 0                                    # numbers checked on the page
    key: str | None = None                              # cache key of the cleaned page image + lines

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.text)


def vl_available() -> bool:
    try:
        return httpx.get(settings.ocr_server_url.rstrip("/") + "/v1/models", timeout=2).status_code == 200
    except Exception:
        return False


def _vl_pipeline():
    global _vl
    if _vl is None:
        from paddleocr import PaddleOCRVL
        _vl = PaddleOCRVL(use_doc_orientation_classify=False, use_doc_unwarping=False,
                          vl_rec_backend="mlx-vlm-server", vl_rec_server_url=settings.ocr_server_url,
                          vl_rec_api_model_name=settings.ocr_vl_model)
    return _vl


def _html_table_to_text(html: str) -> str:
    if "<table" not in html.lower():
        return html
    from bs4 import BeautifulSoup
    rows = []
    for tr in BeautifulSoup(html, "lxml").find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        rows.append(" | ".join(cells))
    return "\n".join(rows)


_NUM = re.compile(r"\d[\d.,/:\-]*\d")


def numbers_in(text: str) -> list[str]:
    """Numbers worth checking: at least 3 digits (amounts, capacities, dates, codes)."""
    return [n for n in dict.fromkeys(_NUM.findall(text)) if sum(ch.isdigit() for ch in n) >= 3]


def cross_check(text: str, lines) -> tuple[list[str], int]:
    """Numbers in the VLM text that the independent latin reader did not also read."""
    second = "".join(ln.text for ln in lines).replace(" ", "")
    nums = numbers_in(text)
    return [n for n in nums if n not in second], len(nums)


def _page_images(path: str) -> list[Image.Image]:
    if path.lower().endswith(".pdf"):
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(path)
        out = []
        for page in pdf:
            scale = min(200 / 72, 2400 / page.get_width())   # ~200 dpi, capped
            out.append(page.render(scale=scale).to_pil())
        return out
    img = Image.open(path)
    img.load()
    return [img]


def _cache(key: str, n: int, img: Image.Image, lines) -> None:
    d = settings.data_dir / "cache" / "ocr" / key
    d.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(d / f"p{n}.jpg", quality=85)
    (d / f"p{n}.json").write_text(json.dumps([{"text": ln.text, "score": round(ln.score, 3), "box": ln.box}
                                              for ln in lines], ensure_ascii=False))


def cached_page(key: str, n: int) -> tuple[Path, list[dict]] | None:
    d = settings.data_dir / "cache" / "ocr" / key
    if not re.fullmatch(r"[0-9a-f]{40}", key) or not (d / f"p{n}.jpg").exists():
        return None
    return d / f"p{n}.jpg", json.loads((d / f"p{n}.json").read_text())


def _vl_page(png: str, n: int) -> OcrPage:
    p = OcrPage(page=n, engine="PaddleOCR-VL-1.6")
    for r in _vl_pipeline().predict(png):
        for b in r.json["res"].get("parsing_res_list", []):
            label = b.get("block_label", "text")
            content = b.get("block_content") or ""
            if label == "table":
                content = _html_table_to_text(content)
            elif label == "seal":
                content = f"[Con dấu: {content}]"
            if content.strip():
                p.blocks.append(OcrBlock(label, content.strip()))
    return p


def ocr_file(path: str, clean: bool = True) -> list[OcrPage]:
    """OCR an image or an (image-only) PDF; returns one OcrPage per page."""
    from dr.ingest import preprocess

    key = hashlib.sha1(Path(path).read_bytes()).hexdigest()
    use_vl = settings.ocr_engine == "vl" and vl_available()
    pages = []
    with _lock:  # the pipelines are not thread-safe
        for n, img in enumerate(_page_images(path), start=1):
            prep = preprocess.prepare(img) if clean else preprocess.Prepared(img.convert("RGB"))
            if not clean:
                prep.lines = preprocess.read_lines(np.asarray(prep.image))
            page = None
            if use_vl:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    prep.image.save(f.name)
                try:
                    page = _vl_page(f.name, n)
                except Exception:
                    log.exception("PaddleOCR-VL failed on page %s, falling back to PP-OCRv5", n)
                finally:
                    os.unlink(f.name)
            if page is None:      # second reader alone (digits fine, Vietnamese diacritics weak)
                page = OcrPage(page=n, engine="PP-OCRv5-latin",
                               blocks=[OcrBlock("text", ln.text) for ln in prep.lines])
            page.steps = prep.steps
            page.doubt, page.numbers = cross_check(page.text, prep.lines) if use_vl else ([], 0)
            page.key = key
            _cache(key, n, prep.image, prep.lines)
            pages.append(page)
    return pages


def ocr_bytes(data: bytes, suffix: str) -> list[OcrPage]:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        return ocr_file(tmp)
    finally:
        os.unlink(tmp)
