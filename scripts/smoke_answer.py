"""One question through the real answer path: checks that a restored database, the tenant files, Ollama and the
reranker/NLI models all work before a long benchmark. Prints "SMOKE OK" (and exits 0) when the answer holds 26,4 m².

    DR_DATA=data/ctg DR_PGDATA=~/.dr_ctg/pgdata DR_PG_PORT=55433 python scripts/smoke_answer.py [model]
"""
from __future__ import annotations

import re
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dr.config import settings  # noqa: E402
from dr.connector.sync import Connector  # noqa: E402
from dr.core import answer  # noqa: E402
from dr.core.pgindex import make_index  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402

QUESTION = "Căn S-01 C.T Plaza Minh Châu có diện tích thông thủy bao nhiêu m²?"


def main() -> int:
    if len(sys.argv) > 1:
        settings.llm_model = sys.argv[1]
    tenant = FakeTenant()
    conn = Connector(tenant)
    conn.full_resync()
    stop = threading.Event()
    threading.Thread(target=conn.run_forever, args=(stop,), daemon=True).start()
    index = make_index()
    index.refresh()
    r = answer.ask(tenant, index, "ctg-b", tenant.users["ctg-b"]["roles"], QUESTION, answer.Deps.real())
    stop.set()
    text = r.get("message") or " ".join(c["text"] for c in r.get("claims", []))
    ok = "264" in re.sub(r"\D", "", text)
    print(f"SMOKE {'OK' if ok else 'FAIL'} ({settings.llm_model}) | {text[:200]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
