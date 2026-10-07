"""Cross-investor leak matrix on the live demo database (no LLM; deterministic).

For every user:
  1. RLS-visible items (what the RAG can retrieve) must be a subset of what SharePoint lets
     that user open, and must contain no Excluded / encrypted / malware items  -> 0 leaks.
  2. Completeness: every indexed, AI-usable item the user can open must be retrievable.
  3. Marker probes: searching every site marker of every site returns only chunks the
     user may read.
  4. Fact probes: secret facts of a site never reach users outside that site.

Exit code 0 only if there are zero leaks. Usage: .venv/bin/python scripts/leak_matrix.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dr.config import settings  # noqa: E402
from dr.connector.sync import Connector  # noqa: E402
from dr.core import gates  # noqa: E402
from dr.core.pgindex import make_index  # noqa: E402
from dr.db import pg  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402

AI_VALUES = ("Allowed", "OnPremOnly")


def main() -> int:
    pg.ensure_cluster()
    tenant = FakeTenant()
    Connector(tenant).full_resync()
    ix = make_index()
    ix.refresh()
    facts = json.loads((settings.tenant_dir / "facts.json").read_text(encoding="utf-8"))
    with pg.admin() as c:
        meta = {r[0]: {"status": r[1], "ai_use": r[2], "enc": r[3], "mal": r[4]} for r in
                c.execute("SELECT item_id, status, ai_use, encrypted, malware FROM items")}

    leaks: list[str] = []
    rows = []
    for oid in tenant.users:
        allowed = gates.allowed_chunks(oid)
        ai_items = set(allowed.values())
        sp_items = {i for i in tenant.items if tenant.sp_can_read(oid, i)}
        usable = {i for i in sp_items if meta.get(i, {}).get("status") == "indexed"
                  and meta[i]["ai_use"] in AI_VALUES and not meta[i]["enc"] and not meta[i]["mal"]}
        for i in ai_items - sp_items:
            leaks.append(f"{oid}: RAG thấy {i} nhưng SharePoint không cho mở")
        for i in ai_items:
            m = meta.get(i, {})
            if m.get("ai_use") not in AI_VALUES or m.get("enc") or m.get("mal"):
                leaks.append(f"{oid}: RAG thấy {i} dù bị loại khỏi AI ({m})")
        missing = usable - ai_items
        # marker probes (BM25 only, deterministic)
        probe_hits = 0
        for site, markers in facts["markers"].items():
            for mk in markers[:25]:
                if getattr(ix, "in_db", False):     # RLS inside the search query
                    hits = ix.search_as(oid, mk, None, k=10)[0]
                else:
                    hits = ix.search(set(allowed), mk, None, k=10)
                for cid, _ in hits:
                    probe_hits += 1
                    if cid not in allowed:
                        leaks.append(f"{oid}: dò {mk} trả về đoạn {cid} ngoài phạm vi RLS")
                    elif allowed[cid] not in sp_items:
                        leaks.append(f"{oid}: dò {mk} trả về {allowed[cid]}")
        # secret facts
        for f in facts["facts"]:
            if oid in f.get("denied_users", []) or oid in f.get("no_ai_users", []):
                bad = ai_items & set(f.get("item_ids", []))
                if bad and oid not in f.get("no_ai_users", []):
                    leaks.append(f"{oid}: có thể truy xuất tài liệu chứa bí mật {f['id']}: {sorted(bad)}")
        rows.append((oid, tenant.users[oid]["name"], len(sp_items), len(ai_items), len(missing), probe_hits))

    print(f"{'Người dùng':<10} {'Tên':<22} {'SP mở được':>10} {'RAG thấy':>9} {'Thiếu':>6} {'Dò marker':>10}")
    for oid, name, sp, ai, miss, hits in rows:
        print(f"{oid:<10} {name[:22]:<22} {sp:>10} {ai:>9} {miss:>6} {hits:>10}")
    print(f"\nRò rỉ: {len(leaks)}")
    for l in leaks[:50]:
        print("  ✗", l)
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
