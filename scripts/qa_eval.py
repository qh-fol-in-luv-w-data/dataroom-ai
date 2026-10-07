"""End-to-end QA check with the real models (needs Ollama).

For every fact in data/tenant/facts.json, ask the question as one allowed user and as one
denied user. Pass = the allowed user's answer contains the expected value with a valid
citation, and the denied user's answer neither contains the value nor cites the site.
Usage: .venv/bin/python scripts/qa_eval.py [--all-users]
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dr.config import settings  # noqa: E402
from dr.connector.sync import Connector  # noqa: E402
from dr.core import answer  # noqa: E402
from dr.core.pgindex import make_index  # noqa: E402
from dr.db import pg  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402


def text_of(r: dict) -> str:
    return " ".join(c["text"] for c in r["claims"]) + " " + " ".join(c["quote"] for c in r["citations"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-users", action="store_true")
    a = ap.parse_args(argv)
    pg.ensure_cluster()
    tenant = FakeTenant()
    conn = Connector(tenant)
    conn.full_resync()
    stop = threading.Event()
    threading.Thread(target=conn.run_forever, args=(stop,), daemon=True).start()
    ix = make_index()
    ix.refresh()
    deps = answer.Deps.real()
    facts = json.loads((settings.tenant_dir / "facts.json").read_text(encoding="utf-8"))["facts"]
    roles = {u: tenant.users[u].get("roles", []) for u in tenant.users}
    ok_allowed = ok_denied = n_allowed = n_denied = 0
    for f in facts:
        allowed = f["allowed_users"] if a.all_users else [u for u in f["allowed_users"] if u.startswith("inv")][:1] or f["allowed_users"][:1]
        denied = f["denied_users"] if a.all_users else f["denied_users"][:1]
        for oid in allowed:
            t0 = time.time()
            r = answer.ask(tenant, ix, oid, roles[oid], f["question"], deps)
            hit = not r["refused"] and any(x.lower() in text_of(r).lower() for x in f["answer_contains"])
            n_allowed += 1
            ok_allowed += hit
            print(f"{'✔' if hit else '✗'} [{f['id']}] {oid:<8} ĐƯỢC PHÉP  {time.time() - t0:5.1f}s  "
                  f"{(r['message'] or ' | '.join(c['text'] for c in r['claims']))[:110]}")
        for oid in denied:
            t0 = time.time()
            r = answer.ask(tenant, ix, oid, roles[oid], f["question"], deps)
            leaked = any(x.lower() in text_of(r).lower() for x in f["answer_contains"]) or \
                any(c["site_id"] == f["site"] for c in r["citations"]) and f["site"] != "COMMON"
            n_denied += 1
            ok_denied += not leaked
            print(f"{'✔' if not leaked else '✗ RÒ RỈ'} [{f['id']}] {oid:<8} KHÔNG PHÉP {time.time() - t0:5.1f}s  "
                  f"{(r['message'] or ' | '.join(c['text'] for c in r['claims']))[:110]}")
    stop.set()
    print(f"\nĐúng cho người được phép: {ok_allowed}/{n_allowed} · Không rò rỉ cho người không được phép: {ok_denied}/{n_denied}")
    return 0 if ok_denied == n_denied else 1


if __name__ == "__main__":
    sys.exit(main())
