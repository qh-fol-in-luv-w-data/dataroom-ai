"""Format parsers producing located text blocks.

Every block carries a *locator* that the UI shows next to a citation:
PDF -> "Trang n", Word -> heading path, PowerPoint -> "Slide n", Excel -> "Sheet!A1:F20",
e-mail -> "Thư" / "Đính kèm: <name> › ...", CSV -> "Dòng a–b".
Scanned PDF pages and images go through PaddleOCR (dr.ingest.ocr).
"""
from __future__ import annotations

import csv
import ctypes
import email
import email.policy
import io
import re
from collections import Counter
from dataclasses import dataclass, field

VI_CHARS = set("aăâbcdđeêghiklmnoôơpqrstuưvxyáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
               "0123456789")


@dataclass
class Block:
    text: str
    locator: str
    kind: str = "text"        # text | table | slide | sheet | email_header
    ocr: bool = False
    meta: dict = field(default_factory=dict)


@dataclass
class ParsedDoc:
    blocks: list[Block]
    converter: str
    attachments: list[tuple[str, str, bytes]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # e.g. hidden text removed


# ---------------------------------------------------------------- PDF
def text_quality(text: str) -> float:
    """Share of word characters that are valid Vietnamese/latin letters or digits."""
    letters = [c for c in text.lower() if c.isalnum()]
    if len(letters) < 40:
        return 0.0
    return sum(c in VI_CHARS for c in letters) / len(letters)


def _visible_page_text(pdfium, page) -> tuple[str, int]:
    """Text of a PDF page, dropping characters drawn in (near) white — hidden text."""
    raw = pdfium.raw
    tp = page.get_textpage()
    out, hidden = [], 0
    try:
        n = tp.count_chars()
        r, g, b, a = (ctypes.c_uint() for _ in range(4))
        for i in range(n):
            code = raw.FPDFText_GetUnicode(tp.raw, i)
            ch = chr(code) if code else ""
            if raw.FPDFText_GetFillColor(tp.raw, i, ctypes.byref(r), ctypes.byref(g), ctypes.byref(b), ctypes.byref(a)):
                if r.value > 245 and g.value > 245 and b.value > 245 and ch.strip():
                    hidden += 1
                    continue
            out.append(ch)
    finally:
        tp.close()          # freed here, under the caller's pdfium lock, not later by the garbage collector
    text = "".join(out).replace("\r\n", "\n").replace("\r", "\n")
    # pdfium gives a character outside the BMP (an emoji) as two UTF-16 halves: join them; a lone half is dropped
    text = text.encode("utf-16", "surrogatepass").decode("utf-16", "ignore")
    return text, hidden


def _chart_candidate(page, text: str) -> bool:
    """A page with a text layer that may hold a chart (a figure is pictures or vector paths, not text).
    Layout detection costs ~1 s a page, so only pages with an image, or with drawn paths AND several
    lines that are bare numbers (axis ticks, value labels: a drawn table rarely has those on lines
    of their own)."""
    import pypdfium2.raw as raw
    kinds = [o.type for o in page.get_objects(max_depth=2)]
    bare_numbers = sum(1 for ln in text.splitlines() if re.fullmatch(r"\s*-?[\d.,]+\s*%?\s*", ln))
    return raw.FPDF_PAGEOBJ_IMAGE in kinds or (kinds.count(raw.FPDF_PAGEOBJ_PATH) >= 10 and bare_numbers >= 4)


def pages_to_ocr(path) -> int:
    """Pages of a PDF without a usable text layer (the ones parse_pdf sends to OCR). Cheap: the plain
    text of each page, no rendering; used to put PDFs with selectable text first in a bulk load."""
    import pypdfium2 as pdfium
    from dr.ingest.ocr import PDFIUM
    with PDFIUM:
        try:
            pdf = pdfium.PdfDocument(str(path))
        except Exception:
            return 0
        try:
            n = 0
            for page in pdf:
                tp = page.get_textpage()
                n += text_quality(tp.get_text_range()) < 0.85
                tp.close()
                page.close()
            return n
        finally:
            pdf.close()


def parse_pdf(data: bytes, name: str) -> ParsedDoc:
    """Two passes. Under the pdfium lock (pdfium is not thread-safe: two ingest workers reading PDFs at
    once crashed it in CPDF_Page::~CPDF_Page): text layers, and page images for the pages that need
    OCR or chart reading. Then, lock released, OCR and chart reading on those images."""
    import pypdfium2 as pdfium
    from dr.config import settings
    from dr.ingest.ocr import PDFIUM, ocr_bytes

    blocks: list[Block] = []
    notes: list[str] = []
    scan_pages: list[int] = []
    scan_png: dict[int, bytes] = {}
    chart_img: dict[int, object] = {}
    want_charts = settings.ocr_engine == "vl"          # chart pictures are read by PaddleOCR-VL
    with PDFIUM:
        pdf = pdfium.PdfDocument(data)
        try:
            n_pages = len(pdf)
            for i in range(n_pages):
                page = pdf[i]
                try:
                    text, hidden = _visible_page_text(pdfium, page)
                    if hidden:
                        notes.append(f"Trang {i + 1}: loại {hidden} ký tự chữ ẩn (màu trắng)")
                    scale = min(200 / 72, 2400 / page.get_width())
                    if text_quality(text) >= 0.85:
                        for para in re.split(r"\n\s*\n|\n(?=[A-ZĐÀ-Ỹ0-9][^\n]{0,80}\n)", text):
                            if para.strip():
                                blocks.append(Block(para.strip(), f"Trang {i + 1}"))
                        if want_charts and _chart_candidate(page, text):
                            chart_img[i] = page.render(scale=scale).to_pil()
                    else:
                        scan_pages.append(i)
                        if len(scan_pages) <= settings.ocr_max_pages:
                            buf = io.BytesIO()
                            page.render(scale=scale).to_pil().save(buf, "PNG")
                            scan_png[i] = buf.getvalue()
                finally:
                    page.close()
        finally:
            pdf.close()
    converter = "pdfium-text"
    if chart_img:
        from dr.ingest import charts
        for i, img in chart_img.items():
            blocks += [Block(t, f"Trang {i + 1}", "table", ocr=True) for t in charts.read(img)]
    if len(scan_pages) > settings.ocr_max_pages:
        notes.append(f"Chỉ OCR {settings.ocr_max_pages}/{len(scan_pages)} trang scan đầu (giới hạn demo)")
        scan_pages = scan_pages[: settings.ocr_max_pages]
    if scan_pages:
        engines = set()
        for i in scan_pages:                 # OCR only the pages without a usable text layer
            res = ocr_bytes(scan_png[i], ".png")
            if not res:
                continue
            p = res[0]
            engines.add(p.engine)
            notes.extend(_ocr_notes(p, f"Trang {i + 1}"))
            for b in p.blocks:
                kind = "table" if b.label in ("table", "chart") else "text"
                blocks.append(Block(b.text, f"Trang {i + 1}", kind, ocr=True, meta=_ocr_meta(p)))
        converter = "+".join(["pdfium-text"] * (len(scan_pages) < n_pages) + sorted(engines))
    blocks.sort(key=lambda b: int(b.locator.split()[1]))
    return ParsedDoc(blocks, converter, notes=notes)


# ---------------------------------------------------------------- Office
def parse_docx(data: bytes, name: str) -> ParsedDoc:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(io.BytesIO(data))
    blocks: list[Block] = []
    heads: list[str] = []
    body = d.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            txt = p.text.strip()
            if not txt:
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            m = re.match(r"heading (\d)", style)
            if m or style == "title":
                level = int(m.group(1)) if m else 1
                heads = heads[: level - 1] + [txt[:60]]
            loc = " › ".join(heads) if heads else "Đầu văn bản"
            blocks.append(Block(txt, loc))
        elif tag == "tbl":
            t = Table(child, d)
            rows = []
            for r in t.rows:
                cells = []
                for c in r.cells:
                    v = c.text.strip()
                    if not cells or cells[-1] != v:  # merged cells repeat
                        cells.append(v)
                rows.append(" | ".join(cells))
            loc = (" › ".join(heads) if heads else "Đầu văn bản") + " › Bảng"
            blocks.append(Block("\n".join(rows), loc, "table"))
    atts = []
    for rel in d.part.rels.values():
        if "image" in rel.reltype and not rel.is_external:   # a linked (web) picture has no bytes here
            blob = rel.target_part.blob
            if len(blob) > 20_000:  # skip icons/logos
                ext = rel.target_part.partname.ext.lower()
                atts.append((f"ảnh nhúng {rel.rId}.{ext}", ext, blob))
    blocks += _chart_blocks(data, "word/charts/")
    return ParsedDoc(blocks, "python-docx", attachments=atts)


def _num(v, fmt: str = "") -> str:
    """Vietnamese number style: 1.250,50; whole numbers without decimals; percentages as 30%."""
    if isinstance(v, bool):
        return str(v)
    if "%" in (fmt or "") and isinstance(v, (int, float)):
        p = v * 100
        return (f"{p:.2f}".rstrip("0").rstrip(".").replace(".", ",")) + "%"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        v = int(v)
    if isinstance(v, int):
        return f"{v:,}".replace(",", ".")
    if isinstance(v, float):
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if hasattr(v, "strftime"):
        return v.strftime("%d/%m/%Y")
    return re.sub(r"\s+", " ", str(v)).strip()


_SHEET_CHUNK = 1400     # characters per sheet block: under the chunker's 1600 for tables, so a block is never cut again
_CELL_MAX = 500         # long free-text cells (assessments, notes) are cut in the row record


def _sheet_rows(ws) -> list[list[tuple]]:
    """Rows as [(value, number_format)], merged ranges filled with their top-left value so that a
    header spanning several columns labels each of them."""
    grid = [[(c.value, c.number_format) for c in row] for row in ws.iter_rows()]
    for rng in ws.merged_cells.ranges:
        top = grid[rng.min_row - 1][rng.min_col - 1] if rng.min_row - 1 < len(grid) else (None, "")
        for r in range(rng.min_row - 1, min(rng.max_row, len(grid))):
            for c in range(rng.min_col - 1, min(rng.max_col, len(grid[r]))):
                grid[r][c] = top
    return grid


def _filled(row) -> list[int]:
    return [i for i, (v, _) in enumerate(row) if v is not None and str(v).strip() != ""]


def _is_numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _sheet_records(grid: list[list[tuple]]) -> list[str]:
    """Each table row as one line 'Column: value; …' (multi-row headers joined per column); rows
    outside a table (titles, 'label | value' forms) as 'a | b'. A row of 3+ labels and no numbers
    after a table starts a new table with its own header."""
    lines: list[str] = []
    header: list[str] = []

    def plain(row) -> str:
        vals = [_num(v, f)[:_CELL_MAX] for v, f in row if v is not None and str(v).strip()]
        return " | ".join(v for i, v in enumerate(vals) if i == 0 or v != vals[i - 1])   # merged cells once

    def make_header(rows) -> list[str]:
        width = max(len(r) for r in rows)
        cols = []
        for c in range(width):
            parts = []
            for r in rows:
                v = r[c][0] if c < len(r) else None
                t = _num(v) if v is not None else ""
                if t and t not in parts:
                    parts.append(t)
            cols.append(parts)
        # a top header over (almost) every column ("TIÊU CHÍ ĐÁNH GIÁ") says nothing per column and makes
        # every cell longer: drop it, so a row's numbers fit in the first part of the record
        named = [c for c in cols if len(c) > 1]
        if named:
            first = Counter(c[0] for c in named).most_common(1)[0]
            if first[1] >= 0.8 * len(named) and len(named) >= 3:
                cols = [c[1:] if len(c) > 1 and c[0] == first[0] else c for c in cols]
        return [" › ".join(c) for c in cols]

    def is_data(row) -> bool:
        idx = _filled(row)
        nums = sum(_is_numeric(row[i][0]) for i in idx)
        return nums >= 2 or (nums >= 1 and len(idx) >= 3)

    def is_label_row(row) -> bool:
        # column labels: several distinct short texts, no numbers ("MÃ SẢN PHẨM | SH09" is a form line)
        idx = _filled(row)
        vals = {str(row[i][0]).strip() for i in idx}
        return len(vals) >= 3 and all(len(v) <= 80 for v in vals) and not any(_is_numeric(row[i][0]) for i in idx)

    k = 0
    while k < len(grid):
        row = grid[k]
        if not _filled(row):
            k += 1
            continue
        if is_data(row) and header:
            idx = _filled(row)
            cells, prev = [], None
            for i in idx:
                v, f = row[i]
                name = header[i] if i < len(header) and header[i] else ""
                val = _num(v, f)[:_CELL_MAX]
                if prev and (prev == (name, val) or (prev[1] == val and not _is_numeric(v))):
                    continue                     # a merged cell spans several columns: say it once
                prev = (name, val)
                if name and name != val:
                    cells.append(f"{name}: {val}")
                else:
                    cells.append(val)
            # short cells (names, codes, numbers) first, long free text after: when a long row is cut,
            # its numbers stay next to what identifies the row
            cells = [c for c in cells if len(c) <= 120] + [c for c in cells if len(c) > 120]
            lines.append("; ".join(cells))
            k += 1
            continue
        if is_label_row(row):
            # header block: this row and following label rows, until the first data row
            j = k
            while j < len(grid) and j - k < 4 and (is_label_row(grid[j]) or not _filled(grid[j])):
                j += 1
            if j < len(grid) and is_data(grid[j]):
                header = make_header([r for r in grid[k:j] if _filled(r)])
                k = j
                continue
        lines.append(plain(row))
        k += 1
    return [ln for ln in lines if ln]


def parse_xlsx(data: bytes, name: str) -> ParsedDoc:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=False)
    blocks: list[Block] = []
    notes: list[str] = []
    for ws in wb.worksheets:
        hidden = ws.sheet_state != "visible"
        if hidden:
            notes.append(f"Sheet ẩn: {ws.title}")
        grid = _sheet_rows(ws)
        unit = ""
        for row in grid[:6]:
            for v, _ in row:
                if isinstance(v, str) and re.search(r"đơn vị|don vi|unit", v, re.I):
                    unit = v.strip()
        records = _sheet_records(grid)
        title = next((r for r in records[:2] if " | " not in r and ": " not in r), "")
        header = f"[Sheet {ws.title.strip()}{' (ẩn)' if hidden else ''}{' – ' + unit if unit else ''}]" + \
            (f" {title[:120]}" if title else "")
        chunk, first = [], 1
        for n, rec in enumerate(records, 1):
            if len(rec) > _SHEET_CHUNK:
                # one long row: cut it into pieces that each repeat the row's key (its first two cells),
                # so a piece holding "TỔNG: 299.000.000" still says which agency/unit it belongs to
                if chunk:
                    loc = f"{ws.title.strip()}!A{first}" + (f" (dòng {first}–{n - 1})" if n - 1 > first else "")
                    blocks.append(Block(header + "\n" + "\n".join(chunk), loc, "sheet", meta={"hidden": hidden}))
                cells = rec.split("; ")
                key = "; ".join(cells[:2])
                piece: list[str] = []
                for cell in cells[2:]:
                    if piece and len(key) + sum(len(x) + 2 for x in piece) + len(cell) > _SHEET_CHUNK:
                        blocks.append(Block(f"{header}\n{key}; " + "; ".join(piece), f"{ws.title.strip()}!A{n}",
                                            "sheet", meta={"hidden": hidden}))
                        piece = []
                    piece.append(cell)
                blocks.append(Block(f"{header}\n{key}" + ("; " + "; ".join(piece) if piece else ""),
                                    f"{ws.title.strip()}!A{n}", "sheet", meta={"hidden": hidden}))
                chunk, first = [], n + 1
                continue
            chunk.append(rec)
            if sum(len(x) for x in chunk) >= _SHEET_CHUNK or n == len(records):
                loc = f"{ws.title.strip()}!A{first}" + (f" (dòng {first}–{n})" if n > first else "")
                blocks.append(Block(header + "\n" + "\n".join(chunk), loc, "sheet", meta={"hidden": hidden}))
                chunk, first = [], n + 1
    blocks += _chart_blocks(data, "xl/charts/")
    return ParsedDoc(blocks, "openpyxl", notes=notes)


# ---------------------------------------------------------------- native charts (Office)
_C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def chart_text(xml: bytes) -> str | None:
    """A native chart as text: type, title, then per series 'category: value' (the numbers cached in
    the chart part, i.e. what the chart shows)."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    plot = root.find(f".//{_C}plotArea")
    if plot is None:
        return None
    kinds = [el.tag.replace(_C, "") for el in plot if el.tag.endswith("Chart")]
    title_el = root.find(f".//{_C}title")
    title = " ".join(t.text or "" for t in title_el.iter(f"{_A}t")).strip() if title_el is not None else ""
    out = []
    for ser in plot.iter(f"{_C}ser"):
        def pts(tag):
            el = ser.find(f"{_C}{tag}")
            if el is None:
                return [], ""
            fmt = el.findtext(f".//{_C}formatCode") or ""
            vals = {int(pt.get("idx", 0)): pt.findtext(f"{_C}v") for pt in el.iter(f"{_C}pt")}
            return [vals.get(i) for i in range(max(vals) + 1)] if vals else [], fmt
        cats, _ = pts("cat")
        vals, fmt = pts("val") if ser.find(f"{_C}val") is not None else pts("yVal")
        sname = " ".join(v.text or "" for v in ser.iter(f"{_C}v") if ser.find(f"{_C}tx") is not None
                         and v in list(ser.find(f"{_C}tx").iter(f"{_C}v")))
        items = []
        for i, v in enumerate(vals):
            if v is None:
                continue
            try:
                num = _num(float(v), fmt)
            except ValueError:
                num = v
            cat = cats[i] if i < len(cats) and cats[i] else f"#{i + 1}"
            items.append(f"{cat.strip()}: {num}")
        if items:
            sname = "" if re.fullmatch(r"(column|series|chuỗi|cột)\s*\d*", sname.strip(), re.I) else sname.strip()
            out.append((f"{sname} – " if sname else "") + "; ".join(items))
    if not out:
        return None
    kind = ", ".join(sorted(set(kinds))) or "chart"
    return f"Biểu đồ ({kind}){': ' + title if title else ''}\n" + "\n".join(out)


def _chart_blocks(data: bytes, prefix: str) -> list[Block]:
    import zipfile
    blocks = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return blocks
    names = sorted((n for n in z.namelist() if n.startswith(prefix) and re.search(r"chart\d+\.xml$", n)),
                   key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    for n in names:
        t = chart_text(z.read(n))
        num = re.search(r"(\d+)\.xml$", n).group(1)
        if t:
            blocks.append(Block(t, f"Biểu đồ {num}", "table"))
    return blocks


def parse_pptx(data: bytes, name: str) -> ParsedDoc:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    blocks: list[Block] = []
    for i, slide in enumerate(prs.slides, start=1):
        parts = []
        for sh in slide.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                parts.append(sh.text_frame.text.strip())
            if getattr(sh, "has_table", False) and sh.has_table:
                for r in sh.table.rows:
                    parts.append(" | ".join(c.text.strip() for c in r.cells))
            if getattr(sh, "has_chart", False) and sh.has_chart:
                t = chart_text(sh.chart.part.blob)
                if t:
                    parts.append(t)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            parts.append("Ghi chú người trình bày: " + slide.notes_slide.notes_text_frame.text.strip())
        if parts:
            blocks.append(Block("\n".join(parts), f"Slide {i}", "slide"))
    return ParsedDoc(blocks, "python-pptx")


# ---------------------------------------------------------------- mail / web / text
def parse_eml(data: bytes, name: str) -> ParsedDoc:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    head = "\n".join(f"{h}: {msg.get(h, '')}" for h in ("From", "To", "Cc", "Date", "Subject") if msg.get(h))
    blocks = [Block(head, "Thư › Tiêu đề", "email_header")]
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is not None:
        content = body.get_content()
        if body.get_content_type() == "text/html":
            content = _html_text(content)
        for para in re.split(r"\n\s*\n", content):
            if para.strip():
                blocks.append(Block(para.strip(), "Thư › Nội dung"))
    atts = []
    for part in msg.iter_attachments():
        fn = part.get_filename() or "dinh-kem"
        ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else "bin"
        atts.append((fn, ext, part.get_payload(decode=True) or b""))
    return ParsedDoc(blocks, "email", attachments=atts)


def _html_text(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style"]):
        t.decompose()
    return soup.get_text("\n")


def parse_html(data: bytes, name: str) -> ParsedDoc:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(data.decode("utf-8", errors="replace"), "lxml")
    for t in soup(["script", "style"]):
        t.decompose()
    blocks: list[Block] = []
    head = "Đầu trang"
    for el in soup.find_all(["h1", "h2", "h3", "p", "li", "table"]):
        if el.find_parent("table") and el.name != "table":
            continue
        if el.name in ("h1", "h2", "h3"):
            head = el.get_text(" ", strip=True)[:60]
            blocks.append(Block(el.get_text(" ", strip=True), head))
        elif el.name == "table":
            rows = [" | ".join(c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"]))
                    for tr in el.find_all("tr")]
            blocks.append(Block("\n".join(rows), head + " › Bảng", "table"))
        else:
            t = el.get_text(" ", strip=True)
            if t:
                blocks.append(Block(t, head))
    return ParsedDoc(blocks, "beautifulsoup")


def parse_csv(data: bytes, name: str) -> ParsedDoc:
    text = data.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return ParsedDoc([], "csv")
    header, body = rows[0], rows[1:]
    blocks = []
    for s in range(0, len(body), 25):
        part = body[s:s + 25]
        lines = [" | ".join(header)] + [" | ".join(r) for r in part]
        blocks.append(Block("\n".join(lines), f"Dòng {s + 2}–{s + 1 + len(part)}", "table"))
    return ParsedDoc(blocks, "csv")


def parse_text(data: bytes, name: str) -> ParsedDoc:
    text = data.decode("utf-8-sig", errors="replace")
    blocks, head = [], "Đầu văn bản"
    for para in re.split(r"\n\s*\n", text):
        p = para.strip()
        if not p:
            continue
        if p.startswith("#"):
            head = p.lstrip("# ").split("\n")[0][:60]
        blocks.append(Block(p, head))
    return ParsedDoc(blocks, "text")


def _ocr_meta(p) -> dict:
    return {"doubt": p.doubt, "page_key": f"{p.key}/p{p.page}" if p.key else None}


def _ocr_notes(p, where: str) -> list[str]:
    out = []
    if p.steps:
        out.append(f"{where}: {', '.join(p.steps)}")
    if p.doubt:
        out.append(f"{where}: {len(p.doubt)}/{p.numbers} con số OCR chưa được bộ đọc thứ hai xác nhận")
    return out


def parse_image(data: bytes, name: str, ext: str) -> ParsedDoc:
    from dr.ingest.ocr import ocr_bytes
    pages = ocr_bytes(data, "." + ext)
    blocks = [Block(b.text, "Ảnh", "table" if b.label in ("table", "chart") else "text", ocr=True, meta=_ocr_meta(p))
              for p in pages for b in p.blocks]
    notes = [n for p in pages for n in _ocr_notes(p, "Ảnh")]
    return ParsedDoc(blocks, pages[0].engine if pages else "ocr", notes=notes)


PARSERS = {
    "pdf": parse_pdf, "docx": parse_docx, "xlsx": parse_xlsx, "pptx": parse_pptx, "eml": parse_eml,
    "html": parse_html, "htm": parse_html, "csv": parse_csv, "txt": parse_text, "md": parse_text,
}
IMAGES = ("png", "jpg", "jpeg", "jfif", "webp")   # jfif is a JPEG; webp is read by Pillow
SUPPORTED = set(PARSERS) | set(IMAGES)


def parse(data: bytes, ext: str, name: str) -> ParsedDoc:
    ext = ext.lower().lstrip(".")
    if ext in IMAGES:
        return parse_image(data, name, ext)
    if ext not in PARSERS:
        raise ValueError(f"Định dạng .{ext} chưa được hỗ trợ")
    return PARSERS[ext](data, name)
