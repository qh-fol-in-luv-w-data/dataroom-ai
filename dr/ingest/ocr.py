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

import contextlib
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
PDFIUM = threading.RLock()     # pdfium is not thread-safe: every use of it in the ingest path holds this
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
        # chart recognition on: a chart region comes back as its data table (35/35 values on the labelled
        # test charts, ~3 s a chart; Vintern-1B read 26/35)
        _vl = PaddleOCRVL(use_doc_orientation_classify=False, use_doc_unwarping=False, use_chart_recognition=True,
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


_GROUPED = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?")   # Vietnamese: 1.234.567,89


def bad_format(n: str) -> bool:
    """A dot-grouped number whose groups are not all 3 digits (e.g. 1.555.36 for 1.555,36):
    both readers can make the same comma/dot mistake, but the format gives it away."""
    if "/" in n or ":" in n or "-" in n or "." not in n:
        return False
    return not _GROUPED.fullmatch(n)            # Vietnamese decimals use a comma, never a dot


def cross_check(text: str, lines) -> tuple[list[str], int]:
    """Numbers in the VLM text that the independent latin reader did not also read, or whose
    Vietnamese number format is impossible."""
    second = "".join((ln.text if hasattr(ln, "text") else ln["text"]) for ln in lines).replace(" ", "")
    nums = numbers_in(text)
    return [n for n in nums if n not in second or bad_format(n)], len(nums)


def _page_images(path: str) -> list[Image.Image]:
    if path.lower().endswith(".pdf"):
        import pypdfium2 as pdfium
        with PDFIUM:
            pdf = pdfium.PdfDocument(path)
            out = []
            try:
                for page in pdf:
                    scale = min(200 / 72, 2400 / page.get_width())   # ~200 dpi, capped
                    out.append(page.render(scale=scale).to_pil())
                    page.close()
            finally:
                pdf.close()
        return out
    img = Image.open(path)
    img.load()
    return [img]


def _cache(key: str, n: int, img: Image.Image, lines) -> None:
    d = settings.data_dir / "cache" / "ocr" / key
    d.mkdir(parents=True, exist_ok=True)
    if settings.tenant_mode != "m365":      # production keeps only line boxes, never page images (plan §4.4)
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
            elif label == "chart" and content.strip():
                content = "Biểu đồ (ảnh, số đọc bằng PaddleOCR-VL):\n" + _html_table_to_text(content).strip()
            if content.strip():
                p.blocks.append(OcrBlock(label, content.strip()))
    return p


def ocr_file(path: str, clean: bool = True) -> list[OcrPage]:
    """OCR an image or an (image-only) PDF; returns one OcrPage per page."""
    from dr.ingest import preprocess

    key = hashlib.sha1(Path(path).read_bytes()).hexdigest()
    use_vl = settings.ocr_engine == "vl"
    if use_vl and not vl_available():
        # no silent fallback to the weaker latin reader: the item fails with the reason and is retried later
        raise RuntimeError(f"OCR server PaddleOCR-VL chưa chạy ({settings.ocr_server_url}): chạy `make ocr-server`")
    use_vintern = settings.ocr_engine == "vintern"
    # the same picture is often in several files (copies in other folders, a logo in every docx):
    # its OCR result is kept per (content hash, engine, clean) and read back instead of OCR-ing it again
    done = settings.data_dir / "cache" / "ocr" / key / f"pages-{settings.ocr_engine}-c-{int(clean)}.json"  # c: with charts
    def load(f: Path) -> list[OcrPage]:
        return [OcrPage(page=p["page"], blocks=[OcrBlock(**b) for b in p["blocks"]], engine=p["engine"],
                        steps=p["steps"], doubt=p["doubt"], numbers=p["numbers"], key=key)
                for p in json.loads(f.read_text(encoding="utf-8"))]

    def save(pages: list[OcrPage]) -> None:
        done.write_text(json.dumps([{"page": p.page, "blocks": [{"label": b.label, "text": b.text} for b in p.blocks],
                                     "engine": p.engine, "steps": p.steps, "doubt": p.doubt, "numbers": p.numbers}
                                    for p in pages], ensure_ascii=False), encoding="utf-8")

    if done.exists():
        return load(done)
    before_charts = done.with_name(f"pages-{settings.ocr_engine}-{int(clean)}.json")
    if use_vintern and before_charts.exists():
        # read before chart reading existed: keep its text, only add the charts of each page
        from dr.ingest import charts
        pages = load(before_charts)
        for page, img in zip(pages, _page_images(path)):
            page.blocks += [OcrBlock("chart", t) for t in charts.read(img.convert("RGB"))]
        save(pages)
        return pages
    pages = []
    # PaddleOCR-VL is one pipeline: one page at a time. With Vintern the CPU clean-up (preprocess, own lock)
    # and the GPU reader (vintern, own lock) overlap across workers instead of waiting for each other.
    with (contextlib.nullcontext() if use_vintern else _lock):
        if done.exists():                     # another worker read the same picture while this one waited
            return ocr_file(path, clean)
        for n, img in enumerate(_page_images(path), start=1):
            cross = settings.ocr_cross_check or not (use_vintern or use_vl)
            prep = preprocess.prepare(img, with_lines=cross) if clean else preprocess.Prepared(img.convert("RGB"))
            if not clean:
                prep.lines = preprocess.read_lines(np.asarray(prep.image))
            page = None
            if use_vl and 0 <= prep.text_boxes < settings.ocr_min_text_boxes:
                page = OcrPage(page=n, engine="PaddleOCR-VL-1.6")      # a photo / render without text
            elif use_vl:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    prep.image.save(f.name)
                try:
                    page = _vl_page(f.name, n)       # a failure fails the item: no other reader is used
                finally:
                    os.unlink(f.name)
            if use_vintern:
                # no fallback: when Vintern is the chosen reader a failure fails the item (status 'error'
                # with the reason), it is never silently read by another model
                from dr.ingest import vintern
                if 0 <= prep.text_boxes < settings.ocr_min_text_boxes:
                    text = ""                     # a photo / render without text: nothing for the reader
                else:
                    sparse = 0 <= prep.text_boxes < 40          # a banner or slide, not a dense page
                    text = vintern.markdown_tables_to_text(vintern.read(prep.image, sparse=sparse))
                page = OcrPage(page=n, engine="Vintern-1B-v3.5",
                               blocks=[OcrBlock("text", t.strip()) for t in re.split(r"\n\s*\n", text) if t.strip()])
                from dr.ingest import charts       # charts drawn on the page: read again as data tables
                page.blocks += [OcrBlock("chart", t) for t in charts.read(prep.image)]
            if page is None:      # second reader alone (digits fine, Vietnamese diacritics weak)
                page = OcrPage(page=n, engine="PP-OCRv5-latin",
                               blocks=[OcrBlock("text", ln.text) for ln in prep.lines])
            page.steps = prep.steps
            page.doubt, page.numbers = cross_check(page.text, prep.lines) if (use_vl or use_vintern) and prep.lines \
                else ([], 0)
            page.key = key
            _cache(key, n, prep.image, prep.lines)
            pages.append(page)
    save(pages)
    return pages


def ocr_bytes(data: bytes, suffix: str) -> list[OcrPage]:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        return ocr_file(tmp)
    finally:
        os.unlink(tmp)
