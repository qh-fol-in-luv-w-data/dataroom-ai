"""Why are claims dropped as "con số trong câu trả lời không khớp câu trích"? Re-asks the given questions through the
real answer path and, for every number of such a dropped claim that its quotes do not support, records flags
only (no text): is a scale word after it (tỷ, triệu…), does its scaled value equal a quoted value, is it in
another sentence given to the model, is it in the question's source chunk.

    DR_DATA=... python scripts/ctg_probe_numbers.py --ids MT083 MT127 …
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from collections import Counter
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ctg_mocktest_eval import values  # noqa: E402

from dr.config import settings  # noqa: E402
from dr.connector.sync import Connector  # noqa: E402
from dr.core import answer, verify  # noqa: E402
from dr.core.pgindex import make_index  # noqa: E402
from dr.db import pg  # noqa: E402
from dr.models import llm  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402

_SCALE_AFTER = re.compile(r"\s*(tỷ|tỉ|triệu|nghìn|ngàn|tr\b|k\b)", re.I)
FLAGS: list[dict] = []
SOURCE = {"text": ""}


def probe():
    check = verify.check

    def wrapped(raw_claims, labels, passages, question=""):
        kept, dropped = check(raw_claims, labels, passages, question)
        given = " ".join(p["text"] for p in passages.values())
        given_vals = values(given)
        for rc, why in dropped:
            if not why.startswith("con số trong câu trả lời"):
                continue
            text = rc.get("text") or ""
            quotes = " ".join(c.get("quote", "") for c in rc.get("citations") or [])
            sources = [n for n in verify.numbers_with_digits(quotes)] + verify.numbers_with_digits(question)
            for m in verify._NUM.finditer(text):
                vals = verify._parse_number(m.group(0))
                if not vals or verify.number_supported(m.group(0), vals, sources):
                    continue
                scale = _SCALE_AFTER.match(text, m.end())
                FLAGS.append({
                    "scale_word_after": bool(scale),
                    "scaled_value_in_quote": bool(scale) and bool(values(m.group(0) + " " + scale.group(1)) & values(quotes)),
                    "value_in_quote_other_digits": bool(vals & values(quotes)),
                    "in_other_given_sentence": bool(vals & given_vals),
                    "in_source_chunk": bool(vals & values(SOURCE["text"])),
                    "digits": len(re.sub(r"\D", "", m.group(0))),
                })
        return kept, dropped
    verify.check = wrapped               # answer.py calls verify.check through the module


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="+", required=True)
    ap.add_argument("--test", default=str(settings.data_dir / "mocktest" / "mocktest_500.jsonl"))
    a = ap.parse_args()
    items = {json.loads(x)["id"]: json.loads(x) for x in Path(a.test).read_text().splitlines() if x.strip()}
    tenant = FakeTenant()
    conn = Connector(tenant)
    conn.full_resync()
    stop = threading.Event()
    threading.Thread(target=conn.run_forever, args=(stop,), daemon=True).start()
    index = make_index()
    index.refresh()
    deps = answer.Deps.real()
    llm.warm()
    probe()
    total = Counter()
    for i in a.ids:
        it = items[i]
        with pg.admin() as cur:
            src = cur.execute("SELECT text FROM chunks WHERE chunk_id = %s", (it["chunk_id"],)).fetchone()
        FLAGS.clear()
        SOURCE["text"] = src[0] if src else ""
        answer.ask(tenant, index, it["user"], tenant.users[it["user"]]["roles"], it["question"], deps)
        for f in FLAGS:
            for k, v in f.items():
                if v is True:
                    total[k] += 1
            total["numbers"] += 1
        print(i, len(FLAGS), "số không khớp:", [{k: v for k, v in f.items() if v} for f in FLAGS], flush=True)
    stop.set()
    print("\nTổng:", dict(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
