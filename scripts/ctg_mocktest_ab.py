"""Side by side: several mock-test runs on the same question subset (A/B of models and methods), counts only.
Rows are runs, columns the right answers per failure group of a reference run's diagnosis (and the questions
that reference run got right), then totals and seconds per question.

    DR_DATA=... python scripts/ctg_mocktest_ab.py --ids subset-8b.txt --diagnosis qwen3-fix2 \
        qwen3-fix2 sub-4b-base sub-8b sub-4b-expand
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dr.config import settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="+")
    ap.add_argument("--ids", required=True, help="file in the mocktest folder (or a path) listing the subset's ids")
    ap.add_argument("--diagnosis", required=True, help="run whose diagnose.jsonl names the failure groups")
    ap.add_argument("--test", default=str(settings.data_dir / "mocktest" / "mocktest_500.jsonl"))
    a = ap.parse_args()
    root = Path(a.test).parent
    ids_path = Path(a.ids) if Path(a.ids).exists() else root / a.ids
    ids = ids_path.read_text().split()
    group = {r["id"]: r["stage"] for r in map(json.loads, (root / f"run-{a.diagnosis}" / "diagnose.jsonl").read_text()
                                              .splitlines())}
    cols = defaultdict(list)
    for i in ids:
        cols[group.get(i, "đang đúng")].append(i)
    names = sorted(cols, key=lambda g: (g != "đang đúng", -len(cols[g])))
    print("| Lượt | " + " | ".join(f"{g} ({len(cols[g])})" for g in names) + " | Đúng | Có kết quả | Giây/câu |")
    print("|---" * (len(names) + 4) + "|")
    for tag in a.tags:
        path = root / f"run-{tag}" / "results.jsonl"
        runs = {r["id"]: r for r in map(json.loads, path.read_text().splitlines())} if path.exists() else {}
        have = [i for i in ids if i in runs]
        right = lambda xs: sum(runs[i]["verdict"] == "đúng" for i in xs if i in runs)
        cells = [f"{right(cols[g])}/{sum(i in runs for i in cols[g])}" for g in names]
        secs = sum(runs[i]["s"] for i in have) / max(1, len(have))
        print(f"| {tag} | " + " | ".join(cells) + f" | **{right(have)}** | {len(have)}/{len(ids)} | {secs:.1f} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
