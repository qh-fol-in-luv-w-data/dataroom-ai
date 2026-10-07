import json
import time

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from dr.m365.auth import AuthError, b64url
from dr.m365.entra_auth import EntraValidator

TID, API = "tid-1", "api-client"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks(key=KEY, kid="k1"):
    n = key.public_key().public_numbers()
    to = lambda i: b64url(i.to_bytes((i.bit_length() + 7) // 8, "big"))
    return {"keys": [{"kty": "RSA", "kid": kid, "n": to(n.n), "e": to(n.e)}]}


def token(key=KEY, kid="k1", **over):
    now = int(time.time())
    claims = {"iss": f"https://login.microsoftonline.com/{TID}/v2.0", "tid": TID, "aud": API, "oid": "u1",
              "scp": "Chat.Use", "roles": ["Investor.AI"], "name": "Nguyễn Văn An", "exp": now + 600, "nbf": now - 5,
              **over}
    h = b64url(json.dumps({"alg": "RS256", "kid": kid}).encode())
    p = b64url(json.dumps(claims).encode())
    s = key.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{h}.{p}.{b64url(s)}"


@pytest.fixture()
def v():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, json=jwks())
    val = EntraValidator(TID, [API, f"api://{API}"], http=httpx.Client(transport=httpx.MockTransport(handler)))
    val.calls = calls
    return val


def test_valid_token(v):
    c = v.validate(token())
    assert c["oid"] == "u1" and c["roles"] == ["Investor.AI"] and not c["admin"]
    v.validate(token(aud=f"api://{API}"))
    assert len(v.calls) == 1                                 # keys are cached


def test_admin_role_flag(v):
    c = v.validate(token(roles=["DataRoom.AIAdmin"]))
    assert c["admin"] and c["roles"] == []


@pytest.mark.parametrize("over,msg", [
    ({"aud": "someone-else"}, "not for this API"),
    ({"exp": int(time.time()) - 3600}, "expired"),
    ({"scp": "User.Read"}, "missing scope"),
    ({"tid": "other-tenant"}, "issuer"),
    ({"iss": "https://evil.example/v2.0"}, "issuer"),
])
def test_rejects_bad_claims(v, over, msg):
    with pytest.raises(AuthError, match=msg):
        v.validate(token(**over))


def test_rejects_forged_signature(v):
    with pytest.raises(AuthError, match="bad signature"):
        v.validate(token(key=OTHER))


def test_unknown_key_id_refreshes_once_then_fails(v):
    v.validate(token())
    with pytest.raises(AuthError, match="unknown signing key"):
        v.validate(token(kid="k-rotated"))


def test_rejects_garbage(v):
    h, p, s = token().split(".")
    alg_none = b64url(json.dumps({"alg": "none", "kid": "k1"}).encode()) + "." + p + "."
    for t in ["", "abc", "a.b.c", alg_none, f"{h}.{p}.{b64url(b'x' * 256)}"]:
        with pytest.raises(AuthError):
            v.validate(t)
