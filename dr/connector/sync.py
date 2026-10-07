"""Connector: polls the tenant's delta feeds and maintains the permission mirror.

Mirror tables (Postgres): sites, items, grants, memberships, user_roles, users_mirror,
revocations, deny_list, feed_status -> rebuilt into item_reader (the RLS source).

Security-relevant rules (master plan §3):
- Entra membership changes are applied immediately; a removal also records a
  per-(oid, group) revocation that excludes grant paths through that group until
  SharePoint is known to have applied the change.
- A ctag change marks the item's existing chunks non-current *now*, before re-ingest.
- AI_Use set to a non-AI value deletes the item's chunks.
- Anyone / organisation links are never expanded into readers.
- If a site has RAC groups, a reader must also be a (non-revoked) member of one of them.
- If the Entra feed fails, feed_status is not refreshed, so the gateway refuses
  questions once the feed is older than FEED_MAX_AGE (fail closed).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from psycopg.types.json import Jsonb  # noqa: F401  (kept for future payloads)

from dr.config import settings
from dr.db import pg
from dr.tenant.service import FakeTenant, TenantUnavailable

log = logging.getLogger("connector")

AI_VALUES = ("Allowed", "OnPremOnly")


class Connector:
    def __init__(self, tenant: FakeTenant, now_fn: Callable[[], float] = time.time):
        self.tenant = tenant
        self.now = now_fn
        self.drive_cursor = 0
        self.entra_cursor = 0
        self.last_error: str | None = None
        self._lock = threading.RLock()   # background thread and admin requests may both poll

    # ------------------------------------------------------------------ public
    def full_resync(self) -> dict:
        """Start from scratch (cursor 0) — used at startup and after a tenant reset."""
        with self._lock:
            return self._full_resync()

    def _full_resync(self) -> dict:
        self.drive_cursor = 0
        self.entra_cursor = 0
        with pg.admin() as c:
            c.execute("DELETE FROM memberships; DELETE FROM user_roles; DELETE FROM users_mirror; "
                      "DELETE FROM revocations; DELETE FROM deny_list; DELETE FROM grants;")
            c.commit()
        return self._poll(full=True)

    def poll_once(self, full: bool = False) -> dict:
        with self._lock:
            return self._poll(full)

    def _poll(self, full: bool) -> dict:
        changes = {"items_changed": [], "items_deleted": [], "ctag_changed": [], "entra_events": 0,
                   "drive_events": 0, "entra_ok": False}
        seen_items: set[str] = set()
        with pg.admin() as c:
            events, cur = self.tenant.drive_delta(self.drive_cursor)
            for ev in events:
                if ev.kind == "site":
                    d = ev.data
                    c.execute("INSERT INTO sites(site_id, name, rac_groups) VALUES (%s,%s,%s) "
                              "ON CONFLICT (site_id) DO UPDATE SET name=EXCLUDED.name, rac_groups=EXCLUDED.rac_groups",
                              (d["site_id"], d["name"], d["rac_groups"]))
                elif ev.kind == "item":
                    self._apply_item(c, ev.data, changes)
                    seen_items.add(ev.data["item_id"])
                elif ev.kind == "item_deleted":
                    c.execute("DELETE FROM items WHERE item_id=%s", (ev.data["item_id"],))
                    c.execute("DELETE FROM grants WHERE item_id=%s", (ev.data["item_id"],))
                    changes["items_deleted"].append(ev.data["item_id"])
            if full:
                # anything in the mirror the tenant no longer has is deleted
                gone = [r[0] for r in c.execute("SELECT item_id FROM items")
                        if r[0] not in self.tenant.items]
                for iid in gone:
                    c.execute("DELETE FROM items WHERE item_id=%s", (iid,))
                    c.execute("DELETE FROM grants WHERE item_id=%s", (iid,))
                    changes["items_deleted"].append(iid)
            self.drive_cursor = cur
            changes["drive_events"] = len(events)
            self._feed_ok(c, "drive")

            try:
                eevents, ecur = self.tenant.entra_delta(self.entra_cursor)
                for ev in eevents:
                    self._apply_entra(c, ev)
                self.entra_cursor = ecur
                changes["entra_events"] = len(eevents)
                changes["entra_ok"] = True
                self._feed_ok(c, "entra")
                self.last_error = None
            except TenantUnavailable as e:
                self.last_error = str(e)
                log.warning("entra feed unavailable: %s", e)

            c.execute("DELETE FROM revocations WHERE until < to_timestamp(%s)", (self.now(),))
            if full or events or changes["entra_events"]:
                self.rebuild_item_reader(c)
            c.commit()
        return changes

    def run_forever(self, stop: threading.Event, on_changes: Callable[[dict], None] | None = None) -> None:
        while not stop.is_set():
            try:
                ch = self.poll_once()
                if on_changes and (ch["items_changed"] or ch["items_deleted"] or ch["entra_events"]):
                    on_changes(ch)
            except Exception as e:  # keep polling; feed age will expose a stuck connector
                self.last_error = repr(e)
                log.exception("connector poll failed")
            stop.wait(settings.poll_seconds)

    # ------------------------------------------------------------------ helpers
    def _feed_ok(self, c, feed: str) -> None:
        c.execute("INSERT INTO feed_status(feed, last_ok) VALUES (%s, clock_timestamp()) "
                  "ON CONFLICT (feed) DO UPDATE SET last_ok = clock_timestamp()", (feed,))

    def _apply_item(self, c, d: dict, changes: dict) -> None:
        iid = d["item_id"]
        row = c.execute("SELECT ctag, etag, ai_use FROM items WHERE item_id=%s", (iid,)).fetchone()
        if row is None:
            c.execute("INSERT INTO items(item_id, site_id, path, name, ext, ctag, etag, ai_use, label, encrypted, "
                      "malware, size, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
                      (iid, d["site_id"], d["path"], d["name"], d["ext"], d["ctag"], d["etag"], d["ai_use"],
                       d.get("label"), d["encrypted"], d["malware"], d.get("size", 0)))
            changes["items_changed"].append(iid)
        else:
            old_ctag, old_etag, old_ai = row
            if old_ctag != d["ctag"]:
                # old version must stop being retrievable immediately
                c.execute("UPDATE chunks SET is_current=false WHERE item_id=%s", (iid,))
                changes["ctag_changed"].append(iid)
            if d["ai_use"] not in AI_VALUES or d["encrypted"] or d["malware"]:
                c.execute("DELETE FROM chunks WHERE item_id=%s", (iid,))
            status_reset = old_ctag != d["ctag"] or (old_ai not in AI_VALUES and d["ai_use"] in AI_VALUES)
            c.execute("UPDATE items SET site_id=%s, path=%s, name=%s, ext=%s, ctag=%s, etag=%s, ai_use=%s, label=%s, "
                      "encrypted=%s, malware=%s, size=%s, updated_at=now()"
                      + (", status='pending', reason=NULL" if status_reset else "") + " WHERE item_id=%s",
                      (d["site_id"], d["path"], d["name"], d["ext"], d["ctag"], d["etag"], d["ai_use"],
                       d.get("label"), d["encrypted"], d["malware"], d.get("size", 0), iid))
            if old_ctag != d["ctag"] or old_etag != d["etag"]:
                changes["items_changed"].append(iid)
        c.execute("DELETE FROM grants WHERE item_id=%s", (iid,))
        for g in d["grants"]:
            c.execute("INSERT INTO grants(item_id, principal_kind, principal_id, source) VALUES (%s,%s,%s,%s) "
                      "ON CONFLICT DO NOTHING", (iid, g["kind"], g["id"], g["source"]))

    def _apply_entra(self, c, ev) -> None:
        d = ev.data
        if ev.kind == "user":
            c.execute("INSERT INTO users_mirror(oid, enabled) VALUES (%s,%s) "
                      "ON CONFLICT (oid) DO UPDATE SET enabled=EXCLUDED.enabled", (d["oid"], d["enabled"]))
            c.execute("DELETE FROM user_roles WHERE oid=%s", (d["oid"],))
            for r in d["roles"]:
                c.execute("INSERT INTO user_roles(oid, role) VALUES (%s,%s) ON CONFLICT DO NOTHING", (d["oid"], r))
            if not d["enabled"]:
                c.execute("INSERT INTO deny_list(oid, reason) VALUES (%s,'account disabled') "
                          "ON CONFLICT (oid) DO NOTHING", (d["oid"],))
            else:
                c.execute("DELETE FROM deny_list WHERE oid=%s AND reason='account disabled'", (d["oid"],))
        elif ev.kind == "member_add":
            c.execute("INSERT INTO memberships(group_id, oid) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                      (d["group"], d["oid"]))
            c.execute("DELETE FROM revocations WHERE oid=%s AND group_id=%s", (d["oid"], d["group"]))
        elif ev.kind == "member_remove":
            c.execute("DELETE FROM memberships WHERE group_id=%s AND oid=%s", (d["group"], d["oid"]))
            until = self.now() + self.tenant.group_lag + 5
            c.execute("INSERT INTO revocations(oid, group_id, until) VALUES (%s,%s,to_timestamp(%s)) "
                      "ON CONFLICT (oid, group_id) DO UPDATE SET until=EXCLUDED.until",
                      (d["oid"], d["group"], until))

    @staticmethod
    def rebuild_item_reader(c) -> None:
        c.execute("DELETE FROM item_reader")
        c.execute("""
            INSERT INTO item_reader(item_id, oid, via_kind, via_id)
            SELECT g.item_id, m.oid, 'group', g.principal_id
              FROM grants g JOIN memberships m ON m.group_id = g.principal_id
             WHERE g.principal_kind = 'group'
               AND NOT EXISTS (SELECT 1 FROM revocations r WHERE r.oid = m.oid AND r.group_id = g.principal_id)
            UNION
            SELECT g.item_id, g.principal_id, g.principal_kind, g.principal_id
              FROM grants g WHERE g.principal_kind IN ('user', 'link_specific')
            ON CONFLICT DO NOTHING""")
        # Restricted Access Control: reader must also be in one of the site's RAC groups.
        c.execute("""
            DELETE FROM item_reader ir USING items i, sites s
             WHERE ir.item_id = i.item_id AND i.site_id = s.site_id
               AND cardinality(s.rac_groups) > 0
               AND NOT EXISTS (SELECT 1 FROM memberships m
                                WHERE m.oid = ir.oid AND m.group_id = ANY(s.rac_groups)
                                  AND NOT EXISTS (SELECT 1 FROM revocations r
                                                   WHERE r.oid = m.oid AND r.group_id = m.group_id))""")
        c.execute("DELETE FROM item_reader WHERE oid IN (SELECT oid FROM deny_list)")
        c.execute("DELETE FROM item_reader WHERE oid NOT IN (SELECT oid FROM users_mirror WHERE enabled)")
