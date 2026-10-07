"""GraphTenant: the real SharePoint Online + Entra ID behind the same interface as FakeTenant.

The connector, the four gates and the answer path run unchanged on top of it:
- drive_delta  : Graph drive delta per document library of each Data Room site, with
                 permissions, the AI_Use list field and the malware facet (app-only, Sites.Selected);
                 folder sharing changes re-resolve the folder's files.
- entra_delta  : snapshot diff every `entra_interval` seconds of the Data Room groups'
                 transitive members, the AI app's role assignments, account state, and
                 SharePoint site groups referenced by grants (SharePoint REST).
- get_item_as_user : the live check (gate 2) — OBO with the asking user's own token, read
                 the item's cTag, eTag and AI_Use as that user. No user token → fail closed.
- download     : app-only file content for ingestion.

Configuration (data/m365.json, not in git): see scripts/m365_probe.py --example-config.
Permission changes are made in SharePoint / Entra, never here (mutations raise).
"""
from __future__ import annotations

import contextvars
import logging
import threading
import time
from urllib.parse import quote

import httpx

from dr.m365.auth import AuthError, Credential, TokenProvider, jwt_claims
from dr.m365.graph import Graph, GraphError
from dr.tenant.service import Event, Grant, TenantUnavailable

log = logging.getLogger("m365")

# The asking user's Entra access token (audience = the AI API), set by the gateway per request.
USER_TOKEN: contextvars.ContextVar[str | None] = contextvars.ContextVar("dr_user_token", default=None)

DELTA_PREFER = {"Prefer": "deltashowremovedasdeleted, deltatraversepermissiongaps, deltashowsharingchanges, "
                          "hierarchicalsharing"}
READ_ONLY = "Quyền được quản trị trên SharePoint / Entra ID, không sửa từ AI core"
SEP = "~"


def item_key(drive_id: str, graph_id: str) -> str:
    return f"{drive_id}{SEP}{graph_id}"


class GraphTenant:
    def __init__(self, cfg: dict, http: httpx.Client | None = None, sleep=time.sleep, now_fn=time.time):
        self.cfg = cfg
        self.now = now_fn
        tid = cfg["tenant_id"]
        self.http = http or httpx.Client(timeout=60, follow_redirects=True)
        reader = TokenProvider(tid, Credential.from_config(cfg["reader"]), self.http)
        self.reader = reader
        self.directory = TokenProvider(tid, Credential.from_config(cfg.get("directory", cfg["reader"])), self.http)
        self.api = TokenProvider(tid, Credential.from_config(cfg["api"]), self.http) if cfg.get("api") else None
        self.graph = Graph(lambda: reader.app_token(), self.http, sleep=sleep)
        self.dir_graph = Graph(lambda: self.directory.app_token(), self.http, sleep=sleep)
        host = cfg.get("sharepoint_host")
        self.sp_scope = f"https://{host}/.default" if host else None
        self.ai_field = cfg.get("ai_use_field", "AI_Use")
        self.group_lag = float(cfg.get("sp_group_lag_seconds", 3600))
        self.entra_interval = float(cfg.get("entra_interval_seconds", 60))
        self.entra_paused = False
        self.admins: dict = {}
        self.users: dict[str, dict] = {}
        self.groups = {gid: {"name": name, "members": set()} for gid, name in cfg.get("groups", {}).items()}
        self.sites = {s["key"]: {"id": s["key"], "name": s.get("name", s["key"]), "graph_id": s["site_id"],
                                 "url": s.get("url"), "groups": list(s.get("rac_groups", [])),
                                 "rac": bool(s.get("rac_groups"))} for s in cfg["sites"]}
        self.items: dict[str, dict] = {}
        self._drives: dict[str, list[str]] = {}
        self._sp_groups: dict[str, tuple[str, int]] = {}      # pseudo group id -> (site key, SP group id)
        self._upn_oid: dict[str, str | None] = {}
        self._seq = 0
        self._last_entra = 0.0
        self._lock = threading.RLock()

    @classmethod
    def from_file(cls, path) -> "GraphTenant":
        import json
        from pathlib import Path
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    # ------------------------------------------------------------------ helpers
    def _ev(self, kind: str, data: dict) -> Event:
        self._seq += 1
        return Event(self._seq, self.now(), kind, data)

    def _site_drives(self, key: str) -> list[str]:
        if key not in self._drives:
            site = self.sites[key]
            only = self.cfg_site(key).get("drives")          # optional: restrict to named libraries
            ds = [d for d in self.graph.pages(f"sites/{site['graph_id']}/drives")
                  if d.get("driveType") == "documentLibrary" and (not only or d.get("name") in only)]
            self._drives[key] = [d["id"] for d in ds]
        return self._drives[key]

    def cfg_site(self, key: str) -> dict:
        return next(s for s in self.cfg["sites"] if s["key"] == key)

    def _loc(self, item_id: str) -> tuple[str, str]:
        drive, _, gid = item_id.partition(SEP)
        if not gid:
            raise KeyError(item_id)
        return drive, gid

    # ------------------------------------------------------------------ permissions
    def _grants(self, site_key: str, perms: list[dict]) -> list[dict]:
        out = []
        for p in perms:
            src = "inherited" if p.get("inheritedFrom") else "unique"
            link = p.get("link")
            if link:
                scope = link.get("scope")
                if scope == "anonymous":
                    out.append({"kind": "link_anyone", "id": p["id"], "source": "link"})
                elif scope == "organization":
                    out.append({"kind": "link_org", "id": p["id"], "source": "link"})
                else:                                        # "users" / "existingAccess"
                    who = p.get("grantedToIdentitiesV2") or ([p["grantedToV2"]] if p.get("grantedToV2") else [])
                    for ident in who:
                        if (ident.get("user") or {}).get("id"):
                            out.append({"kind": "link_specific", "id": ident["user"]["id"], "source": "link"})
                continue
            g = p.get("grantedToV2") or p.get("grantedTo") or {}
            if (g.get("group") or {}).get("id"):
                out.append({"kind": "group", "id": g["group"]["id"], "source": src})
            elif (g.get("siteGroup") or {}).get("id") is not None:
                pid = f"spgroup:{site_key}:{g['siteGroup']['id']}"
                self._sp_groups[pid] = (site_key, int(g["siteGroup"]["id"]))
                self.groups.setdefault(pid, {"name": g["siteGroup"].get("displayName", pid), "members": set()})
                out.append({"kind": "group", "id": pid, "source": src})
            elif (g.get("user") or {}).get("id"):
                out.append({"kind": "user", "id": g["user"]["id"], "source": src})
        return out

    def permissions(self, item_id: str) -> list[Grant]:
        return [Grant(g["kind"], g["id"], g["source"]) for g in self.items.get(item_id, {}).get("grants", [])]

    # ------------------------------------------------------------------ drive delta
    def _metas(self, site_key: str, drive_id: str, files: list[dict]) -> list[dict]:
        """Permissions + AI_Use for a page of files, two requests per file in $batch."""
        reqs = []
        for f in files:
            base = f"/drives/{drive_id}/items/{f['id']}"
            reqs.append({"id": f"p{f['id']}", "method": "GET", "url": f"{base}/permissions"})
            reqs.append({"id": f"f{f['id']}", "method": "GET",
                         "url": f"{base}/listItem?$expand=fields($select={self.ai_field})"})
        res = self.graph.batch(reqs) if reqs else {}
        out = []
        for f in files:
            pr, fr = res.get(f"p{f['id']}", {}), res.get(f"f{f['id']}", {})
            if pr.get("status") != 200:
                raise TenantUnavailable(f"permissions {f['id']}: {pr.get('status')}")
            perms = list((pr.get("body") or {}).get("value", []))
            nxt = (pr.get("body") or {}).get("@odata.nextLink")
            if nxt:
                perms += list(self.graph.pages(nxt))
            fields = ((fr.get("body") or {}).get("fields") or {}) if fr.get("status") == 200 else {}
            name = f.get("name", "")
            path = (f.get("parentReference") or {}).get("path", "")
            path = path.split("root:", 1)[1].strip("/") if "root:" in path else ""
            iid = item_key(drive_id, f["id"])
            meta = {"item_id": iid, "site_id": site_key, "path": path, "name": name,
                    "ext": name.rsplit(".", 1)[-1].lower() if "." in name else "",
                    "ctag": f.get("cTag") or f.get("eTag", ""), "etag": f.get("eTag", ""),
                    "ai_use": fields.get(self.ai_field) or "Excluded", "label": None,
                    "encrypted": False,     # decided on the downloaded bytes (ingest safety check)
                    "malware": "malware" in f, "size": int(f.get("size") or 0),
                    "grants": self._grants(site_key, perms)}
            self.items[iid] = {**meta, "id": iid, "site": site_key, "web_url": f.get("webUrl"),
                               "title": name, "unique": any(g["source"] == "unique" for g in meta["grants"])}
            out.append(meta)
        return out

    def _descendant_files(self, drive_id: str, folder_id: str) -> list[dict]:
        files, stack = [], [folder_id]
        while stack:
            fid = stack.pop()
            for c in self.graph.pages(f"drives/{drive_id}/items/{fid}/children"):
                (stack.append(c["id"]) if "folder" in c else files.append(c))
        return files

    def drive_delta(self, cursor) -> tuple[list[Event], dict]:
        state = dict(cursor) if isinstance(cursor, dict) else {}
        first = not state
        events: list[Event] = []
        try:
            with self._lock:
                if first:
                    for key, s in self.sites.items():
                        events.append(self._ev("site", {"site_id": key, "name": s["name"],
                                                        "rac_groups": s["groups"] if s["rac"] else []}))
                for key in self.sites:
                    for drive_id in self._site_drives(key):
                        link = state.get(drive_id) or f"drives/{drive_id}/root/delta"
                        changed, state[drive_id] = self.graph.delta(link, headers=DELTA_PREFER)
                        files = []
                        for di in changed:
                            if "deleted" in di:
                                iid = item_key(drive_id, di["id"])
                                if self.items.pop(iid, None) is not None or not first:
                                    events.append(self._ev("item_deleted", {"item_id": iid}))
                            elif "root" in di:
                                continue
                            elif "folder" in di:
                                if not first:      # sharing on a folder changed: its files' readers changed
                                    files += self._descendant_files(drive_id, di["id"])
                            elif "file" in di:
                                files.append(di)
                        seen = {}
                        for f in files:
                            seen[f["id"]] = f
                        batch = list(seen.values())
                        for i in range(0, len(batch), 10):
                            for meta in self._metas(key, drive_id, batch[i:i + 10]):
                                events.append(self._ev("item", meta))
        except (GraphError, AuthError, httpx.HTTPError) as e:
            raise TenantUnavailable(f"drive delta: {e}") from e
        return events, state

    # ------------------------------------------------------------------ Entra snapshot diff
    def _members(self, gid: str) -> set[str]:
        return {m["id"] for m in self.dir_graph.pages(f"groups/{gid}/transitiveMembers/microsoft.graph.user",
                                                      params={"$select": "id"})}

    def _oid_for_login(self, login: str) -> set[str]:
        """SharePoint LoginName → Entra user oids (users, security groups, M365 groups)."""
        parts = login.split("|")
        if login.startswith("i:0#.f|membership|"):
            upn = parts[-1]
            if upn not in self._upn_oid:
                try:
                    self._upn_oid[upn] = self.dir_graph.get(f"users/{quote(upn)}", params={"$select": "id"})["id"]
                except GraphError:
                    self._upn_oid[upn] = None
            return {self._upn_oid[upn]} if self._upn_oid[upn] else set()
        if login.startswith("c:0t.c|tenant|") or login.startswith("c:0o.c|federateddirectoryclaimprovider|"):
            gid = parts[-1].removesuffix("_o")
            return self._members(gid)
        return set()                     # "Everyone", "Everyone except external users": never expanded

    def _sp_group_members(self, site_key: str, sp_id: int) -> set[str]:
        url = self.sites[site_key].get("url")
        if not url or not self.sp_scope:
            raise TenantUnavailable(f"SharePoint group {sp_id} on {site_key}: site url / host not configured")
        token = self.reader.app_token(self.sp_scope)
        r = self.graph.request("GET", f"{url}/_api/web/sitegroups/getbyid({sp_id})/users", token=token,
                               headers={"Accept": "application/json;odata=nometadata"})
        if r.status_code != 200:
            raise TenantUnavailable(f"SharePoint group {sp_id}: {r.status_code}")
        out: set[str] = set()
        for u in r.json().get("value", []):
            out |= self._oid_for_login(u.get("LoginName", ""))
        return out

    def _roles(self) -> dict[str, set[str]]:
        sp, roles = self.cfg.get("ai_app_sp_id"), self.cfg.get("app_roles", {})
        out: dict[str, set[str]] = {}
        if not sp:
            return out
        for a in self.dir_graph.pages(f"servicePrincipals/{sp}/appRoleAssignedTo"):
            name = roles.get(a.get("appRoleId"))
            if not name:
                continue
            oids = {a["principalId"]} if a.get("principalType") == "User" else \
                self._members(a["principalId"]) if a.get("principalType") == "Group" else set()
            for o in oids:
                out.setdefault(o, set()).add(name)
        return out

    def _user_info(self, oids: set[str]) -> dict[str, dict]:
        reqs = [{"id": o, "method": "GET",
                 "url": f"/users/{o}?$select=id,displayName,mail,userPrincipalName,accountEnabled,companyName"}
                for o in sorted(oids)]
        res = self.dir_graph.batch(reqs) if reqs else {}
        info = {}
        for o in oids:
            r = res.get(o, {})
            b = r.get("body") or {}
            if r.get("status") == 200:
                upn = b.get("userPrincipalName", "")
                info[o] = {"oid": o, "name": b.get("displayName") or upn, "email": b.get("mail") or upn,
                           "org": b.get("companyName") or "", "type": "guest" if "#EXT#" in upn else "member",
                           "enabled": bool(b.get("accountEnabled"))}
            elif r.get("status") == 404:          # deleted: treat as disabled
                info[o] = {"oid": o, "name": o, "email": "", "org": "", "type": "guest", "enabled": False}
            else:
                raise TenantUnavailable(f"user {o}: {r.get('status')}")
        return info

    def entra_delta(self, cursor) -> tuple[list[Event], dict]:
        state = dict(cursor) if isinstance(cursor, dict) else {}
        if self.entra_paused:
            raise TenantUnavailable("Entra feed paused")
        if state and self.now() - self._last_entra < self.entra_interval:
            return [], state                      # nothing new until the next snapshot
        events: list[Event] = []
        try:
            with self._lock:
                members = {gid: self._members(gid) for gid in self.cfg.get("groups", {})}
                for pid, (site, sp_id) in list(self._sp_groups.items()):
                    members[pid] = self._sp_group_members(site, sp_id)
                roles = self._roles()
                tracked = set(roles) | {o for ms in members.values() for o in ms}
                info = self._user_info(tracked | set(state.get("users", {})))
                old_users = state.get("users", {})
                for oid, u in info.items():
                    r = sorted(roles.get(oid, set()))
                    if old_users.get(oid) != [u["enabled"], r]:
                        events.append(self._ev("user", {"oid": oid, "enabled": u["enabled"], "roles": r}))
                    self.users[oid] = {**u, "roles": r}
                old_m = {g: set(v) for g, v in state.get("members", {}).items()}
                for gid, ms in members.items():
                    prev = old_m.get(gid, set())
                    for oid in sorted(ms - prev):
                        events.append(self._ev("member_add", {"group": gid, "oid": oid}))
                    for oid in sorted(prev - ms):
                        events.append(self._ev("member_remove", {"group": gid, "oid": oid}))
                    self.groups.setdefault(gid, {"name": gid, "members": set()})["members"] = set(ms)
                state = {"users": {o: [u["enabled"], sorted(roles.get(o, set()))] for o, u in info.items()},
                         "members": {g: sorted(v) for g, v in members.items()}}
                self._last_entra = self.now()
        except (GraphError, AuthError, httpx.HTTPError) as e:
            raise TenantUnavailable(f"entra snapshot: {e}") from e
        return events, state

    # ------------------------------------------------------------------ live check, content
    def get_item_as_user(self, oid: str, item_id: str) -> tuple[int, dict | None]:
        token = USER_TOKEN.get()
        if not token or not self.api:
            raise TenantUnavailable("no user token for the live check")
        if jwt_claims(token).get("oid") != oid:
            raise TenantUnavailable("user token does not belong to this principal")
        drive, gid = self._loc(item_id)
        try:
            g = self.api.obo_token(token)
        except AuthError as e:
            raise TenantUnavailable(f"OBO: {e}") from e
        r = self.graph.request("GET", f"drives/{drive}/items/{gid}", token=g,
                               params={"$select": "id,cTag,eTag,name",
                                       "$expand": f"listItem($expand=fields($select={self.ai_field}))"})
        if r.status_code in (401, 403):
            return 403, None
        if r.status_code == 404:
            return 404, None
        if r.status_code != 200:
            raise TenantUnavailable(f"live check {r.status_code}")
        d = r.json()
        fields = (d.get("listItem") or {}).get("fields") or {}
        return 200, {"id": item_id, "ctag": d.get("cTag") or d.get("eTag"), "etag": d.get("eTag"),
                     "ai_use": fields.get(self.ai_field) or "Excluded", "name": d.get("name")}

    def sp_can_read(self, oid: str, item_id: str, now: float | None = None) -> bool:
        """SharePoint's answer when the user's token is at hand; otherwise the mirror (RLS source)."""
        token = USER_TOKEN.get()
        if token and self.api and jwt_claims(token).get("oid") == oid:
            try:
                return self.get_item_as_user(oid, item_id)[0] == 200
            except TenantUnavailable:
                return False
        from dr.db import pg
        with pg.admin() as c:
            return c.execute("SELECT 1 FROM item_reader WHERE oid=%s AND item_id=%s LIMIT 1",
                             (oid, item_id)).fetchone() is not None

    def download(self, item_id: str) -> bytes:
        drive, gid = self._loc(item_id)
        r = self.graph.request("GET", f"drives/{drive}/items/{gid}/content")
        if r.status_code != 200:
            raise GraphError(r.status_code, r.text[:200], f"content {item_id}")
        return r.content

    def web_url(self, item_id: str) -> str | None:
        return self.items.get(item_id, {}).get("web_url")

    def file_path(self, item_id: str):
        raise NotImplementedError("no local copy of SharePoint files (master plan §1.5)")

    def membership_lag_status(self, now: float | None = None) -> list[dict]:
        return []     # SharePoint's own lag is not observable; revocations cover it (§3.4)

    def load(self, original: bool = False) -> None:
        pass

    def save(self) -> None:
        pass

    def _read_only(self, *a, **k):
        raise NotImplementedError(READ_ONLY)

    remove_member = add_member = set_user_enabled = set_roles = set_ai_use = publish_version = _read_only
    set_grant = restore_inheritance = set_site_groups = create_user = folder_grants = _read_only

    def set_entra_paused(self, paused: bool) -> None:
        self.entra_paused = paused
