"""Document search check for UAT-01 (BRD 19/10/2026) on the Sao Mai demo corpus, with the real embedding model.

Each case of scripts/search_eval_set.json describes a document without its file name. Reported:
hit@1, hit@5 and MRR of the first result whose title starts with 'expect' (any such file in the
asker's scope counts), and leaks. The leak oracle does not trust the system under test: SharePoint
(the simulated tenant) must let the asker open the file and the file must be usable with AI.
Usage: .venv/bin/python scripts/search_eval.py   → logs/search_eval-<time>.json, exit 1 on any leak
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dr.connector.sync import Connector  # noqa: E402
from dr.core import answer  # noqa: E402
from dr.core.pgindex import make_index  # noqa: E402
from dr.core.search import search_files  # noqa: E402
from dr.db import pg  # noqa: E402
from dr.models import embed  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402


def usable_by(tenant, oid: str, item_id: str) -> bool:
    it = tenant.items[item_id]
    return (tenant.sp_can_read(oid, item_id) and it["ai_use"] in ("Allowed", "OnPremOnly")
            and not it["encrypted"] and not it["malware"])


def main() -> int:
    cases = json.loads((ROOT / "scripts/search_eval_set.json").read_text(encoding="utf-8"))["cases"]
    pg.ensure_cluster()
    tenant = FakeTenant()
    Connector(tenant).full_resync()
    ix = make_index()
    ix.refresh()
    deps = answer.Deps(embed_query=embed.embed_query)          # search needs no LLM
    by_email = {u["email"]: oid for oid, u in tenant.users.items()}
    log, ranks, leaks, neg_fail = [], [], 0, 0
    for c in cases:
        oid = by_email[c["user"]]
        t0 = time.time()
        r = search_files(tenant, ix, oid, tenant.users[oid]["roles"], c["q"], deps)
        ms = int((time.time() - t0) * 1000)
        got = [x["item_id"] for x in r["results"]]
        leaked = [i for i in got if not usable_by(tenant, oid, i)]
        leaks += len(leaked)
        row = {**c, "oid": oid, "ms": ms, "results": got[:5], "leaked": leaked}
        if "expect" in c:
            targets = {i for i, it in tenant.items.items()
                       if (it.get("title") or "").startswith(c["expect"]) and usable_by(tenant, oid, i)}
            rank = next((k for k, i in enumerate(got, 1) if i in targets), None)
            ranks.append(rank)
            row.update(targets=len(targets), rank=rank)
            mark = "✔" if rank == 1 else ("~" if rank and rank <= 5 else "✗")
            print(f"  {mark} hạng {rank or '-':<3} {c['q'][:62]:<62} ({ms} ms){' LEAK ' + str(leaked) if leaked else ''}")
        else:
            bad = sorted(set(got) & set(c["must_not"]))
            neg_fail += bool(bad)
            row["must_not_returned"] = bad
            print(f"  {'✔' if not bad else '✗'} không thấy {','.join(c['must_not']):<12} {c['q'][:50]:<50}"
                  f"{' LEAK ' + str(leaked) if leaked else ''}")
        log.append(row)
    n = len(ranks)
    hit1 = sum(1 for k in ranks if k == 1)
    hit5 = sum(1 for k in ranks if k and k <= 5)
    mrr = sum(1 / k for k in ranks if k) / n if n else 0.0
    summary = {"cases": n, "hit@1": hit1, "hit@5": hit5, "mrr": round(mrr, 3), "leaks": leaks,
               "must_not_failed": neg_fail, "negatives": len(cases) - n}
    print(f"\nTìm đúng hồ sơ: hạng 1 {hit1}/{n} · top 5 {hit5}/{n} · MRR {mrr:.3f}"
          f"\nRò rỉ (kết quả người hỏi không được mở/không được dùng AI): {leaks} · "
          f"ca 'không được thấy' bị lộ: {neg_fail}/{len(cases) - n}")
    out = ROOT / "logs" / f"search_eval-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "cases": log}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {out.relative_to(ROOT)}")
    return 1 if leaks or neg_fail else 0


if __name__ == "__main__":
    sys.exit(main())
