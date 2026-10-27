"""Permission check of the CT Group data room against its folder matrix (no LLM; deterministic).

For each of the six demo users (CTG-A…F):
  1. Every item RLS lets the user retrieve must be one the matrix (scripts/build_ctg_tenant.MATRIX) and
     SharePoint let the user open                                              -> 0 leaks.
  2. Completeness: every indexed item the matrix gives the user must be retrievable.
  3. Search probes: the opening words of sampled chunks of every folder are searched as every user
     (the RLS-filtered search the chat uses); every hit must be an item the user may read, and a user
     allowed into the folder should find the probed chunk.

Exit code 0 only if there are zero leaks.
    DR_DATA=data/ctg DR_PGDATA=~/.dr_ctg/pgdata DR_PG_PORT=55433 .venv/bin/python scripts/ctg_leak_test.py
"""
from __future__ import annotations

import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_ctg_tenant import MATRIX  # noqa: E402
from dr.connector.sync import Connector  # noqa: E402
from dr.core import gates  # noqa: E402
from dr.core.pgindex import make_index  # noqa: E402
from dr.db import pg  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402

PROBES_PER_FOLDER = 15


def rule(path: str) -> str:
    """The matrix folder that decides access to a file in `path` (longest matching prefix)."""
    best = ""
    for folder in MATRIX:
        if (path == folder or path.startswith(folder + "/")) and len(folder) > len(best):
            best = folder
    return best


def main() -> int:
    pg.ensure_cluster()
    tenant = FakeTenant()
    Connector(tenant).full_resync()          # permissions in Postgres = tenant.json as it is now
    ix = make_index()
    ix.refresh()
    with pg.admin() as c:
        items = {r[0]: {"path": r[1].strip("/"), "status": r[2]}
                 for r in c.execute("SELECT item_id, path, status FROM items")}
        chunks = c.execute("SELECT chunk_id, item_id, text FROM chunks WHERE is_current").fetchall()
    users = {oid: oid.split("-")[1].upper() for oid in tenant.users if oid.startswith("ctg-")}
    text_of = {cid: text for cid, _, text in chunks}

    def may(oid: str, item: str) -> bool:
        return users[oid] in MATRIX.get(rule(items[item]["path"]), "")

    leaks: list[str] = []
    allowed = {oid: gates.allowed_chunks(oid) for oid in users}
    rows = []
    for oid in users:
        rag_items = set(allowed[oid].values())
        sp_items = {i for i in tenant.items if tenant.sp_can_read(oid, i)}
        should = {i for i, m in items.items() if m["status"] == "indexed" and may(oid, i)}
        for i in sorted(rag_items):
            if not may(oid, i):
                leaks.append(f"{oid}: RAG thấy {i} ({items[i]['path']}) – ngoài ma trận quyền")
            if i not in sp_items:
                leaks.append(f"{oid}: RAG thấy {i} nhưng SharePoint không cho mở")
        missing = should - rag_items
        rows.append([oid, len(sp_items), len(rag_items), len(should), len(missing)])

    # search probes: opening words of sampled chunks per matrix folder
    by_folder = defaultdict(list)
    for cid, item, text in chunks:
        if items.get(item, {}).get("status") == "indexed":
            by_folder[rule(items[item]["path"])].append((cid, item, text))
    rnd = random.Random(0)
    probe = {oid: [0, 0, 0] for oid in users}           # hits checked, probes allowed, probe chunk found
    folder_rows = []
    for folder in MATRIX:
        sample = rnd.sample(by_folder[folder], min(PROBES_PER_FOLDER, len(by_folder[folder])))
        for cid, item, text in sample:
            words = re.findall(r"\w+", re.sub(r"^\[[^\]]*\]", "", text))[:10]
            if len(words) < 4:
                continue
            q = " ".join(words)
            for oid in users:
                hits = ix.search_as(oid, q, None, k=10)[0]
                for hid, _ in hits:
                    probe[oid][0] += 1
                    if hid not in allowed[oid]:
                        leaks.append(f"{oid}: dò '{q[:40]}' trả về đoạn {hid} ngoài RLS")
                    elif not may(oid, allowed[oid][hid]):
                        leaks.append(f"{oid}: dò '{q[:40]}' trả về {allowed[oid][hid]} ngoài ma trận")
                if users[oid] in MATRIX[folder]:
                    probe[oid][1] += 1            # found: the chunk or a copy of its text (search keeps one copy)
                    probe[oid][2] += any(text_of.get(hid) == text for hid, _ in hits)
        folder_rows.append((folder, MATRIX[folder], len({i for _, i, _ in by_folder[folder]}), len(sample)))

    print("Thư mục theo ma trận            Nhóm    File đã nạp  Mẫu dò")
    for f, l, n, s in folder_rows:
        print(f"  {f[:38]:<38} {l:<7} {n:>6} {s:>7}")
    print(f"\n{'Người dùng':<8} {'SP mở':>7} {'RAG thấy':>9} {'Đúng ra':>8} {'Thiếu':>6} {'Kết quả dò':>11} {'Tìm thấy mẫu':>13}")
    for oid, sp, rag, should, miss in rows:
        h, n, f = probe[oid]
        print(f"{oid:<8} {sp:>7} {rag:>9} {should:>8} {miss:>6} {h:>11} {f:>7}/{n:<5}")
    print(f"\nRò rỉ: {len(leaks)}")
    for line in leaks[:50]:
        print("  ✗", line)
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
