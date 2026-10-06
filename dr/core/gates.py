"""The four permission gates (master plan v0.5 §3.3).

Gate 1  RLS on the permission mirror           -> allowed_chunks()
Gate 2  live check with SharePoint as the user -> live_check()
Gate 3  per-(oid, group) revocation set         -> applied inside item_reader by the connector
Gate 4  principal gate (role, deny list, feed freshness) -> principal_gate()
"""
from __future__ import annotations

from dataclasses import dataclass

from dr.config import settings
from dr.db import pg
from dr.tenant.service import FakeTenant

AI_ROLES = ("Investor.AI", "Staff.AI")
AI_VALUES = ("Allowed", "OnPremOnly")


@dataclass
class GateResult:
    ok: bool
    reason: str = ""
    detail: dict | None = None


def principal_gate(oid: str, token_roles: list[str]) -> GateResult:
    with pg.as_principal(oid) as cur:
        denied = cur.execute("SELECT me_denied()").fetchone()[0]
        mirror_roles = [r for r in AI_ROLES if cur.execute("SELECT me_has_role(%s)", (r,)).fetchone()[0]]
        entra_age = cur.execute("SELECT feed_age('entra')").fetchone()[0]
        drive_age = cur.execute("SELECT feed_age('drive')").fetchone()[0]
    detail = {"entra_feed_age_s": round(entra_age, 1), "drive_feed_age_s": round(drive_age, 1),
              "roles_token": token_roles, "roles_mirror": mirror_roles}
    if entra_age > settings.feed_max_age_seconds or drive_age > settings.feed_max_age_seconds:
        return GateResult(False, "feed_stale", detail)
    if denied:
        return GateResult(False, "denied", detail)
    if not (set(token_roles) & set(mirror_roles)):
        return GateResult(False, "no_ai_role", detail)
    return GateResult(True, "", detail)


def allowed_chunks(oid: str, site: str | None = None) -> dict[int, str]:
    """chunk_id -> item_id for every chunk RLS lets this principal read."""
    with pg.as_principal(oid) as cur:
        if site:
            rows = cur.execute("SELECT chunk_id, item_id FROM chunks WHERE site_id=%s", (site,)).fetchall()
        else:
            rows = cur.execute("SELECT chunk_id, item_id FROM chunks").fetchall()
    return {r[0]: r[1] for r in rows}


def fetch_passages(oid: str, chunk_ids: list[int]) -> dict[int, dict]:
    if not chunk_ids:
        return {}
    with pg.as_principal(oid) as cur:
        rows = cur.execute(
            "SELECT c.chunk_id, c.item_id, c.text, c.locator, c.ocr, c.injection_flag, c.kind, i.name, i.ctag, "
            "i.site_id, i.ext FROM chunks c JOIN items i ON i.item_id = c.item_id WHERE c.chunk_id = ANY(%s)",
            (chunk_ids,)).fetchall()
    return {r[0]: {"chunk_id": r[0], "item_id": r[1], "text": r[2], "locator": r[3], "ocr": r[4],
                   "injection_flag": r[5], "kind": r[6], "name": r[7], "ctag": r[8], "site_id": r[9], "ext": r[10]}
            for r in rows}


def live_check(tenant: FakeTenant, oid: str, items: dict[str, str]) -> dict[str, tuple[bool, str]]:
    """items: item_id -> ctag the passages were indexed from. SharePoint must answer 200,
    with the same ctag and an AI_Use value that allows AI."""
    out = {}
    for item_id, ctag in items.items():
        try:
            status, meta = tenant.get_item_as_user(oid, item_id)
        except Exception as e:  # transient failure: not "allowed"
            out[item_id] = (False, f"transient:{e.__class__.__name__}")
            continue
        if status != 200:
            out[item_id] = (False, str(status))
        elif meta["ctag"] != ctag:
            out[item_id] = (False, "version_changed")
        elif meta["ai_use"] not in AI_VALUES:
            out[item_id] = (False, "ai_use")
        else:
            out[item_id] = (True, "200")
    return out
