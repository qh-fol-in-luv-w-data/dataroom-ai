"""Where the time goes: per-step latency of the answer path, read from the trace each answer carries.

Runs a fixed set of questions (fact VI/EN, summary, list, compare, full text, out of scope) as one
investor, with the LLM memo cleared so every question is a fresh one, and prints the average time of
each pipeline step plus end-to-end times. Needs Postgres, Ollama and the reranker/NLI models.
Usage: .venv/bin/python scripts/latency_profile.py [--oid inv-ab] [--repeat 1]
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dr.connector.sync import Connector  # noqa: E402
from dr.core import answer  # noqa: E402
from dr.core.pgindex import make_index  # noqa: E402
from dr.db import pg  # noqa: E402
from dr.models import llm  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402

QUESTIONS = [
    ("fact", "Phí thu xếp áp dụng cho nhóm quỹ trong nước là bao nhiêu?"),
    ("fact", "Tổng công suất lắp đặt của Sao Mai là bao nhiêu MW?"),
    ("fact", "Doanh thu thuần năm 2025 của Sao Mai là bao nhiêu?"),
    ("fact-en", "What arrangement fee applies to the domestic fund group?"),
    ("fact-en", "What was Sao Mai's net revenue in 2025?"),
    ("list", "Sao Mai có những nhà máy nào, công suất bao nhiêu?"),
    ("summary", "Tóm tắt các điều khoản dành riêng cho Nhóm B"),
    ("compare", "So sánh phí thu xếp của nhóm A với room ngoại của nhóm B."),
    ("full", "Trích nguyên văn điều khoản thanh toán trong hợp đồng mua bán điện"),
    ("other-group", "Nhà đầu tư chiến lược được đề cử bao nhiêu thành viên HĐQT?"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oid", default="inv-ab")
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args(argv)
    pg.ensure_cluster()
    tenant = FakeTenant()
    conn = Connector(tenant)
    conn.full_resync()
    stop = threading.Event()
    threading.Thread(target=conn.run_forever, args=(stop,), daemon=True).start()
    ix = make_index()
    ix.refresh()
    deps = answer.Deps.real()
    deps.rerank("khởi động", ["khởi động"])                                   # load every model first,
    deps.nli_many([("khởi động", "khởi động")])                                 # so steps are timed warm
    deps.embed_query("khởi động")
    llm.warm()
    llm.clear_cache()
    steps: dict[str, list[int]] = defaultdict(list)
    for _ in range(a.repeat):
        for kind, q in QUESTIONS:
            llm.clear_cache()
            t0 = time.time()
            r = answer.ask(tenant, ix, a.oid, tenant.users[a.oid]["roles"], q, deps)
            total = (time.time() - t0) * 1000
            for s in r["trace"]:
                steps[s["step"].split(" (")[0].split(" –")[0][:46]].append(s["ms"])
            ok = "trả lời" if r["claims"] else ("ngoài phạm vi" if r.get("out_of_scope") else "từ chối")
            print(f"{kind:12} {total / 1000:5.1f}s  {ok:13} {q[:60]}", flush=True)
    stop.set()
    print("\nThời gian trung bình theo bước (ms, chỉ tính lần bước đó chạy):")
    for name, v in sorted(steps.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        print(f"  {sum(v) / len(v):8.0f}  ×{len(v):<3} {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
