"""OCR accuracy on the hard-scan set (data/eval/hard_scans, see gen_hard_scans.py).

For every document it OCRs the file twice — "raw" (PaddleOCR-VL on the page as is) and
"clean" (preprocess.py first) — and reports, per degradation kind:
- number recall: key numbers (≥3 digits) found exactly in the OCR text of their page;
- phrase recall: Vietnamese phrases with diacritics found exactly;
- for "clean": how well the second-reader cross-check flags wrong numbers
  (wrong numbers flagged vs. correct numbers flagged by mistake).
Usage: .venv/bin/python scripts/ocr_eval.py [--limit N] [--modes raw,clean]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dr.ingest import ocr  # noqa: E402

SET = ROOT / "data" / "eval" / "hard_scans"
OUT = ROOT / "logs" / "ocr_eval.json"


def norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).replace(" ", "").replace("\n", "").lower()


def digits(s: str) -> int:
    return sum(ch.isdigit() for ch in s)


def run(limit: int | None, modes: list[str]) -> dict:
    truth = json.loads((SET / "truth.json").read_text(encoding="utf-8"))["docs"][:limit]
    if not ocr.vl_available():
        sys.exit("OCR server (PaddleOCR-VL) chưa chạy: make ocr-server")
    res: dict = {m: defaultdict(lambda: defaultdict(float)) for m in modes}
    for d in truth:
        for mode in modes:
            t0 = time.time()
            pages = ocr.ocr_file(str(SET / d["file"]), clean=(mode == "clean"))
            dt = time.time() - t0
            text = {p.page: norm(p.text) for p in pages}
            whole = "".join(text.values())
            r = res[mode][d["kind"]]
            r["docs"] += 1
            r["pages"] += len(pages)
            r["seconds"] += dt
            truth_nums = [x for x in d["numbers"] if digits(x["text"]) >= 3]
            for x in truth_nums:
                hit = norm(x["text"]) in text.get(x["page"], whole)
                r["num_total"] += 1
                r["num_hit"] += hit
                if x.get("covered"):
                    r["cov_total"] += 1
                    r["cov_hit"] += hit
                if x.get("handwritten"):
                    r["hand_total"] += 1
                    r["hand_hit"] += hit
            for ph in d["phrases"]:
                r["phr_total"] += 1
                r["phr_hit"] += norm(ph) in whole
            if mode == "clean":
                good = {norm(x["text"]) for x in d["numbers"]}
                for p in pages:
                    flagged = set(p.doubt)
                    for n in ocr.numbers_in(p.text):
                        if norm(n) in good:
                            r["ok_seen"] += 1
                            r["ok_flagged"] += n in flagged
                        else:
                            r["bad_seen"] += 1
                            r["bad_flagged"] += n in flagged
                    r["steps"] = sorted(set(r.get("steps", [])) | {s.split(" ")[0] + " " + s.split(" ")[1]
                                                                      for s in p.steps if " " in s})
            hit = sum(norm(x["text"]) in whole for x in truth_nums)
            print(f"{d['file']:<32} {mode:<5} số {hit:>3}/{len(truth_nums):<3} {dt:5.1f}s "
                  f"{'; '.join(s for p in pages for s in p.steps) if mode == 'clean' else ''}", flush=True)
    return {m: {k: dict(v) for k, v in kinds.items()} for m, kinds in res.items()}


def report(data: dict) -> None:
    modes = list(data)
    kinds = sorted({k for m in modes for k in data[m]})
    pct = lambda a, b: f"{100 * a / b:5.1f}%" if b else "   — "
    print(f"\n{'Loại':<20}" + "".join(f"{'số ' + m:>12}{'chữ ' + m:>12}" for m in modes) + f"{'s/trang':>9}")
    tot = {m: defaultdict(float) for m in modes}
    for k in kinds:
        row = f"{k:<20}"
        for m in modes:
            r = data[m].get(k, {})
            row += f"{pct(r.get('num_hit', 0), r.get('num_total', 0)):>12}{pct(r.get('phr_hit', 0), r.get('phr_total', 0)):>12}"
            for f, v in r.items():
                if isinstance(v, (int, float)):
                    tot[m][f] += v
        r = data[modes[-1]].get(k, {})
        row += f"{r.get('seconds', 0) / max(1, r.get('pages', 1)):9.1f}"
        print(row)
    row = f"{'TỔNG':<20}"
    for m in modes:
        t = tot[m]
        row += f"{pct(t['num_hit'], t['num_total']):>12}{pct(t['phr_hit'], t['phr_total']):>12}"
    print(row)
    for m in modes:
        t = tot[m]
        print(f"{m}: số bị dấu/chữ ký đè {pct(t['cov_hit'], t['cov_total'])}, số viết tay {pct(t['hand_hit'], t['hand_total'])}, "
              f"{t['seconds'] / max(1, t['pages']):.1f} s/trang")
    if "clean" in data:
        t = tot["clean"]
        print(f"Đối chiếu 2 bộ đọc: bắt được {pct(t['bad_flagged'], t['bad_seen'])} số đọc sai "
              f"({int(t['bad_flagged'])}/{int(t['bad_seen'])}), báo nhầm {pct(t['ok_flagged'], t['ok_seen'])} số đúng "
              f"({int(t['ok_flagged'])}/{int(t['ok_seen'])})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--modes", default="raw,clean")
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args(argv)
    if a.report_only:
        report(json.loads(OUT.read_text()))
        return 0
    data = run(a.limit, a.modes.split(","))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    report(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
