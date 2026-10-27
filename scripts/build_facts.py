"""Build the fact index (dr/core/facts.py) from the chunks already in Postgres, without re-ingesting.
New and changed files get their facts at ingest (pipeline.ingest_item).

    DR_DATA=data/ctg DR_PGDATA=~/.dr_ctg/pgdata DR_PG_PORT=55433 .venv/bin/python scripts/build_facts.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dr.core import facts  # noqa: E402
from dr.core.gates import doc_context  # noqa: E402
from dr.db import pg  # noqa: E402


def main() -> None:
    t0 = time.time()
    pg.ensure_cluster()                           # applies the schema: creates the facts table and its policy
    with pg.admin() as c:
        items = c.execute("SELECT item_id, path, name FROM items WHERE status = 'indexed'").fetchall()
        n = 0
        for i, (item_id, path, name) in enumerate(items, 1):
            n += facts.index_item(c, item_id, doc_context(path, name))
            if i % 500 == 0:
                c.commit()
                print(f"  {i}/{len(items)} file, {n} dữ kiện", flush=True)
        c.commit()
        kinds = c.execute("SELECT kind, count(*), count(DISTINCT item_id) FROM facts GROUP BY kind").fetchall()
    print(f"{n} dữ kiện từ {len(items)} file trong {time.time() - t0:.0f}s")
    for kind, k, files in kinds:
        print(f"  {kind:5} {k:6} dữ kiện, {files} file")


if __name__ == "__main__":
    main()
