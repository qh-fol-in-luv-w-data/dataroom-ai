"""A small, hand-written tenant used by unit tests."""
import json
from pathlib import Path


class Clock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


def make_tenant(root: Path) -> Path:
    files = root / "files"
    files.mkdir(parents=True, exist_ok=True)
    docs = {
        "c1": ("COMMON", "Chung", "Báo cáo chung KS-COMMON-0001. Doanh thu năm 2025 là 1.250 tỷ đồng."),
        "a1": ("GRP-A", "Tai-lieu", "Thỏa thuận nhóm A KS-GRPA-0001. Phí thu xếp 0,8%."),
        "a2": ("GRP-A", "Rieng-a1", "Phụ lục riêng cho An KS-GRPA-0002."),
        "b1": ("GRP-B", "Tai-lieu", "Cam kết nhóm B KS-GRPB-0001. Bảo lãnh tỷ giá 25.400."),
        "b2": ("GRP-B", "Tai-lieu", "Tài liệu B chia sẻ nhầm cho C KS-GRPB-0002."),
        "x1": ("COMMON", "Chung", "Tài liệu bị loại khỏi AI KS-COMMON-0002."),
        "i1": ("INTERNAL", "Noi-bo", "Định giá nội bộ KS-INTERNAL-0001."),
    }
    items = []
    for iid, (site, folder, text) in docs.items():
        f = files / f"{iid}.txt"
        f.write_text(text, encoding="utf-8")
        items.append({"id": iid, "site": site, "path": folder, "name": f"{iid}.txt", "ext": "txt",
                      "file": f.name, "ai_use": "Allowed", "grants": []})
    (files / "a1_v2.txt").write_text("Thỏa thuận nhóm A (bản đã biên tập) KS-GRPA-0001.", encoding="utf-8")
    for it in items:
        if it["id"] == "x1":
            it["ai_use"] = "Excluded"
        if it["id"] == "b2":
            it["grants"] = [{"kind": "link_specific", "id": "inv-c1"}, {"kind": "link_anyone", "id": "*"}]
        if it["id"] == "a1":
            it["pending_versions"] = [{"file": "a1_v2.txt", "note": "redacted"}]
    tenant = {
        "users": [
            {"oid": "inv-a1", "name": "An", "type": "guest", "roles": ["Investor.AI"]},
            {"oid": "inv-b1", "name": "Bình", "type": "guest", "roles": ["Investor.AI"]},
            {"oid": "inv-c1", "name": "Cường", "type": "guest", "roles": ["Investor.AI"]},
            {"oid": "inv-ab", "name": "Hai nhóm", "type": "guest", "roles": ["Investor.AI"]},
            {"oid": "inv-noai", "name": "Không AI", "type": "guest", "roles": []},
            {"oid": "staff-1", "name": "Nhân viên", "type": "member", "roles": ["Staff.AI"]},
        ],
        "groups": [
            {"id": "DR-INV-A", "members": ["inv-a1", "inv-ab", "inv-noai"]},
            {"id": "DR-INV-B", "members": ["inv-b1", "inv-ab"]},
            {"id": "DR-INV-C", "members": ["inv-c1"]},
            {"id": "STAFF", "members": ["staff-1"]},
        ],
        "sites": [
            {"id": "COMMON", "name": "Chung", "groups": ["DR-INV-A", "DR-INV-B", "DR-INV-C", "STAFF"], "rac": True},
            {"id": "GRP-A", "name": "Nhóm A", "groups": ["DR-INV-A", "STAFF"], "rac": True},
            {"id": "GRP-B", "name": "Nhóm B", "groups": ["DR-INV-B", "STAFF"], "rac": True},
            {"id": "INTERNAL", "name": "Nội bộ", "groups": ["STAFF"], "rac": True},
        ],
        "folders": [
            {"site": "GRP-A", "path": "Rieng-a1", "unique": True,
             "grants": [{"kind": "user", "id": "inv-a1"}, {"kind": "group", "id": "STAFF"}]},
        ],
        "items": items,
    }
    (root / "tenant.json").write_text(json.dumps(tenant, ensure_ascii=False, indent=1), encoding="utf-8")
    return root
