"""Charts drawn as pictures (screenshots, scans, PDF figures): find them, read them as numbers.

PP-DocLayoutV3 finds the chart regions of a page (6/6 test charts found, no false hit on scans,
tables or photos; ~1.2 s a page on the CPU). Each region is cropped and Vintern-1B-v3.5 is asked for
the chart as a data table. On a labelled test set Vintern read 26/35 values (74%, ~5 s a chart):
bars, stacked bars, pies, unlabelled bars estimated from the axis; a line chart with two series is
its weak spot (values of the two lines mixed). deepseek-ocr 46%, qwen3-vl:8b 23% (57 s), glm-ocr 20%.

Native Office charts are not pictures: their numbers are read from the chart part (parsers.chart_text).
"""
from __future__ import annotations

import logging
import tempfile
import threading

from PIL import Image

log = logging.getLogger("charts")
_lock = threading.Lock()
_layout = None
MIN_SCORE = 0.5
MIN_SIDE = 120          # px: smaller "charts" are icons or sparklines, not readable
PROMPT = ("Đây là một biểu đồ. Chuyển biểu đồ thành bảng dữ liệu Markdown: mỗi dòng là một nhãn (hạng mục) "
          "và giá trị của từng chuỗi dữ liệu. Ghi tiêu đề biểu đồ ở dòng đầu. Nếu biểu đồ không ghi số, ước lượng "
          "theo trục và ghi số ước lượng.")


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
    """Each chart of the page as text: 'Biểu đồ (ảnh):' then its data table rows. With PaddleOCR-VL as
    the engine its own chart recognition reads the page's charts; with Vintern, each region found by
    the layout model is cropped and read with the chart prompt."""
    from dr.config import settings
    if settings.ocr_engine == "vl":
        # the layout model first (~1 s, CPU): a page with a logo or a signature image has no chart, and the
        # whole VL page read (~60 s, every block of the page) would be spent only to find that out
        if not find(img):
            return []
        from dr.ingest.ocr import _lock as vl_lock, _vl_page
        with vl_lock, tempfile.NamedTemporaryFile(suffix=".png") as f:   # the VL pipeline is not thread-safe
            img.convert("RGB").save(f.name)
            page = _vl_page(f.name, 1)
        return [b.text for b in page.blocks if b.label == "chart"]
    from dr.ingest import vintern
    out = []
    for x0, y0, x1, y1 in find(img):
        pad = 12
        crop = img.crop((max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad)))
        text = vintern.markdown_tables_to_text(vintern.read(crop, prompt=PROMPT))
        if text.strip():
            out.append("Biểu đồ (ảnh, số đọc bằng Vintern – có thể là số ước lượng theo trục):\n" + text.strip())
    return out
