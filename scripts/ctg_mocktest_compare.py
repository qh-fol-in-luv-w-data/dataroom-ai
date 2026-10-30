"""Before/after tables of two mock-test runs (ctg_mocktest_eval.py), counts and ids only:
per document kind (full set and clean set), per failure group of the first run's diagnosis, permission
questions, out-of-scope questions, seconds per question.

    DR_DATA=... python scripts/ctg_mocktest_compare.py --before qwen3-binding --after qwen3-fix1 \
        [--diagnosis diagnose-orig.jsonl]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dr.config import settings  # noqa: E402


def load(run: Path) -> dict[str, dict]:
    return {r["id"]: r for r in map(json.loads, (run / "results.jsonl").read_text().splitlines()) if r}


def pct(a: int, n: int) -> str:
    return f"{a} ({100 * a / n:.0f}%)" if n else "0"


def kinds(before: dict, after: dict, skip: set[str]) -> list[str]:
    ids = [i for i, r in before.items() if r["type"] == "fact" and i not in skip and i in after]
    by = defaultdict(list)
    for i in ids:
        by[before[i]["kind"]].append(i)
    out = ["| Loại tài liệu | Số câu | Đúng trước | Đúng sau | Sai trước → sau | Từ chối trước → sau | "
           "Đúng + trích đúng file nguồn trước → sau |", "|---|---|---|---|---|---|---|"]
    for k, xs in sorted(by.items()) + [("**Tổng**", ids)]:
        c = lambda run, v: sum(run[i]["verdict"] == v for i in xs)
        src = lambda run: sum(run[i]["verdict"] == "đúng" and run[i].get("cites_source") for i in xs)
        out.append(f"| {k} | {len(xs)} | {pct(c(before, 'đúng'), len(xs))} | {pct(c(after, 'đúng'), len(xs))} | "
                   f"{c(before, 'sai')} → {c(after, 'sai')} | {c(before, 'từ chối')} → {c(after, 'từ chối')} | "
                   f"{src(before)} → {src(after)} |")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--test", default=str(settings.data_dir / "mocktest" / "mocktest_500.jsonl"))
    ap.add_argument("--diagnosis", default="diagnose-orig.jsonl", help="the first run's diagnosis file")
    a = ap.parse_args()
    root = Path(a.test).parent
    b_run, a_run = root / f"run-{a.before}", root / f"run-{a.after}"
    before, after = load(b_run), load(a_run)
    ex_path = a_run / "excluded.json"
    excluded = json.loads(ex_path.read_text()) if ex_path.exists() else {}
    bad_facts = {i for i, why in excluded.items() if why in ("gold_bad", "leaky")}
    lines = [f"# Trước/sau: {a.before} → {a.after}", "",
             f"{len(after)}/{len(before)} câu có ở cả hai lượt.", "", "## Câu sự kiện, tập gốc", ""]
    lines += kinds(before, after, set())
    lines += ["", f"## Câu sự kiện, tập sạch (bỏ {len(bad_facts)} câu gold_bad/leaky)", ""]
    lines += kinds(before, after, bad_facts)
    diag = root / f"run-{a.before}" / a.diagnosis
    if diag.exists():
        groups = defaultdict(list)
        for r in map(json.loads, diag.read_text().splitlines()):
            groups[r["stage"]].append(r["id"])
        lines += ["", "## Theo nhóm lỗi của lượt trước (chẩn đoán)", "",
                  "| Nhóm | Số câu | Kết quả lượt sau |", "|---|---|---|"]
        for g, ids in sorted(groups.items(), key=lambda x: -len(x[1])):
            ids = [i for i in ids if i in after]
            cnt = Counter(after[i]["verdict"] for i in ids)
            lines.append(f"| {g} | {len(ids)} | {', '.join(f'{v} {n}' for v, n in cnt.most_common())} |")
    facts = [i for i in after if after[i]["type"] == "fact" and i in before]
    lost = [i for i in facts if before[i]["verdict"] == "đúng" and after[i]["verdict"] != "đúng"]
    gained = [i for i in facts if before[i]["verdict"] != "đúng" and after[i]["verdict"] == "đúng"]
    lines += ["", f"Câu sự kiện: được {len(gained)}, mất {len(lost)} câu đúng: {' '.join(lost)}"]
    perm = [i for i in after if after[i]["type"] == "perm"]
    if perm:
        leak = [i for i in perm if after[i]["verdict"] == "lộ"]
        real = [i for i in leak if excluded.get(i) != "perm_false_alarm"]
        lines += ["", "## Câu phân quyền", "",
                  f"{len(perm)} câu. Trước: lộ {sum(before[i]['verdict'] == 'lộ' for i in perm)}. "
                  f"Sau: lộ {len(leak)} ({' '.join(leak) or '-'}), trong đó báo động nhầm (số liệu có trong tài liệu "
                  f"người hỏi được đọc) {len(leak) - len(real)}, **lộ thật {len(real)}**; từ chối "
                  f"{sum(after[i]['verdict'] == 'từ chối' for i in perm)}, trả lời khác "
                  f"{sum(after[i]['verdict'] == 'trả lời khác' for i in perm)}."]
    oos = [i for i in after if after[i]["type"] == "oos"]
    if oos:
        lines += ["", "## Câu ngoài phạm vi", "",
                  f"{len(oos)} câu có trả lời (bịa): trước {sum(before[i]['verdict'] == 'bịa' for i in oos)}, "
                  f"sau {sum(after[i]['verdict'] == 'bịa' for i in oos)}."]
    common = [i for i in after if i in before]
    avg = lambda run, ids: sum(run[i]["s"] for i in ids) / max(1, len(ids))
    lines += ["", "## Thời gian", "", "| Loại câu | Giây/câu trước | Giây/câu sau |", "|---|---|---|"]
    for t in ("fact", "perm", "oos"):
        ids = [i for i in common if after[i]["type"] == t]
        if ids:
            lines.append(f"| {t} | {avg(before, ids):.1f} | {avg(after, ids):.1f} |")
    lines.append(f"| tất cả | {avg(before, common):.1f} | {avg(after, common):.1f} |")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
