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
from urllib.parse import quote
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


def response_parts(title: str, who: str, body: str, *, crumb: str = "", item_id: str = "",
                   summary: bool = False) -> tuple[str, dict]:
    """The viewer page and its headers. crumb (folder path) and item_id/summary only decorate the header:
    the summary button is a plain link into the app, which checks the account again before summarising."""
    nonce = secrets.token_urlsafe(16)
    stamp = _e(f"{who} · {time.strftime('%d/%m/%Y %H:%M')}")
    marks = "".join(f"<span>{stamp}</span>" for _ in range(48))
    parts = [c for c in crumb.replace("\\", "/").split("/") if c]
    trail = "".join(f"<span>{_e(c)}</span>" for c in parts)
    sumlink = (f'<a class="btn" target="_blank" rel="noopener" href="/#/search?summary={quote(item_id)}&amp;name={quote(title)}">'
               "&#10024; Tóm tắt tài liệu</a>") if summary and item_id else ""
    page = f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(title)}</title>
<style nonce="{nonce}">
:root{{--bg:#f4f5f7;--ink:#1d2330;--card:#fff;--line:#dde1e8;--muted:#5b6475;--soft:#f4f5f7;--warn:#8a4b00;--warnbg:#fffaeb;--brand:#0e6b5c;--z:1}}
*{{box-sizing:border-box}}
body{{margin:0;font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--ink)}}
header{{position:sticky;top:0;z-index:2;background:var(--card);border-bottom:1px solid var(--line)}}
.hrow{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:8px 16px}}
.ttl{{flex:1;min-width:200px}} .ttl b{{display:block;overflow-wrap:anywhere;line-height:1.3}}
.crumb{{display:flex;flex-wrap:wrap;gap:2px;font-size:12px;color:var(--muted)}}
.crumb span+span::before{{content:"\\203A";margin:0 6px;opacity:.6}}
.tools{{display:flex;gap:6px;align-items:center;flex-wrap:wrap}}
.btn{{font:inherit;font-size:13px;height:32px;min-width:32px;padding:0 10px;border:1px solid var(--line);border-radius:8px;
  background:var(--card);color:var(--ink);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:4px;text-decoration:none}}
.btn:hover{{background:var(--soft)}} .btn:disabled{{opacity:.4;cursor:default}}
.btn:focus-visible{{outline:2px solid var(--brand);outline-offset:2px}}
.pgno,.zm{{font-size:13px;color:var(--muted);min-width:54px;text-align:center;font-variant-numeric:tabular-nums}}
.notice{{padding:4px 16px;font-size:12.5px;background:var(--warnbg);color:var(--warn);border-top:1px solid var(--line)}}
main{{max-width:980px;margin:16px auto;padding:16px 20px;background:var(--card);border:1px solid var(--line);border-radius:8px;font-size:calc(15px * var(--z))}}
main p{{white-space:pre-wrap;overflow-wrap:anywhere}} h2{{font-size:1.15em;margin:20px 0 8px}}
.note{{color:var(--muted)}} .mail{{background:var(--soft);padding:8px 12px;border-radius:6px}}
.tw{{overflow-x:auto;margin:8px 0}} table{{border-collapse:collapse;font-size:.87em}}
th,td{{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}} th{{background:var(--soft)}}
main.paged{{max-width:none;background:transparent;border:0;padding:8px 12px}}
.pg{{display:block;width:calc(min(100%,980px) * var(--z));max-width:none;margin:0 auto 12px;border:1px solid var(--line);
  background:#fff;-webkit-user-drag:none;-webkit-user-select:none;user-select:none}}
.wm{{position:fixed;inset:-60%;z-index:3;display:grid;grid-template-columns:repeat(6,1fr);gap:60px 20px;
  transform:rotate(-28deg);pointer-events:none;opacity:.09;font-size:15px;white-space:nowrap;color:#000}}
@media (max-width:640px){{.hrow{{padding:8px 12px}} main{{margin:8px;padding:12px}} .ttl{{min-width:100%}} .sumtxt{{display:none}}}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14171d;--ink:#e4e7ec;--card:#1c2028;--line:#2c323d;--muted:#a3abba;--soft:#252a34;--warn:#f0b264;--warnbg:#2f2213;--brand:#2fb39b}}
  .wm{{color:#fff}}}}
@media print{{body{{display:none}}}}
</style></head><body>
<header><div class="hrow"><div class="ttl"><b>{_e(title)}</b><div class="crumb">{trail}</div></div>
<div class="tools">
<span id="pn" hidden><button class="btn" id="pprev" aria-label="Trang trước">&#8249;</button> <span class="pgno" id="pno"></span> <button class="btn" id="pnext" aria-label="Trang sau">&#8250;</button></span>
<button class="btn" id="zout" aria-label="Thu nhỏ">&minus;</button><span class="zm" id="zv">100%</span><button class="btn" id="zin" aria-label="Phóng to">+</button>
{sumlink}</div></div>
<div class="notice">&#128274; Chỉ xem &ndash; không tải về, không in. Tên bạn và thời gian xem được in chìm trên tài liệu.</div></header>
<main>{body}</main><div class="wm" aria-hidden="true">{marks}</div>
<script nonce="{nonce}">
const stop = (e) => e.preventDefault();
for (const k of ["contextmenu", "dragstart"]) document.addEventListener(k, stop);
document.addEventListener("keydown", (e) => {{
  if ((e.ctrlKey || e.metaKey) && ["s", "p"].includes(e.key.toLowerCase())) stop(e); }});
const root = document.documentElement, pgs = [...document.querySelectorAll(".pg")];
let z = 1, cur = 1;
const zoom = (d) => {{ z = Math.min(2.5, Math.max(0.5, Math.round((z + d) * 10) / 10));
  root.style.setProperty("--z", z); document.getElementById("zv").textContent = Math.round(z * 100) + "%"; }};
document.getElementById("zin").onclick = () => zoom(0.1);
document.getElementById("zout").onclick = () => zoom(-0.1);
if (pgs.length) {{
  document.querySelector("main").classList.add("paged");
  const pn = document.getElementById("pn"), no = document.getElementById("pno");
  const show = (n) => {{ cur = Math.min(pgs.length, Math.max(1, n)); no.textContent = cur + " / " + pgs.length;
    document.getElementById("pprev").disabled = cur === 1; document.getElementById("pnext").disabled = cur === pgs.length; }};
  const go = (n) => {{ show(n); pgs[cur - 1].scrollIntoView({{ block: "start" }}); }};
  pn.hidden = pgs.length < 2; show(1);
  document.getElementById("pprev").onclick = () => go(cur - 1);
  document.getElementById("pnext").onclick = () => go(cur + 1);
  document.addEventListener("keydown", (e) => {{
    if (e.key === "PageDown" || e.key === "ArrowRight") go(cur + 1);
    else if (e.key === "PageUp" || e.key === "ArrowLeft") go(cur - 1); }});
  if ("IntersectionObserver" in window) {{
    const io = new IntersectionObserver((es) => {{ for (const x of es) if (x.isIntersecting) show(pgs.indexOf(x.target) + 1); }},
      {{ rootMargin: "-45% 0px -50% 0px" }});
    pgs.forEach((p) => io.observe(p));
  }}
}}
</script></body></html>"""
    csp = (f"default-src 'none'; img-src 'self'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
           "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    return page, {**NO_STORE, "Content-Security-Policy": csp}
