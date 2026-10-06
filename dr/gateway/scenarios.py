"""Demo scenarios: each mutates the fake tenant (or the mirror, for the fault-injection
case) and explains what to try next."""
from __future__ import annotations

from dr.db import pg

GROUP_NAMES = {"DR-INV-A": "Nhóm A", "DR-INV-B": "Nhóm B", "DR-INV-C": "Nhóm C"}


def _first_item(tenant, site: str, exclude: tuple = ()) -> str:
    for iid, it in tenant.items.items():
        if it["site"] == site and it["ai_use"] == "Allowed" and not it["encrypted"] and not it["malware"] \
                and iid not in exclude and not iid.startswith("sp-") and it["ext"] in ("docx", "pdf", "xlsx", "pptx"):
            return iid
    raise ValueError(f"không tìm thấy tài liệu phù hợp ở site {site}")


def run(name: str, params: dict, tenant, connector) -> dict:
    lag = int(tenant.group_lag)
    if name == "remove_from_group":
        oid, gid = params.get("oid", "inv-ab"), params.get("group", "DR-INV-A")
        tenant.remove_member(gid, oid)
        return {"title": f"Gỡ {tenant.users[oid]['name']} khỏi {GROUP_NAMES.get(gid, gid)}",
                "explain": (f"Entra đổi ngay; SharePoint giả lập mất {lag} giây mới áp (thực tế tới 1 ngày). "
                            "Trong khoảng đó người này vẫn MỞ được file trên SharePoint, nhưng AI đã chặn nhờ tập thu hồi "
                            "theo (người, nhóm) và vẫn trả lời từ nhóm còn lại."),
                "try": f"Đăng nhập {oid}, hỏi một câu về {GROUP_NAMES.get(gid, gid)} và xem tab Phạm vi."}
    if name == "move_group":
        oid, src, dst = params.get("oid", "inv-a2"), params.get("from", "DR-INV-A"), params.get("to", "DR-INV-C")
        tenant.remove_member(src, oid)
        tenant.add_member(dst, oid)
        return {"title": f"Chuyển {tenant.users[oid]['name']} từ {GROUP_NAMES.get(src)} sang {GROUP_NAMES.get(dst)}",
                "explain": (f"Quyền mới có hiệu lực ở AI sau một lần đồng bộ; SharePoint cần {lag} giây. Tài liệu nhóm cũ bị "
                            "AI chặn ngay. Tài liệu nhóm mới: AI chỉ dùng khi SharePoint cũng xác nhận (kiểm tra trực tiếp), "
                            f"nên trong {lag} giây đầu có thể chưa thấy."),
                "try": f"Đăng nhập {oid}, so sánh tab Phạm vi trước và sau {lag} giây."}
    if name == "exclude_file":
        iid = params.get("item_id") or _first_item(tenant, "COMMON")
        tenant.set_ai_use(iid, "Excluded")
        return {"title": f"Đặt AI_Use = Excluded cho «{tenant.items[iid]['name']}»",
                "explain": "Kiểm tra trực tiếp đọc lại AI_Use nên câu hỏi kế tiếp đã không dùng được file; "
                           "connector xóa các đoạn của file ở lần đồng bộ kế tiếp. Nhà đầu tư vẫn mở file trên SharePoint.",
                "try": "Xem tab Phạm vi: file chuyển sang trạng thái 'Không cho AI'.", "item_id": iid}
    if name == "publish_redacted_version":
        iid = params.get("item_id", "sp-version")
        ok = tenant.publish_version(iid)
        return {"title": f"Thay «{tenant.items[iid]['name']}» bằng bản đã biên tập",
                "explain": ("ctag đổi → các đoạn của bản cũ bị vô hiệu ngay (is_current=false) và kiểm tra trực tiếp so ctag, "
                            "nên AI không bao giờ trích bản cũ; bản mới được nạp lại ở nền." if ok else
                            "File này không còn phiên bản chờ."),
                "try": "Đăng nhập inv-b1 hỏi về 'đối tác bảo lãnh, hạn mức' trước và sau."}
    if name == "offboard":
        oid = params.get("oid", "inv-b2")
        tenant.set_user_enabled(oid, False)
        return {"title": f"Ngừng quyền (offboard) {tenant.users[oid]['name']}",
                "explain": "Tài khoản bị tắt trong Entra → danh sách chặn của AI cập nhật trong vài giây; "
                           "token cũ dù còn hạn cũng bị cổng 4 từ chối.",
                "try": f"Giữ phiên của {oid} và hỏi tiếp: câu trả lời bị từ chối."}
    if name == "corrupt_mirror":
        oid = params.get("oid", "inv-b1")
        iid = params.get("item_id") or _first_item(tenant, "GRP-A")
        with pg.admin() as c:
            c.execute("INSERT INTO item_reader VALUES (%s,%s,'group','FAULT-INJECTION') ON CONFLICT DO NOTHING",
                      (iid, oid))
            c.commit()
        return {"title": f"Cố tình làm hỏng bản chép quyền: cho {oid} 'đọc' «{tenant.items[iid]['name']}» (Nhóm A)",
                "explain": "RLS bây giờ cho phép sai, nhưng cổng 2 hỏi lại SharePoint bằng danh tính người dùng → 403 → "
                           "file bị loại im lặng. Bản chép sai sẽ được sửa ở lần dựng lại kế tiếp.",
                "try": f"Đăng nhập {oid}, hỏi về nội dung Nhóm A rồi mở 'Chi tiết các cổng'.", "item_id": iid}
    if name == "pause_entra_feed":
        tenant.set_entra_paused(True)
        return {"title": "Ngắt nguồn delta của Entra (giả lập sự cố)",
                "explain": "Danh sách chặn và tập thu hồi không còn cập nhật được. Sau 30 giây hệ thống tự từ chối mọi câu hỏi "
                           "(đóng an toàn) thay vì trả lời với dữ liệu quyền cũ.",
                "try": "Đợi 30 giây rồi hỏi bất kỳ câu nào; sau đó bấm 'Khôi phục nguồn'."}
    if name == "resume_entra_feed":
        tenant.set_entra_paused(False)
        return {"title": "Khôi phục nguồn delta Entra", "explain": "Lần đồng bộ kế tiếp làm mới mốc thời gian.", "try": ""}
    if name == "reset":
        tenant.load()
        connector.full_resync()
        with pg.admin() as c:
            c.execute("DELETE FROM item_reader WHERE via_id='FAULT-INJECTION'")
            c.commit()
        return {"title": "Khôi phục trạng thái ban đầu",
                "explain": "Nạp lại tenant gốc và đồng bộ toàn bộ; file đã đổi phiên bản sẽ được nạp lại ở nền.", "try": ""}
    raise ValueError(f"Kịch bản không tồn tại: {name}")
