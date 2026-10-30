"""Where does each failed mock-test question go wrong? Re-asks it through the real answer path (code of the
ctg-dataroom worktree) with probes on search, passage selection, sentence focus and the trace, and names the
first stage that lost the answer:

  gold_bad        the expected figure is not in the source chunk (the generated question/answer is wrong)
  not_retrieved   no chunk of the source file among the search hits
  ranked_out      in the hits, but no passage holding the answer was selected for the model (rerank/selection)
  focus_cut       a selected passage holds the answer, the sentences sent to the model do not (sentence focus)
  llm_no_claim    the model had the answer and returned no claim
  verify_dropped  the model's claims were all dropped by the deterministic check (reasons recorded)
  relevance_drop  claims dropped by the on-topic check
  pii_masked      the answer was masked as personal data after verification
  echo            the reply repeats the question
  wrong_claim     the model answered from another passage / with another figure

Prints only counts, question ids and stage timings (no document text); details go to <run>/diagnose.jsonl
(--out names another file, e.g. for a quick check on a few --ids).
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
import threading
from collections import Counter, defaultdict
from pathlib import Path

CTG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CTG))
sys.path.insert(0, str(CTG / "scripts"))

from ctg_mocktest_eval import holds, reply_text, score  # noqa: E402

from dr.config import settings  # noqa: E402
from dr.connector.sync import Connector  # noqa: E402
from dr.core import answer  # noqa: E402
from dr.core.pgindex import make_index  # noqa: E402
from dr.db import pg  # noqa: E402
from dr.models import llm  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402

CAP: dict = {}


def probe(index) -> None:
    search_as, select, focus = index.search_as, answer.select_passages, answer.focus_sentences

    def p_search(oid, q, v, k=40, site=None):
        hs, info = search_as(oid, q, v, k=k, site=site)
        CAP.setdefault("hits", []).extend(c for c, _ in hs)
        return hs, info

    def p_select(order, passages, chosen, n, per):
        s = select(order, passages, chosen, n, per)
        CAP["order_items"] = [passages[c]["item_id"] for c in order]
        CAP["selected"] = {c: passages[c]["text"] for c in s}
        CAP["selected_items"] = [passages[c]["item_id"] for c in s]
        return s

    def p_focus(q, llm_in, *a, **k):
        out = focus(q, llm_in, *a, **k)
        CAP["llm_in"] = [x["text"] for x in out]
        return out

    index.search_as = p_search
    answer.select_passages = p_select
    answer.focus_sentences = p_focus


def source_texts(it: dict) -> tuple[str, list[str]]:
    with pg.admin() as c:
        r = c.execute("SELECT text FROM chunks WHERE chunk_id=%s", (it["chunk_id"],)).fetchone()
        allt = [x[0] for x in c.execute("SELECT text FROM chunks WHERE item_id=%s AND is_current", (it["item_id"],))]
    return (r[0] if r else ""), allt


def item_hits(hits: list[int]) -> set[str]:
    if not hits:
        return set()
    with pg.admin() as c:
        return {x[0] for x in c.execute("SELECT DISTINCT item_id FROM chunks WHERE chunk_id = ANY(%s)", (hits,))}


def step(trace: list[dict], prefix: str) -> dict | None:
    return next((s for s in trace if s["step"].startswith(prefix)), None)


def stage(it: dict, r: dict, verdict: str) -> tuple[str, dict]:
    ans = it["answer"]
    src, all_src = source_texts(it)
    d: dict = {}
    if not holds(ans, src) and not any(holds(ans, t) for t in all_src):
        return "gold_bad", d
    d["source_in_hits"] = it["item_id"] in item_hits(CAP.get("hits", []))
    oi = CAP.get("order_items", [])
    d["source_rank_items"] = len(dict.fromkeys(oi[:oi.index(it["item_id"])])) if it["item_id"] in oi else None
    sel = CAP.get("selected", {})
    d["answer_in_selected"] = any(holds(ans, t) for t in sel.values())
    d["source_selected"] = it["item_id"] in CAP.get("selected_items", [])
    tr = r.get("trace", [])
    if not d["answer_in_selected"]:
        return ("not_retrieved" if not d["source_in_hits"] else "ranked_out"), d
    if CAP.get("llm_in") is not None and not any(holds(ans, t) for t in CAP["llm_in"]):
        return "focus_cut", d
    llm_s = step(tr, "LLM ")
    ver = [s for s in tr if s["step"].startswith("Kiểm chứng tất định")]
    rel = step(tr, "Kiểm tra đúng trọng tâm")
    pii = step(tr, "Che thông tin cá nhân trong câu trả lời")
    d["raw_claims"] = llm_s.get("raw_claims") if llm_s else None
    d["dropped_reasons"] = [x for v in ver for x in v.get("dropped_reasons", [])]
    d["retries"] = [s["step"] for s in tr if s["step"].startswith(("Thử lại", "Hỏi model dự phòng"))]
    if verdict == "từ chối":
        if llm_s and not llm_s.get("raw_claims") and not d["dropped_reasons"]:
            return "llm_no_claim", d
        if rel and rel.get("dropped"):
            return "relevance_drop", d
        if d["dropped_reasons"]:
            return "verify_dropped", d
        return "llm_no_claim", d
    text = reply_text(r)
    if pii:
        d["pii_kinds"] = pii.get("kinds")
        return "pii_masked", d
    if difflib.SequenceMatcher(None, text.lower(), it["question"].lower()).ratio() > 0.7:
        return "echo", d
    return "wrong_claim", d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--test", default=str(settings.data_dir / "mocktest" / "mocktest_500.jsonl"))
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--out", default="diagnose.jsonl", help="file name in the run folder (keep the full run's file)")
    a = ap.parse_args()
    items = {json.loads(x)["id"]: json.loads(x) for x in Path(a.test).read_text().splitlines() if x.strip()}
    run = Path(a.test).parent / f"run-{a.tag}"
    rows = [json.loads(x) for x in (run / "results.jsonl").read_text().splitlines()]
    bad = [r for r in rows if (r["type"] == "fact" and r["verdict"] in ("sai", "từ chối"))
           or (r["type"] == "perm" and r["verdict"] == "lộ") or (r["type"] == "oos" and r["verdict"] == "bịa")
           or r["verdict"] == "lỗi"]
    if a.ids:
        bad = [r for r in bad if r["id"] in set(a.ids)]
    tenant = FakeTenant()
    conn = Connector(tenant)
    conn.full_resync()
    stop = threading.Event()
    threading.Thread(target=conn.run_forever, args=(stop,), daemon=True).start()
    index = make_index()
    index.refresh()
    deps = answer.Deps.real()
    llm.warm()
    probe(index)
    out = run / a.out
    cats, ms = defaultdict(list), defaultdict(list)
    same = Counter()
    with out.open("w") as f:
        for n, row in enumerate(bad, 1):
            it = items[row["id"]]
            CAP.clear()
            try:
                r = answer.ask(tenant, index, it["user"], tenant.users[it["user"]]["roles"], it["question"], deps)
            except Exception as e:
                cats["error"].append(it["id"])
                print(f"[{n}/{len(bad)}] {it['id']} lỗi {type(e).__name__}", flush=True)
                continue
            s = score(it, r)
            for st in r.get("trace", []):
                ms[st["step"][:48]].append(st["ms"])
            if it["type"] != "fact":
                cat, d = f"{it['type']}_{s['verdict']}", {}
            elif s["verdict"] == "đúng":
                cat, d = "now_right", {}           # LLM / GPU non-determinism: right on the second ask
            else:
                cat, d = stage(it, r, s["verdict"])
            same[s["verdict"] == row["verdict"]] += 1
            cats[cat].append(it["id"])
            f.write(json.dumps({"id": it["id"], "kind": it.get("kind"), "first": row["verdict"], "now": s["verdict"],
                                "stage": cat, **d}, ensure_ascii=False, default=str) + "\n")
            f.flush()
            print(f"[{n}/{len(bad)}] {it['id']} {row['verdict']} → {s['verdict']}: {cat}", flush=True)
    stop.set()
    print(f"\n{len(bad)} câu chưa đạt; hỏi lại cho cùng kết quả: {same[True]}, khác: {same[False]}\n")
    for c, ids in sorted(cats.items(), key=lambda x: -len(x[1])):
        print(f"{c:16} {len(ids):4}  {' '.join(ids[:12])}{' …' if len(ids) > 12 else ''}")
    print("\nThời gian trung bình theo bước (ms):")
    for k, v in sorted(ms.items(), key=lambda x: -sum(x[1]) / len(x[1]))[:12]:
        print(f"  {sum(v) / len(v):8.0f}  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
