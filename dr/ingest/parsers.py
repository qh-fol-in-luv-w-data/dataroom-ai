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
    n = tp.count_chars()
    out, hidden = [], 0
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    for i in range(n):
        code = raw.FPDFText_GetUnicode(tp.raw, i)
        ch = chr(code) if code else ""
        if raw.FPDFText_GetFillColor(tp.raw, i, ctypes.byref(r), ctypes.byref(g), ctypes.byref(b), ctypes.byref(a)):
            if r.value > 245 and g.value > 245 and b.value > 245 and ch.strip():
                hidden += 1
                continue
        out.append(ch)
    text = "".join(out).replace("\r\n", "\n").replace("\r", "\n")
    return text, hidden


def parse_pdf(data: bytes, name: str) -> ParsedDoc:
    import pypdfium2 as pdfium
    from dr.ingest.ocr import ocr_bytes

    pdf = pdfium.PdfDocument(data)
    blocks: list[Block] = []
    notes: list[str] = []
    scan_pages: list[int] = []
    for i in range(len(pdf)):
        page = pdf[i]
        text, hidden = _visible_page_text(pdfium, page)
        if hidden:
            notes.append(f"Trang {i + 1}: loại {hidden} ký tự chữ ẩn (màu trắng)")
        if text_quality(text) >= 0.85:
            for para in re.split(r"\n\s*\n|\n(?=[A-ZĐÀ-Ỹ0-9][^\n]{0,80}\n)", text):
                if para.strip():
                    blocks.append(Block(para.strip(), f"Trang {i + 1}"))
        else:
            scan_pages.append(i)
    converter = "pdfium-text"
    from dr.config import settings
    if len(scan_pages) > settings.ocr_max_pages:
        notes.append(f"Chỉ OCR {settings.ocr_max_pages}/{len(scan_pages)} trang scan đầu (giới hạn demo)")
        scan_pages = scan_pages[: settings.ocr_max_pages]
    if scan_pages:
        # OCR only the pages without a usable text layer
        if len(scan_pages) == len(pdf) and len(pdf) <= settings.ocr_max_pages:
            pages = ocr_bytes(data, ".pdf")
            mapping = {p.page - 1: p for p in pages}
        else:
            mapping = {}
            for i in scan_pages:
                img = pdf[i].render(scale=2).to_pil()
                buf = io.BytesIO()
                img.save(buf, "PNG")
                res = ocr_bytes(buf.getvalue(), ".png")
                if res:
                    mapping[i] = res[0]
        engines = set()
        for i in scan_pages:
            p = mapping.get(i)
            if not p:
                continue
            engines.add(p.engine)
            notes.extend(_ocr_notes(p, f"Trang {i + 1}"))
            for b in p.blocks:
                kind = "table" if b.label == "table" else "text"
                blocks.append(Block(b.text, f"Trang {i + 1}", kind, ocr=True, meta=_ocr_meta(p)))
        blocks.sort(key=lambda b: int(b.locator.split()[1]))
        converter = "+".join(["pdfium-text"] * (len(scan_pages) < len(pdf)) + sorted(engines))
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
        if "image" in rel.reltype:
            blob = rel.target_part.blob
            if len(blob) > 20_000:  # skip icons/logos
                ext = rel.target_part.partname.ext.lower()
                atts.append((f"ảnh nhúng {rel.rId}.{ext}", ext, blob))
    return ParsedDoc(blocks, "python-docx", attachments=atts)


def parse_xlsx(data: bytes, name: str) -> ParsedDoc:
    import openpyxl
    from openpyxl.utils import get_column_letter

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=False)
    blocks: list[Block] = []
    notes: list[str] = []
    for ws in wb.worksheets:
        hidden = ws.sheet_state != "visible"
        if hidden:
            notes.append(f"Sheet ẩn: {ws.title}")
        unit = ""
        rows = list(ws.iter_rows(values_only=True))
        for row in rows[:6]:
            for v in row:
                if isinstance(v, str) and re.search(r"đơn vị|don vi|unit", v, re.I):
                    unit = v.strip()
        width = max((len(r) for r in rows), default=0)
        step = 20
        for start in range(0, len(rows), step):
            part = rows[start:start + step]
            lines = []
            for r in part:
                vals = []
                for v in r:
                    if v is None:
                        continue
                    if isinstance(v, float):
                        v = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    vals.append(str(v))
                if vals:
                    lines.append(" | ".join(vals))
            if not lines:
                continue
            header = f"[Sheet {ws.title}{' (ẩn)' if hidden else ''}{' – ' + unit if unit else ''}]"
            loc = f"{ws.title}!A{start + 1}:{get_column_letter(max(width, 1))}{start + len(part)}"
            blocks.append(Block(header + "\n" + "\n".join(lines), loc, "sheet", meta={"hidden": hidden}))
    return ParsedDoc(blocks, "openpyxl", notes=notes)


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
    blocks = [Block(b.text, "Ảnh", "table" if b.label == "table" else "text", ocr=True, meta=_ocr_meta(p))
              for p in pages for b in p.blocks]
    notes = [n for p in pages for n in _ocr_notes(p, "Ảnh")]
    return ParsedDoc(blocks, pages[0].engine if pages else "ocr", notes=notes)


PARSERS = {
    "pdf": parse_pdf, "docx": parse_docx, "xlsx": parse_xlsx, "pptx": parse_pptx, "eml": parse_eml,
    "html": parse_html, "htm": parse_html, "csv": parse_csv, "txt": parse_text, "md": parse_text,
}
SUPPORTED = set(PARSERS) | {"png", "jpg", "jpeg"}


def parse(data: bytes, ext: str, name: str) -> ParsedDoc:
    ext = ext.lower().lstrip(".")
    if ext in ("png", "jpg", "jpeg"):
        return parse_image(data, name, ext)
    if ext not in PARSERS:
        raise ValueError(f"Định dạng .{ext} chưa được hỗ trợ")
    return PARSERS[ext](data, name)
