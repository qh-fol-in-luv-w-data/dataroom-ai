"""Q&A benchmark on what was OCR-ed (images, scanned contracts) in the CT Group tenant, with follow-up
questions, a recap, and questions asked by users who may not read the answer's folder.

Runs the real answer path in-process (gates, search, rerank, LLM, verification, conversation memory).
A case passes when every expected number (digits only) and word is in the answer and, for a refusal case,
none of the forbidden numbers is. Pause bulk ingest first: it shares Ollama.

    DR_DATA=data/ctg DR_PGDATA=~/.dr_ctg/pgdata DR_PG_PORT=55433 python scripts/ctg_ocr_eval.py
"""
from __future__ import annotations

import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dr.connector.sync import Connector  # noqa: E402
from dr.core import answer, conversation  # noqa: E402
from dr.core.pgindex import make_index  # noqa: E402
from dr.models import llm  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402

# (user, conversation or None, kind, question, digits that must appear ("a|b": either, when the data room holds two
#  versions of the document), words that must appear, digits that must not). A refusal case uses a fact found only
#  in folders the user may not read (checked against the chunks: e.g. Busway contract 224/2022 only in 03.x).
CASES = [
    ("ctg-b", "nh", "ảnh: mặt bằng", "Căn hộ B4 dự án C.T Plaza Nguyên Hồng có diện tích thông thủy bao nhiêu?",
     ["5255|5288"], [], []),
    ("ctg-b", "nh", "hỏi nối tiếp", "Còn căn A6 thì diện tích thông thủy là bao nhiêu?", ["6341|6351"], [], []),
    ("ctg-b", "nh", "tổng hợp", "Tổng hợp lại diện tích thông thủy các căn hộ đã hỏi ở trên", ["5255|5288", "6341|6351"], [], []),
    ("ctg-b", None, "ảnh: mặt bằng", "Căn hộ A6 C.T Plaza Nguyên Hồng có diện tích xây dựng bao nhiêu?", ["6709|6681"], [], []),
    # two floor plans of B4 disagree: the answer must give both values, not pick one (conflicts.py)
    ("ctg-b", None, "mâu thuẫn", "Diện tích thông thủy của căn hộ B4 C.T Plaza Nguyên Hồng là bao nhiêu?",
     ["5255", "5288"], [], []),
    ("ctg-b", None, "ảnh: bảng", "Căn S-01 C.T Plaza Minh Châu có diện tích thông thủy bao nhiêu m²?", ["264"], [], []),
    ("ctg-b", None, "ảnh: bảng", "Căn S-08 C.T Plaza Minh Châu có diện tích thông thủy bao nhiêu?", ["284"], [], []),
    ("ctg-b", None, "ảnh: bảng", "Căn penthouse PS1 của Léman Luxury có diện tích thông thủy bao nhiêu?", ["30309"], [], []),
    ("ctg-b", None, "ảnh: bảng", "Căn penthouse PD2 của Léman Luxury có diện tích thông thủy bao nhiêu?",
     ["16309|32618"], [], []),     # PD2 spans floors 23 and 24: 163.09 m² a floor, 326.18 m² in the price list
    ("ctg-b", None, "ảnh: mặt bằng", "Căn hộ 3 phòng ngủ loại E của C.T Plaza Minh Châu có diện tích thông thủy bao nhiêu?", ["9085"], [], []),
    ("ctg-b", None, "ảnh: quảng cáo", "Căn studio C.T Plaza Minh Châu có giá chỉ từ bao nhiêu?", [], ["1,4"], []),
    ("ctg-b", None, "ảnh: ấn phẩm", "Dự án căn hộ studio DIYAS ở địa chỉ nào?", ["16"], ["Nguyễn Đức Thuận"], []),
    ("ctg-b", None, "ảnh: khuyến mãi", "Chương trình 'Thanh toán nhanh tay đón ngay tài lộc' mùa hè 2022 của CT Plaza "
                                       "Minh Châu có giải nhất là gì?", [], ["vàng"], []),
    ("ctg-b", None, "ảnh: khuyến mãi", "Khách hàng nữ mua căn hộ C.T Plaza Nguyên Hồng dịp 20/10/2016 nhận quà tổng "
                                       "giá trị bao nhiêu?", ["70"], ["triệu"], []),
    ("ctg-b", None, "ảnh: danh thiếp", "Mã số thuế của Công ty TNHH Đại lý thuế Hoài Nhơn là gì?", ["4101592575"], [], []),
    ("ctg-b", None, "ảnh: ấn phẩm", "Dự án Diamond Square có địa chỉ ở đâu?", ["29"], ["Trần Hưng Đạo"], []),
    ("ctg-b", None, "ảnh: tuyển dụng", "Tin tuyển dụng Cyber Sale 4.0 của Léman Parking Lot hứa thu nhập bao nhiêu "
                                       "mỗi tháng?", ["50"], [], []),
    ("ctg-b", None, "PDF scan", "Hợp đồng cung cấp và lắp đặt Busway dự án Minh Châu ngày 23/06/2022 có số hợp đồng là gì?",
     ["2242022"], [], []),
    ("ctg-b", None, "PDF scan", "Số hợp đồng cung cấp và lắp đặt hệ thống PCCC ngày 12/08/2022 là gì?", ["3072022"], [], []),
    ("ctg-b", None, "PDF scan", "Nhà chung cư MONTALP Residences nằm ở địa chỉ nào?", ["360"], ["Võ Nguyên Giáp"], []),
    ("ctg-b", None, "PDF scan", "Dự án MONTALP Residences thuộc thửa đất số mấy, tờ bản đồ số mấy?", ["13", "83"], [], []),
    ("ctg-b", None, "PDF scan", "Công văn của Cục Tác chiến ngày 02/6/2009 về việc đính chính văn bản, gửi Công ty "
                                "Minh Châu, mang số hiệu bao nhiêu?", ["1336"], [], []),
    ("ctg-f", None, "khách: được phép", "Căn hộ A6 C.T Plaza Nguyên Hồng có diện tích xây dựng bao nhiêu?", ["6709|6681"], [], []),
    ("ctg-f", None, "vượt quyền", "Hợp đồng cung cấp và lắp đặt Busway dự án Minh Châu ngày 23/06/2022 có số hợp đồng "
                                  "là gì?", [], [], ["2242022"]),
    ("ctg-d", None, "vượt quyền", "Hợp đồng cung cấp và lắp đặt Busway dự án Minh Châu ngày 23/06/2022 có số hợp đồng "
                                  "là gì?", [], [], ["2242022"]),
    ("ctg-e", None, "vượt quyền", "Hợp đồng cung cấp và lắp đặt Busway dự án Minh Châu ngày 23/06/2022 có số hợp đồng "
                                  "là gì?", [], [], ["2242022"]),
    ("ctg-e", None, "vượt quyền", "Tin tuyển dụng Cyber Sale 4.0 của Léman Parking Lot hứa thu nhập bao nhiêu mỗi tháng?",
     [], [], ["50"]),
    ("ctg-c", None, "vượt quyền", "Tin tuyển dụng Cyber Sale 4.0 của Léman Parking Lot hứa thu nhập bao nhiêu mỗi tháng?",
     [], [], ["50"]),
]


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def main() -> int:
    tenant = FakeTenant()
    conn = Connector(tenant)
    conn.full_resync()
    stop = threading.Event()        # keep the permission feed fresh like the app does (gate 4)
    threading.Thread(target=conn.run_forever, args=(stop,), daemon=True).start()
    index = make_index()
    index.refresh()
    deps = answer.Deps.real()
    llm.warm()
    results, times = [], []
    for oid, conv, kind, q, need, words, never in CASES:
        conv_id = f"eval-{conv}" if conv else None
        t = time.time()
        r = answer.ask(tenant, index, oid, tenant.users[oid]["roles"], q, deps,
                       history=conversation.history(oid, conv_id) if conv_id else None)
        if conv_id:
            conversation.remember(oid, conv_id, q, r)
        dt = time.time() - t
        times.append(dt)
        text = r.get("message") or " ".join(c["text"] for c in r.get("claims", []))
        d = digits(text)
        good = (all(any(a in d for a in e.split("|")) for e in need) and all(w.lower() in text.lower() for w in words)
                and not any(e in d for e in never))
        results.append((kind, good))
        print(f"[{'ĐÚNG' if good else 'SAI '}] {dt:5.1f}s {oid} ({kind}) {q}\n         → {text[:230]}", flush=True)
    stop.set()
    by_kind: dict[str, list[int]] = {}
    for kind, good in results:
        g = "vượt quyền" if kind == "vượt quyền" else kind.split(":")[0]
        by_kind.setdefault(g, [0, 0])
        by_kind[g][0] += good
        by_kind[g][1] += 1
    print(f"\nĐúng {sum(g for _, g in results)}/{len(results)} · TB {sum(times) / len(times):.1f}s/câu · lâu nhất {max(times):.1f}s")
    for g, (ok, n) in by_kind.items():
        print(f"  {g:<18} {ok}/{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
