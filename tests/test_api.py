import pytest
from fastapi.testclient import TestClient

from dr.connector.sync import Connector
from dr.core import answer
from dr.core.pgindex import PgSearchIndex, tsv_literal
from dr.db import pg
from dr.gateway import app as appmod
from dr.ingest.chunker import fold
from dr.security import ratelimit
from dr.tenant.service import FakeTenant
from tests.mini_tenant import TEST_PASSWORD, make_tenant
from tests.test_gates import stub_llm


@pytest.fixture()
def client(db, tmp_path):
    tenant = FakeTenant(make_tenant(tmp_path), group_lag=60)
    conn = Connector(tenant)
    conn.full_resync()
    with pg.admin() as c:
        for iid, site, ctag in c.execute("SELECT item_id, site_id, ctag FROM items").fetchall():
            text = tenant.download(iid).decode()
            c.execute("INSERT INTO chunks(item_id, site_id, ctag, ordinal, locator, text, text_folded, converter, "
                      "tsv, tlen) VALUES (%s,%s,%s,0,'Đầu văn bản',%s,%s,'text',%s::tsvector,%s)",
                      (iid, site, ctag, text, fold(text), *tsv_literal(text)))
            c.execute("UPDATE items SET status='indexed', chunk_count=1 WHERE item_id=%s", (iid,))
        c.commit()
    S = appmod.S
    S.tenant, S.connector, S.index = tenant, conn, PgSearchIndex()  # the app default
    S.index.refresh()
    S.deps = answer.Deps(llm=stub_llm)
    ratelimit.limiter.reset()
    return TestClient(appmod.app)  # no lifespan: state injected above


def login(client, oid):
    r = client.post("/api/auth/login", json={"email": f"{oid}@test.example", "password": TEST_PASSWORD})
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_scope_matches_sharepoint(client):
    h = login(client, "inv-a1")
    sc = client.get("/api/scope", headers=h).json()
    ids = {f["item_id"] for s in sc["sites"] for fo in s["folders"] for f in fo["files"]}
    t = appmod.S.tenant
    assert ids == {i for i in t.items if t.sp_can_read("inv-a1", i)}
    assert sc["violations_ai_without_sharepoint"] == []
    statuses = {f["item_id"]: f["status"] for s in sc["sites"] for fo in s["folders"] for f in fo["files"]}
    assert statuses["x1"] == "excluded" and statuses["a1"] == "ai_ok"


def test_admin_endpoints_protected(client):
    h = login(client, "inv-a1")
    assert client.get("/api/matrix", headers=h).status_code == 403
    assert client.post("/api/scenario/reset", headers=h).status_code == 403
    ha = login(client, "admin")
    assert client.get("/api/matrix", headers=ha).status_code == 200


def test_open_requires_sharepoint_permission(client):
    tok = login(client, "inv-b1")["Authorization"].split()[1]
    assert client.get("/open/a1", params={"t": tok}).status_code == 403
    assert client.get("/open/b1", params={"t": tok}).status_code == 200


def test_offboard_scenario_blocks_existing_token(client):
    h = login(client, "inv-b1")
    ha = login(client, "admin")
    assert client.post("/api/scenario/offboard", headers=ha, json={"params": {"oid": "inv-b1"}}).status_code == 200
    appmod.S.connector.poll_once()
    r = client.post("/api/chat", headers=h, json={"question": "bảo lãnh tỷ giá"}).json()
    assert r["refused"]


def test_remove_from_group_scenario(client):
    h = login(client, "inv-ab")
    ha = login(client, "admin")
    client.post("/api/scenario/remove_from_group", headers=ha, json={"params": {"oid": "inv-ab", "group": "DR-INV-A"}})
    appmod.S.connector.poll_once()
    sc = client.get("/api/scope", headers=h).json()
    statuses = {f["item_id"]: f["status"] for s in sc["sites"] for fo in s["folders"] for f in fo["files"]}
    assert statuses.get("a1") == "ai_blocked"   # SharePoint still lets them open it (lag), AI does not
    assert statuses.get("b1") == "ai_ok"


def test_login_wrong_password_and_lockout(client):
    for _ in range(5):
        r = client.post("/api/auth/login", json={"email": "inv-c1@test.example", "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "inv-c1@test.example", "password": TEST_PASSWORD})
    assert r.status_code == 429


def test_demo_accounts_has_no_secrets(client):
    data = client.get("/api/auth/demo-accounts").json()
    assert data and all("pw" not in a and "password" not in a for a in data)


def test_admin_grant_and_revoke_via_api(client):
    ha, hb = login(client, "admin"), login(client, "inv-b1")
    # GRP-A has RAC: a direct grant alone is not enough, so grant on a COMMON file B cannot see yet
    r = client.post("/api/admin/grants", headers=ha, json={"target": "item", "site": "COMMON", "key": "c1",
                                                           "kind": "group", "id": "DR-INV-B", "add": False})
    assert r.status_code == 200
    sc = client.get("/api/scope", headers=hb).json()
    assert "c1" not in {f["item_id"] for s in sc["sites"] for fo in s["folders"] for f in fo["files"]}
    tree = client.get("/api/admin/tree/COMMON", headers=ha).json()
    f = next(x for fo in tree["folders"] for x in fo["files"] if x["item_id"] == "c1")
    assert f["unique"] and "DR-INV-B" not in {g["id"] for g in f["grants"]}
    client.post("/api/admin/grants/inherit", headers=ha, json={"target": "item", "site": "COMMON", "key": "c1"})
    sc = client.get("/api/scope", headers=hb).json()
    assert "c1" in {f["item_id"] for s in sc["sites"] for fo in s["folders"] for f in fo["files"]}


def test_admin_disable_user_blocks_login(client):
    ha = login(client, "admin")
    client.post("/api/admin/users/inv-b1/enabled", headers=ha, json={"enabled": False})
    r = client.post("/api/auth/login", json={"email": "inv-b1@test.example", "password": TEST_PASSWORD})
    assert r.status_code == 403


def test_admin_create_user(client):
    ha = login(client, "admin")
    r = client.post("/api/admin/users", headers=ha, json={"name": "Nhà đầu tư mới", "email": "moi@quy.example",
                                                          "roles": ["Investor.AI"], "groups": ["DR-INV-C"],
                                                          "password": "a-long-password"})
    assert r.status_code == 200
    r = client.post("/api/auth/login", json={"email": "moi@quy.example", "password": "a-long-password"})
    assert r.status_code == 200


def test_investor_cannot_call_admin(client):
    hb = login(client, "inv-b1")
    assert client.get("/api/admin/directory", headers=hb).status_code == 403


def test_crop_follows_sharepoint_permission(client, tmp_path, monkeypatch):
    from PIL import Image
    from dr.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    key = "a" * 40
    d = tmp_path / "cache" / "ocr" / key
    d.mkdir(parents=True)
    Image.new("RGB", (400, 600), "white").save(d / "p1.jpg")
    (d / "p1.json").write_text("[]")
    with pg.admin() as c:
        c.execute("UPDATE chunks SET ocr = true, ocr_page = %s WHERE item_id = 'a1'", (f"{key}/p1",))
        c.commit()
    ta = login(client, "inv-a1")["Authorization"].split()[1]
    tb = login(client, "inv-b1")["Authorization"].split()[1]
    q = {"page": f"{key}/p1", "box": "10,10,200,200"}
    r = client.get("/crop/a1", params={"t": ta, **q})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert client.get("/crop/a1", params={"t": tb, **q}).status_code == 403      # SharePoint says no
    assert client.get("/crop/b1", params={"t": tb, **q}).status_code == 404      # page is not b1's
    assert client.get("/crop/a1", params={"t": ta, "page": "../../etc/p1"}).status_code == 404


def test_chat_rate_limited(client):
    h = login(client, "inv-a1")
    codes = [client.post("/api/chat", headers=h, json={"question": "phí thu xếp"}).status_code for _ in range(10)]
    assert codes[:8] == [200] * 8 and codes[8] == 429


def test_auth_config_demo_mode(client):
    assert client.get("/api/auth/config").json() == {"mode": "demo"}


def test_citations_carry_no_web_url_in_demo(client):
    h = login(client, "inv-a1")
    r = client.post("/api/chat", headers=h, json={"question": "phí thu xếp nhóm A"}).json()
    assert not r["refused"] and all(c["web_url"] is None for c in r["citations"])
