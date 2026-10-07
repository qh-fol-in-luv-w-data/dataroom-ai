"""Fill the DAIT BRD Word template with the AI Data Room project — text only.

The template is copied unchanged: same paragraphs, same runs, same table rows and cells,
same headers, styles, numbering and document properties. Only the text inside existing runs
is replaced (new text goes into the first run of a paragraph, the other runs are emptied).
`--check` proves it: the two files must be identical once all text is blanked out.
Usage: .venv/bin/python scripts/make_brd.py TEMPLATE.docx OUT.docx [--check]
"""
from __future__ import annotations

import re
import sys
import zipfile

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

TITLE = ("DỰ ÁN: AI CORE CHO DATA ROOM IPO", " TRÊN SHAREPOINT")
DATE = ("Ngày lập: 07/10/2026", " - ", "Phiên bản: v1.0")
HEADER = "DAIT – DATA ROOM | BUSINESS REQUIREMENT DOCUMENT | AI CORE DATA ROOM IPO"

INFO = [
    ("Đơn vị nghiệp vụ", "Chủ Data Room IPO (Deal team) - Quản trị tenant Microsoft 365"),
    ("Đơn vị triển khai", "Ban DAIT - Phát triển ứng dụng – Team AI"),
    ("Mục tiêu giai đoạn", "Ready for Pilot/UAT ngày 20/11/2026"),
    ("Phạm vi chính", "AI core on-prem trả lời câu hỏi trên tài liệu Data Room SharePoint, đúng quyền SharePoint, "
                      "có trích dẫn nguyên văn đã kiểm chứng"),
    ("Tình trạng", "Dự thảo – Đang chờ Chủ Data Room và BOD xác nhận các Business Rule và một số yêu cầu liên quan"),
]

OBJECTIVE = ("Mục tiêu: Xây AI core chạy on-prem tại Việt Nam cho Data Room IPO trên SharePoint Online, cho phép nhà đầu "
             "tư và nhân viên hỏi đáp trên tài liệu, chỉ trả lời từ tài liệu người hỏi được mở trên SharePoint và được phép "
             "dùng AI, mọi ý có trích dẫn nguyên văn đã kiểm chứng, không rò rỉ chéo giữa các nhóm nhà đầu tư.")
IN_SCOPE = ("Phạm vi In-scope: Bắt đầu từ khi tài liệu đã nằm trên site Data Room SharePoint (đã gán AI_Use và nhãn) → "
            "Đồng bộ quyền & nạp tài liệu (OCR) → Hỏi đáp qua 4 cổng quyền → Trả lời có trích dẫn & Nhật ký.")
OUT_SCOPE = ("Phạm vi Out-of-scope: Không xây Data Room, trình xem, watermark hay chức năng cấp quyền (thuộc SharePoint, "
             "Entra, Purview do Chủ Data Room và Quản trị tenant thực hiện). Không lưu file gốc on-prem. Mở cho nhà đầu tư "
             "(Go-live) sau khi Pilot/UAT đạt các cổng; câu hỏi đếm/tổng thuộc Bản 2.")

PIPE_INTRO = "Quy trình hệ thống tuân theo luồng xử lý:"
PIPE_B0 = ("B0 – Chuẩn bị Data Room: Chủ Data Room đưa tài liệu lên SharePoint, gán AI_Use và nhãn; Quản trị tenant cấp "
           "quyền cho nhà đầu tư (khách Entra B2B). AI core bắt đầu xử lý khi tài liệu xuất hiện trong delta của Graph. ")
PIPE = ["B1 Đồng bộ quyền & delta → B2 Nạp tài liệu & OCR → B3 Lập chỉ mục theo phân vùng",
        "B4 Hỏi & kiểm 4 cổng quyền → B5 Tìm kiếm & kiểm tra trực tiếp SharePoint",
        "B6 Sinh & kiểm chứng câu trả lời → B7 Trả lời & Ghi nhật ký"]

BR = [
    ("BR-01", "Đăng nhập & Vai trò AI",
     "Nhà đầu tư (khách Entra B2B) và nhân viên đăng nhập bằng Entra (MFA, Conditional Access). Quyền dùng AI cấp qua "
     "app role Investor.AI / Investor.AI.Summarize / Staff.AI theo access package của từng nhóm; Chủ Data Room cấu hình "
     "AI_Use cho từng thư mục/file.",
     "Không tạo tài khoản riêng trong AI core. File chưa gán AI_Use được coi là Excluded."),
    ("BR-02", "Nạp tài liệu (Input/OCR)",
     "Nạp Word, Excel, PowerPoint, PDF, bản scan/ảnh, email, HTML, CSV. Bản scan được làm sạch (nắn ảnh chụp, xoay, "
     "chỉnh nghiêng, phóng to) rồi OCR bằng PaddleOCR-VL; con số được bộ đọc thứ hai đối chiếu.",
     "File Excluded, mã hóa, có mã độc → không nạp, ghi lý do. Trang có số chưa xác nhận/viết tay → hàng chờ duyệt."),
    ("BR-03", "Đồng bộ quyền & Thu hồi",
     "Đọc quyền SharePoint/Entra qua Graph delta (60 giây), dựng bản chép quyền. Gỡ khỏi nhóm, offboard, đổi AI_Use, "
     "thay phiên bản có hiệu lực ở AI ngay, kể cả khi SharePoint còn trễ.",
     "Bắt buộc đóng an toàn: nguồn quyền ngừng cập nhật quá ngưỡng → từ chối mọi câu hỏi."),
    ("BR-04", "Hỏi đáp đúng quyền (4 cổng)",
     "Chỉ trả lời từ tài liệu người hỏi mở được trên SharePoint và được phép AI: RLS + kiểm tra trực tiếp SharePoint "
     "bằng token người hỏi + tập thu hồi + danh sách chặn. Người dùng xem được phạm vi AI truy xuất của mình.",
     "Áp dụng triệt để: 0 rò rỉ chéo giữa các nhóm nhà đầu tư. Từ chối trung tính, không tiết lộ tài liệu ngoài quyền."),
    ("BR-05", "Trích dẫn & Kiểm chứng",
     "Mọi ý có trích dẫn nguyên văn; con số phải có trong câu trích; số từ bản scan chưa xác nhận gắn nhãn \"chưa "
     "chắc\"; link mở đúng file và vị trí trên SharePoint.",
     "Bắt buộc: Tuyệt đối không trả file gốc hay downloadUrl; câu trả lời chỉ gửi sau khi kiểm chứng xong."),
    ("BR-06", "Bảo mật đầu vào/đầu ra",
     "Chuẩn hóa câu hỏi, chặn prompt injection (luật tiếng Việt/Anh + bộ phân loại), che dữ liệu cá nhân, hạn mức theo "
     "người dùng; tài liệu luôn được coi là dữ liệu không đáng tin.",
     "Không tư vấn đầu tư. Chặn nhầm > 1% trên câu hỏi thật → chuyển sang chỉ ghi log."),
    ("BR-07", "Audit Log & Dashboard",
     "Ghi mọi câu hỏi, câu trả lời, file và phiên bản đã trích, từ chối, thay đổi quyền (chuỗi hash chống sửa). Dashboard "
     "trạng thái đồng bộ, model, chỉ mục, hàng chờ duyệt.",
     "Phục vụ kiểm toán IPO và truy vết an toàn thông tin (bắt buộc)."),
]

RULES = [
    ("1", ("AI có được tổng hợp câu trả lời cho nhà đầu tư hay chỉ tìm và trích nguyên văn? ",
           "(Bật/tắt Investor.AI.Summarize)."),
     "BR-01, BR-05, phạm vi PoC và cổng độ chính xác.", "Chờ cung cấp/xác nhận"),
    ("2", "Tách mỗi nhóm nhà đầu tư một site và bật RAC không; AI_Use mặc định cho file đang có?",
     "BR-03, BR-04, chỉ mục theo phân vùng, độ phủ AI.", "Chờ cung cấp/xác nhận"),
    ("3", "Có cho trích câu từ tài liệu chỉ-xem (chặn tải) và hiển thị ảnh cắt vùng trang scan không?",
     "BR-05, chính sách hiển thị, trách nhiệm vận hành.", "Chờ cung cấp/xác nhận"),
    ("4", "Ngưỡng chấp nhận: độ đúng ≥ 99% (tin cậy 95%), từ chối nhầm ≤ 15%, 0 rò rỉ; bộ lọc injection chặn hay chỉ ghi log.",
     "BR-06, tiêu chí UAT/Go-live, truyền thông với nhà đầu tư.", "Chờ cung cấp/xác nhận"),
]

INPUTS = [
    ("1", "Site thử Data Room, ≥ 10 tài khoản khách thử (B2B), cấp quyền Sites.Selected; chuyển người dùng OTP kiểu cũ sang B2B.",
     "Quản trị tenant", "Trước 14/10/2026 (Dùng cho 9 phép thử tích hợp; OTP trước 31/10/2026)"),
    ("2", "Tối thiểu 100 câu hỏi mẫu có đáp án và 50 trang scan mẫu (dấu đỏ, bảng, chữ ký) kèm con số chép lại.",
     "Trưởng deal team (Người nghiệp vụ)", "Trước 16/10/2026 (Dùng để Test & Tinh chỉnh độ chính xác)"),
]

UAT = [
    ("UAT-01", "Hỏi bộ câu chuẩn trên site thử (≥ 100 câu).",
     "Đánh giá theo các chỉ số: độ đúng ≥ 99% (tin cậy 95%) / từ chối nhầm ≤ 15% / 100% trích dẫn hợp lệ."),
    ("UAT-02", "Nhà đầu tư Nhóm B hỏi nội dung chỉ Nhóm A có.", "Hệ thống từ chối trung tính, 0 rò rỉ trên ma trận ≥ 3.000 phép thử."),
    ("UAT-03", "Gỡ nhà đầu tư khỏi nhóm / offboard / ngắt nguồn quyền.",
     "AI chặn ≤ 2 phút; nguồn quyền ngừng cập nhật → từ chối mọi câu hỏi trong ≤ 3 phút."),
    ("UAT-04", "Hỏi về bản scan bị xoay/mờ/dấu đè số.", "Số khớp đáp án người chép; số chưa xác nhận luôn có nhãn \"chưa chắc\"."),
    ("UAT-05", "Bắn bộ tấn công prompt injection đa ngôn ngữ.",
     "Không mẫu nào làm lộ dữ liệu; chặn nhầm ≤ 1% trên câu hỏi thật."),
]

MS_INTRO = "Dự án được phân bổ nguồn lực để hoàn thiện và nghiệm thu (UAT) trước ngày 20/11/2026."
MILESTONES = [
    ("07/10/2026", "Khởi động Dự án", "Kế hoạch tổng v0.6; demo local 4 cổng quyền, OCR, lớp bảo mật đã chạy. (Đang thực hiện)"),
    ("16/10/2026", "Baseline nghiệp vụ & PoC",
     "Chủ Data Room xác nhận Business Rule; có site thử, khách thử; chạy 9 phép thử tích hợp M365."),
    ("23/10/2026", "Tích hợp Luồng Lõi",
     "Kết nối Graph thật (delta, quyền, kiểm tra trực tiếp) thay tenant giả lập; nạp tài liệu site thử."),
    ("30/10/2026", "Demo Lần 1", "Demo trên site thử cho Chủ Data Room/BOD để lấy feedback; hạn chuyển OTP sang B2B 31/10."),
    ("13/11/2026", "Hoàn thiện Toàn bộ Tính năng",
     "Đăng nhập Entra, giao diện, kiểm chứng, nhật ký, dashboard, bộ lọc bảo mật; đo trên bộ câu chuẩn."),
    ("18/11/2026", "Kiểm thử & Quét bảo mật (Security Scan)", "QA nội bộ, ma trận rò rỉ, red-team, quét lỗ hổng."),
    ("20/11/2026", "Ready for Pilot / UAT", "Pilot nội bộ (nhân viên, cố vấn) → UAT → Fix → Sign-off trước khi mở cho nhà đầu tư."),
]

MATRIX = [
    ("Rò rỉ dữ liệu chéo ", "AI không trả lời thông tin mật của nhà đầu tư này cho nhà đầu tư khác ", "BR-04", "Must "),
    ("Prompt injection trực tiếp ", "Chặn câu hỏi ép bỏ quy tắc, lộ cấu hình, vượt quyền ", "BR-06", "Must "),
    ("Injection gián tiếp ", "Lệnh cài trong tài liệu chỉ được coi là dữ liệu, có gắn cờ ", "BR-02, BR-06", "Must "),
    ("Đa ngôn ngữ ", "Câu hỏi và tấn công tiếng Việt, tiếng Anh, trộn lẫn, ký tự ẩn ", "BR-06", "Must"),
    ("Phân quyền trước truy xuất ", "AI không tự quyết quyền; lọc quyền trước và trong lúc truy xuất ", "BR-04", "Should "),
    ("Quyền AI_QUERY ", "Cho phép AI đọc tài liệu để trả lời ", "BR-01, BR-04", "Must "),
    ("Quyền AI_SUMMARIZE ", "Cho phép AI tóm tắt, tổng hợp câu trả lời ", ("BR-01, ", "Pending Decision"), "Pending Decision "),
    ("Quyền AI_CITATION ", "Trích dẫn nguồn (phiên bản, trang, vị trí) ", "BR-05", "Must "),
    ("SSO, MFA, IAM ", "Định danh và phân quyền người dùng qua Entra ", "BR-01", "Must "),
    ("Input security ", "Chuẩn hóa Unicode, nhận diện ngôn ngữ, lọc PII, chặn ghi đè chỉ dẫn ", "BR-06", "Must "),
    ("Document security ", "Quét mã độc, phát hiện nội dung ẩn trong PDF/Excel ", "BR-02", "Should "),
    ("Permission-aware RAG ", "Lọc theo quyền, quản lý phiên bản tài liệu ", "BR-03, BR-04", "Must "),
    ("Output security ", "Chống hallucination, che dữ liệu nhạy cảm (DLP) ", "BR-05, BR-06", "Must "),
    ("Metadata quyền ", "Bản chép quyền + RLS + kiểm tra trực tiếp thay cho metadata trên vector DB ", "BR-03", "Must "),
    ("Quyền hết hạn ", "Quyền có hạn và access review hằng tháng ", "BR-03", "Pending Decision"),
    ("Guardrail tự host ", "Bộ lọc tự xây chạy nội bộ (không phụ thuộc cloud vendor) ", "BR-06", "Must "),
    ("Red-team đa ngôn ngữ ", "Bộ tấn công giữ riêng ≥ 300 câu + câu hỏi hợp lệ để đo chặn nhầm ", "BR-06", "Must "),
    ("Prompt an toàn ", "Đóng gói tài liệu trong thẻ <untrusted_document> ", "BR-06", "Must "),
    ("Grounding ", "Chỉ trả lời từ tài liệu; không có thì từ chối trung tính ", "BR-05", "Should "),
    ("OCR bản scan ", "Đọc PDF scan/ảnh, giữ dấu tiếng Việt, bảng, con dấu ", "BR-02", "Must "),
    ("Excel tài chính ", "Đọc trực tiếp xlsx, giữ đơn vị, kỳ, sheet ẩn ", "BR-02", "Must "),
    ("Làm sạch ký tự ẩn ", "Bỏ zero-width, ký tự giả dạng ở khâu nạp và ở câu hỏi ", "BR-02, BR-06", "Should "),
    ("Cắt đoạn theo cấu trúc ", "Không cắt giữa bảng tài chính ", "BR-02", "Should "),
    ("Audit log riêng cho AI ", "Ai hỏi gì, lúc nào, file và phiên bản nào ", "BR-07", "Should "),
    ("Bảo mật API & secret ", "Chỉ kết nối chiều ra, WAF tại DMZ, kho khóa riêng ", "BR-07", "Should "),
    ("Data residency ", "LLM on-prem tại Việt Nam, dữ liệu không ra ngoài ", "BR-04, BR-07", "Must "),
    ("Chống cạn tài nguyên ", "Hạn mức theo người dùng, trần số câu xử lý đồng thời ", "BR-06", "Should "),
    ("Số liệu chính xác ", "Con số phải có trong câu trích; độ đúng ≥ 99% (tin cậy 95%) ", "BR-05", "Should"),
]

REMOVE = (39, 40)   # the two reference lines under heading 9 (left empty on request)

HEADINGS = {27: "BUSINESS RULE CẦN CHỦ DATA ROOM XÁC NHẬN", 29: "CÁC BÊN CẦN CUNG CẤP (INPUTS)"}


# ------------------------------------------------------------------ text-only helpers
W_T = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _texts(p: Paragraph):
    return [t for r in p.runs for t in r._r.iter(W_T)]


def _set(t, text: str) -> None:
    t.text = text
    if text != text.strip():
        t.set(XML_SPACE, "preserve")


def put(p: Paragraph, text: str) -> None:
    """New text in the first text node; other text nodes emptied. Runs, tabs, breaks and
    formatting are never touched."""
    ts = _texts(p)
    if not ts:
        if text:
            raise ValueError(f"paragraph without text nodes: {p.text!r}")
        return
    _set(ts[0], text)
    for t in ts[1:]:
        _set(t, "")


def put_runs(p: Paragraph, parts) -> None:
    ts = _texts(p)
    assert len(parts) <= len(ts), (parts, [t.text for t in ts])
    for i, t in enumerate(ts):
        _set(t, parts[i] if i < len(parts) else "")


def put_cell(cell, value) -> None:
    parts = value if isinstance(value, tuple) else (value,)
    ps = cell.paragraphs
    assert len(parts) <= len(ps), (parts, [p.text for p in ps])
    for i, p in enumerate(ps):
        put(p, parts[i] if i < len(parts) else "")


def fill(t: Table, rows) -> None:
    body = t.rows[1:]
    assert len(rows) == len(body), f"table has {len(body)} rows, content has {len(rows)}"
    for r, vals in zip(body, rows):
        cells = r.cells
        assert len(vals) == len(cells)
        for c, v in zip(cells, vals):
            put_cell(c, v)


def build(src: str, out: str) -> None:
    d = docx.Document(src)
    els = list(d.element.body.iterchildren())
    P = lambda i: Paragraph(els[i], d)
    T = lambda i: Table(els[i], d)
    put_runs(P(5), TITLE)
    put_runs(P(9), DATE)
    for r, (k, v) in zip(T(12).rows, INFO):
        put_cell(r.cells[0], k)
        put_cell(r.cells[1], v)
    put(P(16), OBJECTIVE)
    put(P(17), IN_SCOPE)
    put(P(18), OUT_SCOPE)
    put(P(20), PIPE_INTRO)
    put(P(21), PIPE_B0)
    for i, line in zip((22, 23, 24), PIPE):
        put(P(i), line)
    fill(T(26), BR)
    for i, h in HEADINGS.items():
        put(P(i), h)
    fill(T(28), RULES)
    fill(T(30), INPUTS)
    fill(T(32), UAT)
    put(P(34), MS_INTRO)
    fill(T(35), MILESTONES)
    fill(T(37), [(str(i), *row) for i, row in enumerate(MATRIX, 1)])
    for i in REMOVE:                       # mục 9 để trống theo yêu cầu: bỏ hẳn 2 dòng tham khảo
        els[i].getparent().remove(els[i])
    for s in d.sections:
        for p in s.header.paragraphs:
            if p.text.strip():
                put(p, HEADER)
    tmp = out + ".tmp"
    d.save(tmp)
    with zipfile.ZipFile(src) as zs:
        changed = {n for n in zs.namelist() if n == "word/document.xml" or re.fullmatch(r"word/header\d+\.xml", n)}
    with zipfile.ZipFile(src) as zs, zipfile.ZipFile(tmp) as zt, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for info in zs.infolist():
            data = zt.read(info.filename) if info.filename in changed else zs.read(info.filename)
            zo.writestr(info, data)
    import os
    os.remove(tmp)


# ------------------------------------------------------------------ proof: only text changed
def _tree(el):
    """(tag, attributes, text, children) — namespace prefixes and formatting whitespace ignored."""
    text = (el.text or "").strip() if not isinstance(el.tag, str) or not el.tag.endswith("}t") else ""
    return (el.tag if isinstance(el.tag, str) else "#", tuple(sorted(el.attrib.items())), text,
            tuple(_tree(c) for c in el))


def skeleton(path: str, drop=()) -> dict[str, bytes]:
    """Every part, canonicalised (C14N), with all w:t text blanked and xml:space dropped."""
    from lxml import etree
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    out = {}
    with zipfile.ZipFile(path) as z:
        for n in sorted(z.namelist()):
            data = z.read(n)
            if n.endswith(".xml") or n.endswith(".rels"):
                root = etree.fromstring(data)
                if drop and n == "word/document.xml":
                    body = root.find(W + "body")
                    kids = list(body)
                    for i in drop:
                        body.remove(kids[i])
                for t in root.iter(W + "t"):
                    t.text = None
                    t.attrib.pop("{http://www.w3.org/XML/1998/namespace}space", None)
                data = repr(_tree(root)).encode()
            out[n] = data
    return out


def check(src: str, out: str) -> bool:
    a, b = skeleton(src, REMOVE), skeleton(out)   # the only intended structural change
    if set(a) != set(b):
        print("Khác danh sách phần:", set(a) ^ set(b))
        return False
    diff = [n for n in a if a[n] != b[n]]
    print("Phần khác ngoài chữ:", diff or "không có")
    return not diff


if __name__ == "__main__":
    src, out = sys.argv[1], sys.argv[2]
    build(src, out)
    print("Đã lưu", out)
    if "--check" in sys.argv:
        sys.exit(0 if check(src, out) else 1)
