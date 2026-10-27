"""View-only viewer (demo stand-in for the CT VDR viewer): every file type is shown, none is handed out."""
import email.message
import html
import io
import re
from pathlib import Path

import docx
import openpyxl
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from dr import audit
from dr.gateway import app as appmod
from dr.gateway import auth
from tests.test_api import client, login  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]


def view(client, oid, item_id):
    url = client.post(f"/api/files/{item_id}/link", headers=login(client, oid)).json()["url"]
    return client.get(url)


def put(item_id, name, data: bytes):
    """Give a test file another content and type (b1: group B reads it)."""
    t = appmod.S.tenant
    (t.dir / "files" / name).write_bytes(data)
    t.items[item_id].update(name=name, file=name, ext=name.rsplit(".", 1)[1])


def assert_view_only(r):
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["content-disposition"] == "inline" and r.headers["cache-control"] == "no-store"
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp and "'unsafe-inline'" not in csp
    assert "download" not in r.text.lower() and "@media print{body{display:none}}" in r.text
    assert b"PK\x03\x04" not in r.content and b"%PDF" not in r.content        # never the file itself


def saved(obj) -> bytes:
    buf = io.BytesIO()
    obj.save(buf)
    return buf.getvalue()


def docx_bytes():
    d = docx.Document()
    d.add_heading("Điều 1. Phạm vi", 1)
    d.add_paragraph("Bên B bảo lãnh tỷ giá 25.400.")
    t = d.add_table(rows=2, cols=2)
    for (r, c), v in {(0, 0): "Hạng mục", (0, 1): "Giá trị", (1, 0): "Phí", (1, 1): "0,8%"}.items():
        t.cell(r, c).text = v
    return saved(d)


def xlsx_bytes():
    wb = openpyxl.Workbook()
    wb.active.append(["Năm", "Doanh thu"])
    wb.active.append([2025, 1250])
    hidden = wb.create_sheet("Ẩn")
    hidden.append(["Ghi chú nội bộ"])
    hidden.sheet_state = "hidden"
    return saved(wb)


def pptx_bytes():
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Doanh thu 2025"
    s.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1)).text_frame.text = "Tăng 18%"
    return saved(prs)


def eml_bytes():
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = "ipo@saomai.example", "inv-b1@test.example", "Hồ sơ nhóm B"
    m.set_content("Kính gửi Quý nhà đầu tư,\n\nĐính kèm phụ lục.")
    m.add_attachment(b"%PDF-SECRET-ATTACHMENT", maintype="application", subtype="pdf", filename="phu-luc.pdf")
    return m.as_bytes()


def test_every_text_type_is_shown_as_escaped_html_never_as_the_file(client):
    cases = {
        "hop-dong.docx": (docx_bytes(), ["<h2>Điều 1. Phạm vi</h2>", "25.400", "<td>0,8%</td>"]),
        "so-lieu.xlsx": (xlsx_bytes(), ["<td>1.250</td>", "Ẩn (sheet ẩn)", "Ghi chú nội bộ"]),
        "trinh-bay.pptx": (pptx_bytes(), ["<h2>Slide 1</h2>", "Doanh thu 2025", "Tăng 18%"]),
        "thu.eml": (eml_bytes(), ["Subject: Hồ sơ nhóm B", "<li>phu-luc.pdf</li>", "không tải được"]),
        "trang.html": (b"<h1>Ti\xc3\xaau \xc4\x91\xe1\xbb\x81</h1><p>N\xe1\xbb\x99i dung</p><script>alert('x')</script>"
                       b"<p><img src=x onerror=alert(1)></p>", ["<h2>Tiêu đề</h2>", "<p>Nội dung</p>"]),
        "bang.csv": ("Mục,Giá trị\nPhí,\"0,8%\"\n".encode(), ["<th>Mục</th>", "<td>0,8%</td>"]),
        "ghi-chu.md": ("# Tóm lược\n\nDòng <b>đậm</b>".encode(), ["<h2>Tóm lược</h2>", "Dòng &lt;b&gt;đậm&lt;/b&gt;"]),
    }
    for name, (data, expect) in cases.items():
        put("b1", name, data)
        r = view(client, "inv-b1", "b1")
        assert_view_only(r)
        assert "Bình – inv-b1@test.example" in r.text                                 # watermark: who is viewing
        assert all(e in r.text for e in expect), (name, [e for e in expect if e not in r.text])
        assert "alert" not in r.text and "SECRET-ATTACHMENT" not in r.text, name      # the file's markup never runs
    assert any(a["kind"] == "file_view" and a["payload"]["item_id"] == "b1" for a in audit.recent(5))


def test_pdf_and_images_are_shown_page_by_page(client):
    pdf = io.BytesIO()
    Image.new("RGB", (600, 800), "white").save(pdf, "PDF", save_all=True, append_images=[Image.new("RGB", (600, 800))])
    put("b1", "bao-cao.pdf", pdf.getvalue())
    r = view(client, "inv-b1", "b1")
    assert_view_only(r)
    pages = [html.unescape(s) for s in re.findall(r'src="(/open/b1/page/\d\?ticket=[^"]+)"', r.text)]
    assert len(pages) == 2
    p = client.get(pages[0])
    assert p.status_code == 200 and p.headers["content-type"] == "image/jpeg" and p.content[:3] == b"\xff\xd8\xff"
    assert p.headers["cache-control"] == "no-store" and p.headers["content-disposition"] == "inline"
    assert client.get(pages[0]).status_code == 200                      # a page ticket is reused until it expires
    assert client.get(pages[1].replace("/page/2", "/page/3")).status_code == 404
    png = io.BytesIO()
    Image.new("RGB", (40, 40), "red").save(png, "PNG")
    put("b1", "so-do.png", png.getvalue())
    pages = [html.unescape(s) for s in re.findall(r'src="(/open/b1/page/\d\?ticket=[^"]+)"', view(client, "inv-b1", "b1").text)]
    assert len(pages) == 1 and client.get(pages[0]).content[:3] == b"\xff\xd8\xff"      # re-encoded, not the PNG


def test_page_tickets_check_access_for_every_page(client):
    pdf = io.BytesIO()
    Image.new("RGB", (300, 400), "white").save(pdf, "PDF")
    put("b1", "bao-cao.pdf", pdf.getvalue())
    page = auth.issue_ticket("inv-b1", "b1", "page")
    get = lambda path, t: client.get(path, params={"ticket": t}).status_code
    assert get("/open/b1/page/1", page) == 200
    # an open ticket is not a page ticket, nor the other way round, nor one for another file
    assert get("/open/b1/page/1", auth.issue_ticket("inv-b1", "b1", "open")) == 401
    assert get("/open/b1", page) == 401 and get("/open/a1/page/1", page) == 401
    # access is checked again for every page: another group, the admin identity, a disabled account
    assert get("/open/b1/page/1", auth.issue_ticket("inv-a1", "b1", "page")) == 403
    assert get("/open/b1/page/1", auth.issue_ticket(auth.ADMIN_OID, "b1", "page")) == 403
    appmod.S.tenant.set_user_enabled("inv-b1", False)
    assert get("/open/b1/page/1", page) == 403


def test_malware_is_not_opened_and_a_broken_file_shows_a_note(client):
    appmod.S.tenant.items["b1"]["malware"] = True
    assert view(client, "inv-b1", "b1").status_code == 403
    appmod.S.tenant.items["b1"]["malware"] = False
    put("b1", "hong.pdf", b"%PDF-1.4 not a real pdf")
    r = view(client, "inv-b1", "b1")
    assert r.status_code == 200 and "Không hiển thị được" in r.text and "%PDF" not in r.text


def test_no_download_anywhere():
    """No route sends a file as an attachment and the web UI has no download link."""
    gateway = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "dr" / "gateway").glob("*.py"))
    assert "FileResponse" not in gateway and "attachment" not in gateway.replace("attachments", "")
    web = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "web").glob("*.*") if p.suffix in (".js", ".html"))
    assert not re.search(r"\bdownload\b|createObjectURL", web)
