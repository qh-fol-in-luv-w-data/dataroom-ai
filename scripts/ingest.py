"""Offline bulk ingestion: sync the tenant mirror, then parse/OCR/embed every pending item.

Usage: .venv/bin/python scripts/ingest.py [--workers 3] [--only ITEM_ID ...]
Needs: Ollama running (bge-m3); for scanned pages, the OCR server (make ocr-server).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dr.connector.sync import Connector  # noqa: E402
from dr.db import pg  # noqa: E402
from dr.ingest import ocr, pipeline  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    pg.ensure_cluster()
    tenant = FakeTenant()
    conn = Connector(tenant)
    ch = conn.full_resync()
    print(f"Đồng bộ: {len(tenant.items)} tài liệu, {len(tenant.users)} người dùng, {len(ch['items_changed'])} mục mới/đổi")
    if not ocr.vl_available():
        print("⚠ OCR server (PaddleOCR-VL/MLX) chưa chạy — trang scan sẽ dùng PP-OCRv5 (kém tiếng Việt). "
              "Chạy `make ocr-server` ở terminal khác để có chất lượng tốt nhất.")
    t0 = time.time()
    if a.only:
        res = [pipeline.ingest_item(tenant, i) for i in a.only]
    else:
        def progress(done, total, r):
            extra = f"{r.get('chunks', '')} đoạn, {r.get('seconds', '')}s" if r["status"] == "indexed" else r.get("reason", "")
            print(f"[{done}/{total}] {r['status']:8} {r['item_id']}  {extra}", flush=True)
        res = pipeline.ingest_pending(tenant, workers=a.workers, progress=progress)
    st = Counter(r["status"] for r in res)
    with pg.admin() as c:
        n_chunks = c.execute("SELECT count(*) FROM chunks WHERE is_current").fetchone()[0]
        reasons = c.execute("SELECT reason, count(*) FROM items WHERE status IN ('skipped','error') "
                            "GROUP BY reason ORDER BY 2 DESC").fetchall()
    print(f"\nXong trong {time.time() - t0:.0f}s: {dict(st)} · {n_chunks} đoạn hiện hành")
    for r, n in reasons:
        print(f"  bỏ qua/lỗi ({n}): {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
