"""Sort a SharePoint download into the AI Data Room folder tree (01 Tổng quan … 07 Khác).

Each file is classified from its own name first, then from its folders (deepest first), then from
the numbered section it came from on SharePoint. The target keeps the company and the rest of the
original path below the category folder, so nothing collides and context is not lost:

    <out>/<03. Pháp lý>/<3.2 Hợp đồng>/<CTY …>/<original sub-path>/<file>

    python scripts/organize_dataroom.py SRC OUT            # writes OUT/_plan.csv only
    python scripts/organize_dataroom.py SRC OUT --apply    # moves files, writes OUT/_moves.csv
    python scripts/organize_dataroom.py SRC OUT --undo     # moves them back using _moves.csv
"""
import argparse
import csv
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

TREE = {
    "1.1": ("01. Tổng quan dự án", "1.1 Giới thiệu"),
    "1.2": ("01. Tổng quan dự án", "1.2 Kế hoạch & Tiến độ"),
    "1.3": ("01. Tổng quan dự án", "1.3 Các bên liên quan"),
    "2.1": ("02. Tài chính", "2.1 Báo cáo tài chính"),
    "2.2": ("02. Tài chính", "2.2 Ngân sách & Dòng tiền"),
    "2.3": ("02. Tài chính", "2.3 Kiểm toán"),
    "3.1": ("03. Pháp lý", "3.1 Giấy phép & Phê duyệt"),
    "3.2": ("03. Pháp lý", "3.2 Hợp đồng"),
    "3.3": ("03. Pháp lý", "3.3 Tuân thủ & Quy định"),
    "4.1": ("04. Kỹ thuật & Vận hành", "4.1 Thiết kế kỹ thuật"),
    "4.2": ("04. Kỹ thuật & Vận hành", "4.2 Vận hành & Bảo trì"),
    "4.3": ("04. Kỹ thuật & Vận hành", "4.3 An toàn & Môi trường"),
    "5.1": ("05. Thị trường & Kinh doanh", "5.1 Nghiên cứu thị trường"),
    "5.2": ("05. Thị trường & Kinh doanh", "5.2 Khách hàng & Đối tác"),
    "5.3": ("05. Thị trường & Kinh doanh", "5.3 Chiến lược kinh doanh"),
    "6.1": ("06. Nhân sự & Tổ chức", "6.1 Cơ cấu tổ chức"),
    "6.2": ("06. Nhân sự & Tổ chức", "6.2 Chính sách nhân sự"),
    "7": ("07. Khác", None),
}

# Checked in this order against one name at a time (file name, then each folder deepest-first);
# patterns are matched on upper-case text with Vietnamese accents removed.
RULES = [
    ("2.3", r"KIEM TOAN|AUDIT"),
    ("2.1", r"BCTC|BAO CAO TAI CHINH|FINANCIAL STATEMENT|BANG CAN DOI|KET QUA KINH DOANH"),
    ("2.2", r"NGAN SACH|DONG TIEN|CASH ?FLOW|BUDGET|DU TOAN|DON GIA|CHI PHI|TAM UNG|THANH TOAN|QUYET TOAN|BAO GIA"),
    ("6.1", r"SO DO TO CHUC|CO CAU TO CHUC|ORG ?CHART|BO MAY"),
    ("6.2", r"NHAN SU|TUYEN DUNG|TIEN LUONG|BANG LUONG|\bKPI\b|DAO TAO|\bHR\b"),
    ("4.3", r"PCCC|PHONG CHAY|\bAN TOAN\b|MOI TRUONG|\bDTM\b|\bHSE\b"),
    ("3.2", r"HOP DONG|\bHD\b|\bHDMB\b|CONTRACT|PHU LUC|THOA THUAN|DAT COC|\bMOU\b"),
    ("3.1", r"GIAY PHEP|PHE DUYET|QUYET DINH|\bQD\b|TO TRINH|CHU TRUONG|GIAY CHUNG NHAN|\bGCN|SO DO|GPXD|PHAP LY"),
    ("3.3", r"QUY CHE|QUY DINH|QUY TRINH|\bQTNB\b|TUAN THU|THONG BAO|CONG VAN|UY QUYEN"),
    ("4.2", r"BAN GIAO|VAN HANH|BAO TRI|BAO DUONG|NGHIEM THU|QUAN LY BDS|DON GIA DIEN|HO SO KY THUAT"),
    ("4.1", r"BAN VE|\bBV\b|THIET KE|KET CAU|KIEN TRUC|\bMEP\b|CAO DO|MAT BANG|SAN XUAT-XAY DUNG|XAY DUNG|THI CONG|\bTKCS\b|\bTKKT\b"),
    ("1.2", r"TIEN DO|SCHEDULE|TIMELINE|KE HOACH TRIEN KHAI"),
    ("1.3", r"NHA THAU|CHU DAU TU|CAC BEN|STAKEHOLDER"),
    ("1.1", r"GIOI THIEU|PROFILE|TONG QUAN|OVERVIEW"),
    ("5.1", r"NGHIEN CUU|THI TRUONG|KHAO SAT|DOI THU|MARKET RESEARCH|PHAN TICH"),
    ("5.3", r"SALES? ?KIT|SHOW ?FLAT|SALES? GALLER"),  # sales collateral is marketing, not customers
    ("5.2", r"KHACH HANG|DAI LY|DOI TAC|\bSALES?\b|\bKH\b|\bF1\b|CUSTOMER|PARTNER"),
    ("5.3", r"KE HOACH KINH DOANH|CHIEN LUOC|CHINH SACH BAN HANG|MARKETING|TRUYEN THONG|5PS|PROMOT|PRODUCT|PLAC|PRIC|\bPR\b|"
            r"EVENT|SALES ?KIT|VIRAL|BANNER|SOCIAL|KINH DOANH TIEP THI|KE HOACH"),
]
RULES = [(code, re.compile(p)) for code, p in RULES]
FONT_EXT = {".ttf", ".otf", ".woff", ".woff2", ".fon"}


def plain(s):
    s = unicodedata.normalize("NFD", s.replace("Đ", "D").replace("đ", "d"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper()


def classify(rel):
    parts = Path(rel).parts
    if Path(rel).suffix.lower() in FONT_EXT:
        return "7", "font"
    names = [Path(parts[-1]).stem] + list(reversed(parts[1:-1]))  # skip the company folder
    for name in names:
        n = plain(name)
        for code, rx in RULES:
            if rx.search(n):
                return code, name
    return "7", ""


def target(out, rel, code):
    top, sub = TREE[code]
    base = Path(out) / top / sub if sub else Path(out) / top
    return base / rel


def plan(src, out):
    rows = []
    for root, _, files in os.walk(src):
        for f in files:
            if f in ("_manifest.json", "_plan.csv", "_moves.csv", ".DS_Store") or f.endswith(".part"):
                continue
            rel = os.path.relpath(os.path.join(root, f), src)
            code, why = classify(rel)
            rows.append({"src": rel, "code": code, "dest": str(target(out, rel, code).relative_to(out)), "why": why})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true")
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)

    if args.undo:
        with open(out / "_moves.csv", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                d, s = out / r["dest"], src / r["src"]
                if d.exists():
                    s.parent.mkdir(parents=True, exist_ok=True)
                    os.rename(d, s)
        print("Đã chuyển ngược lại", src)
        return

    rows = plan(src, out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "_plan.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["code", "src", "dest", "why"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["code"], r["src"])))
    counts = Counter(r["code"] for r in rows)
    for code, (top, sub) in TREE.items():
        print(f"{counts.get(code, 0):6}  {top} / {sub or ''}")
    print(f"{len(rows):6}  tổng — kế hoạch: {out / '_plan.csv'}")

    if args.apply:
        log = out / "_moves.csv"
        new_log = not log.exists()
        with open(log, "a", encoding="utf-8", newline="") as fh:  # append: --apply can be re-run on leftovers
            w = csv.DictWriter(fh, fieldnames=["src", "dest"])
            if new_log:
                w.writeheader()
            for r in rows:
                d = out / r["dest"]
                d.parent.mkdir(parents=True, exist_ok=True)
                os.rename(src / r["src"], d)  # same disk: a rename, no extra space
                w.writerow({"src": r["src"], "dest": r["dest"]})
        for root, _, _ in sorted(os.walk(src), key=lambda t: -len(t[0])):
            if root != str(src) and not os.listdir(root):
                os.rmdir(root)
        print("Đã di chuyển", len(rows), "file vào", out)


if __name__ == "__main__":
    sys.exit(main())
