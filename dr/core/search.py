"""Document search (BRD BR-02, mục 3 #2–#3): find files by keywords, content or meaning, and by
file name or attributes (folder, site, label, file type).

Same gates as the answer path, no LLM: gate 4 (identity, AI role, feed freshness), RLS inside
the search (gate 1 + revocations), then the live check (gate 2) on every file returned, so a
result is never a file the user cannot open right now or that may not be used with AI.
Only AI-allowed files are searched (BRD: search obeys the same rights as chat).
"""
from __future__ import annotations

import math
import re

from unidecode import unidecode

from dr import audit
from dr.core import gates, intent
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


NAME_COVERAGE = 0.6     # share of the query words a file name / folder must hold to count as a name match
RRF_K = 5               # rank fusion of the name list and the content list
# short forms common in Vietnamese file names (folded): a name holding one also matches the long form
ABBREV = {"dmt": "dien mat troi", "hdqt": "hoi dong quan tri", "dhdcd": "dai hoi dong co dong",
          "bctc": "bao cao tai chinh", "ndt": "nha dau tu"}
# words that say nothing about which file is meant
STOP = {"cua", "cho", "va", "cac", "nhung", "mot", "la", "ve", "voi", "tai", "lieu", "ho", "so", "file",
        "the", "of", "for", "and", "to", "in", "on", "an"}


def _tokens(text: str) -> set[str]:
    toks = re.findall(r"[0-9a-z]+", _fold(text))
    return set(toks) | {w for t in toks if t in ABBREV for w in ABBREV[t].split()}


def _has(word: str, toks: set[str]) -> bool:
    # whole word; a longer word may also be the start of one ("2023" in "20232025")
    return word in toks or (len(word) >= 4 and any(t.startswith(word) for t in toks))


def name_matches(items: dict[str, dict], query: str) -> list[tuple[str, float]]:
    """Files whose name, folder, site or label hold most words of the query (accents ignored, filler
    words dropped, short forms such as ĐMT/HĐQT spelled out): (item_id, share of words found), best first.
    A word found in the file name itself counts more. Short words count too: codes such as "a1", "quý 2"."""
    words = [w for w in dict.fromkeys(re.findall(r"[0-9a-z]+", _fold(query)))
             if (len(w) >= 2 or w.isdigit()) and w not in STOP]
    if not words:
        return []
    need = 1 if len(words) == 1 else max(2, math.ceil(len(words) * NAME_COVERAGE))
    scored = []
    for pos, (item_id, m) in enumerate(items.items()):       # ties keep folder order
        name = _tokens(m["name"])
        meta = _tokens(" ".join(filter(None, [m["path"], m["site_id"], m["site_name"], m["label"]])))
        in_name = sum(_has(w, name) for w in words)
        found = sum(_has(w, name) or _has(w, meta) for w in words)
        if found >= need:
            scored.append((-(found + in_name), pos, item_id, found / len(words)))
    return [(i, share) for _, _, i, share in sorted(scored)]


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
    # 1) name / attributes: most words in the file name, folder, site or label
    by_name = name_matches(usable, query) if query.strip() else []
    # 2) content: hybrid search under RLS (an English query also gets its Vietnamese terms, as in chat),
    #    kept to the usable files that pass the filters
    best: dict[str, dict] = {}
    if query.strip():
        q_content = intent.expand_en(query) if lang == "en" else query
        qvec = deps.embed_query(q_content) if deps and deps.embed_query else None
        if getattr(index, "in_db", False):
            hits, _ = index.search_as(oid, q_content, qvec, k=60, site=site)
        else:
            allowed = gates.allowed_chunks(oid, site)
            hits = index.search(set(allowed), q_content, qvec, k=60)
        passages = gates.fetch_passages(oid, [c for c, _ in hits])          # RLS again
        for cid, _ in hits:
            p = passages.get(cid)
            if p and p["item_id"] in usable and p["item_id"] not in best:
                best[p["item_id"]] = p
            if len(best) >= MAX_FILES:
                break
    if query.strip():
        # rank fusion; a name holding all the words weighs twice a top content match
        score: dict[str, float] = {}
        for r, (i, share) in enumerate(by_name, 1):
            score[i] = score.get(i, 0.0) + 2 * share / (RRF_K + r)
        for r, i in enumerate(best, 1):
            score[i] = score.get(i, 0.0) + 1 / (RRF_K + r)
        order = sorted(score, key=lambda i: -score[i])[:MAX_FILES]
    else:
        order = list(usable)[:MAX_LISTED]                     # filters only: list the files
    live = gates.live_check(tenant, oid, {i: usable[i]["ctag"] for i in order}) if order else {}
    terms = _terms(query)
    named = {i for i, _ in by_name}
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
