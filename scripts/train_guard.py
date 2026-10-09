"""Train the input-guard classifier: logistic regression on bge-m3 embeddings.

Data: data/eval/prompt_attacks/train.jsonl (see gen_attack_set.py). The test split is never
read here — it is only for scripts/attack_eval.py.
The threshold is chosen on 5-fold out-of-fold scores so that, together with the rules,
at most --max-fpr of benign training questions would be blocked.
Usage: .venv/bin/python scripts/train_guard.py [--max-fpr 0.03]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.model_selection import StratifiedKFold  # noqa: E402

from dr.models.embed import embed_texts  # noqa: E402
from dr.security import guard  # noqa: E402

DATA = ROOT / "data" / "eval" / "prompt_attacks"


def load(split: str) -> list[dict]:
    return [json.loads(line) for line in (DATA / f"{split}.jsonl").read_text(encoding="utf-8").splitlines() if line]


def embed_all(texts: list[str], batch: int = 32) -> np.ndarray:
    out = []
    for i in range(0, len(texts), batch):
        out.extend(embed_texts([guard.clean(t) for t in texts[i:i + batch]]))
    return np.asarray(out, dtype=np.float32)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-fpr", type=float, default=0.03)
    ap.add_argument("--C", type=float, default=4.0)
    a = ap.parse_args(argv)
    rows = load("train")
    y = np.array([r["label"] == "attack" for r in rows], dtype=int)
    t0 = time.time()
    X = embed_all([r["text"] for r in rows])
    print(f"{len(rows)} câu huấn luyện ({y.sum()} tấn công), embedding {time.time() - t0:.0f}s")
    rule = np.array([bool(guard.rule_hits(r["text"])) for r in rows])

    # long questions are also scored sentence by sentence (max), exactly as guard.inspect does
    segs = [guard.segments(r["text"]) for r in rows]
    flat = [t for ss in segs for t in ss]
    S = embed_all(flat) if flat else np.zeros((0, X.shape[1]), dtype=np.float32)
    owner = np.array([i for i, ss in enumerate(segs) for _ in ss], dtype=int)
    oof = np.zeros(len(rows))          # whole question
    oof_seg = np.zeros(len(rows))      # best single sentence of a long question (0 = no segments)
    for tr, va in StratifiedKFold(5, shuffle=True, random_state=7).split(X, y):
        m = LogisticRegression(C=a.C, class_weight="balanced", max_iter=2000).fit(X[tr], y[tr])
        oof[va] = m.predict_proba(X[va])[:, 1]
        in_va = np.isin(owner, va)
        if in_va.any():
            for i, p_ in zip(owner[in_va], m.predict_proba(S[in_va])[:, 1]):
                oof_seg[i] = max(oof_seg[i], p_)

    # Both thresholds are chosen on out-of-fold training scores only (the test split is never used):
    # the highest detection whose benign block rate, rules included, stays within --max-fpr.
    benign_free = (y == 0) & ~rule                       # benign questions the rules let through
    best = None
    for th in np.linspace(0.3, 0.99, 70):
        for sth in list(np.linspace(0.5, 0.99, 25)) + [1.01]:
            hit = rule | (oof >= th) | (oof_seg >= sth)
            fp = ((y == 0) & hit).sum() / max(1, (y == 0).sum())
            tp = ((y == 1) & hit).sum() / max(1, y.sum())
            if fp <= a.max_fpr and (best is None or tp > best[2] or (tp == best[2] and (th, -sth) < (best[0], -best[1]))):
                best = (float(th), float(sth), float(tp), float(fp))
    th, sth, tp, fp = best or (0.99, 1.01, 0.0, 0.0)
    print(f"Ngưỡng cả câu {th:.3f}, từng câu {sth:.3f}: phát hiện (CV) {tp:.1%}, chặn nhầm (CV) {fp:.1%}; "
          f"riêng luật: phát hiện {rule[y == 1].mean():.1%}, chặn nhầm {rule[y == 0].mean():.1%}; "
          f"câu hợp lệ không dính luật: {benign_free.sum()}")

    m = LogisticRegression(C=a.C, class_weight="balanced", max_iter=2000).fit(X, y)
    guard.MODEL.write_text(json.dumps({
        "w": [round(float(v), 6) for v in m.coef_[0]], "b": float(m.intercept_[0]), "threshold": th,
        "segment_threshold": sth, "operating_point": "both thresholds from 5-fold CV on the train split only",
        "trained_on": len(rows), "cv_detection": round(tp, 4), "cv_false_positive": round(fp, 4),
        "embedding": "bge-m3 (Ollama)", "C": a.C,
    }))
    print(f"Đã lưu {guard.MODEL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
