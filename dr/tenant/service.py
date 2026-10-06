"""Fake SharePoint Online + Entra ID.

This is the *source of truth* for files, groups, roles and permissions, playing the
role Microsoft 365 plays in production. It deliberately reproduces the behaviours
the AI core has to cope with:

- Entra changes (group membership, account state, app roles) are visible to the
  connector immediately through ``entra_delta`` but SharePoint applies group
  membership changes only after ``group_lag`` seconds (Microsoft documents up to a day).
- ``get_item_as_user`` is the live check: SharePoint's own decision for that user now.
- "Anyone" / organisation links never grant an authenticated user anything here.
- Restricted Access Control (RAC): when a site has RAC on, a user also needs to be in
  one of the site's RAC groups, even if a link or direct grant exists.
"""
from __future__ import annotations

import copy
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from dr.config import settings


class TenantUnavailable(RuntimeError):
    pass


@dataclass
class Grant:
    kind: str   # group | user | link_specific | link_anyone | link_org
    id: str
    source: str = "inherited"


@dataclass
class Event:
    seq: int
    t: float
    kind: str
    data: dict = field(default_factory=dict)


class FakeTenant:
    def __init__(self, tenant_dir: Path | None = None, now_fn: Callable[[], float] = time.time,
                 group_lag: float | None = None):
        self.dir = Path(tenant_dir or settings.tenant_dir)
        self.now = now_fn
        self.group_lag = settings.group_lag_seconds if group_lag is None else group_lag
        self._lock = threading.RLock()
        self.entra_paused = False
        self.load()

    # ------------------------------------------------------------------ loading
    def load(self) -> None:
        with self._lock:
            raw = json.loads((self.dir / "tenant.json").read_text(encoding="utf-8"))
            self.raw = raw
            self.users = {u["oid"]: copy.deepcopy(u) for u in raw["users"]}
            self.groups = {g["id"]: {"name": g.get("name", g["id"]), "members": set(g["members"])}
                           for g in raw["groups"]}
            self.sites = {s["id"]: copy.deepcopy(s) for s in raw["sites"]}
            self.folders = {(f["site"], f["path"]): copy.deepcopy(f) for f in raw.get("folders", [])}
            self.items = {}
            for it in raw["items"]:
                it = copy.deepcopy(it)
                it.setdefault("version", 1)
                it.setdefault("ctag", f"c-{it['id']}-1")
                it.setdefault("etag", f"e-{it['id']}-1")
                it.setdefault("ai_use", "Excluded")
                it.setdefault("encrypted", False)
                it.setdefault("malware", False)
                it.setdefault("grants", [])
                it.setdefault("unique", False)
                it.setdefault("pending_versions", [])
                self.items[it["id"]] = it
            # SharePoint's view of group membership lags behind Entra.
            self._membership_changes: list[tuple[float, str, str, str]] = []  # (t, op, group, oid)
            self.entra_events: list[Event] = []
            self.drive_events: list[Event] = []
            self._snapshot_events()

    def _snapshot_events(self) -> None:
        t = self.now()
        for oid, u in self.users.items():
            self._entra(t, "user", oid=oid, enabled=u.get("enabled", True), roles=list(u.get("roles", [])))
        for gid, g in self.groups.items():
            for oid in sorted(g["members"]):
                self._entra(t, "member_add", group=gid, oid=oid)
        for site in self.sites.values():
            self.drive_events.append(Event(len(self.drive_events) + 1, t, "site", {
                "site_id": site["id"], "name": site["name"],
                "rac_groups": site.get("groups", []) if site.get("rac", False) else []}))
        for item_id in self.items:
            self._drive_upsert(item_id, t)

    def _entra(self, t: float, kind: str, **data) -> None:
        self.entra_events.append(Event(len(self.entra_events) + 1, t, kind, data))

    def _drive_upsert(self, item_id: str, t: float | None = None) -> None:
        it = self.items[item_id]
        self.drive_events.append(Event(len(self.drive_events) + 1, t or self.now(), "item", self.item_meta(item_id)))

    # ------------------------------------------------------------------ metadata
    def item_meta(self, item_id: str) -> dict:
        it = self.items[item_id]
        return {"item_id": it["id"], "site_id": it["site"], "path": it["path"], "name": it["name"],
                "ext": it["ext"], "ctag": it["ctag"], "etag": it["etag"], "ai_use": it["ai_use"],
                "label": it.get("label"), "encrypted": bool(it["encrypted"]), "malware": bool(it["malware"]),
                "size": self.file_path(item_id).stat().st_size if self.file_path(item_id).exists() else 0,
                "grants": [g.__dict__ for g in self.permissions(item_id)]}

    def file_path(self, item_id: str) -> Path:
        return self.dir / "files" / self.items[item_id]["file"]

    # ------------------------------------------------------------------ permissions
    def permissions(self, item_id: str) -> list[Grant]:
        """Resolved grants for an item: unique item grants, else nearest unique folder,
        else the site's groups. Sharing links are always added on top."""
        it = self.items[item_id]
        links = [Grant(g["kind"], g["id"], "link") for g in it["grants"] if g["kind"].startswith("link_")]
        if it["unique"]:
            base = [Grant(g["kind"], g["id"], "unique") for g in it["grants"] if not g["kind"].startswith("link_")]
            return base + links
        parts = it["path"].strip("/").split("/") if it["path"].strip("/") else []
        for i in range(len(parts), 0, -1):
            f = self.folders.get((it["site"], "/".join(parts[:i])))
            if f and f.get("unique"):
                src = f"folder:{'/'.join(parts[:i])}"
                return [Grant(g["kind"], g["id"], src) for g in f["grants"]] + links
        site = self.sites[it["site"]]
        return [Grant("group", gid, f"site:{site['id']}") for gid in site.get("groups", [])] + links

    def _sp_members(self, gid: str, now: float) -> set[str]:
        """Group membership as SharePoint sees it: Entra state minus changes still in flight."""
        members = set(self.groups[gid]["members"])
        for t, op, g, oid in reversed(self._membership_changes):
            if g != gid or t + self.group_lag <= now:
                continue
            # undo a change SharePoint has not applied yet
            if op == "remove":
                members.add(oid)
            else:
                members.discard(oid)
        return members

    def sp_can_read(self, oid: str, item_id: str, now: float | None = None) -> bool:
        now = self.now() if now is None else now
        with self._lock:
            u = self.users.get(oid)
            it = self.items.get(item_id)
            if not u or not it or not u.get("enabled", True):
                return False
            site = self.sites[it["site"]]
            if site.get("rac"):
                if not any(oid in self._sp_members(g, now) for g in site.get("groups", [])):
                    return False
            for g in self.permissions(item_id):
                if g.kind == "group" and oid in self._sp_members(g.id, now):
                    return True
                if g.kind in ("user", "link_specific") and g.id == oid:
                    return True
            return False

    def get_item_as_user(self, oid: str, item_id: str) -> tuple[int, dict | None]:
        """Live check (Graph GET driveItem with the user's delegated token)."""
        with self._lock:
            if item_id not in self.items:
                return 404, None
            if not self.sp_can_read(oid, item_id):
                return 403, None
            it = self.items[item_id]
            return 200, {"id": item_id, "ctag": it["ctag"], "etag": it["etag"], "ai_use": it["ai_use"],
                         "name": it["name"]}

    def download(self, item_id: str) -> bytes:
        return self.file_path(item_id).read_bytes()

    def entra_members(self, gid: str) -> set[str]:
        return set(self.groups[gid]["members"])

    # ------------------------------------------------------------------ delta feeds
    def entra_delta(self, cursor: int) -> tuple[list[Event], int]:
        with self._lock:
            if self.entra_paused:
                raise TenantUnavailable("Entra delta endpoint unavailable (simulated outage)")
            ev = self.entra_events[cursor:]
            return ev, len(self.entra_events)

    def drive_delta(self, cursor: int) -> tuple[list[Event], int]:
        with self._lock:
            ev = self.drive_events[cursor:]
            return ev, len(self.drive_events)

    # ------------------------------------------------------------------ mutations (scenarios)
    def remove_member(self, gid: str, oid: str) -> None:
        with self._lock:
            if oid in self.groups[gid]["members"]:
                self.groups[gid]["members"].discard(oid)
                t = self.now()
                self._membership_changes.append((t, "remove", gid, oid))
                self._entra(t, "member_remove", group=gid, oid=oid)

    def add_member(self, gid: str, oid: str) -> None:
        with self._lock:
            if oid not in self.groups[gid]["members"]:
                self.groups[gid]["members"].add(oid)
                t = self.now()
                self._membership_changes.append((t, "add", gid, oid))
                self._entra(t, "member_add", group=gid, oid=oid)

    def set_user_enabled(self, oid: str, enabled: bool) -> None:
        with self._lock:
            u = self.users[oid]
            u["enabled"] = enabled
            self._entra(self.now(), "user", oid=oid, enabled=enabled, roles=list(u.get("roles", [])))

    def set_roles(self, oid: str, roles: list[str]) -> None:
        with self._lock:
            u = self.users[oid]
            u["roles"] = list(roles)
            self._entra(self.now(), "user", oid=oid, enabled=u.get("enabled", True), roles=list(roles))

    def set_ai_use(self, item_id: str, value: str) -> None:
        with self._lock:
            it = self.items[item_id]
            it["ai_use"] = value
            it["etag"] = f"e-{item_id}-{it['version']}-{len(self.drive_events)}"
            self._drive_upsert(item_id)

    def publish_version(self, item_id: str) -> bool:
        """Replace the file with its next prepared version (e.g. a redacted copy)."""
        with self._lock:
            it = self.items[item_id]
            if not it["pending_versions"]:
                return False
            nxt = it["pending_versions"].pop(0)
            it["file"] = nxt["file"]
            it["version"] += 1
            it["ctag"] = f"c-{item_id}-{it['version']}"
            it["etag"] = f"e-{item_id}-{it['version']}"
            self._drive_upsert(item_id)
            return True

    def set_entra_paused(self, paused: bool) -> None:
        with self._lock:
            self.entra_paused = paused

    def membership_lag_status(self, now: float | None = None) -> list[dict]:
        now = self.now() if now is None else now
        out = []
        for t, op, g, oid in self._membership_changes:
            remaining = t + self.group_lag - now
            out.append({"op": op, "group": g, "oid": oid, "sharepoint_applies_in": max(0.0, round(remaining, 1))})
        return out
