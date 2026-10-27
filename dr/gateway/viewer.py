"""View-only demo viewer, standing in for the CT VDR Viewer: in production sources open there and AI Data Room
makes no viewer of its own (BRD 19/10, BRULE-08); this one exists only for the demo (BRULE-06).

No operation hands the file out: its bytes are never sent. Word, Excel, PowerPoint, mail, web pages and text
are shown as escaped HTML; PDF pages and images as pictures rendered here, one page per request through a
short-lived ticket. The page has no download link, is served inline and no-store under a strict CSP, blocks
the save and print shortcuts, printing, dragging and the context menu, and carries the viewer's name and the
time as a watermark. A screenshot or the browser's developer tools can still copy what is on screen; the
watermark is there for that."""
from __future__ import annotations

import csv
import html
import io
import secrets
import time
from pathlib import Path

from PIL import Image

from dr.ingest import parsers
from dr.ingest.ocr import PDFIUM

PAGED = ("pdf", "png", "jpg", "jpeg")
MAX_ROWS, MAX_COLS = 1000, 40
NOT_SHOWN = '<p class="note">Không hiển thị được nội dung tài liệu này trong trình xem (tệp mã hóa, hỏng hoặc định dạng chưa hỗ trợ).</p>'
NO_STORE = {"Cache-Control": "no-store", "Content-Disposition": "inline", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer"}

_e = html.escape


def page_count(path: Path, ext: str) -> int:
    if ext != "pdf":
        return 1
    import pypdfium2 as pdfium
    with PDFIUM:
        pdf = pdfium.PdfDocument(str(path))
        try:
            return len(pdf)
        finally:
            pdf.close()


def page_jpeg(path: Path, ext: str, n: int) -> bytes | None:
    if ext == "pdf":
        import pypdfium2 as pdfium
        with PDFIUM:
            pdf = pdfium.PdfDocument(str(path))
            try:
                if not 1 <= n <= len(pdf):
                    return None
                page = pdf[n - 1]
                img = page.render(scale=min(150 / 72, 1400 / page.get_width())).to_pil()
                page.close()
            finally:
                pdf.close()
    elif n == 1:
        img = Image.open(path)
        img.load()
    else:
        return None
    img.thumbnail((1400, 4000))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=82)
    return buf.getvalue()


def pages_html(item_id: str, count: int, ticket: str) -> str:
    return "".join(f'<img class="pg" loading="lazy" draggable="false" alt="Trang {n}" '
                   f'src="/open/{_e(item_id)}/page/{n}?ticket={_e(ticket)}">' for n in range(1, count + 1))


def _table(rows: list[list[str]], head: bool = True) -> str:
    rows = [r[:MAX_COLS] for r in rows[:MAX_ROWS]]
    if not rows:
        return ""
    cell = lambda tag, v: f"<{tag}>{_e(v)}</{tag}>"
    first = "".join(cell("th" if head else "td", v) for v in rows[0])
    rest = "".join("<tr>" + "".join(cell("td", v) for v in r) + "</tr>" for r in rows[1:])
    return f'<div class="tw"><table><tr>{first}</tr>{rest}</table></div>'


def _sheets(path: Path) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    out = []
    for ws in wb.worksheets:      # hidden sheets too, marked: the AI may quote them, so they must be checkable
        rows = [["" if v is None else parsers._num(v, f) for v, f in r] for r in parsers._sheet_rows(ws)]
        hidden = " (sheet ẩn)" if ws.sheet_state != "visible" else ""
        out.append(f"<h2>{_e(ws.title)}{hidden}</h2>" + (_table(rows, head=False) or '<p class="note">Trống</p>'))
    return "".join(out)


def body_html(path: Path, ext: str) -> str:
    """The file's content as escaped HTML (never the file itself, never its own markup or scripts)."""
    if ext == "xlsx":
        return _sheets(path)
    data = path.read_bytes()
    if ext == "csv":
        return _table(list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace")))))
    doc = parsers.parse(data, ext, path.name)
    out = []
    for b in doc.blocks:
        if b.kind == "table":
            out.append(_table([line.split(" | ") for line in b.text.split("\n")]))
        elif b.kind == "slide":
            out.append(f"<h2>{_e(b.locator)}</h2>" + "".join(f"<p>{_e(t)}</p>" for t in b.text.split("\n")))
        elif b.kind == "email_header":
            out.append(f'<p class="mail">{_e(b.text)}</p>')
        elif b.text.startswith("#") or b.text[:60] == b.locator.split(" › ")[-1]:
            out.append(f"<h2>{_e(b.text.lstrip('# '))}</h2>")
        else:
            out.append(f"<p>{_e(b.text)}</p>")
    if ext == "eml" and doc.attachments:
        names = "".join(f"<li>{_e(n)}</li>" for n, _, _ in doc.attachments)
        out.append(f'<p class="note">Tệp đính kèm (chỉ liệt kê tên, không tải được):</p><ul>{names}</ul>')
    return "".join(out) or '<p class="note">Tài liệu không có nội dung chữ.</p>'


def response_parts(title: str, who: str, body: str) -> tuple[str, dict]:
    """The viewer page and its headers."""
    nonce = secrets.token_urlsafe(16)
    stamp = _e(f"{who} · {time.strftime('%d/%m/%Y %H:%M')}")
    marks = "".join(f"<span>{stamp}</span>" for _ in range(48))
    page = f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(title)}</title>
<style nonce="{nonce}">
body{{margin:0;font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;background:#f4f5f7;color:#1d2330}}
header{{position:sticky;top:0;z-index:2;display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:10px 16px;
  background:#fff;border-bottom:1px solid #dde1e8}}
header b{{flex:1;min-width:0;overflow-wrap:anywhere}} header span{{font-size:13px;color:#8a4b00}}
main{{max-width:980px;margin:16px auto;padding:16px 20px;background:#fff;border:1px solid #dde1e8;border-radius:8px}}
main p{{white-space:pre-wrap;overflow-wrap:anywhere}} h2{{font-size:17px;margin:20px 0 8px}}
.note{{color:#5b6475}} .mail{{background:#f4f5f7;padding:8px 12px;border-radius:6px}}
.tw{{overflow-x:auto;margin:8px 0}} table{{border-collapse:collapse;font-size:13px}}
th,td{{border:1px solid #dde1e8;padding:4px 8px;text-align:left;vertical-align:top}} th{{background:#f4f5f7}}
.pg{{display:block;max-width:100%;margin:0 auto 12px;border:1px solid #dde1e8;-webkit-user-drag:none}}
.wm{{position:fixed;inset:-60%;z-index:3;display:grid;grid-template-columns:repeat(6,1fr);gap:60px 20px;
  transform:rotate(-28deg);pointer-events:none;opacity:.09;font-size:15px;white-space:nowrap;color:#000}}
@media (prefers-color-scheme:dark){{body{{background:#14171d;color:#e4e7ec}}
  header,main{{background:#1c2028;border-color:#2c323d}} th,.mail{{background:#252a34}} th,td{{border-color:#2c323d}}
  .note{{color:#a3abba}} header span{{color:#f0b264}} .wm{{color:#fff}}}}
@media print{{body{{display:none}}}}
</style></head><body>
<header><b>{_e(title)}</b><span>Chỉ xem · không tải về, không in</span></header>
<main>{body}</main><div class="wm" aria-hidden="true">{marks}</div>
<script nonce="{nonce}">
const stop = (e) => e.preventDefault();
for (const k of ["contextmenu", "dragstart"]) document.addEventListener(k, stop);
document.addEventListener("keydown", (e) => {{
  if ((e.ctrlKey || e.metaKey) && ["s", "p"].includes(e.key.toLowerCase())) stop(e); }});
</script></body></html>"""
    csp = (f"default-src 'none'; img-src 'self'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
           "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    return page, {**NO_STORE, "Content-Security-Policy": csp}
