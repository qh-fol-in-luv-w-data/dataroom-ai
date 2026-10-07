"""Demo sign-in accounts (stand-in for the Entra sign-in page).

Passwords are stored as PBKDF2-SHA256 hashes in tenant.json ("pw" on each user and on each
entry of "admins"). Repeated failures lock the e-mail for a short time.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import threading
import time

ITERATIONS = 200_000
LOCK_AFTER = 5
LOCK_SECONDS = 60

_fails: dict[str, list[float]] = {}
_lock = threading.Lock()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("pbkdf2$"):
        return False
    _, it, salt, dk = stored.split("$")
    got = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(it))
    return hmac.compare_digest(got, base64.b64decode(dk))


def locked(email: str) -> float:
    """Seconds remaining on a lockout, or 0."""
    with _lock:
        now = time.time()
        recent = [t for t in _fails.get(email, []) if now - t < LOCK_SECONDS]
        _fails[email] = recent
        return LOCK_SECONDS - (now - recent[0]) if len(recent) >= LOCK_AFTER else 0.0


def record_failure(email: str) -> None:
    with _lock:
        _fails.setdefault(email, []).append(time.time())


def clear_failures(email: str) -> None:
    with _lock:
        _fails.pop(email, None)


def find_account(tenant, email: str) -> tuple[str, dict] | None:
    """-> ("admin" | "user", record) by e-mail (case-insensitive)."""
    email = email.strip().lower()
    for a in tenant.admins.values():
        if a.get("email", "").lower() == email:
            return "admin", a
    for u in tenant.users.values():
        if u.get("email", "").lower() == email:
            return "user", u
    return None
