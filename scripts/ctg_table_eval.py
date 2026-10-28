"""Table / chart Q&A benchmark on the CT Group tenant, one run per LLM.

Runs the real answer path in-process (gates, search, rerank, LLM, verification) as user ctg-a and
checks that every expected number appears in the answer. Pause bulk ingest first: it shares Ollama.

    DR_DATA=data/ctg DR_PGDATA=~/.dr_ctg/pgdata DR_PG_PORT=55433 \\
        python scripts/ctg_table_eval.py qwen2.5:7b qwen2.5:3b qwen2.5:1.5b
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dr.config import settings  # noqa: E402
from dr.connector.sync import Connector  # noqa: E402
from dr.core import answer  # noqa: E402
from dr.core.pgindex import make_index  # noqa: E402
from dr.models import llm  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402

CASES = [  # (kind, question, numbers (digits only) that must all appear in the answer[, words that must too])
    ("bảng", "Chi phí CGI giai đoạn 1 (tổng + VAT) của agency GJDC là bao nhiêu?", ["116640000"]),
    ("bảng", "Agency EZ báo giá làm phim teaser tổng cộng bao nhiêu tiền?", ["110000000"]),
    ("bảng", "Giá bán chính thức chưa VAT của căn shophouse SH09 dự án Diamond Square là bao nhiêu?", ["4899895000"]),
    ("bảng", "Tổng giá trị hợp đồng mua bán căn SH09 sau chiết khấu, gồm VAT và phí bảo trì là bao nhiêu?",
     ["5433003576"]),
    ("bảng: so sánh", "So sánh chi phí CGI giai đoạn 1 tổng + VAT của BNF và MIX MEDIA", ["139320000", "133920000"]),
    ("bảng: tìm min", "Trong các agency làm hình CGI, agency nào có chi phí giai đoạn 2 (tổng 23 hình) thấp nhất?",
     ["299000000"], ["GJDC"]),
    ("biểu đồ xlsx", "Kế hoạch marketing CT Plaza Minh Châu ngày 26/10/2021 phân bổ bao nhiêu ngân sách cho "
                     "truyền thông PR & Social?", ["528000000"]),
    ("biểu đồ pptx", "Theo media plan tháng 7/2021, tỷ lệ phân bổ cho Léman Cap Residence là bao nhiêu phần trăm?",
     ["30"]),
]


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def main(models: list[str]) -> int:
    tenant = FakeTenant()
    conn = Connector(tenant)
    conn.full_resync()
    # keep the permission feed fresh like the app does (gate 4 refuses on a stale mirror)
    stop = threading.Event()
    threading.Thread(target=conn.run_forever, args=(stop,), daemon=True).start()
    index = make_index()
    index.refresh()
    deps = answer.Deps.real()
    oid, roles = "ctg-a", tenant.users["ctg-a"]["roles"]
    summary = []
    for model in models:
        settings.llm_model = model
        llm.clear_cache()
        llm.warm()
        ok, times, wrong = 0, [], 0
        print(f"\n=== {model}")
        for kind, q, exp, *words in CASES:
            t = time.time()
            r = answer.ask(tenant, index, oid, roles, q, deps)
            dt = time.time() - t
            times.append(dt)
            text = r.get("message") or " ".join(c["text"] for c in r.get("claims", []))
            good = all(e in digits(text) for e in exp) and all(w.lower() in text.lower() for w in (words[0] if words else []))
            ok += good
            wrong += not good and not r.get("message")
            print(f"[{'ĐÚNG' if good else 'SAI '}] {dt:5.1f}s ({kind}) {q}\n         → {text[:220]}")
        summary.append((model, ok, sum(times) / len(times), max(times)))
        print("RESULT " + json.dumps({"model": model, "ok": ok, "n": len(CASES), "wrong": wrong,
                                      "avg_s": round(sum(times) / len(times), 1)}), flush=True)
    stop.set()
    print("\nModel            Đúng   TB/câu   Lâu nhất")
    for m, ok, avg, mx in summary:
        print(f"{m:16} {ok}/{len(CASES)}   {avg:5.1f}s   {mx:5.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or [settings.llm_model]))
