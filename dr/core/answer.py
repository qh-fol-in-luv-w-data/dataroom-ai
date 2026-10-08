"""Question answering with the four gates, verification and audit.

Order (master plan v0.5 §4.4):
  gate 4 -> gate 1 (RLS ids) -> hybrid search -> passages under RLS -> rerank -> group by file
  -> gate 2 live check (silent drop + backfill) -> LLM (JSON, quotes) -> deterministic verify
  -> NLI score -> gate 2 again on cited files + gate 4 again -> audit -> release one block.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from dr import audit
from dr.config import BLOCKED_MESSAGE, NEUTRAL_REFUSAL, RETRY_MESSAGE, UNAVAILABLE_MESSAGE, settings
from dr.core import gates, verify
from dr.core.index import SearchIndex
from dr.core import lang as lang_mod
from dr.core import review
from dr.security import guard, pii
from dr.tenant.service import FakeTenant

NO_ROLE_MESSAGE = "Tài khoản của bạn chưa được cấp quyền sử dụng trợ lý AI trong Data Room."
MAX_CHUNKS_PER_FILE = 3
MAX_PASSAGES = 10
FOCUSED_PASSAGES = 5   # retry size when a small local model finds nothing in 10 passages


@dataclass
class Deps:
    embed_query: Callable | None = None
    rerank: Callable | None = None
    llm: Callable | None = None
    nli: Callable | None = None
    embed_many: Callable | None = None     # batch embeddings (input guard scores parts of long questions)

    @classmethod
    def real(cls) -> "Deps":
        from dr.models import embed, llm, nli, rerank
        return cls(embed.embed_query, rerank.rerank, llm.answer_json, nli.entail, embed_many=embed.embed_texts)


@dataclass
class Trace:
    steps: list[dict] = field(default_factory=list)
    _t: float = field(default_factory=time.time)

    def add(self, step: str, ok: bool, **detail):
        now = time.time()
        self.steps.append({"step": step, "ok": ok, "ms": int((now - self._t) * 1000), **detail})
        self._t = now


_MARKER = re.compile(r"mã kiểm soát:?\s*ks-[a-z]+-\d{4}", re.IGNORECASE)


def _signature(text: str) -> str:
    """Content signature ignoring per-document control markers, case and spacing."""
    return hashlib.sha1(verify.norm(_MARKER.sub(" ", text)).encode()).hexdigest()


def select_passages(order: list[int], passages: dict[int, dict], chosen: set[str],
                    max_passages: int, max_per_file: int) -> list[int]:
    """Best-first passages from live-checked files, skipping near-duplicate content
    (e.g. the same financial statement sheet copied into many workbooks)."""
    selected: list[int] = []
    per_file: dict[str, int] = {}
    seen: set[str] = set()
    for c in order:
        if len(selected) >= max_passages:
            break
        it = passages[c]["item_id"]
        if it not in chosen or per_file.get(it, 0) >= max_per_file:
            continue
        sig = _signature(passages[c]["text"])
        if sig in seen:
            continue
        seen.add(sig)
        selected.append(c)
        per_file[it] = per_file.get(it, 0) + 1
    return selected


def _refuse(oid, question, message, trace, kind="refusal", extra=None) -> dict:
    seq = audit.append(oid, kind, {"question": pii.mask(question)[0] if settings.mask_pii else question,
                                   "message": message,
                                   "trace": [s["step"] + (":ok" if s["ok"] else ":fail") for s in trace.steps],
                                   **(extra or {})})
    return {"refused": True, "message": message, "claims": [], "citations": [], "trace": trace.steps,
            "audit_seq": seq}


def crop_for(page_ref: str | None, quote: str) -> dict | None:
    """Region of the cleaned scan page that holds the quote (lines read by the 2nd OCR reader)."""
    if not page_ref or "/p" not in page_ref:
        return None
    from unidecode import unidecode
    from dr.ingest.ocr import cached_page
    key, _, n = page_ref.partition("/p")
    got = cached_page(key, int(n)) if n.isdigit() else None
    if not got:
        return None
    _, lines = got
    from difflib import SequenceMatcher
    flat = lambda t: "".join(ch for ch in unidecode(t).lower() if ch.isalnum())
    q = flat(quote)

    def overlaps(line: str) -> bool:      # the line lies in the quote, or the quote in the line
        f = flat(line)
        if len(f) < 4 or not q:
            return False
        m = SequenceMatcher(None, f, q, autojunk=False).find_longest_match(0, len(f), 0, len(q))
        return m.size >= max(4, 0.7 * min(len(f), len(q)))

    boxes = [ln["box"] for ln in lines if overlaps(ln["text"])]
    if not boxes:
        return {"page": page_ref, "box": None}
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    return {"page": page_ref, "box": [max(0, x0 - 30), max(0, y0 - 30), x1 + 30, y1 + 30]}


def ask(tenant: FakeTenant, index: SearchIndex, oid: str, roles: list[str], question: str,
        deps: Deps, scope_site: str | None = None) -> dict:
    trace = Trace()
    question = question.strip()[:1000]
    lang = lang_mod.detect(question)

    def refuse(message: str, **kw) -> dict:
        r = _refuse(oid, question, lang_mod.tr(message, lang), trace, **kw)
        r["lang"] = lang
        return r

    # ---- gate 4: principal
    g = gates.principal_gate(oid, roles)
    trace.add("Cổng 4 – danh tính, vai trò, độ tươi nguồn quyền", g.ok, reason=g.reason, **(g.detail or {}))
    if not g.ok:
        msg = {"feed_stale": UNAVAILABLE_MESSAGE, "no_ai_role": NO_ROLE_MESSAGE}.get(g.reason, UNAVAILABLE_MESSAGE)
        return refuse(msg)

    # ---- gate 1 (+3): RLS over the mirror; revoked group paths already excluded
    if getattr(index, "in_db", False):
        n_files, n_allowed = index.allowed_scope(oid, scope_site)
    else:
        allowed = gates.allowed_chunks(oid, scope_site)
        n_files, n_allowed = len(set(allowed.values())), len(allowed)
    trace.add("Cổng 1+3 – RLS trên bản chép quyền (đã trừ tập thu hồi)", True,
              allowed_chunks=n_allowed, allowed_files=n_files)
    if not n_allowed:
        return refuse(NEUTRAL_REFUSAL)

    # ---- layer 2: input security (normalise, injection rules, classifier, personal data)
    if settings.input_guard:
        clean_q = guard.clean(question)
        qvec = deps.embed_query(clean_q) if deps.embed_query else None
        v = guard.inspect(question, qvec, deps.embed_many)
        trace.add("Lớp đầu vào – chuẩn hóa, luật chống prompt injection, bộ phân loại", not v.blocked,
                  rules=v.rules, score=v.score, normalized=v.changed)
        if v.blocked:
            return refuse(BLOCKED_MESSAGE, kind="input_blocked",
                           extra={"rules": v.rules, "score": v.score})
        question = clean_q
    else:
        qvec = deps.embed_query(question) if deps.embed_query else None
    # ---- sensitive topics (BRD BR-08): not answered by the AI; the asker is pointed to a person
    topics = review.topics_of(question)
    is_staff = "Staff.AI" in set(g.detail.get("roles_mirror", []))
    if topics and not is_staff and settings.sensitive_mode == "contact":
        msg = (f"Nội dung này hơi nhạy cảm, bạn hãy liên hệ trực tiếp {settings.sensitive_contact} để được hỗ trợ."
               if lang == "vi" else
               f"This topic is sensitive. Please contact {settings.sensitive_contact_en} directly for assistance.")
        trace.add("Câu hỏi nhạy cảm → không trả lời, chuyển người liên hệ", True, topics=topics)
        r = refuse(msg, kind="sensitive_redirect", extra={"topics": topics})
        r["sensitive"] = True
        return r
    if settings.mask_pii:
        masked_q, kinds = pii.mask(question)
        if kinds:
            trace.add("Che thông tin cá nhân trong câu hỏi", True, kinds=kinds)
            question = masked_q
    if getattr(index, "in_db", False):
        hits, info = index.search_as(oid, question, qvec, k=settings.rerank_top, site=scope_site)
        trace.add("Tìm kiếm lai BM25 + vector trong Postgres (RLS ngay trong câu truy vấn)", True,
                  hits=len(hits), **info)
    else:
        hits = index.search(set(allowed), question, qvec, k=settings.rerank_top)
        trace.add("Tìm kiếm lai BM25 + vector (chỉ trên id được phép)", True, hits=len(hits))
    passages = gates.fetch_passages(oid, [cid for cid, _ in hits])
    order = [cid for cid, _ in hits if cid in passages]

    if deps.rerank and order:
        scores = deps.rerank(question, [passages[c]["text"] for c in order])
        for c, s in zip(order, scores):
            passages[c]["rerank"] = s
        order = [c for _, c in sorted(zip(scores, order), key=lambda x: -x[0])]
        trace.add("Rerank bge-reranker-v2-m3", True, top_score=round(max(scores), 3) if scores else None)

    # group by file, keep file order by best chunk
    files: list[str] = []
    seen_sig: set[str] = set()
    for c in order:
        it = passages[c]["item_id"]
        sig = _signature(passages[c]["text"])
        if sig in seen_sig:      # near-duplicate content must not take a file slot
            continue
        seen_sig.add(sig)
        if it not in files:
            files.append(it)

    # ---- gate 2: live check, silent drop, backfill up to max_files
    chosen: list[str] = []
    dropped_live: dict[str, str] = {}
    transient = False
    i = 0
    while len(chosen) < settings.max_files and i < len(files):
        batch = files[i:i + (settings.max_files - len(chosen))]
        i += len(batch)
        res = gates.live_check(tenant, oid, {f: next(p["ctag"] for p in passages.values() if p["item_id"] == f)
                                             for f in batch})
        for f in batch:
            ok, why = res[f]
            if ok:
                chosen.append(f)
            else:
                dropped_live[f] = why
                transient |= why.startswith("transient")
    trace.add("Cổng 2 – kiểm tra trực tiếp với SharePoint (lần 1)", True, checked=len(chosen) + len(dropped_live),
              passed=len(chosen), dropped=len(dropped_live))
    if transient and files and files[0] in dropped_live:
        return refuse(RETRY_MESSAGE)

    selected = select_passages(order, passages, set(chosen), MAX_PASSAGES, MAX_CHUNKS_PER_FILE)
    if not selected:
        return refuse(NEUTRAL_REFUSAL)
    sel_passages = {c: passages[c] for c in selected}
    flagged = [c for c in selected if passages[c]["injection_flag"]]
    if flagged:
        trace.add("Đoạn bị gắn cờ prompt injection (vẫn bọc là dữ liệu)", True, chunks=len(flagged))

    # ---- LLM
    llm_in = [{"chunk_id": c, "text": passages[c]["text"],
               "source": f'{passages[c]["name"]} · {passages[c]["locator"]}'} for c in selected]
    raw, labels = deps.llm(question, llm_in, lang=lang)
    trace.add(f"LLM {settings.llm_model} (JSON có ràng buộc)", True, raw_claims=len(raw.get("claims", [])))

    # ---- deterministic verification
    kept, dropped = verify.check(raw.get("claims", []), labels, sel_passages, question)
    trace.add("Kiểm chứng tất định (trích dẫn nguyên văn, con số)", True, kept=len(kept), dropped=len(dropped),
              dropped_reasons=[r for _, r in dropped])
    if not kept and len(selected) > FOCUSED_PASSAGES:
        # Small local models lose facts in long contexts: retry once on the top passages only.
        focus = llm_in[:FOCUSED_PASSAGES]
        raw, labels = deps.llm(question, focus, lang=lang)
        kept, dropped2 = verify.check(raw.get("claims", []), labels,
                                      {p["chunk_id"]: sel_passages[p["chunk_id"]] for p in focus}, question)
        dropped += dropped2
        trace.add(f"Thử lại có trọng tâm ({FOCUSED_PASSAGES} đoạn đầu) + kiểm chứng", True, kept=len(kept),
                  dropped_reasons=[r for _, r in dropped2])
    if deps.nli:
        for cl in kept:
            cl.nli = round(deps.nli(" ".join(c.quote for c in cl.citations), cl.text), 3)
        trace.add("NLI mDeBERTa (tín hiệu phụ)", True, scores=[cl.nli for cl in kept])

    # ---- gate 2 again on cited files, gate 4 again
    cited_items = {sel_passages[c.chunk_id]["item_id"] for cl in kept for c in cl.citations}
    res2 = gates.live_check(tenant, oid, {f: next(sel_passages[c]["ctag"] for c in selected
                                                   if sel_passages[c]["item_id"] == f) for f in cited_items})
    failed2 = {f for f, (ok, _) in res2.items() if not ok}
    if failed2:
        kept = [cl for cl in kept if not any(sel_passages[c.chunk_id]["item_id"] in failed2 for c in cl.citations)]
    g2 = gates.principal_gate(oid, roles)
    trace.add("Cổng 2 + 4 – kiểm tra lại trước khi trả lời", g2.ok,
              cited_files=len(cited_items), failed=len(failed2))
    if not g2.ok:
        return refuse(UNAVAILABLE_MESSAGE)
    if not kept:
        return refuse(NEUTRAL_REFUSAL,
                       extra={"llm_no_answer": raw.get("no_answer"), "dropped": [r for _, r in dropped]})

    # ---- answer mode (BR-04): without a summarize-capable role, only verbatim quotes are shown
    held_roles = set(g2.detail.get("roles_mirror", []))
    summarize = bool(held_roles & {"Investor.AI.Summarize", "Staff.AI"})
    if not summarize:
        quoted, seen_q = [], set()
        for cl in kept:
            for c in cl.citations:
                if c.quote not in seen_q:
                    seen_q.add(c.quote)
                    quoted.append(verify.Claim(f"“{c.quote}”", [c], None))
        kept = quoted
        trace.add("Chế độ tra cứu – chỉ trả câu trích nguyên văn (không có quyền tổng hợp)", True, quotes=len(kept))

    # ---- build response
    cites, claims_out = [], []
    cite_index: dict[tuple, int] = {}
    for cl in kept:
        refs = []
        for c in cl.citations:
            p = sel_passages[c.chunk_id]
            key = (p["item_id"], p["locator"])
            if key not in cite_index:
                cite_index[key] = len(cites) + 1
                quote = c.quote.replace("。", ".").replace("，", ",")
                cites.append({"n": cite_index[key], "item_id": p["item_id"], "name": p["name"],
                              "locator": p["locator"], "ocr": p["ocr"], "site_id": p["site_id"],
                              "quote": quote, "chunk_id": c.chunk_id, "ctag": p["ctag"],
                              "crop": crop_for(p["ocr_page"], quote) if p["ocr"] and settings.tenant_mode != "m365" else None,
                              "web_url": getattr(tenant, "web_url", lambda _: None)(p["item_id"]),
                              "public": getattr(tenant, "public_url", lambda _: None)(p["item_id"])})
            refs.append(cite_index[key])
        # numbers in the claim or its quotes that only the VLM read (second OCR reader disagreed)
        doubt = sorted({n for c in cl.citations for n in sel_passages[c.chunk_id].get("ocr_doubt", [])
                        if n in cl.text or n in c.quote})
        claims_out.append({"text": cl.text, "refs": sorted(set(refs)), "nli": cl.nli, "ocr_doubt": doubt,
                           "uncertain": bool(doubt) or (cl.nli is not None and cl.nli < settings.nli_threshold)})
    if settings.mask_pii:      # after verification (quotes were checked against the real text)
        masked_kinds: set[str] = set()
        for c in claims_out:
            c["text"], k = pii.mask(c["text"])
            masked_kinds.update(k)
        for c in cites:
            c["quote"], k = pii.mask(c["quote"])
            masked_kinds.update(k)
        if masked_kinds:
            trace.add("Che thông tin cá nhân trong câu trả lời", True, kinds=sorted(masked_kinds))
    answer_text = "\n".join(c["text"] for c in claims_out)
    seq = audit.append(oid, "answer", {
        "question": question,
        "allowed_chunks": n_allowed,
        "files_checked": len(chosen) + len(dropped_live),
        "files_dropped_live": len(dropped_live),
        "cited": [{"item_id": c["item_id"], "locator": c["locator"], "chunk_id": c["chunk_id"]} for c in cites],
        "versions": {f: sel_passages[next(c for c in selected if sel_passages[c]["item_id"] == f)]["ctag"]
                     for f in cited_items},
        "answer_sha256": hashlib.sha256(answer_text.encode()).hexdigest(),
        "dropped_claims": [r for _, r in dropped],
    })
    trace.add("Ghi nhật ký (chuỗi hash)", True, audit_seq=seq)
    result = {"refused": False, "message": None, "claims": claims_out, "citations": cites, "trace": trace.steps,
              "audit_seq": seq, "lang": lang, "mode": "summary" if summarize else "quote"}
    # ---- sensitive questions (BR-08): investors get the answer only after a reviewer approves it
    if topics and not is_staff and settings.sensitive_mode == "review":
        trace.add("Câu hỏi nhạy cảm → bản nháp chờ người duyệt", True, topics=topics)
        return review.hold(oid, question, lang, topics, result, lang_mod.tr(review.HOLD_MESSAGE, lang))
    return result
