"""OCR / document structure with PaddleOCR.

Primary engine: PaddleOCR-VL-1.6 (layout detection PP-DocLayoutV3 + 0.9B VLM recogniser),
with the VLM served by mlx-vlm on the Apple GPU (``make ocr-server``). It reads
Vietnamese diacritics, tables and seals far better than the latin PP-OCR models.
Fallback engine: PP-OCRv5 (det) + latin_PP-OCRv5_mobile_rec — used if the VL server is
not reachable, so ingestion never silently skips scanned pages.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field

import httpx

from dr.config import settings

log = logging.getLogger("ocr")
_lock = threading.Lock()
_vl = None
_pp = None


@dataclass
class OcrBlock:
    label: str   # text | table | seal | title | ...
    text: str


@dataclass
class OcrPage:
    page: int
    blocks: list[OcrBlock] = field(default_factory=list)
    engine: str = ""

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


def _pp_pipeline():
    global _pp
    if _pp is None:
        from paddleocr import PaddleOCR
        _pp = PaddleOCR(text_detection_model_name="PP-OCRv5_mobile_det",
                        text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
                        use_doc_orientation_classify=False, use_doc_unwarping=False,
                        use_textline_orientation=False)
    return _pp


def _html_table_to_text(html: str) -> str:
    if "<table" not in html.lower():
        return html
    from bs4 import BeautifulSoup
    rows = []
    for tr in BeautifulSoup(html, "lxml").find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def ocr_file(path: str) -> list[OcrPage]:
    """OCR an image or an (image-only) PDF; returns one OcrPage per page."""
    engine = settings.ocr_engine
    with _lock:  # the pipelines are not thread-safe
        if engine == "vl" and vl_available():
            try:
                pages = []
                for i, r in enumerate(_vl_pipeline().predict(path)):
                    res = r.json["res"]
                    p = OcrPage(page=int(res.get("page_index") or i) + 1, engine="PaddleOCR-VL-1.6")
                    for b in res.get("parsing_res_list", []):
                        label = b.get("block_label", "text")
                        content = b.get("block_content") or ""
                        if label == "table":
                            content = _html_table_to_text(content)
                        elif label == "seal":
                            content = f"[Con dấu: {content}]"
                        if content.strip():
                            p.blocks.append(OcrBlock(label, content.strip()))
                    pages.append(p)
                return pages
            except Exception:
                log.exception("PaddleOCR-VL failed, falling back to PP-OCRv5")
        pages = []
        for i, r in enumerate(_pp_pipeline().predict(path)):
            res = r.json["res"]
            p = OcrPage(page=int(res.get("page_index") or i) + 1, engine="PP-OCRv5-latin")
            p.blocks = [OcrBlock("text", t) for t in res.get("rec_texts", []) if t.strip()]
            pages.append(p)
        return pages


def ocr_bytes(data: bytes, suffix: str) -> list[OcrPage]:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        return ocr_file(tmp)
    finally:
        os.unlink(tmp)
