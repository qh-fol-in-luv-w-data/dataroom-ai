"""Document search (BRD BR-02): find files by keywords, content or meaning.

Same gates as the answer path, no LLM: gate 4 (identity, AI role, feed freshness), RLS inside
the search (gate 1 + revocations), then the live check (gate 2) on every file returned, so a
result is never a file the user cannot open right now or that may not be used with AI.
Only AI-allowed files are searched (BRD: search obeys the same rights as chat).
"""
from __future__ import annotations

import re

from unidecode import unidecode

from dr import audit
from dr.core import gates
from dr.core import lang as lang_mod
from dr.security import guard, pii

MAX_FILES = 20


def _terms(query: str) -> list[str]:
    return [w for w in re.findall(r"[0-9a-z]+", unidecode(query).lower()) if len(w) >= 3]


def snippet(text: str, terms: list[str], width: int = 260) -> str:
    """The part of the passage around the first query term (accent-insensitive)."""
    folded = unidecode(text).lower()
    pos = min((folded.find(t) for t in terms if folded.find(t) >= 0), default=0)
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def search_files(tenant, index, oid: str, roles: list[str], query: str, deps, site: str | None = None) -> dict:
    query = guard.clean(query)[:300]
    lang = lang_mod.detect(query)
    g = gates.principal_gate(oid, roles)
    if not g.ok:
        msg = ("Tài khoản của bạn chưa được cấp quyền sử dụng trợ lý AI trong Data Room."
               if g.reason == "no_ai_role" else "Trợ lý AI tạm ngừng để đảm bảo an toàn phân quyền. Vui lòng thử lại sau.")
        return {"refused": True, "message": lang_mod.tr(msg, lang), "results": []}
    if not query.strip():
        return {"refused": False, "results": [], "query": query}
    qvec = deps.embed_query(query) if deps and deps.embed_query else None
    if getattr(index, "in_db", False):
        hits, _ = index.search_as(oid, query, qvec, k=60, site=site)
    else:
        allowed = gates.allowed_chunks(oid, site)
        hits = index.search(set(allowed), query, qvec, k=60)
    passages = gates.fetch_passages(oid, [c for c, _ in hits])          # RLS again
    best: dict[str, dict] = {}
    for rank, (cid, _) in enumerate(hits):
        p = passages.get(cid)
        if p and p["item_id"] not in best:
            best[p["item_id"]] = {**p, "rank": rank}
        if len(best) >= MAX_FILES:
            break
    live = gates.live_check(tenant, oid, {i: p["ctag"] for i, p in best.items()}) if best else {}
    terms = _terms(query)
    results = []
    for item_id, p in sorted(best.items(), key=lambda kv: kv[1]["rank"]):
        if not live.get(item_id, (False, ""))[0]:
            continue
        it = getattr(tenant, "items", {}).get(item_id, {})
        results.append({
            "item_id": item_id, "name": p["name"], "ext": p["ext"], "site_id": p["site_id"],
            "path": it.get("path", ""), "locator": p["locator"], "ocr": p["ocr"],
            "snippet": pii.mask(snippet(p["text"], terms))[0]})
    audit.append(oid, "search", {"query": pii.mask(query)[0], "site": site,
                                 "results": [r["item_id"] for r in results],
                                 "dropped_live": sum(1 for i in best if not live.get(i, (False, ""))[0])})
    return {"refused": False, "query": query, "terms": terms, "results": results, "lang": lang}
