import pytest

from dr.tenant.service import FakeTenant, TenantUnavailable
from tests.mini_tenant import Clock, make_tenant


@pytest.fixture()
def tenant(tmp_path):
    clock = Clock()
    t = FakeTenant(make_tenant(tmp_path), now_fn=clock, group_lag=60)
    t.clock = clock
    return t


def test_site_inheritance(tenant):
    assert tenant.sp_can_read("inv-a1", "a1")
    assert tenant.sp_can_read("inv-b1", "c1")
    assert not tenant.sp_can_read("inv-b1", "a1")
    assert not tenant.sp_can_read("inv-a1", "i1")
    assert tenant.sp_can_read("staff-1", "i1")


def test_unique_folder(tenant):
    assert tenant.sp_can_read("inv-a1", "a2")
    assert not tenant.sp_can_read("inv-ab", "a2")  # in group A but folder has unique perms


def test_links_and_rac(tenant):
    # specific-people link to inv-c1 on a GRP-B file, but RAC on GRP-B blocks C
    assert not tenant.sp_can_read("inv-c1", "b2")
    # an Anyone link never grants an authenticated user
    assert not tenant.sp_can_read("inv-a1", "b2")


def test_group_lag(tenant):
    tenant.remove_member("DR-INV-A", "inv-ab")
    ev, _ = tenant.entra_delta(0)
    assert ev[-1].kind == "member_remove"
    assert tenant.sp_can_read("inv-ab", "a1")       # SharePoint has not applied it yet
    tenant.clock.advance(61)
    assert not tenant.sp_can_read("inv-ab", "a1")
    assert tenant.sp_can_read("inv-ab", "b1")       # still in B


def test_publish_version_changes_ctag(tenant):
    old = tenant.items["a1"]["ctag"]
    _, cur = tenant.drive_delta(0)
    assert tenant.publish_version("a1")
    ev, _ = tenant.drive_delta(cur)
    assert ev and ev[-1].data["ctag"] != old
    assert "biên tập" in tenant.download("a1").decode()


def test_live_check(tenant):
    assert tenant.get_item_as_user("inv-b1", "a1") == (403, None)
    status, meta = tenant.get_item_as_user("inv-a1", "a1")
    assert status == 200 and meta["ai_use"] == "Allowed"
    assert tenant.get_item_as_user("inv-a1", "nope")[0] == 404


def test_disabled_user(tenant):
    tenant.set_user_enabled("inv-a1", False)
    assert not tenant.sp_can_read("inv-a1", "a1")


def test_grant_folder_breaks_inheritance(tenant):
    assert not tenant.sp_can_read("inv-b1", "a1")
    tenant.set_grant("folder", "GRP-A", "Tai-lieu", "user", "inv-b1", add=True)
    unique, grants = tenant.folder_grants("GRP-A", "Tai-lieu")
    assert unique and {"DR-INV-A", "inv-b1"} <= {g.id for g in grants}   # inherited copied + new
    assert not tenant.sp_can_read("inv-b1", "a1")       # RAC on GRP-A still blocks B
    tenant.sites["GRP-A"]["rac"] = False
    assert tenant.sp_can_read("inv-b1", "a1")
    tenant.restore_inheritance("folder", "GRP-A", "Tai-lieu")
    assert not tenant.sp_can_read("inv-b1", "a1")


def test_remove_group_grant_from_item(tenant):
    tenant.set_grant("item", "COMMON", "c1", "group", "DR-INV-B", add=False)
    assert not tenant.sp_can_read("inv-b1", "c1") and tenant.sp_can_read("inv-a1", "c1")


def test_create_user_and_save_reload(tenant):
    tenant.create_user({"oid": "inv-new", "name": "Mới", "email": "new@x.example", "type": "guest",
                        "roles": ["Investor.AI"]}, ["DR-INV-B"])
    assert not tenant.sp_can_read("inv-new", "b1")     # SharePoint lag on the new membership
    tenant.clock.advance(61)
    assert tenant.sp_can_read("inv-new", "b1")
    tenant.save()
    tenant.load()
    assert "inv-new" in tenant.users and "inv-new" in tenant.groups["DR-INV-B"]["members"]
    tenant.load(original=True)
    assert "inv-new" not in tenant.users


def test_entra_pause(tenant):
    tenant.set_entra_paused(True)
    with pytest.raises(TenantUnavailable):
        tenant.entra_delta(0)
