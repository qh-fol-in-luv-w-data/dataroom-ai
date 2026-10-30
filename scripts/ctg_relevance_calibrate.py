"""Calibrates the on-topic check (answer.py, "Kiểm tra đúng trọng tâm câu hỏi") on a mock-test run made with
`ctg_mocktest_eval.py --record-relevance` (every claim kept, its reranker score / term overlap recorded).

Each candidate rule is replayed on the recorded claims (reranker score, term overlap of claim + quotes, and — runs made after the evidence
check — evidence: the question's key terms in the cited documents themselves): an out-of-scope question still answered if any claim
passes; a fact question right if a passing claim holds the expected answer, refused if no claim passes.
Prints counts only (no document or question text).

    DR_DATA=... python scripts/ctg_relevance_calibrate.py --tag qwen3-fixcal
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dr.config import settings  # noqa: E402


def outcome(row: dict, keep) -> str:
    """The verdict of one question when only the claims `keep(rel, ovl, top)` accepts are released."""
    rel, ovl, ans = row.get("rel") or [], row.get("ovl") or [], row.get("claim_ans") or []
    ev = row.get("evidence") or [1.0] * len(rel)            # runs recorded before the evidence check: no signal
    if not rel:                                  # no on-topic step (other intent, or refused before it)
        return row["verdict"]
    passed = [i for i in range(len(rel)) if keep(rel[i], ovl[i], row.get("top_rerank") or 0.0, ev[i])]
    if row["type"] == "oos":
        return "bịa" if passed else "không tìm thấy"
    if not passed:
        return "từ chối"
    if any(ans[i] for i in passed if i < len(ans)):
        return "đúng"
    # the answer spread over several claims (holds() on the joined reply): right only if all of them pass
    if row["verdict"] == "đúng" and not any(ans) and len(passed) == len(rel):
        return "đúng"
    return "sai"


def rules() -> dict[str, callable]:
    out = {"gốc: rel>=0.1 OR ovl>=0.6": lambda r, o, t, e: r >= 0.1 or o >= 0.6}
    for x in (0.5, 0.6, 0.65, 0.7, 0.75, 0.8):
        out[f"(rel>=0.1 OR ovl>=0.6) AND evidence>={x}"] = lambda r, o, t, e, x=x: (r >= 0.1 or o >= 0.6) and e >= x
    for a in (0.1, 0.2, 0.3, 0.4, 0.5):
        for b in (0.6, 0.75, 0.9, 1.0):
            out[f"rel>={a} OR ovl>={b}"] = lambda r, o, t, e, a=a, b=b: r >= a or o >= b
            for c in (0.01, 0.03, 0.05):
                out[f"rel>={a} OR (ovl>={b} AND rel>={c})"] = \
                    lambda r, o, t, e, a=a, b=b, c=c: r >= a or (o >= b and r >= c)
    for a in (0.05, 0.1, 0.2, 0.3):
        for b in (0.3, 0.5, 0.6):
            out[f"rel>={a} AND ovl>={b}"] = lambda r, o, t, e, a=a, b=b: r >= a and o >= b
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--test", default=str(settings.data_dir / "mocktest" / "mocktest_500.jsonl"))
    ap.add_argument("--exclude", default="", help="excluded.json of a run (clean set: gold_bad/leaky left out)")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    run = Path(a.test).parent / f"run-{a.tag}"
    rows = [json.loads(x) for x in (run / "results.jsonl").read_text().splitlines() if x.strip()]
    if a.exclude:
        ex = json.loads(Path(a.exclude).read_text())
        rows = [r for r in rows if not (r["type"] == "fact" and r["id"] in ex)]
    oos = [r for r in rows if r["type"] == "oos"]
    facts = [r for r in rows if r["type"] == "fact"]
    print(f"{len(facts)} câu sự kiện, {len(oos)} câu ngoài phạm vi; "
          f"{sum(bool(r.get('rel')) for r in rows)} câu có bước kiểm tra trọng tâm")
    res = []
    for name, keep in rules().items():
        f = [outcome(r, keep) for r in facts]
        o = [outcome(r, keep) for r in oos]
        res.append((name, f.count("đúng"), f.count("sai"), f.count("từ chối"), o.count("bịa")))
    base = res[0]
    print(f"\n{'quy tắc':42} đúng  sai  từ chối  oos bịa")
    print(f"{base[0]:42} {base[1]:4} {base[2]:4} {base[3]:8} {base[4]:8}")
    for lost in (0, 2, 5):
        print(f"-- mất tối đa {lost} câu đúng so với quy tắc gốc, xếp theo số câu oos còn bịa")
        ok = [r for r in res[1:] if base[1] - r[1] <= lost]
        for r in sorted(ok, key=lambda x: (x[4], -x[1]))[:a.top // 3]:
            print(f"{r[0]:42} {r[1]:4} {r[2]:4} {r[3]:8} {r[4]:8}")
    # where the right answers and the out-of-scope claims sit
    def best(r, k):
        return max(r[k]) if r.get(k) else None
    right = [r for r in facts if any(r.get("claim_ans") or [])]
    print("\nPhân bố (max theo câu):")
    for label, group, pick in (("claim đúng của câu sự kiện", right,
                                lambda r: max(x for x, h in zip(r["rel"], r["claim_ans"]) if h)),
                               ("claim của câu oos", [r for r in oos if r.get("rel")], lambda r: best(r, "rel"))):
        xs = sorted(pick(r) for r in group)
        if xs:
            q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]
            print(f"  rerank {label:28} n={len(xs):3}  p10={q(.1):.3f} p25={q(.25):.3f} p50={q(.5):.3f} p75={q(.75):.3f}")
    for label, group, pick in (("claim đúng của câu sự kiện", right,
                                lambda r: max(x for x, h in zip(r["ovl"], r["claim_ans"]) if h)),
                               ("claim của câu oos", [r for r in oos if r.get("ovl")], lambda r: best(r, "ovl"))):
        xs = sorted(pick(r) for r in group)
        if xs:
            q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]
            print(f"  overlap {label:27} n={len(xs):3}  p10={q(.1):.2f} p25={q(.25):.2f} p50={q(.5):.2f} p75={q(.75):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
