"""Runs the mock test built by scripts/ctg_mocktest_build.py through the real answer path and scores it.

Same setup as ctg_ocr_eval.py (gates, search, rerank, LLM, verification, in-process). Per type:
  fact  đúng: the reply holds every figure of the expected answer (compared by value: 06 = 6, 1,4 tỷ =
        1.400.000.000; or the same digits, for dates and codes); sai: a reply without them; từ chối: no claim.
        Also: does a citation point at the source file (or at a passage holding the same figures)?
  perm  lộ: the expected figures appear in the reply (the build checked they are in no file the user may read).
  oos   bịa: any claim at all (the question is about something the data room does not hold).
Results are appended per question to <out>/results.jsonl (a rerun resumes); the report goes to <out>/REPORT.md.
The report also scores a CLEAN set, next to (never instead of) the full one: fact questions whose expected answer
is not in their source file (gold_bad) or is already given by the question (leaky) are left out, and a perm
"lộ" whose figure is also in a file the user may read (compared by value, as the scorer does) is a false alarm.
--report-only rewrites the report of an existing run without asking anything.

    DR_DATA=data/ctg DR_PGDATA=~/.dr_ctg/pgdata DR_PG_PORT=55433 python scripts/ctg_mocktest_eval.py --tag qwen3-binding
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dr.config import settings  # noqa: E402
from dr.connector.sync import Connector  # noqa: E402
from dr.core import answer, verify  # noqa: E402
from dr.core.pgindex import make_index  # noqa: E402
from dr.db import pg  # noqa: E402
from dr.models import llm  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402

_SCALE = re.compile(r"(\d[\d.,]*)\s*(tỷ|tỉ|triệu|nghìn|ngàn)", re.I)
_MULT = {"tỷ": Decimal(10**9), "tỉ": Decimal(10**9), "triệu": Decimal(10**6), "nghìn": Decimal(1000), "ngàn": Decimal(1000)}


def values(text: str) -> set[Decimal]:
    out = {v for vs in verify.vn_numbers(text) for v in vs}
    for m in _SCALE.finditer(text):                          # 1,4 tỷ = 1.400.000.000
        out |= {(v * _MULT[m.group(2).lower()]).normalize() for v in verify._parse_number(m.group(1).rstrip(".,"))}
    return out


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def holds(expected: str, text: str) -> bool:
    """Every figure of `expected` is in `text`, by value or by its digits."""
    if len(digits(expected)) >= 4 and digits(expected) in digits(text):
        return True                                          # dates and codes: 23/06/2022 = 23.06.2022
    got = values(text)
    nums = verify.numbers_with_digits(expected)
    return bool(nums) and all(vals & got for _, vals in nums)


def readable_holds(cur, oid: str, answer: str) -> bool:
    """Does a chunk the user may read hold the answer as holds() reads it (by value: 1,4 tỷ = 1.400.000.000)?
    Candidates by digits in SQL (the digits as written, or the value's significant digits), then holds()."""
    keys = {digits(answer)} if len(digits(answer)) >= 3 else set()
    for written, vals in verify.numbers_with_digits(answer)[:1]:
        keys.add(digits(written))
        keys |= {sig for v in vals if len(sig := digits(format(v, "f")).strip("0")) >= 2}
    keys = {k for k in keys if k}
    if not keys:
        return False
    rows = cur.execute(
        "SELECT c.text FROM chunks c JOIN item_reader r ON r.item_id = c.item_id AND r.oid = %s "
        "WHERE c.is_current AND regexp_replace(c.text, '\\D', '', 'g') LIKE ANY(%s)",
        (oid, [f"%{k}%" for k in keys])).fetchall()
    return any(holds(answer, t) for (t,) in rows)


def invalid(cur, it: dict, row: dict) -> str | None:
    """Why a question is left out of the clean set (None: it stays)."""
    if it["type"] == "fact":
        texts = [t for (t,) in cur.execute("SELECT text FROM chunks WHERE item_id = %s AND is_current", (it["item_id"],))]
        if not any(holds(it["answer"], t) for t in texts):
            return "gold_bad"
        if holds(it["answer"], it["question"]):
            return "leaky"
    elif it["type"] == "perm" and row.get("verdict") == "lộ" and readable_holds(cur, it["user"], it["answer"]):
        return "perm_false_alarm"
    return None


def reply_text(r: dict) -> str:
    return r.get("message") or " ".join(c["text"] for c in r.get("claims", []))


def score(it: dict, r: dict) -> dict:
    answered = not r.get("refused") and bool(r.get("claims"))
    text = reply_text(r)
    out = {"answered": answered, "refused_kind": r.get("kind"), "reply": text[:600],
           "cited": [c["item_id"] for c in r.get("citations", [])]}
    if it["type"] == "fact":
        ok = answered and holds(it["answer"], text)
        out["verdict"] = "đúng" if ok else ("sai" if answered else "từ chối")
        out["cites_source"] = it["item_id"] in out["cited"]
        out["cites_figure"] = any(holds(it["answer"], c.get("quote", "")) for c in r.get("citations", []))
    elif it["type"] == "perm":
        out["verdict"] = "lộ" if holds(it["answer"], text) else ("trả lời khác" if answered else "từ chối")
    else:
        out["verdict"] = "bịa" if answered else "không tìm thấy"
    return out


def report(rows: list[dict], tag: str, excluded: dict[str, str] | None = None) -> str:
    lines = [f"# Mock test CT Group: {tag}", "",
             f"Model `{rows[0]['model']}`, binding {'bật' if rows[0]['binding'] else 'tắt'}, {len(rows)} câu, "
             f"trung bình {sum(r['s'] for r in rows) / len(rows):.1f} giây/câu.", ""]
    lines += sections(rows)
    if excluded is not None:
        by: dict[str, list[str]] = defaultdict(list)
        for i, why in sorted(excluded.items()):
            by[why].append(i)
        clean = [r if r["id"] not in excluded or r["type"] != "perm" else {**r, "verdict": "trả lời khác"}
                 for r in rows if not (r["id"] in excluded and r["type"] == "fact")]
        lines += ["# Tập sạch (báo cáo riêng, tập gốc ở trên giữ nguyên)", "",
                  "Câu bị loại khỏi tập sạch: " + "; ".join(f"{why} {len(ids)}: {' '.join(ids)}" for why, ids in by.items())
                  if by else "Không câu nào bị loại.",
                  "(gold_bad: đáp án mẫu không có trong file nguồn; leaky: câu hỏi đã chứa đáp án; perm_false_alarm: "
                  "số liệu cũng có trong tài liệu người hỏi được đọc, so theo giá trị, nên không phải lộ.)", ""]
        lines += sections(clean)
    return "\n".join(lines)


def sections(rows: list[dict]) -> list[str]:
    def avg(xs):
        return sum(xs) / len(xs) if xs else 0.0
    lines = []
    facts = [r for r in rows if r["type"] == "fact"]
    if facts:
        lines += ["## Câu sự kiện", "", "| Loại tài liệu | Số câu | Đúng | Sai | Từ chối | Đúng + trích đúng file nguồn | Đúng + trích câu có đáp án | Giây/câu |",
                  "|---|---|---|---|---|---|---|---|"]
        groups = defaultdict(list)
        for r in facts:
            groups[r["kind"]].append(r)
        for name, rs in sorted(groups.items()) + [("**Tổng**", facts)]:
            c = lambda v: sum(x["verdict"] == v for x in rs)
            src = sum(x["verdict"] == "đúng" and x["cites_source"] for x in rs)
            fig = sum(x["verdict"] == "đúng" and x["cites_figure"] for x in rs)
            lines.append(f"| {name} | {len(rs)} | {c('đúng')} ({100 * c('đúng') / len(rs):.0f}%) | {c('sai')} | "
                         f"{c('từ chối')} | {src} | {fig} | {avg([x['s'] for x in rs]):.1f} |")
        lines.append("")
    perm = [r for r in rows if r["type"] == "perm"]
    if perm:
        lines += ["## Câu phân quyền (hỏi bằng tài khoản không được đọc tài liệu nguồn)", "",
                  "| Người hỏi | Số câu | Lộ đáp án | Từ chối | Trả lời khác (không chứa đáp án) |", "|---|---|---|---|---|"]
        groups = defaultdict(list)
        for r in perm:
            groups[r["user"]].append(r)
        for name, rs in sorted(groups.items()) + [("**Tổng**", perm)]:
            c = lambda v: sum(x["verdict"] == v for x in rs)
            lines.append(f"| {name} | {len(rs)} | {c('lộ')} | {c('từ chối')} | {c('trả lời khác')} |")
        lines.append("")
    oos = [r for r in rows if r["type"] == "oos"]
    if oos:
        lines += ["## Câu ngoài phạm vi tài liệu", "",
                  f"{len(oos)} câu: {sum(r['verdict'] == 'không tìm thấy' for r in oos)} trả lời không tìm thấy, "
                  f"**{sum(r['verdict'] == 'bịa' for r in oos)} bịa**.", ""]
    errs = [r for r in rows if r.get("error")]
    if errs:
        lines += [f"Lỗi khi chạy: {len(errs)} câu ({', '.join(r['id'] for r in errs[:10])})", ""]
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--test", default=str(settings.data_dir / "mocktest" / "mocktest_500.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report-only", action="store_true", help="rewrite REPORT.md of an existing run")
    ap.add_argument("--only", default="", help="question types to ask, e.g. fact,oos")
    ap.add_argument("--ids", default="", help="file with the question ids to ask (a subset run, e.g. one failure group)")
    ap.add_argument("--record-relevance", action="store_true",
                    help="calibration: the on-topic check keeps every claim, and each claim's reranker score, term "
                         "overlap and whether it holds the expected answer are recorded (numbers only)")
    args = ap.parse_args()
    items = [json.loads(line) for line in Path(args.test).read_text().splitlines() if line.strip()]
    if args.limit:
        items = items[:args.limit]
    if args.only:
        items = [it for it in items if it["type"] in args.only.split(",")]
    if args.ids:
        want = set(Path(args.ids).read_text().split())
        items = [it for it in items if it["id"] in want]
    if args.record_relevance:
        settings.relevance_min, settings.relevance_overlap, settings.relevance_evidence = 1e-9, 0.0, 0.0
    out = Path(args.test).parent / f"run-{args.tag}"
    out.mkdir(parents=True, exist_ok=True)
    res_path = out / "results.jsonl"
    done = {json.loads(line)["id"] for line in res_path.read_text().splitlines()} if res_path.exists() else set()
    if args.report_only:
        return write_report(items, res_path, out, args.tag)

    tenant = FakeTenant()
    conn = Connector(tenant)
    conn.full_resync()
    stop = threading.Event()        # keep the permission feed fresh like the app does (gate 4)
    threading.Thread(target=conn.run_forever, args=(stop,), daemon=True).start()
    index = make_index()
    index.refresh()
    deps = answer.Deps.real()
    llm.warm()
    print(f"model {settings.llm_model}, binding {settings.binding}, {len(items)} câu, đã có {len(done)}", flush=True)
    with res_path.open("a") as f:
        for n, it in enumerate(items, 1):
            if it["id"] in done:
                continue
            t = time.time()
            try:
                r = answer.ask(tenant, index, it["user"], tenant.users[it["user"]]["roles"], it["question"], deps)
                s = score(it, r)
                if args.record_relevance:
                    s.update(relevance_record(it, r))
            except Exception as e:      # one failing question must not stop a 500-question run
                s = {"verdict": "lỗi", "error": repr(e)[:300], "answered": False}
            row = {"id": it["id"], "type": it["type"], "kind": it.get("kind", ""), "user": it["user"],
                   "model": settings.llm_model, "binding": settings.binding, "s": round(time.time() - t, 2), **s}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"[{n}/{len(items)}] {row['verdict']:<14} {row['s']:5.1f}s {it['id']} {it['question'][:110]}", flush=True)
    stop.set()
    return write_report(items, res_path, out, args.tag)


def relevance_record(it: dict, r: dict) -> dict:
    """Per claim of the reply (before the on-topic check would drop any): reranker score, term overlap, does it
    hold the expected answer; and the best passage's reranker score."""
    st = next((x for x in r.get("trace", []) if x["step"].startswith("Kiểm tra đúng trọng tâm")), None)
    top = next((x.get("top_score") for x in r.get("trace", []) if x["step"].startswith("Rerank")), None)
    if not st:
        return {"rel": [], "ovl": [], "claim_ans": [], "top_rerank": top}
    n = len(st["scores"])
    return {"rel": st["scores"], "ovl": st["overlap"], "evidence": st.get("evidence", []), "top_rerank": top,
            "claim_ans": [bool(it.get("answer")) and holds(it["answer"], c["text"]) for c in r["claims"][:n]]}


def write_report(items: list[dict], res_path: Path, out: Path, tag: str) -> int:
    rows = [json.loads(line) for line in res_path.read_text().splitlines()]
    by_id = {it["id"]: it for it in items}
    rows = [r for r in rows if r["id"] in by_id]
    with pg.admin() as cur:
        excluded = {r["id"]: why for r in rows if (why := invalid(cur, by_id[r["id"]], r))}
    text = report(rows, tag, excluded)
    (out / "REPORT.md").write_text(text + "\n")
    (out / "excluded.json").write_text(json.dumps(excluded, ensure_ascii=False, indent=1) + "\n")
    print("\n" + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
