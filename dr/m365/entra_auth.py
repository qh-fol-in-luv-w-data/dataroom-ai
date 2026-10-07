"""Validate Entra ID access tokens for the AI API (gateway, master plan §4.4 L1).

RS256 signature against the tenant's published JWKS (cached, refreshed on an unknown key
id at most every 5 minutes), then: issuer = this tenant, audience = the AI API, not expired,
delegated scope `Chat.Use` present. App roles (Investor.AI, Staff.AI, …) come from the
`roles` claim; gate 4 still re-checks the mirror on every question.
"""
from __future__ import annotations

import base64
import json
import threading
import time

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from dr.m365.auth import AuthError


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class EntraValidator:
    def __init__(self, tenant_id: str, audiences: list[str], required_scope: str = "Chat.Use",
                 admin_role: str = "DataRoom.AIAdmin", http: httpx.Client | None = None,
                 authority: str = "https://login.microsoftonline.com", now=time.time, leeway: int = 60):
        self.tid = tenant_id
        self.audiences = set(audiences)
        self.scope = required_scope
        self.admin_role = admin_role
        self.http = http or httpx.Client(timeout=10)
        self.jwks_url = f"{authority}/{tenant_id}/discovery/v2.0/keys"
        self.issuers = {f"{authority}/{tenant_id}/v2.0", f"https://sts.windows.net/{tenant_id}/"}
        self.now = now
        self.leeway = leeway
        self._keys: dict[str, rsa.RSAPublicKey] = {}
        self._fetched = 0.0
        self._lock = threading.Lock()

    def _load_keys(self, force: bool = False) -> None:
        with self._lock:
            if self._keys and not force and self.now() - self._fetched < 86400:
                return
            if force and self.now() - self._fetched < 300:
                return
            r = self.http.get(self.jwks_url)
            r.raise_for_status()
            keys = {}
            for k in r.json().get("keys", []):
                if k.get("kty") == "RSA" and k.get("kid"):
                    n = int.from_bytes(_b64d(k["n"]), "big")
                    e = int.from_bytes(_b64d(k["e"]), "big")
                    keys[k["kid"]] = rsa.RSAPublicNumbers(e, n).public_key()
            self._keys, self._fetched = keys, self.now()

    def validate(self, token: str) -> dict:
        try:
            h64, p64, s64 = token.split(".")
            header, claims = json.loads(_b64d(h64)), json.loads(_b64d(p64))
        except ValueError as e:
            raise AuthError("malformed token") from e
        if header.get("alg") != "RS256":
            raise AuthError("unexpected token algorithm")
        self._load_keys()
        key = self._keys.get(header.get("kid"))
        if key is None:
            self._load_keys(force=True)
            key = self._keys.get(header.get("kid"))
        if key is None:
            raise AuthError("unknown signing key")
        try:
            key.verify(_b64d(s64), f"{h64}.{p64}".encode(), padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature as e:
            raise AuthError("bad signature") from e
        now = self.now()
        if claims.get("iss") not in self.issuers or claims.get("tid") != self.tid:
            raise AuthError("wrong issuer / tenant")
        if claims.get("aud") not in self.audiences:
            raise AuthError("token is not for this API")
        if claims.get("exp", 0) + self.leeway < now or claims.get("nbf", 0) - self.leeway > now:
            raise AuthError("token expired or not yet valid")
        if self.scope not in (claims.get("scp") or "").split():
            raise AuthError(f"missing scope {self.scope}")
        roles = list(claims.get("roles") or [])
        return {"oid": claims["oid"], "roles": [r for r in roles if r != self.admin_role],
                "name": claims.get("name") or claims.get("preferred_username") or claims["oid"],
                "upn": claims.get("preferred_username", ""), "exp": claims["exp"],
                "admin": self.admin_role in roles}
