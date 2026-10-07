"""GraphTenant against an HTTP-level fake of Microsoft Graph, Entra token endpoint and
SharePoint REST: the real connector and gates run on top, only the network is simulated."""
import base64
import datetime as dt
import json
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from dr.connector.sync import Connector
from dr.core import gates
from dr.db import pg
from dr.m365.auth import Credential, TokenProvider, b64url
from dr.m365.tenant import USER_TOKEN, GraphTenant, item_key
from dr.tenant.service import TenantUnavailable

TID, SITE, DRIVE, SP = "tid-1", "host,s1,w1", "b!d1", "sp-ai"
ROLE_INV = "role-inv"


def cert_pem() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "dataroom-test")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()) + cert.public_bytes(serialization.Encoding.PEM)


def user_jwt(oid: str) -> str:
    return ".".join([b64url(b'{"alg":"none"}'), b64url(json.dumps({"oid": oid}).encode()), "x"])


def f(id_, name, folder="Hop-dong", ctag="c1"):
    return {"id": id_, "name": name, "file": {}, "cTag": ctag, "eTag": ctag + "e", "size": 10,
            "webUrl": f"https://host/sites/dr/{name}", "parentReference": {"path": f"/drives/{DRIVE}/root:/{folder}"}}


class FakeGraph:
    def __init__(self, pem: bytes):
        self.cert = x509.load_pem_x509_certificate(pem)
        self.groups = {"GA": {"u1", "u2"}, "GB": {"u3"}}
        self.roles = [("User", "u1", ROLE_INV), ("Group", "GB", ROLE_INV), ("User", "u4", ROLE_INV)]
        self.users = {"u1": True, "u2": True, "u3": True, "u4": False}
        self.files = {"fA": f("fA", "a.pdf"), "fB": f("fB", "b.pdf"), "fAny": f("fAny", "any.pdf"),
                      "fSpec": f("fSpec", "spec.pdf"), "fSp": f("fSp", "sp.pdf")}
        inh = {"grantedToV2": {"group": {"id": "GA"}}, "inheritedFrom": {"id": "root"}, "id": "p0"}
        self.perms = {
            "fA": [inh],
            "fB": [{"grantedToV2": {"group": {"id": "GB"}}, "id": "p1"}],
            "fAny": [inh, {"link": {"scope": "anonymous"}, "id": "l1"}, {"link": {"scope": "organization"}, "id": "l2"}],
            "fSpec": [inh, {"link": {"scope": "users"}, "id": "l3", "grantedToIdentitiesV2": [{"user": {"id": "u3"}}]}],
            "fSp": [{"grantedToV2": {"siteGroup": {"id": "5", "displayName": "DR Visitors"}}, "id": "p2"}],
        }
        self.ai = {"fA": "Allowed", "fB": "Allowed", "fSpec": "Allowed", "fSp": "OnPremOnly"}
        self.sp_group = ["i:0#.f|membership|u4@x.example", "c:0t.c|tenant|GB", "c:0(.s|true"]
        self.delta_pages = [list(self.files.values()) + [{"id": "root", "root": {}, "folder": {}}]]
        self.calls: list[str] = []
        self.fail_once: set[str] = set()

    # -- token endpoint
    def token(self, req: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        assertion = form.get("client_assertion")
        if assertion:                                    # verify the certificate-signed client assertion
            h, p, s = assertion.split(".")
            pad = lambda x: base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
            self.cert.public_key().verify(pad(s), f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
            claims = json.loads(pad(p))
            assert claims["aud"].endswith(f"/{TID}/oauth2/v2.0/token") and claims["iss"] == form["client_id"]
        elif form.get("client_secret") != "s3cret":
            return httpx.Response(401, json={"error": "invalid_client"})
        if form["grant_type"] == "client_credentials":
            return httpx.Response(200, json={"access_token": "app|" + form["scope"], "expires_in": 3600})
        oid = json.loads(base64.urlsafe_b64decode(form["assertion"].split(".")[1] + "=="))["oid"]
        return httpx.Response(200, json={"access_token": f"obo|{oid}", "expires_in": 3600})

    # -- graph
    def graph(self, method: str, path: str, query: dict, auth: str) -> tuple[int, dict | bytes]:
        if path == f"sites/{SITE}/drives":
            return 200, {"value": [{"id": DRIVE, "driveType": "documentLibrary", "name": "Documents"}]}
        if path == f"drives/{DRIVE}/root/delta":
            page = int(query.get("token", "0"))
            return 200, {"value": self.delta_pages[page] if page < len(self.delta_pages) else [],
                         "@odata.deltaLink": f"https://graph.microsoft.com/v1.0/drives/{DRIVE}/root/delta?token={page + 1}"}
        if path == f"drives/{DRIVE}/root/children":
            return 200, {"value": list(self.files.values())}
        m = re.fullmatch(rf"drives/{re.escape(DRIVE)}/items/([^/]+)(/.*)?", path)
        if m:
            iid, rest = m.group(1), m.group(2) or ""
            if rest == "/versions":
                return 200, {"value": [{"id": "1.0"}, {"id": "2.0"}]}
            if rest == "/content" and query.get("format") == "pdf":
                return 302, {"location": "https://westus-dm2.download.example/x.pdf"}
            if rest == "/permissions":
                return 200, {"value": self.perms[iid]}
            if rest == "/listItem":
                return 200, {"fields": {"AI_Use": self.ai[iid]} if iid in self.ai else {}}
            if rest == "/content":
                return 200, b"%PDF-1.4 fake"
            if rest == "" and auth.startswith("obo|"):     # live check as the user
                oid = auth.split("|")[1]
                readers = self.readers(iid)
                if oid not in readers:
                    return 403, {"error": {"code": "accessDenied"}}
                return 200, {"id": iid, "cTag": self.files[iid]["cTag"], "eTag": self.files[iid]["eTag"],
                             "name": self.files[iid]["name"], "listItem": {"fields": {"AI_Use": self.ai.get(iid)}}}
        m = re.fullmatch(r"groups/([^/]+)/transitiveMembers/microsoft.graph.user", path)
        if m:
            return 200, {"value": [{"id": o} for o in sorted(self.groups[m.group(1)])]}
        if path == f"servicePrincipals/{SP}/appRoleAssignedTo":
            return 200, {"value": [{"principalType": t, "principalId": p, "appRoleId": r} for t, p, r in self.roles]}
        m = re.fullmatch(r"users/([^/]+)", path)
        if m:
            key = unquote(m.group(1))
            if "@" in key:
                return 200, {"id": key.split("@")[0]}
            if key not in self.users:
                return 404, {"error": {"code": "Request_ResourceNotFound"}}
            return 200, {"id": key, "displayName": key.upper(), "userPrincipalName": f"{key}#EXT#@t",
                         "accountEnabled": self.users[key]}
        return 404, {"error": {"code": "notFound", "path": path}}

    def readers(self, iid: str) -> set[str]:
        out = set()
        for p in self.perms[iid]:
            g = p.get("grantedToV2") or {}
            if "group" in g:
                out |= self.groups[g["group"]["id"]]
            if p.get("link", {}).get("scope") == "users":
                out |= {i["user"]["id"] for i in p["grantedToIdentitiesV2"]}
        return out

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = req.url
        if url.host == "login.microsoftonline.com":
            return self.token(req)
        auth = req.headers.get("authorization", "").removeprefix("Bearer ")
        if "/_api/web/" in url.path and not url.path.endswith("/users"):
            assert auth == "app|https://host.example/.default"
            return httpx.Response(200, json={"value": []})
        if url.path.endswith("/_api/web/sitegroups/getbyid(5)/users"):
            assert auth == "app|https://host.example/.default"
            return httpx.Response(200, json={"value": [{"LoginName": x} for x in self.sp_group]})
        path = url.path.removeprefix("/v1.0/")
        self.calls.append(path)
        if path in self.fail_once:
            self.fail_once.discard(path)
            return httpx.Response(429, headers={"Retry-After": "1"})
        if path == "$batch":
            out = []
            for r in json.loads(req.content)["requests"]:
                u = urlparse(r["url"])
                st, body = self.graph("GET", u.path.lstrip("/"), {k: v[0] for k, v in parse_qs(u.query).items()}, auth)
                out.append({"id": r["id"], "status": st, "body": body})
            return httpx.Response(200, json={"responses": out})
        st, body = self.graph(req.method, path, {k: v for k, v in url.params.items()}, auth)
        if st == 302:
            return httpx.Response(302, headers={"location": body["location"]})
        return httpx.Response(st, content=body) if isinstance(body, bytes) else httpx.Response(st, json=body)


@pytest.fixture()
def m365(db):
    pem = cert_pem()
    fake = FakeGraph(pem)
    http = httpx.Client(transport=httpx.MockTransport(fake), follow_redirects=True)
    cfg = {"tenant_id": TID, "sharepoint_host": "host.example",
           "reader": {"client_id": "reader", "cert_pem": pem.decode()},
           "directory": {"client_id": "dir", "secret": "s3cret"},
           "api": {"client_id": "api", "cert_pem": pem.decode()},
           "ai_app_sp_id": SP, "app_roles": {ROLE_INV: "Investor.AI"},
           "groups": {"GA": "DR-INV-A", "GB": "DR-INV-B"},
           "sites": [{"key": "COMMON", "site_id": SITE, "name": "Data Room", "url": "https://host.example/sites/dr"}],
           "entra_interval_seconds": 0, "sp_group_lag_seconds": 120}
    sleeps = []
    tenant = GraphTenant(cfg, http=http, sleep=sleeps.append)
    return fake, tenant, Connector(tenant), sleeps


def readers(item: str) -> set[str]:
    with pg.admin() as c:
        return {r[0] for r in c.execute("SELECT oid FROM item_reader WHERE item_id=%s", (item_key(DRIVE, item),))}


def test_full_sync_builds_mirror_like_sharepoint(m365):
    fake, tenant, conn, _ = m365
    ch = conn.full_resync()
    assert ch["entra_ok"] and len(ch["items_changed"]) == 5
    assert readers("fA") == {"u1", "u2"}
    assert readers("fB") == {"u3"}
    assert readers("fAny") == {"u1", "u2"}                  # anyone / organisation links never expanded
    assert readers("fSpec") == {"u1", "u2", "u3"}           # specific-people link counts
    assert readers("fSp") == {"u3"}                         # SharePoint group → Entra group GB; u4 disabled
    with pg.admin() as c:
        ai = dict(c.execute("SELECT item_id, ai_use FROM items").fetchall())
        roles = set(c.execute("SELECT oid, role FROM user_roles").fetchall())
        denied = {r[0] for r in c.execute("SELECT oid FROM deny_list")}
    assert ai[item_key(DRIVE, "fAny")] == "Excluded"        # no AI_Use value means Excluded
    assert ai[item_key(DRIVE, "fSp")] == "OnPremOnly"
    assert ("u1", "Investor.AI") in roles and ("u3", "Investor.AI") in roles and not any(o == "u2" for o, _ in roles)
    assert "u4" in denied
    assert tenant.items[item_key(DRIVE, "fA")]["path"] == "Hop-dong"


def test_group_removal_revokes_and_version_change(m365):
    fake, tenant, conn, _ = m365
    conn.full_resync()
    fake.groups["GA"].discard("u2")
    fake.files["fA"] = f("fA", "a.pdf", ctag="c2")
    fake.delta_pages.append([fake.files["fA"]])
    ch = conn.poll_once()
    assert item_key(DRIVE, "fA") in ch["ctag_changed"]
    assert readers("fA") == {"u1"}
    with pg.admin() as c:
        assert c.execute("SELECT 1 FROM revocations WHERE oid='u2' AND group_id='GA'").fetchone()


def test_live_check_uses_users_own_token(m365):
    fake, tenant, conn, _ = m365
    conn.full_resync()
    a, b = item_key(DRIVE, "fA"), item_key(DRIVE, "fB")
    with pytest.raises(TenantUnavailable):                    # no user token → fail closed
        tenant.get_item_as_user("u1", a)
    tok = USER_TOKEN.set(user_jwt("u1"))
    try:
        st, meta = tenant.get_item_as_user("u1", a)
        assert st == 200 and meta["ai_use"] == "Allowed" and meta["ctag"] == "c1"
        assert tenant.get_item_as_user("u1", b)[0] == 403
        with pytest.raises(TenantUnavailable):                # token of someone else
            tenant.get_item_as_user("u3", b)
        res = gates.live_check(tenant, "u1", {a: "c1", b: "c1"})
        assert res[a][0] and not res[b][0]
    finally:
        USER_TOKEN.reset(tok)


def test_throttling_is_retried(m365):
    fake, tenant, conn, sleeps = m365
    fake.fail_once.add("$batch")
    conn.full_resync()
    assert sleeps == [1.0] and tenant.graph.throttled == 1
    assert readers("fB") == {"u3"}


def test_feed_failure_fails_closed(m365):
    fake, tenant, conn, _ = m365
    conn.full_resync()
    tenant.set_entra_paused(True)
    ch = conn.poll_once()
    assert not ch["entra_ok"] and "paused" in conn.last_error


def test_secret_and_bad_credentials():
    fake = FakeGraph(cert_pem())
    http = httpx.Client(transport=httpx.MockTransport(fake))
    ok = TokenProvider(TID, Credential("dir", secret="s3cret"), http)
    assert ok.app_token().startswith("app|")
    bad = TokenProvider(TID, Credential("dir", secret="wrong"), http)
    with pytest.raises(Exception, match="invalid_client"):
        bad.app_token()


def test_mutations_are_refused(m365):
    _, tenant, _, _ = m365
    with pytest.raises(NotImplementedError):
        tenant.remove_member("GA", "u1")


def test_integration_probe_runs_against_graph(m365):
    """scripts/m365_probe.py tests 1, 2 and 8 end to end on the HTTP fake."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("probe", "scripts/m365_probe.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    _, tenant, _, _ = m365
    f = probe.test1(tenant)
    assert probe.R["1"]["status"] == "PASS" and probe.R["1"]["versions"] == 2
    assert probe.R["1"]["format_pdf_redirect_host"] == "westus-dm2.download.example"
    probe.test2(tenant, f)
    assert probe.R["2"]["status"] == "PASS" and probe.R["2"]["rest_getchanges"] == 200
    probe.test8(tenant, f, n=5)
    assert probe.R["8"]["status"] == "PASS"
    probe.test3(tenant, f, None, None)
    assert probe.R["3"]["status"] == "SKIP"
