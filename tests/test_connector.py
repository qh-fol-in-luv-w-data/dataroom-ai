import pytest

from dr.connector.sync import Connector
from dr.db import pg
from dr.tenant.service import FakeTenant
from tests.mini_tenant import Clock, make_tenant


@pytest.fixture()
def env(db, tmp_path):
    clock = Clock()
    tenant = FakeTenant(make_tenant(tmp_path), now_fn=clock, group_lag=60)
    conn = Connector(tenant, now_fn=clock)
    conn.full_resync()
    return tenant, conn, clock


def readers():
    with pg.admin() as c:
        return {(r[0], r[1]) for r in c.execute("SELECT DISTINCT item_id, oid FROM item_reader")}


def test_mirror_matches_sharepoint(env):
    tenant, _, _ = env
    truth = {(i, u) for i in tenant.items for u in tenant.users if tenant.sp_can_read(u, i)}
    assert readers() == truth


def test_group_removal_applies_before_sharepoint(env):
    tenant, conn, _ = env
    tenant.remove_member("DR-INV-A", "inv-ab")
    conn.poll_once()
    r = readers()
    assert ("a1", "inv-ab") not in r          # AI side: revoked now
    assert tenant.sp_can_read("inv-ab", "a1")  # SharePoint side: still lagging
    assert ("b1", "inv-ab") in r              # other group's access kept
    assert ("c1", "inv-ab") in r              # COMMON via group B still fine


def test_disabled_user_removed(env):
    tenant, conn, _ = env
    tenant.set_user_enabled("inv-a1", False)
    conn.poll_once()
    assert not any(u == "inv-a1" for _, u in readers())
    with pg.admin() as c:
        assert c.execute("SELECT count(*) FROM deny_list WHERE oid='inv-a1'").fetchone()[0] == 1


def test_publish_version_invalidates_chunks(env):
    tenant, conn, _ = env
    with pg.admin() as c:
        c.execute("INSERT INTO chunks(item_id, site_id, ctag, ordinal, locator, text, text_folded, converter) "
                  "SELECT item_id, site_id, ctag, 0, 'p1', 'old text', 'old text', 't' FROM items WHERE item_id='a1'")
        c.commit()
    tenant.publish_version("a1")
    ch = conn.poll_once()
    assert "a1" in ch["ctag_changed"]
    with pg.admin() as c:
        assert c.execute("SELECT bool_or(is_current) FROM chunks WHERE item_id='a1'").fetchone()[0] is False


def test_entra_outage_freezes_feed(env):
    tenant, conn, _ = env
    with pg.admin() as c:
        before = c.execute("SELECT last_ok FROM feed_status WHERE feed='entra'").fetchone()[0]
    tenant.set_entra_paused(True)
    ch = conn.poll_once()
    assert ch["entra_ok"] is False
    with pg.admin() as c:
        after = c.execute("SELECT last_ok FROM feed_status WHERE feed='entra'").fetchone()[0]
    assert after == before


def test_exclude_deletes_chunks(env):
    tenant, conn, _ = env
    with pg.admin() as c:
        c.execute("INSERT INTO chunks(item_id, site_id, ctag, ordinal, locator, text, text_folded, converter) "
                  "SELECT item_id, site_id, ctag, 0, 'p1', 'x', 'x', 't' FROM items WHERE item_id='c1'")
        c.commit()
    tenant.set_ai_use("c1", "Excluded")
    conn.poll_once()
    with pg.admin() as c:
        assert c.execute("SELECT count(*) FROM chunks WHERE item_id='c1'").fetchone()[0] == 0
