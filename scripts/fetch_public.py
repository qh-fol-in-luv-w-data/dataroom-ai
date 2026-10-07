"""Download the approved public IPO / disclosure documents and add them to the tenant.

Only run after the list in data/public_sources.json has been reviewed and approved.
Files go to data/tenant/files/COMMON/Cong-bo-thong-tin/<issuer>/ and are registered as
items of the COMMON site (visible to every investor group), ai_use = Allowed.

Usage: .venv/bin/python scripts/fetch_public.py [--max-mb 35] [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
TENANT = ROOT / "data" / "tenant"


def slug(s: str, n: int = 60) -> str:
    s = unicodedata.normalize("NFD", s).replace("đ", "d").replace("Đ", "D")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:n] or "tai-lieu"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-mb", type=float, default=35)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    sources = json.loads((ROOT / "data" / "public_sources.json").read_text(encoding="utf-8"))["items"]
    tj = TENANT / "tenant.json"
    if not tj.exists():
        print("Chưa có data/tenant/tenant.json — chạy `make data` trước.")
        return 1
    tenant = json.loads(tj.read_text(encoding="utf-8"))
    existing = {it["id"] for it in tenant["items"]}
    added = skipped = 0
    with httpx.Client(follow_redirects=True, timeout=120,
                      headers={"User-Agent": "Mozilla/5.0 (dataroom-ai-demo; public disclosure sample)"}) as c:
        for i, src in enumerate(sources, start=1):
            if a.limit and added >= a.limit:
                break
            iid = f"pub-{i:03d}"
            if iid in existing:
                continue
            size = src.get("size_bytes") or 0
            if size and size > a.max_mb * 1e6:
                print(f"bỏ qua (>{a.max_mb} MB): {src['title']}")
                skipped += 1
                continue
            issuer = slug(src.get("issuer", "khac"), 30)
            ext = (src.get("format") or "pdf").lower()
            name = f"{slug(src['title'])}.{ext}"
            rel = Path("COMMON") / "Cong-bo-thong-tin" / issuer / name
            dest = TENANT / "files" / rel
            print(f"[{i}/{len(sources)}] {src['title'][:70]} ({(size or 0) / 1e6:.1f} MB)")
            if a.dry_run:
                continue
            if not dest.exists():
                try:
                    r = c.get(src["url"])
                    r.raise_for_status()
                    if ext == "pdf" and not r.content.startswith(b"%PDF"):
                        print("   ✗ không phải PDF, bỏ qua")
                        skipped += 1
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(r.content)
                except Exception as e:
                    print(f"   ✗ lỗi tải: {e}")
                    skipped += 1
                    continue
            tenant["items"].append({
                "id": iid, "site": "COMMON", "path": f"Cong-bo-thong-tin/{issuer}", "name": name, "ext": ext,
                "file": str(rel), "ai_use": "Allowed", "label": "Công khai", "encrypted": False, "malware": False,
                "unique": False, "grants": [], "source_url": src["url"]})
            added += 1
    if not a.dry_run:
        tj.write_text(json.dumps(tenant, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nĐã thêm {added} tài liệu công khai, bỏ qua {skipped}. Chạy `make ingest` để nạp.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
