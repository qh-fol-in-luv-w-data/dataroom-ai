"""Entra ID tokens without extra dependencies: client credentials (certificate or secret)
and on-behalf-of (OBO) for the live check with the asking user's own identity.

Certificates: the app proves itself with a JWT client assertion signed RS256 by the private
key (master plan §6.1: keys live in the key store; here a PEM file path or PEM text).
"""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

GRAPH_SCOPE = "https://graph.microsoft.com/.default"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt_claims(token: str) -> dict:
    """Payload of a JWT *without* verifying it (only for tokens already validated upstream)."""
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


class AuthError(RuntimeError):
    pass


@dataclass
class Credential:
    client_id: str
    cert_pem: bytes | None = None        # certificate + private key (PEM)
    secret: str | None = None            # development only

    @classmethod
    def from_config(cls, d: dict) -> "Credential":
        pem = None
        if d.get("cert_path"):
            with open(d["cert_path"], "rb") as f:
                pem = f.read()
        elif d.get("cert_pem"):
            pem = d["cert_pem"].encode()
        return cls(d["client_id"], pem, d.get("secret"))


class TokenProvider:
    def __init__(self, tenant_id: str, cred: Credential, http: httpx.Client | None = None,
                 authority: str = "https://login.microsoftonline.com"):
        self.tenant_id = tenant_id
        self.cred = cred
        self.http = http or httpx.Client(timeout=20)
        self.token_url = f"{authority}/{tenant_id}/oauth2/v2.0/token"
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ client auth
    def _assertion(self) -> str:
        key = serialization.load_pem_private_key(self.cred.cert_pem, password=None)
        cert = x509.load_pem_x509_certificate(self.cred.cert_pem)
        der = cert.public_bytes(serialization.Encoding.DER)
        header = {"alg": "RS256", "typ": "JWT", "x5t#S256": b64url(hashlib.sha256(der).digest())}
        now = int(time.time())
        claims = {"aud": self.token_url, "iss": self.cred.client_id, "sub": self.cred.client_id,
                  "jti": str(uuid.uuid4()), "nbf": now - 60, "exp": now + 600}
        signing = b64url(json.dumps(header).encode()) + "." + b64url(json.dumps(claims).encode())
        sig = key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
        return signing + "." + b64url(sig)

    def _client_auth(self) -> dict:
        if self.cred.cert_pem:
            return {"client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                    "client_assertion": self._assertion()}
        if self.cred.secret:
            return {"client_secret": self.cred.secret}
        raise AuthError(f"app {self.cred.client_id}: no certificate or secret configured")

    def _post(self, form: dict, cache_key: str) -> str:
        with self._lock:
            hit = self._cache.get(cache_key)
            if hit and hit[1] - 120 > time.time():
                return hit[0]
        r = self.http.post(self.token_url, data={"client_id": self.cred.client_id, **form, **self._client_auth()})
        if r.status_code != 200:
            try:
                err = r.json()
                msg = f"{err.get('error')}: {err.get('error_description', '')[:200]}"
            except ValueError:
                msg = r.text[:200]
            raise AuthError(f"token request failed ({r.status_code}) {msg}")
        d = r.json()
        with self._lock:
            self._cache[cache_key] = (d["access_token"], time.time() + int(d.get("expires_in", 3600)))
        return d["access_token"]

    # ------------------------------------------------------------------ flows
    def app_token(self, scope: str = GRAPH_SCOPE) -> str:
        return self._post({"grant_type": "client_credentials", "scope": scope}, f"app|{scope}")

    def obo_token(self, user_assertion: str, scope: str = GRAPH_SCOPE) -> str:
        """Exchange the user's token (audience = this API) for a delegated Graph token."""
        key = "obo|" + scope + "|" + hashlib.sha256(user_assertion.encode()).hexdigest()
        return self._post({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                           "requested_token_use": "on_behalf_of", "assertion": user_assertion,
                           "scope": scope}, key)
