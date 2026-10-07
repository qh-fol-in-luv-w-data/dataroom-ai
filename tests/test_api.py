import pytest
from fastapi.testclient import TestClient

from dr.connector.sync import Connector
from dr.core import answer
from dr.core.index import SearchIndex
from dr.db import pg
from dr.gateway import app as appmod
from dr.ingest.chunker import fold
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
            c.execute("INSERT INTO chunks(item_id, site_id, ctag, ordinal, locator, text, text_folded, converter) "
                      "VALUES (%s,%s,%s,0,'Đầu văn bản',%s,%s,'text')", (iid, site, ctag, text, fold(text)))
            c.execute("UPDATE items SET status='indexed', chunk_count=1 WHERE item_id=%s", (iid,))
        c.commit()
    S = appmod.S
    S.tenant, S.connector, S.index = tenant, conn, SearchIndex()
    S.index.refresh()
    S.deps = answer.Deps(llm=stub_llm)
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
