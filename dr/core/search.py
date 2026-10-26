"""Document search (BRD BR-02, mục 3 #2–#3): find files by keywords, content or meaning, and by
file name or attributes (folder, site, label, file type).

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
MAX_LISTED = 50          # a filter without words lists the matching files (browse by attribute)

# file-type filter: UI choice -> extensions
KINDS = {"pdf": ("pdf",), "word": ("doc", "docx"), "excel": ("xls", "xlsx", "csv"), "slide": ("ppt", "pptx"),
         "email": ("eml", "msg"), "image": ("png", "jpg", "jpeg")}


def _fold(text: str | None) -> str:
    return unidecode(text or "").lower()


def _terms(query: str) -> list[str]:
    return [w for w in re.findall(r"[0-9a-z]+", _fold(query)) if len(w) >= 3]


def usable_items(oid: str, site: str | None = None, exts: tuple[str, ...] | None = None) -> dict[str, dict]:
    """Metadata of the files this user can read AND may use with AI, as the user: RLS on items (reader)
    and on chunks (AI_Use, encryption, malware, current version) decides, the app adds no rule of its own."""
    from dr.db import pg
    sql = ("SELECT i.item_id, i.name, i.ext, i.site_id, i.path, i.label, i.size, i.ctag, s.name FROM items i "
           "LEFT JOIN sites s ON s.site_id = i.site_id "
           "WHERE EXISTS (SELECT 1 FROM chunks c WHERE c.item_id = i.item_id AND c.ctag = i.ctag)")
    args: list = []
    if site:
        sql += " AND i.site_id = %s"
        args.append(site)
    if exts:
        sql += " AND lower(i.ext) = ANY(%s)"
        args.append(list(exts))
    with pg.as_principal(oid) as cur:
        rows = cur.execute(sql + " ORDER BY i.site_id, i.path, i.name", args).fetchall()
    return {r[0]: {"item_id": r[0], "name": r[1], "ext": r[2], "site_id": r[3], "path": r[4], "label": r[5],
                   "size": r[6], "ctag": r[7], "site_name": r[8] or r[3]} for r in rows}


def name_matches(items: dict[str, dict], query: str) -> list[str]:
    """Files whose name, folder, site or label hold every word of the query (accents ignored),
    a word in the file name counting double. Short words count too: file codes such as "a1"."""
    words = [w for w in re.findall(r"[0-9a-z]+", _fold(query)) if len(w) >= 2]
    if not words:
        return []
    scored = []
    for pos, (item_id, m) in enumerate(items.items()):       # ties keep folder order
        name, meta = _fold(m["name"]), _fold(" ".join(filter(None, [m["path"], m["site_id"], m["site_name"],
                                                                      m["label"]])))
        if all(w in name or w in meta for w in words):
            scored.append((-sum(2 if w in name else 1 for w in words), pos, item_id))
    return [i for _, _, i in sorted(scored)]


def snippet(text: str, terms: list[str], width: int = 260) -> str:
    """The part of the passage around the first query term (accent-insensitive)."""
    folded = unidecode(text).lower()
    pos = min((folded.find(t) for t in terms if folded.find(t) >= 0), default=0)
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def search_files(tenant, index, oid: str, roles: list[str], query: str, deps, site: str | None = None,
                 kind: str | None = None) -> dict:
    query = guard.clean(query)[:300]
    lang = lang_mod.detect(query)
    g = gates.principal_gate(oid, roles)
    if not g.ok:
        msg = ("Tài khoản của bạn chưa được cấp quyền sử dụng trợ lý AI trong Data Room."
               if g.reason == "no_ai_role" else "Trợ lý AI tạm ngừng để đảm bảo an toàn phân quyền. Vui lòng thử lại sau.")
        return {"refused": True, "message": lang_mod.tr(msg, lang), "results": []}
    exts = KINDS.get(kind or "")
    if not query.strip() and not (site or exts):
        return {"refused": False, "results": [], "query": query}
    usable = usable_items(oid, site, exts)
    # 1) name / attributes: every word in the file name, folder, site or label (no words = list by filter)
    by_name = name_matches(usable, query) if query.strip() else list(usable)
    # 2) content: hybrid search under RLS, kept to the usable files that pass the filters
    best: dict[str, dict] = {}
    if query.strip():
        qvec = deps.embed_query(query) if deps and deps.embed_query else None
        if getattr(index, "in_db", False):
            hits, _ = index.search_as(oid, query, qvec, k=60, site=site)
        else:
            allowed = gates.allowed_chunks(oid, site)
            hits = index.search(set(allowed), query, qvec, k=60)
        passages = gates.fetch_passages(oid, [c for c, _ in hits])          # RLS again
        for cid, _ in hits:
            p = passages.get(cid)
            if p and p["item_id"] in usable and p["item_id"] not in best:
                best[p["item_id"]] = p
            if len(best) >= MAX_FILES:
                break
    cap = MAX_FILES if query.strip() else MAX_LISTED
    order = list(dict.fromkeys(by_name[:cap] + list(best)))[:cap]
    live = gates.live_check(tenant, oid, {i: usable[i]["ctag"] for i in order}) if order else {}
    terms = _terms(query)
    named = set(by_name) if query.strip() else set()          # a filter-only list matched no words
    results = []
    for item_id in order:
        if not live.get(item_id, (False, ""))[0]:
            continue
        m, p = usable[item_id], best.get(item_id)
        results.append({
            "item_id": item_id, "name": m["name"], "ext": m["ext"], "site_id": m["site_id"],
            "site_name": m["site_name"], "path": m["path"], "label": m["label"], "size": m["size"],
            "match": [k for k, hit in (("name", item_id in named), ("content", p is not None)) if hit],
            "locator": p["locator"] if p else "", "ocr": p["ocr"] if p else False,
            "snippet": pii.mask(snippet(p["text"], terms))[0] if p else ""})
    audit.append(oid, "search", {"query": pii.mask(query)[0], "site": site, "kind": kind if exts else None,
                                 "results": [r["item_id"] for r in results],
                                 "dropped_live": sum(1 for i in order if not live.get(i, (False, ""))[0])})
    return {"refused": False, "query": query, "terms": terms, "results": results, "lang": lang}
