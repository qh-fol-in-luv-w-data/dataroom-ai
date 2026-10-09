"""Demo sign-in: HMAC-signed tokens standing in for Entra ID access tokens.

A token carries oid + app roles as of sign-in (like an Entra access token) and expires
after TOKEN_TTL. Revocation does not depend on expiry: gate 4 re-checks the mirror
(deny list, roles, feed freshness) on every request.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from dr.config import settings

ADMIN_OID = "admin"


def _sign(body: bytes) -> str:
    return hmac.new(settings.token_secret.encode(), body, hashlib.sha256).hexdigest()


def issue(oid: str, roles: list[str], name: str) -> str:
    body = json.dumps({"oid": oid, "roles": roles, "name": name,
                       "exp": int(time.time()) + settings.token_ttl_seconds}, ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + _sign(body)


def verify(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    b64, sig = token.rsplit(".", 1)
    try:
        body = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
    except Exception:
        return None
    if not hmac.compare_digest(_sign(body), sig):
        return None
    claims = json.loads(body)
    if claims["exp"] < time.time():
        return None
    return claims


# ------------------------------------------------------------------ file tickets
# A link to a file must never carry the session token (URLs end up in history, logs and
# forwarded messages). The backend checks the user's access first and then hands out a
# ticket bound to that user, that file and a purpose, valid for a short time. "open" tickets
# are single-use; "crop" tickets (page images inside an answer) may be reused until expiry.
_used: dict[str, float] = {}


def issue_ticket(oid: str, item_id: str, purpose: str, ttl: int = 120) -> str:
    body = json.dumps({"k": "ticket", "oid": oid, "item": item_id, "p": purpose, "exp": int(time.time()) + ttl,
                       "n": base64.urlsafe_b64encode(hashlib.sha256(f"{time.time_ns()}{oid}".encode()).digest()[:9]).decode()},
                      separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + _sign(b"ticket|" + body)


def verify_ticket(ticket: str | None, item_id: str, purpose: str) -> dict | None:
    if not ticket or "." not in ticket:
        return None
    b64, sig = ticket.rsplit(".", 1)
    try:
        body = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
        claims = json.loads(body)
    except Exception:
        return None
    if not hmac.compare_digest(_sign(b"ticket|" + body), sig):
        return None
    now = time.time()
    if claims.get("k") != "ticket" or claims["item"] != item_id or claims["p"] != purpose or claims["exp"] < now:
        return None
    if purpose == "open":
        for n, exp in list(_used.items()):
            if exp < now:
                _used.pop(n, None)
        if claims["n"] in _used:
            return None
        _used[claims["n"]] = claims["exp"]
    return claims
