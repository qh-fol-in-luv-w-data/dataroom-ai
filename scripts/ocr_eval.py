"""OCR accuracy on the hard-scan set (data/eval/hard_scans, see gen_hard_scans.py).

Every document is OCR'd twice — "raw" (PaddleOCR-VL on the page as is) and "clean"
(preprocess.py first, plus the second-reader number check). Raw OCR output is saved to
logs/ocr_eval_pages.json so scoring can be changed and re-run without OCR (--report-only).

Per degradation kind it reports:
- number recall: key numbers (≥3 digits) found exactly on their page;
- phrase recall: Vietnamese phrases with diacritics, ignoring markdown marks and dash style;
- misreads: number tokens that are 1–2 characters away from a key number (a wrong read of
  it), and how many of those the second-reader check flagged — versus how many correctly
  read key numbers it flagged by mistake.
Usage: .venv/bin/python scripts/ocr_eval.py [--limit N] [--modes raw,clean] [--only hs-006,...]
       .venv/bin/python scripts/ocr_eval.py --report-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SET = ROOT / "data" / "eval" / "hard_scans"
PAGES = ROOT / "logs" / "ocr_eval_pages.json"
OUT = ROOT / "logs" / "ocr_eval.json"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s).lower()
    s = re.sub(r"[*#_`|>]", "", s)                        # markdown from the VLM
    s = re.sub(r"[‐-―−]", "-", s)                          # dash variants
    return re.sub(r"\s+", "", s)


def digits(s: str) -> int:
    return sum(ch.isdigit() for ch in s)


def char_acc(phrase: str, text: str) -> float:
    """1 − character error rate of the phrase against its best-matching window of the text."""
    from difflib import SequenceMatcher
    n = len(phrase)
    if not n or not text:
        return 0.0
    if phrase in text:
        return 1.0
    best = 0.0
    for i in range(0, max(1, len(text) - n + 1), max(1, n // 4)):
        sm = SequenceMatcher(None, phrase, text[max(0, i - 3): i + n + 3], autojunk=False)
        best = max(best, sum(b.size for b in sm.get_matching_blocks()) / n)
    return best


def lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ------------------------------------------------------------------ OCR (slow)
def run(limit: int | None, modes: list[str], only: list[str] | None) -> list[dict]:
    from dr.ingest import ocr
    truth = json.loads((SET / "truth.json").read_text(encoding="utf-8"))["docs"][:limit]
    if only:
        truth = [d for d in truth if any(o in d["file"] for o in only)]
    if not ocr.vl_available():
        sys.exit("OCR server (PaddleOCR-VL) chưa chạy: make ocr-server")
    out = []
    for d in truth:
        for mode in modes:
            t0 = time.time()
            pages = ocr.ocr_file(str(SET / d["file"]), clean=(mode == "clean"))
            rec = {"file": d["file"], "mode": mode, "seconds": round(time.time() - t0, 1),
                   "pages": [{"page": p.page, "text": p.text, "doubt": p.doubt, "steps": p.steps} for p in pages]}
            out.append(rec)
            whole = norm(" ".join(p["text"] for p in rec["pages"]))
            nums = [x for x in d["numbers"] if digits(x["text"]) >= 3]
            print(f"{d['file']:<32} {mode:<5} số {sum(norm(x['text']) in whole for x in nums):>3}/{len(nums):<3} "
                  f"{rec['seconds']:5.1f}s {'; '.join(s for p in pages for s in p.steps)}", flush=True)
    return out


# ------------------------------------------------------------------ scoring (fast)
def score(records: list[dict]) -> dict:
    from dr.ingest.ocr import cached_page, cross_check, numbers_in
    truth = {d["file"]: d for d in json.loads((SET / "truth.json").read_text(encoding="utf-8"))["docs"]}
    res: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for rec in records:
        d, mode = truth[rec["file"]], rec["mode"]
        r = res[mode][d["kind"]]
        text = {p["page"]: norm(p["text"]) for p in rec["pages"]}
        whole = "".join(text.values())
        r["docs"] += 1
        r["pages"] += len(rec["pages"])
        r["seconds"] += rec["seconds"]
        keys = [x for x in d["numbers"] if digits(x["text"]) >= 3]
        for x in keys:
            hit = norm(x["text"]) in text.get(x["page"], whole)
            r["num_total"] += 1
            r["num_hit"] += hit
            for tag in ("covered", "handwritten"):
                if x.get(tag):
                    r[f"{tag}_total"] += 1
                    r[f"{tag}_hit"] += hit
        for ph in d["phrases"]:
            r["phr_total"] += 1
            r["phr_hit"] += norm(ph) in whole
            r["chr_sum"] += char_acc(norm(ph), whole)
        # second-reader check: flags on misreads vs. flags on correct reads of key numbers
        key_set = {x["text"] for x in keys}
        sha = hashlib.sha1((SET / rec["file"]).read_bytes()).hexdigest() if mode == "clean" else None
        for p in rec["pages"]:
            got = cached_page(sha, p["page"]) if sha else None
            # recompute with the current cross_check so --report-only reflects code changes
            flagged = set(cross_check(p["text"], got[1])[0]) if got else set(p["doubt"])
            for tok in numbers_in(p["text"]):
                if tok not in key_set and any(tok in k for k in key_set):
                    continue                      # digits of a code like FT2659212019: not a misread
                if tok in key_set:
                    r["ok_seen"] += 1
                    r["ok_flagged"] += tok in flagged
                elif any(abs(len(tok) - len(k)) <= 2 and lev(tok, k) <= 2 for k in key_set):
                    r["bad_seen"] += 1
                    r["bad_flagged"] += tok in flagged
    return {m: {k: dict(v) for k, v in kinds.items()} for m, kinds in res.items()}


def report(data: dict) -> None:
    modes = [m for m in ("raw", "clean") if m in data]
    kinds = sorted({k for m in modes for k in data[m]})
    pct = lambda a, b: f"{100 * a / b:5.1f}%" if b else "   — "
    print(f"\n{'Loại':<20}" + "".join(f"{'số ' + m:>11}{'cụm ' + m:>11}{'ký tự ' + m:>12}" for m in modes) + f"{'s/trang':>9}")
    tot = {m: defaultdict(float) for m in modes}
    for k in kinds:
        row = f"{k:<20}"
        for m in modes:
            r = data[m].get(k, {})
            row += (f"{pct(r.get('num_hit', 0), r.get('num_total', 0)):>11}{pct(r.get('phr_hit', 0), r.get('phr_total', 0)):>11}"
                    f"{pct(r.get('chr_sum', 0), r.get('phr_total', 0)):>12}")
            for f, v in r.items():
                tot[m][f] += v
        r = data[modes[-1]].get(k, {})
        print(row + f"{r.get('seconds', 0) / max(1, r.get('pages', 1)):9.1f}")
    print(f"{'TỔNG':<20}" + "".join(f"{pct(tot[m]['num_hit'], tot[m]['num_total']):>11}"
                                     f"{pct(tot[m]['phr_hit'], tot[m]['phr_total']):>11}"
                                     f"{pct(tot[m]['chr_sum'], tot[m]['phr_total']):>12}" for m in modes))
    for m in modes:
        t = tot[m]
        print(f"{m}: {int(t['num_hit'])}/{int(t['num_total'])} số; bị dấu/chữ ký/vết bẩn đè "
              f"{pct(t['covered_hit'], t['covered_total'])}; viết tay {pct(t['handwritten_hit'], t['handwritten_total'])}; "
              f"{t['seconds'] / max(1, t['pages']):.1f} s/trang")
    if "clean" in data:
        t = tot["clean"]
        print(f"Đối chiếu 2 bộ đọc (clean): gắn cờ {int(t['bad_flagged'])}/{int(t['bad_seen'])} số đọc lệch "
              f"({pct(t['bad_flagged'], t['bad_seen']).strip()}), báo nhầm {int(t['ok_flagged'])}/{int(t['ok_seen'])} "
              f"số đọc đúng ({pct(t['ok_flagged'], t['ok_seen']).strip()})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--modes", default="raw,clean")
    ap.add_argument("--only", help="comma-separated file name parts, e.g. hs-006,hs-012")
    ap.add_argument("--report-only", action="store_true", help="re-score saved OCR output, no OCR")
    a = ap.parse_args(argv)
    if a.report_only:
        records = json.loads(PAGES.read_text(encoding="utf-8"))
    else:
        records = run(a.limit, a.modes.split(","), a.only.split(",") if a.only else None)
        if not a.only:
            PAGES.parent.mkdir(exist_ok=True)
            PAGES.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    data = score(records)
    if not a.only:
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    report(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
