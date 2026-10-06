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
