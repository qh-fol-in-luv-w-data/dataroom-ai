"""Build a demo tenant from the CT Group SharePoint download sorted by organize_dataroom.py.

One site ("AI Data Room CT Group") holds the 01–07 folder tree; six groups A–F get access per
folder following the permission matrix of the proposal (Read and Edit both count as access).
Files are hard-linked into the tenant, so no disk space is used twice.

    python scripts/build_ctg_tenant.py "data/AI Data Room" data/ctg
    DR_DATA=data/ctg DR_PGDATA=pgdata_ctg DR_PG_PORT=55433 python scripts/ingest.py

Writes <out>/tenant/tenant.json, <out>/tenant/files/CTG/..., <out>/tenant/DEMO_ACCOUNTS.md.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dr.gateway.accounts import hash_password  # noqa: E402

SITE = "CTG"
GROUPS = {  # id: (name, demo user oid, user name, org, roles)
    "CTG-A": ("Nhà đầu tư / CĐT (Investor)", "ctg-a", "Nhà đầu tư A", "Quỹ đầu tư (demo)",
              ["Investor.AI", "Investor.AI.Summarize"]),
    "CTG-B": ("Ban dự án (Deal Team)", "ctg-b", "Ban dự án B", "CT Group", ["Staff.AI"]),
    "CTG-C": ("Ban lãnh đạo (BOD)", "ctg-c", "Ban lãnh đạo C", "CT Group", ["Staff.AI"]),
    "CTG-D": ("Nhân sự nội bộ thẩm định (Internal DD)", "ctg-d", "Thẩm định nội bộ D", "CT Group", ["Staff.AI"]),
    "CTG-E": ("Tư vấn / Đối tác (Advisor)", "ctg-e", "Tư vấn E", "Công ty tư vấn (demo)",
              ["Investor.AI", "Investor.AI.Summarize"]),
    "CTG-F": ("Khách khác (Guest)", "ctg-f", "Khách F", "Khách (demo)", ["Investor.AI"]),
}
# Folder -> groups with access, from the matrix. Sub-folders not listed inherit their top folder.
MATRIX = {
    "01. Tổng quan dự án": "ABCDEF",
    "02. Tài chính": "ABCDE",
    "02. Tài chính/2.1 Báo cáo tài chính": "ABE",
    "02. Tài chính/2.2 Ngân sách & Dòng tiền": "ABE",
    "02. Tài chính/2.3 Kiểm toán": "ABE",
    "03. Pháp lý": "ABCDE",
    "03. Pháp lý/3.1 Giấy phép & Phê duyệt": "ABC",
    "03. Pháp lý/3.2 Hợp đồng": "ABC",
    "03. Pháp lý/3.3 Tuân thủ & Quy định": "ABC",
    "04. Kỹ thuật & Vận hành": "ABCDE",
    "05. Thị trường & Kinh doanh": "ABCD",
    "06. Nhân sự & Tổ chức": "BD",
    "07. Khác": "A",
}

# BR-08 topics narrowed to the IPO meaning: in a real-estate room "phân bổ ngân sách" and "bảng giá căn hộ"
# are ordinary questions, unlike share allocation or the offering price (default list in dr/core/review.py)
SENSITIVE_TOPICS = {
    "dinh_gia": {"label": "Định giá doanh nghiệp",
                 "terms": ["dinh gia doanh nghiep", "dinh gia cong ty", "valuation", "gia tri doanh nghiep",
                           "enterprise value", "ev/ebitda", "p/e"]},
    "gia_chao_ban": {"label": "Giá chào bán cổ phiếu",
                     "terms": ["gia chao ban co phieu", "gia phat hanh co phieu", "gia co phieu du kien", "offering price",
                               "offer price", "ipo price", "price range"]},
    "phan_bo": {"label": "Phân bổ cổ phần",
                "terms": ["phan bo co phan", "phan bo co phieu", "share allocation", "allotment",
                          "duoc mua bao nhieu co phieu", "uu tien mua co phieu"]},
    "cam_ket_loi_nhuan": {"label": "Cam kết lợi nhuận / cổ tức",
                          "terms": ["cam ket loi nhuan", "loi nhuan dam bao", "guaranteed return", "co tuc du kien",
                                    "expected dividend", "dividend forecast"]},
    "du_bao": {"label": "Dự báo tài chính",
               "terms": ["du bao loi nhuan", "du bao doanh thu", "ke hoach loi nhuan", "profit forecast",
                         "revenue forecast", "guidance"]},
    "tranh_chap": {"label": "Tranh chấp / kiện tụng",
                   "terms": ["tranh chap", "kien tung", "litigation", "lawsuit", "khieu kien", "dispute",
                             "arbitration", "trong tai"]},
}


def write_topics(tdir: Path) -> None:
    (tdir / "sensitive_topics.json").write_text(json.dumps(SENSITIVE_TOPICS, ensure_ascii=False, indent=1),
                                                encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="folder produced by organize_dataroom.py")
    ap.add_argument("out", help="data dir for the app (DR_DATA); the tenant goes to <out>/tenant")
    ap.add_argument("--password")
    a = ap.parse_args(argv)
    src, tdir = Path(a.src), Path(a.out) / "tenant"
    files_root = tdir / "files" / SITE

    items, n_new = [], 0
    for root, _, names in os.walk(src):
        for name in sorted(names):
            if name.startswith("_") and root == str(src) or name == ".DS_Store":
                continue
            rel = Path(os.path.relpath(os.path.join(root, name), src))
            dest = files_root / rel
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.link(os.path.join(root, name), dest)  # hard link: same bytes, no extra space
                n_new += 1
            items.append({"id": f"ctg-{len(items) + 1:05d}", "site": SITE, "path": rel.parent.as_posix(),
                          "name": name, "ext": rel.suffix.lower().lstrip("."), "file": f"{SITE}/{rel.as_posix()}",
                          "ai_use": "Allowed", "label": "Nội bộ", "title": rel.stem})

    folders = [{"site": SITE, "path": path, "unique": True,
                "grants": [{"kind": "group", "id": f"CTG-{g}"} for g in letters]}
               for path, letters in MATRIX.items()]
    pw = a.password or f"CTGroup-{secrets.token_hex(3)}-2026"
    users = [{"oid": oid, "name": uname, "org": org, "type": "guest" if "Investor.AI" in roles else "member",
              "enabled": True, "roles": roles, "email": f"{oid}@ctgroup-demo.example", "pw": hash_password(pw)}
             for gid, (_, oid, uname, org, roles) in GROUPS.items()]
    admins = [{"oid": "admin", "name": "Quản trị Data Room CT Group", "email": "admin@ctgroup-demo.example",
               "org": "CT Group", "type": "admin", "pw": hash_password(pw)}]
    tenant = {"tenant": "CT Group (demo)", "seed": 0, "users": users,
              "groups": [{"id": gid, "name": g[0], "members": [g[1]]} for gid, g in GROUPS.items()],
              "sites": [{"id": SITE, "name": "AI Data Room CT Group", "groups": list(GROUPS), "rac": True}],
              "folders": folders, "items": items, "admins": admins}
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "tenant.json").write_text(json.dumps(tenant, ensure_ascii=False, indent=1), encoding="utf-8")
    (tdir / "tenant.original.json").unlink(missing_ok=True)
    write_topics(tdir)

    lines = ["# Tài khoản demo CT Group (chỉ dùng trên máy local)", "",
             f"Mật khẩu chung: `{pw}`", "", "| Email | Nhóm | Vai trò |", "|---|---|---|",
             f"| {admins[0]['email']} | Quản trị | — |"]
    for gid, (gname, oid, _, _, roles) in GROUPS.items():
        lines.append(f"| {oid}@ctgroup-demo.example | {gid[-1]} – {gname} | {', '.join(roles)} |")
    lines += ["", "## Quyền theo thư mục", "", "| Thư mục | Nhóm được xem |", "|---|---|"]
    lines += [f"| {p} | {', '.join(l)} |" for p, l in MATRIX.items()]
    (tdir / "DEMO_ACCOUNTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(items)} file ({n_new} liên kết mới), {len(users)} người dùng, {len(folders)} thư mục có quyền riêng")
    print(f"Tenant: {tdir}  ·  tài khoản: {tdir / 'DEMO_ACCOUNTS.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
