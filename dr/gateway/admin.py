"""Permission administration (Data Room owner / tenant admin view).

Every change goes to the simulated SharePoint/Entra first (the source of truth), is saved,
audited, and then picked up by the connector exactly like a real tenant change — so the AI
core's gates (mirror, revocation set, live check, SharePoint lag) apply unchanged.
"""
from __future__ import annotations

import re
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dr import audit
from dr.db import pg
from dr.gateway.accounts import hash_password

ROLES = ["Investor.AI", "Investor.AI.Summarize", "Staff.AI", "Reviewer"]
AI_USE = ["Allowed", "OnPremOnly", "Excluded"]


class Enabled(BaseModel):
    enabled: bool


class Roles(BaseModel):
    roles: list[str]


class Member(BaseModel):
    oid: str
    add: bool


class NewUser(BaseModel):
    name: str
    email: str
    org: str = ""
    type: str = "guest"
    roles: list[str] = []
    groups: list[str] = []
    password: str


class GrantIn(BaseModel):
    target: str          # folder | item
    site: str
    key: str             # folder path or item id
    kind: str            # user | group
    id: str
    add: bool


class InheritIn(BaseModel):
    target: str
    site: str
    key: str


class SiteGroups(BaseModel):
    groups: list[str]


class AiUse(BaseModel):
    value: str



def build_router(state, admin_only: Callable, on_changes: Callable) -> APIRouter:
    r = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_only)])

    def commit(action: str, detail: dict) -> dict:
        state.tenant.save()
        audit.append("admin", "permission_change", {"action": action, **detail})
        ch = state.connector.poll_once()
        on_changes(ch)
        return {"ok": True, "action": action, "pending_sharepoint": state.tenant.membership_lag_status()}

    def groups_of(oid: str) -> list[str]:
        return sorted(g for g, v in state.tenant.groups.items() if oid in v["members"])

    @r.get("/directory")
    def directory():
        t = state.tenant
        users = [{"oid": u["oid"], "name": u["name"], "email": u.get("email", ""), "org": u.get("org", ""),
                  "type": u.get("type", "guest"), "enabled": u.get("enabled", True), "roles": u.get("roles", []),
                  "groups": groups_of(u["oid"])} for u in t.users.values()]
        groups = [{"id": g, "name": v["name"], "members": sorted(v["members"])} for g, v in t.groups.items()]
        sites = [{"id": s["id"], "name": s["name"], "groups": s.get("groups", []), "rac": s.get("rac", False)}
                 for s in t.sites.values()]
        with pg.admin() as c:
            deny = {r[0]: r[1] for r in c.execute("SELECT oid, reason FROM deny_list")}
            revs = [{"oid": r[0], "group": r[1]} for r in c.execute("SELECT oid, group_id FROM revocations")]
        return {"users": users, "groups": groups, "sites": sites, "roles": ROLES, "ai_use": AI_USE,
                "deny_list": deny, "revocations": revs, "pending_sharepoint": t.membership_lag_status()}


    @r.post("/users/{oid}/enabled")
    def set_enabled(oid: str, body: Enabled):
        if oid not in state.tenant.users:
            raise HTTPException(404, "Không có người dùng này")
        state.tenant.set_user_enabled(oid, body.enabled)
        return commit("user_enabled", {"oid": oid, "enabled": body.enabled})


    @r.post("/users/{oid}/roles")
    def set_roles(oid: str, body: Roles):
        if oid not in state.tenant.users:
            raise HTTPException(404, "Không có người dùng này")
        bad = set(body.roles) - set(ROLES)
        if bad:
            raise HTTPException(400, f"Vai trò không hợp lệ: {sorted(bad)}")
        state.tenant.set_roles(oid, body.roles)
        return commit("user_roles", {"oid": oid, "roles": body.roles})


    @r.post("/groups/{gid}/members")
    def member(gid: str, body: Member):
        if gid not in state.tenant.groups or body.oid not in state.tenant.users:
            raise HTTPException(404, "Không có nhóm hoặc người dùng này")
        (state.tenant.add_member if body.add else state.tenant.remove_member)(gid, body.oid)
        return commit("group_member", {"group": gid, "oid": body.oid, "add": body.add})


    @r.post("/users")
    def create_user(body: NewUser):
        if not re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+$", body.email):
            raise HTTPException(400, "Email không hợp lệ")
        if any(u.get("email", "").lower() == body.email.lower() for u in state.tenant.users.values()):
            raise HTTPException(400, "Email đã tồn tại")
        if len(body.password) < 8:
            raise HTTPException(400, "Mật khẩu tối thiểu 8 ký tự")
        base = re.sub(r"[^a-z0-9]+", "-", body.email.split("@")[0].lower()).strip("-") or "user"
        oid, n = f"usr-{base}", 1
        while oid in state.tenant.users:
            n += 1
            oid = f"usr-{base}-{n}"
        state.tenant.create_user({"oid": oid, "name": body.name.strip(), "email": body.email.strip(),
                                  "org": body.org.strip(), "type": body.type if body.type in ("guest", "member") else "guest",
                                  "roles": [x for x in body.roles if x in ROLES], "pw": hash_password(body.password)},
                                 [g for g in body.groups if g in state.tenant.groups])
        return commit("user_created", {"oid": oid, "email": body.email, "groups": body.groups, "roles": body.roles})

    # ------------------------------------------------------------- folders / files
    @r.get("/tree/{site}")
    def tree(site: str):
        t = state.tenant
        if site not in t.sites:
            raise HTTPException(404, "Không có site này")
        with pg.admin() as c:
            st = {row[0]: {"status": row[1], "chunks": row[2]} for row in
                  c.execute("SELECT item_id, status, chunk_count FROM items WHERE site_id=%s", (site,))}
        folders: dict[str, dict] = {}
        for iid, it in t.items.items():
            if it["site"] != site:
                continue
            path = it["path"]
            if path not in folders:
                unique, grants = t.folder_grants(site, path)
                folders[path] = {"path": path, "unique": unique,
                                 "grants": [{"kind": g.kind, "id": g.id, "source": g.source} for g in grants],
                                 "files": []}
            perms = t.permissions(iid)
            folders[path]["files"].append({
                "item_id": iid, "name": it["name"], "ext": it["ext"], "ai_use": it["ai_use"],
                "label": it.get("label"), "encrypted": it["encrypted"], "malware": it["malware"],
                "unique": it["unique"], "grants": [{"kind": g.kind, "id": g.id, "source": g.source} for g in perms],
                **st.get(iid, {"status": "pending", "chunks": 0})})
        s = t.sites[site]
        return {"site": {"id": site, "name": s["name"], "groups": s.get("groups", []), "rac": s.get("rac", False)},
                "folders": sorted(folders.values(), key=lambda f: f["path"])}


    @r.post("/grants")
    def grant(body: GrantIn):
        t = state.tenant
        if body.site not in t.sites or body.target not in ("folder", "item") or body.kind not in ("user", "group"):
            raise HTTPException(400, "Tham số không hợp lệ")
        if body.kind == "user" and body.id not in t.users or body.kind == "group" and body.id not in t.groups:
            raise HTTPException(404, "Không có người dùng hoặc nhóm này")
        if body.target == "item" and body.key not in t.items:
            raise HTTPException(404, "Không có tài liệu này")
        t.set_grant(body.target, body.site, body.key, body.kind, body.id, body.add)
        return commit("grant", body.model_dump())


    @r.post("/grants/inherit")
    def inherit(body: InheritIn):
        state.tenant.restore_inheritance(body.target, body.site, body.key)
        return commit("restore_inheritance", body.model_dump())


    @r.post("/sites/{site}/groups")
    def site_groups(site: str, body: SiteGroups):
        t = state.tenant
        if site not in t.sites or set(body.groups) - set(t.groups):
            raise HTTPException(400, "Site hoặc nhóm không hợp lệ")
        t.set_site_groups(site, body.groups)
        return commit("site_groups", {"site": site, "groups": body.groups})


    @r.post("/items/{item_id}/ai_use")
    def ai_use(item_id: str, body: AiUse):
        if item_id not in state.tenant.items or body.value not in AI_USE:
            raise HTTPException(400, "Tham số không hợp lệ")
        state.tenant.set_ai_use(item_id, body.value)
        return commit("ai_use", {"item_id": item_id, "value": body.value})

    @r.post("/restore")
    def restore():
        state.tenant.load(original=True)
        audit.append("admin", "permission_change", {"action": "restore_original"})
        state.connector.full_resync()
        on_changes({"items_changed": list(state.tenant.items), "ctag_changed": [], "items_deleted": [], "entra_events": 1})
        return {"ok": True, "action": "restore_original"}

    return r
