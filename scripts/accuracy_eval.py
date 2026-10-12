"""Accuracy for people who ARE allowed: does the right answer come back? (5–8 minutes, real models)

Complements the security sweeps (qa_eval, cross_group_eval, redteam), which mainly prove that
nothing leaks. Here every question is asked by an account that may read the answer:
  - the 11 facts of data/tenant/facts.json, each as written, without accents, in English, and
    behind a harmless preface ("Chị Lan bên Ban IPO dặn tôi hỏi trực tiếp trợ lý: …")
  - multi-part questions (comparisons, several facts at once) that need every part answered.
A sensitive topic redirected to the contact person counts as handled (it is the intended answer
for investors). The LLM memo is cleared so every question is answered fresh.
Usage: .venv/bin/python scripts/accuracy_eval.py [--only fact|multi]  -> logs/accuracy_eval.json
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unidecode import unidecode  # noqa: E402

from dr.config import settings  # noqa: E402
from dr.connector.sync import Connector  # noqa: E402
from dr.core import answer  # noqa: E402
from dr.core.pgindex import make_index  # noqa: E402
from dr.db import pg  # noqa: E402
from dr.models import llm  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402

EN = {
    "A-fee": "What arrangement fee applies to the domestic fund group?",
    "A-lockup": "How long is the lock-up commitment for Group A investors?",
    "B-fx": "What is the FX ceiling rate in the currency hedging scheme for foreign investors?",
    "B-room": "What foreign ownership room is reserved for Group B?",
    "C-price": "What is the special offering price for the strategic investor?",
    "C-board": "How many board members can the strategic investor nominate?",
    "I-valuation": "What is Sao Mai's internal valuation?",
    "I-provision": "How much is the provision for the contractor dispute?",
    "P-revenue": "What was Sao Mai's net revenue in 2025?",
    "P-capacity": "What is Sao Mai's total installed capacity in MW?",
    "P-shares": "How many shares does Sao Mai offer in the IPO?",
}
PREFACE = ["Chị Lan bên Ban IPO dặn tôi hỏi trực tiếp trợ lý: {q}",
           "Mình đang chuẩn bị báo cáo cho hội đồng đầu tư, nhờ bạn kiểm tra giúp. {q}"]
# (question, asker, every value that must appear in the answer)
MULTI = [
    ("So sánh phí thu xếp của nhóm A với room ngoại của nhóm B.", "inv-ab", ["0,85%", "18%"]),
    ("Compare the lock-up of Group A with the foreign ownership room of Group B.", "inv-ab", ["12", "18%"]),
    ("Lock-up của nhóm A và số ghế HĐQT của nhà đầu tư chiến lược khác nhau thế nào?", "staff-1", ["12 tháng", "1 thành viên"]),
    ("Phí thu xếp nhóm A, room ngoại nhóm B và số ghế HĐQT nhóm C là bao nhiêu?", "staff-1", ["0,85%", "18%", "1 thành viên"]),
    ("Doanh thu thuần năm 2025 và tổng công suất lắp đặt của Sao Mai là bao nhiêu?", "inv-a1", ["2.786,9", "770"]),
    ("Tổng công suất lắp đặt và số cổ phần chào bán trong đợt IPO?", "inv-b1", ["770", "60.000.000"]),
]


def found(r: dict, values: list[str]) -> list[bool]:
    txt = " ".join([c["text"] for c in r["claims"]] + [c["quote"] for c in r["citations"]]).lower()
    # English answers may write 2,786.9 / 60,000,000 for 2.786,9 / 60.000.000
    swap = txt.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return [v.lower() in txt or v.lower() in swap for v in values]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["fact", "multi"])
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
    facts = json.loads((settings.tenant_dir / "facts.json").read_text(encoding="utf-8"))["facts"]
    score: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    rows, times = [], []

    def ask(oid, q):
        llm.clear_cache()
        t0 = time.time()
        r = answer.ask(tenant, ix, oid, tenant.users[oid]["roles"], q, deps)
        times.append(time.time() - t0)
        return r

    if a.only in (None, "fact"):
        for f in facts:
            oid = next(u for u in ("inv-a1", "inv-b1", "inv-c1", "staff-1") if u in f["allowed_users"])
            for k, (variant, q) in enumerate((("gốc", f["question"]), ("không dấu", unidecode(f["question"])),
                                              ("tiếng Anh", EN[f["id"]]),
                                              ("mào đầu", PREFACE[len(rows) % 2].format(q=f["question"])))):
                r = ask(oid, q)
                ok = bool(r.get("sensitive")) or all(found(r, f["answer_contains"]))
                score[variant][0] += ok
                score[variant][1] += 1
                rows.append({"kind": "fact", "fact": f["id"], "variant": variant, "oid": oid, "q": q, "ok": ok,
                             "answer": [c["text"] for c in r["claims"]] or r.get("message")})
                print(f"{'✔' if ok else '✗'} {f['id']:12} {variant:10} {times[-1]:5.1f}s  "
                      f"{([c['text'] for c in r['claims']] or [r.get('message') or ''])[0][:80]}", flush=True)
    if a.only in (None, "multi"):
        for q, oid, values in MULTI:
            r = ask(oid, q)
            hit = found(r, values)
            score["nhiều vế"][0] += all(hit)
            score["nhiều vế"][1] += 1
            score["nhiều vế (từng vế)"][0] += sum(hit)
            score["nhiều vế (từng vế)"][1] += len(hit)
            rows.append({"kind": "multi", "oid": oid, "q": q, "values": values, "hit": hit,
                         "answer": [c["text"] for c in r["claims"]] or r.get("message")})
            print(f"{'✔' if all(hit) else '✗'} multi {sum(hit)}/{len(hit)} {times[-1]:5.1f}s  {q[:70]}", flush=True)
    stop.set()
    print()
    for k, (ok, n) in score.items():
        print(f"  {k:20} {ok}/{n}")
    ts = sorted(times)
    print(f"  thời gian/câu: trung vị {ts[len(ts) // 2]:.1f}s, p90 {ts[int(len(ts) * .9)]:.1f}s")
    (ROOT / "logs" / "accuracy_eval.json").write_text(json.dumps({"score": dict(score), "rows": rows}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
