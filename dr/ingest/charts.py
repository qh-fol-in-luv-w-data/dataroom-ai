"""Charts drawn as pictures on a PDF page with a text layer: find them, read them as numbers.

PP-DocLayoutV3 finds the chart regions of a page (6/6 test charts found, no false hit on scans, tables or
photos; ~1.2 s a page on the CPU). Only a page with a chart region is read by PaddleOCR-VL with chart
recognition (35/35 values on the labelled test charts, ~3 s a chart): a page whose picture is a logo or a
signature costs the layout check only, not a whole VL page read (~60 s).

Scanned pages and images do not come here: their charts are read with the rest of the page (ocr.py).
Native Office charts are not pictures: their numbers are read from the chart part (parsers.chart_text).
"""
from __future__ import annotations

import tempfile
import threading

from PIL import Image

_lock = threading.Lock()
_layout = None
MIN_SCORE = 0.5
MIN_SIDE = 120          # px: smaller "charts" are icons or sparklines, not readable


def _model():
    global _layout
    if _layout is None:
        from paddleocr import LayoutDetection
        _layout = LayoutDetection(model_name="PP-DocLayoutV3")
    return _layout


def find(img: Image.Image) -> list[tuple[int, int, int, int]]:
    """Boxes (x0, y0, x1, y1) of the charts on a page image."""
    with _lock, tempfile.NamedTemporaryFile(suffix=".png") as f:
        img.convert("RGB").save(f.name)
        boxes = _model().predict(f.name)[0].json["res"]["boxes"]
    out = []
    for b in boxes:
        if b["label"] != "chart" or b["score"] < MIN_SCORE:
            continue
        x0, y0, x1, y1 = (int(v) for v in b["coordinate"])
        if x1 - x0 >= MIN_SIDE and y1 - y0 >= MIN_SIDE:
            out.append((x0, y0, x1, y1))
    return out


def read(img: Image.Image) -> list[str]:
    """Each chart of the page as text: 'Biểu đồ (ảnh, số đọc bằng PaddleOCR-VL):' then its data table."""
    if not find(img):
        return []
    from dr.ingest.ocr import _lock as vl_lock, _vl_page
    with vl_lock, tempfile.NamedTemporaryFile(suffix=".png") as f:   # the VL pipeline is not thread-safe
        img.convert("RGB").save(f.name)
        page = _vl_page(f.name, 1)
    return [b.text for b in page.blocks if b.label == "chart"]
