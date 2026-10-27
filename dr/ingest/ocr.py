"""OCR / document structure with PaddleOCR.

Engine (settings.ocr_engine):
- ``vl`` (default): PaddleOCR-VL-1.6 (layout detection PP-DocLayoutV3 + 0.9B VLM recogniser, chart
  recognition on), the VLM served by mlx-vlm on the Apple GPU (``make ocr-server``). If the server is
  down the item fails with the reason and is retried later: it is never read by another model.
- ``ppocr``: PP-OCRv5 det + latin_PP-OCRv5_mobile_rec only (CPU, no server; weak on Vietnamese
  diacritics) — for machines without the VL server.

Every page is cleaned up first (preprocess.py: perspective, lighting, fax noise, upscaling,
orientation, skew). With DR_OCR_CROSSCHECK=1 the latin PP-OCRv5 reader also reads the cleaned page as
an independent second opinion: a number the VLM produced that the second reader does not see is
recorded as *doubtful*, and answers quoting it are marked "chưa chắc".
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
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


_MATH = re.compile(r"\$([^$\n]{0,60})\$")
_SUP = {"2": "²", "3": "³", "(2)": "²", "(3)": "³"}
_TEX = {r"\Phi": "Φ", r"\phi": "φ", r"\pm": "±", r"\times": "×", r"\checkmark": "✓", r"\cdot": "·",
        r"\geq": "≥", r"\leq": "≤", r"\%": "%", r"\circ": "°"}


def clean_math(text: str) -> str:
    """PaddleOCR-VL writes units and symbols as LaTeX ('52.55 $ m^{{2}} $', '$ \\Phi 300 $'): plain text
    instead, so the reader, the search and the number checks see '52.55 m²', 'Φ 300'. Only fragments that
    are LaTeX (or empty) are touched; a '$' from a broken PDF font is left as it is."""
    def one(m: re.Match) -> str:
        s = m.group(1).strip()
        if s and not re.search(r"[\\^{}]", s) and not re.fullmatch(r"[=+\-±×]", s):
            return m.group(0)
        s = re.sub(r"\^\{+\s*(\(?\d\)?)\s*\}+", lambda x: _SUP.get(x.group(1), x.group(1)), s)
        s = re.sub(r"\^(\d)", lambda x: _SUP.get(x.group(1), x.group(1)), s)
        for _ in range(3):                    # nested: \underline{\text{Don vi}}
            s = re.sub(r"\\(?:text|textbf|mathrm|underline|overline|underset\{[^{}]*\})\s*\{([^{}]*)\}", r"\1", s)
        for k, v in _TEX.items():
            s = s.replace(k, v)
        return " " + re.sub(r"[{}\\]", "", s).strip() + " " if s else " "
    return re.sub(r"(\S) +([²³])", r"\1\2", re.sub(r"[ \t]{2,}", " ", _MATH.sub(one, text)))


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
            content = clean_math(b.get("block_content") or "")
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
    # the same picture is often in several files (copies in other folders, a logo in every docx):
    # its OCR result is kept per (content hash, engine, clean) and read back instead of OCR-ing it again
    done = settings.data_dir / "cache" / "ocr" / key / f"pages-{settings.ocr_engine}-c-{int(clean)}.json"  # c: with charts
    def load(f: Path) -> list[OcrPage]:
        return [OcrPage(page=p["page"], blocks=[OcrBlock(b["label"], clean_math(b["text"])) for b in p["blocks"]],
                        engine=p["engine"], steps=p["steps"], doubt=p["doubt"], numbers=p["numbers"], key=key)
                for p in json.loads(f.read_text(encoding="utf-8"))]

    def save(pages: list[OcrPage]) -> None:
        done.write_text(json.dumps([{"page": p.page, "blocks": [{"label": b.label, "text": b.text} for b in p.blocks],
                                     "engine": p.engine, "steps": p.steps, "doubt": p.doubt, "numbers": p.numbers}
                                    for p in pages], ensure_ascii=False), encoding="utf-8")

    if done.exists():
        return load(done)
    pages = []
    with _lock:                               # PaddleOCR-VL is one pipeline: one page at a time
        if done.exists():                     # another worker read the same picture while this one waited
            return ocr_file(path, clean)
        for n, img in enumerate(_page_images(path), start=1):
            cross = settings.ocr_cross_check or not use_vl
            prep = preprocess.prepare(img, with_lines=cross) if clean else preprocess.Prepared(img.convert("RGB"))
            if not clean:
                prep.lines = preprocess.read_lines(np.asarray(prep.image))
            if use_vl and 0 <= prep.text_boxes < settings.ocr_min_text_boxes:
                page = OcrPage(page=n, engine="PaddleOCR-VL-1.6")      # a photo / render without text
            elif use_vl:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    prep.image.save(f.name)
                try:
                    page = _vl_page(f.name, n)       # a failure fails the item: no other reader is used
                finally:
                    os.unlink(f.name)
            else:                 # ppocr: the latin reader alone (digits fine, Vietnamese diacritics weak)
                page = OcrPage(page=n, engine="PP-OCRv5-latin",
                               blocks=[OcrBlock("text", ln.text) for ln in prep.lines])
            page.steps = prep.steps
            page.doubt, page.numbers = cross_check(page.text, prep.lines) if use_vl and prep.lines else ([], 0)
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
