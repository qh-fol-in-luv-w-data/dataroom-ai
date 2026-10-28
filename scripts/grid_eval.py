"""Cross benchmark of LLMs x accuracy methods on the CT Group tenant (ctg_ocr_eval.py + ctg_table_eval.py).

A full grid (5 models x 2^6 methods x settings) would take weeks, so it runs in stages:
  1. models: every model with the current pipeline;
  2. methods one at a time (each DR_* flag of dr/config.py on its own) on qwen2.5:3b and the best other model;
  3. greedy combination per model: the methods that helped, added best first, each kept only if the score
     does not drop;
  4. the best configurations run once more (the local GPU is not perfectly repeatable: ±1 question).
Score = right answers of both sets (36); ties go to fewer wrong answers (an answer given and wrong is worse than
a refusal), then speed. Runs one configuration at a time (two evals at once make the permission feed stale).

    DR_DATA=data/ctg DR_PGDATA=~/.dr_ctg/pgdata DR_PG_PORT=55433 DR_OCR_MD_DIR=data/ctg/md \\
        python scripts/grid_eval.py [--out data/ctg/grid] [--models qwen2.5:3b,qwen2.5:7b,...]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ["qwen2.5:3b", "qwen2.5:7b", "qwen3:4b", "gemma3:4b", "phi4-mini"]
SMALL = "qwen2.5:3b"
METHODS = {                      # name -> env of that method alone
    "doctype": {"DR_DOCTYPE": "1"},
    "binding": {"DR_BINDING": "1"},
    "two_stage": {"DR_TWO_STAGE": "1"},
    "fewshot": {"DR_FEWSHOT": "1"},
    "vote3": {"DR_VOTE": "3"},
    "sent8": {"DR_MAX_SENTENCES": "8"},
    "sent24": {"DR_MAX_SENTENCES": "24"},
    "pass3": {"DR_MAX_PASSAGES": "3"},
    "fallback7b": {"DR_LLM_FALLBACK": "qwen2.5:7b"},
}
EXCLUSIVE = [{"sent8", "sent24"}]       # settings of one knob: at most one in a combination


def run_config(model: str, methods: list[str], out: Path) -> dict:
    name = model + ("+" + "+".join(methods) if methods else "")
    log = out / (re.sub(r"[^\w.+-]", "_", name) + ".log")
    cached = out / "results.jsonl"
    if cached.exists():                  # resume: a configuration already measured is not run again
        for line in cached.read_text().splitlines():
            r = json.loads(line)
            if r["name"] == name and r.get("rerun", 0) == 0:
                return r
    env = {**os.environ, "DR_LLM": model, "DR_LLM_KEEP_ALIVE": "10m", "PYTHONUNBUFFERED": "1"}
    for m in methods:
        env.update(METHODS[m])
    res = {"name": name, "model": model, "methods": methods}
    t = time.time()
    with log.open("w") as f:
        for script, args, key in (("ctg_ocr_eval.py", [], "ocr"), ("ctg_table_eval.py", [model], "table")):
            p = subprocess.run([sys.executable, "-u", str(ROOT / "scripts" / script), *args], env=env, cwd=ROOT,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            f.write(p.stdout)
            got = [json.loads(line[7:]) for line in p.stdout.splitlines() if line.startswith("RESULT ")]
            res[key] = got[-1] if got else {"ok": 0, "n": 0, "wrong": 0, "avg_s": 0, "error": p.returncode}
    res["ok"] = res["ocr"]["ok"] + res["table"]["ok"]
    res["n"] = res["ocr"]["n"] + res["table"]["n"]
    res["wrong"] = res["ocr"]["wrong"] + res["table"]["wrong"]
    res["avg_s"] = round((res["ocr"]["avg_s"] * res["ocr"]["n"] + res["table"]["avg_s"] * res["table"]["n"])
                         / max(1, res["n"]), 1)
    res["minutes"] = round((time.time() - t) / 60, 1)
    if "error" in res["ocr"] or "error" in res["table"]:
        raise SystemExit(f"{name}: an eval failed, see {log}")     # never score a crash as 0 right answers
    with cached.open("a") as f:
        f.write(json.dumps(res, ensure_ascii=False) + "\n")
    print(f"{name:55} {res['ok']}/{res['n']}  sai {res['wrong']}  {res['avg_s']}s/câu  ({res['minutes']} phút)",
          flush=True)
    return res


def key(r: dict) -> tuple:
    return (-r["ok"], r["wrong"], r["avg_s"])


def unload(model: str) -> None:
    subprocess.run(["ollama", "stop", model], capture_output=True)


def report(out: Path) -> None:
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
    best: dict[str, list[dict]] = {}
    for r in rows:
        best.setdefault(r["name"], []).append(r)
    lines = ["| Cấu hình | Đúng (OCR+bảng) | OCR | Bảng | Trả lời sai | Giây/câu | Số lần chạy |", "|---|---|---|---|---|---|---|"]
    agg = []
    for name, rs in best.items():
        ok = sum(r["ok"] for r in rs) / len(rs)
        agg.append((-ok, sum(r["wrong"] for r in rs) / len(rs), rs[0]["avg_s"], name, rs))
    for nok, wrong, avg, name, rs in sorted(agg):
        lines.append(f"| {name} | {-nok:.1f}/{rs[0]['n']} | {'/'.join(str(r['ocr']['ok']) for r in rs)} | "
                     f"{'/'.join(str(r['table']['ok']) for r in rs)} | {wrong:.1f} | {avg} | {len(rs)} |")
    (out / "REPORT.md").write_text("# Grid search: model × phương pháp\n\n" + "\n".join(lines) + "\n")
    print("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/ctg/grid")
    ap.add_argument("--models", default=",".join(MODELS))
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    models = args.models.split(",")

    print("== 1. model, pipeline hiện tại", flush=True)
    base = {}
    for m in models:
        for _ in range(180):            # a model still downloading (ollama pull) is waited for, up to 30 min
            names = subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout.split()
            if m in names or f"{m}:latest" in names:
                break
            time.sleep(10)
        base[m] = run_config(m, [], out)
        unload(m)
    others = sorted((r for m, r in base.items() if m != SMALL), key=key)
    tuned = [SMALL] + ([others[0]["model"]] if others else [])

    print("\n== 2. từng phương pháp riêng lẻ trên " + ", ".join(tuned), flush=True)
    gains: dict[str, list[tuple[int, str]]] = {}
    for m in tuned:
        for meth in METHODS:
            if meth == "fallback7b" and m == "qwen2.5:7b":
                continue
            r = run_config(m, [meth], out)
            # gain: right answers first, a wrong answer fewer counts half
            gain = (r["ok"] - base[m]["ok"]) + 0.5 * (base[m]["wrong"] - r["wrong"])
            gains.setdefault(m, []).append((gain, meth))
        unload(m)

    print("\n== 3. kết hợp tham lam", flush=True)
    finals = []
    for m in tuned:
        cur, cur_r = [], base[m]
        for gain, meth in sorted(gains[m], reverse=True):
            if gain <= 0 or any(meth in g and set(cur) & (g - {meth}) for g in EXCLUSIVE):
                continue
            r = run_config(m, cur + [meth], out)
            if key(r) <= key(cur_r):
                cur, cur_r = cur + [meth], r
        finals.append(cur_r)
        unload(m)

    print("\n== 4. chạy lại cấu hình tốt nhất", flush=True)
    for r in sorted(finals, key=key)[:2]:
        rerun = rerun_one(r["model"], r["methods"], out)
        print(f"  lặp lại {rerun['name']}: {rerun['ok']}/{rerun['n']} (lần 1: {r['ok']})", flush=True)
    report(out)
    return 0


def rerun_one(model: str, methods: list[str], out: Path) -> dict:
    """Same configuration measured again (not taken from the resume cache)."""
    tmp = out / "rerun"
    tmp.mkdir(exist_ok=True)
    r = run_config(model, methods, tmp)
    r["rerun"] = 1
    with (out / "results.jsonl").open("a") as f:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (tmp / "results.jsonl").unlink(missing_ok=True)
    return r


if __name__ == "__main__":
    sys.exit(main())
