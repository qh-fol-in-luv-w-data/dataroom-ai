"""Questions about another investor group.

An investor who asks about a group they are not in (by name or alias: "Nhóm A", "quỹ trong
nước", "nhà đầu tư chiến lược"...) must not get an answer built from their *own* group's
documents (asked about group A's lock-up, a group C investor would otherwise get group C's
lock-up). Such a question is answered only from shared documents (sites that are not
group-specific, e.g. the common Data Room); if those do not answer it, the investor gets a
polite out-of-scope message.

The decision uses only the question text and the sites this user can read under RLS, never
the other group's documents, so the message reveals nothing about what those documents hold.

Aliases: DEFAULT_AUDIENCES, overridable by data/tenant/audiences.json
({"site_id": ["folded alias", ...]}); in M365 mode the keys are the group sites' ids.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from unidecode import unidecode

from dr.config import settings
from dr.db import pg

DEFAULT_AUDIENCES = {
    "GRP-A": ["nhom a", "group a", "quy trong nuoc", "nhom quy trong nuoc", "domestic fund", "domestic funds",
              "nha dau tu trong nuoc", "domestic investor", "domestic investors"],
    "GRP-B": ["nhom b", "group b", "quy ngoai", "quy nuoc ngoai", "nhom quy ngoai", "foreign fund", "foreign funds",
              "nha dau tu nuoc ngoai", "foreign investor", "foreign investors"],
    "GRP-C": ["nhom c", "group c", "nha dau tu chien luoc", "strategic investor", "strategic investors"],
}


@lru_cache(maxsize=1)
def audiences() -> dict[str, list[str]]:
    f = settings.tenant_dir / "audiences.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return DEFAULT_AUDIENCES


@lru_cache(maxsize=1)
def _patterns() -> dict[str, re.Pattern]:
    return {site: re.compile(r"\b(?:" + "|".join(re.escape(a) for a in aliases) + r")\b")
            for site, aliases in audiences().items()}


def group_sites() -> set[str]:
    return set(audiences())


def mentioned(question: str) -> set[str]:
    """Group sites the question names."""
    q = re.sub(r"\s+", " ", unidecode(question).lower())
    return {site for site, pat in _patterns().items() if pat.search(q)}


def readable_sites(oid: str) -> set[str]:
    with pg.as_principal(oid) as cur:                      # RLS: only what this user may read
        return {r[0] for r in cur.execute("SELECT DISTINCT site_id FROM items").fetchall()}


def other_groups_only(oid: str, question: str) -> list[str]:
    """Group sites named by the question that the user cannot read, when the question names
    none of the user's own groups (a question naming both is answered normally)."""
    named = mentioned(question)
    if not named:
        return []
    mine = readable_sites(oid)
    if named & mine:
        return []
    return sorted(named - mine)
