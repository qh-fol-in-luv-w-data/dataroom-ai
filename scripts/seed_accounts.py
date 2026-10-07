"""Give every demo user (and a Data Room admin) a sign-in password.

Generates one random demo password, stores only its PBKDF2 hash in tenant.json and writes
the plain value to data/tenant/DEMO_ACCOUNTS.md (local, git-ignored) for the presenter.
Usage: .venv/bin/python scripts/seed_accounts.py [--password VALUE]
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dr.gateway.accounts import hash_password  # noqa: E402

ADMINS = [{"oid": "admin", "name": "Quản trị Data Room", "email": "admin@saomai.example",
           "org": "Ban IPO Sao Mai", "type": "admin"}]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--password")
    ap.add_argument("--tenant", default=str(ROOT / "data" / "tenant"))
    a = ap.parse_args(argv)
    tdir = Path(a.tenant)
    tj = tdir / "tenant.json"
    t = json.loads(tj.read_text(encoding="utf-8"))
    pw = a.password or f"SaoMai-{secrets.token_hex(3)}-2026"
    t["admins"] = [dict(x) for x in ADMINS]
    for rec in t["users"] + t["admins"]:
        rec["pw"] = hash_password(pw)
    tj.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
    orig = tdir / "tenant.original.json"
    if orig.exists():
        orig.unlink()  # the freshly seeded file is the new baseline
    lines = ["# Tài khoản demo (chỉ dùng trên máy local)", "",
             f"Mật khẩu chung cho mọi tài khoản demo: `{pw}`", "",
             "| Email | Tên | Vai trò |", "|---|---|---|"]
    for r in t["admins"]:
        lines.append(f"| {r['email']} | {r['name']} | Quản trị Data Room |")
    for u in t["users"]:
        lines.append(f"| {u['email']} | {u['name']} | {', '.join(u.get('roles', [])) or '—'} |")
    (tdir / "DEMO_ACCOUNTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Đã tạo mật khẩu cho {len(t['users']) + len(t['admins'])} tài khoản. Xem {tdir / 'DEMO_ACCOUNTS.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
