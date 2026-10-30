"""Question answering with the four gates, verification and audit.

Order (master plan v0.5 §4.4):
  gate 4 -> gate 1 (RLS ids) -> hybrid search -> passages under RLS -> rerank -> group by file
  -> gate 2 live check (silent drop + backfill) -> LLM (JSON, quotes) -> deterministic verify
  -> NLI score -> gate 2 again on cited files + gate 4 again -> audit -> release one block.
"""
from __future__ import annotations

import hashlib
import inspect
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from unidecode import unidecode

from dr import audit
from dr.config import (BLOCKED_MESSAGE, NEUTRAL_REFUSAL, OUT_OF_SCOPE_MESSAGE, RETRY_MESSAGE, UNAVAILABLE_MESSAGE,
                       settings)
from dr.core import accents, audience, conflicts, conversation, doctype, facts, gates, intent, tables, verify
from dr.core.index import SearchIndex
from dr.core import lang as lang_mod
from dr.core import review
from dr.security import guard, pii
from dr.tenant.service import FakeTenant

NO_ROLE_MESSAGE = "Tài khoản của bạn chưa được cấp quyền sử dụng trợ lý AI trong Data Room."
NO_SUMMARY_ROLE_MESSAGE = "Tài khoản của bạn chưa được cấp quyền tóm tắt tài liệu."
FOCUSED_PASSAGES = 3   # retry size when the model finds nothing although the reranker found a strong match
RETRY_MIN_RERANK = 0.5


@dataclass
class Deps:
    embed_query: Callable | None = None
    rerank: Callable | None = None
    llm: Callable | None = None
    nli: Callable | None = None
    embed_many: Callable | None = None     # batch embeddings (input guard scores parts of long questions)
    llm_quotes: Callable | None = None     # quote mode: model picks sentence ids, quotes are the sentences
    nli_many: Callable | None = None       # NLI for all claims in one batch
    rewrite: Callable | None = None        # follow-up question -> standalone question (conversation context)

    @classmethod
    def real(cls) -> "Deps":
        from dr.models import embed, llm, nli, rerank
        return cls(embed.embed_query, rerank.rerank, llm.answer_json, nli.entail, embed_many=embed.embed_texts,
                   llm_quotes=llm.answer_quotes, nli_many=nli.entail_many, rewrite=llm.rewrite_question)


@dataclass
class Trace:
    steps: list[dict] = field(default_factory=list)
    _t: float = field(default_factory=time.time)
    on_step: Callable | None = None        # progress callback (streamed to the UI); never sees answer content

    def add(self, step: str, ok: bool, **detail):
        now = time.time()
        self.steps.append({"step": step, "ok": ok, "ms": int((now - self._t) * 1000), **detail})
        self._t = now
        if self.on_step:
            try:
                self.on_step({"step": step, "ok": ok, "ms": self.steps[-1]["ms"]})
            except Exception:
                pass

    def stage(self, name: str):
        """Announce the stage that is about to run (progress only, not part of the trace)."""
        if self.on_step:
            try:
                self.on_step({"stage": name})
            except Exception:
                pass


_MARKER = re.compile(r"mã kiểm soát:?\s*ks-[a-z]+-\d{4}", re.IGNORECASE)


def _signature(text: str) -> str:
    """Content signature ignoring per-document control markers, case and spacing."""
    return hashlib.sha1(verify.norm(_MARKER.sub(" ", text)).encode()).hexdigest()


def _weight(p: dict) -> float:
    """Trust in the source: a rejected / old version lower, a signed / approved / legal document higher."""
    return conflicts.source_weight(p.get("path", ""), p["name"])


OLD_VERSION = 0.9      # another file of the same name with a later date / version is in the candidates


def rank_weights(order: list[int], passages: dict[int, dict]) -> dict[int, float]:
    """Each candidate's trust (_weight), a little lower when a later version of its file is a candidate too."""
    older = conflicts.older_versions({passages[c]["item_id"]: passages[c]["name"] for c in order})
    return {c: _weight(passages[c]) * (OLD_VERSION if passages[c]["item_id"] in older else 1.0) for c in order}


def _date_note(p: dict) -> str:
    d = conflicts.doc_date(p["name"])
    return f", ngày {d:%d/%m/%Y}" if d else ""


def _with_context(p: dict) -> str:
    """A passage as the reranker sees it: where its file sits (company › project › folder › file), then the text."""
    return f"{p['context']}\n{p['text']}" if p.get("context") else p["text"]


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


def _call(fn, *args, **kwargs):
    """Pass only the keyword arguments fn accepts (test stubs take (question, passages, lang))."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(*args, **kwargs)
    if any(p.kind is p.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kwargs)
    return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


def _source(p: dict) -> str:
    """The passage's place as the model sees it; with DR_DOCTYPE its kind first (survives the 160-char cut)."""
    src = p.get("context") or p["name"]
    kind = doctype.classify(p.get("path", ""), p["name"]) if settings.doc_type else ""
    return f"loại: {kind} · {src}" if kind else src


def vote(runs: list[tuple[dict, dict]], passages: dict[int, dict], question: str) -> tuple[tuple[dict, dict], int]:
    """DR_VOTE: of several sampled answers, the one whose verified claims most samples agree on (same figures, or
    the same words when there is no figure); the first (temperature 0) wins a tie. -> (run, how many agree)."""
    sigs = []
    for raw, labels in runs:
        kept, _ = verify.check(raw.get("claims", []), labels, passages, question)
        nums = sorted({re.sub(r"\D", "", d) for cl in kept for d, _ in verify.numbers_with_digits(cl.text)})
        sigs.append(tuple(nums) if nums else tuple(sorted(verify.norm(cl.text) for cl in kept)))
    counts = {sig: sigs.count(sig) for sig in sigs if sig}
    if not counts:
        return runs[0], 0
    best = max(counts.values())
    k = next(k for k, sig in enumerate(sigs) if counts.get(sig) == best)
    return runs[k], best


def document_chunks(oid: str, codes: list[str], files: list[str], limit: int = 400) -> list[int]:
    """All current chunks, in reading order, of the documents a question names (by control code
    or file name) that this user can read (RLS)."""
    from dr.db import pg
    if not codes and not files:
        return []
    with pg.as_principal(oid) as cur:
        items = {r[0] for r in cur.execute(
            "SELECT DISTINCT c.item_id FROM chunks c JOIN items i ON i.item_id = c.item_id "
            "WHERE (c.text LIKE ANY(%s) OR lower(i.name) = ANY(%s)) LIMIT 5",
            ([f"%{c}%" for c in codes] or ["\x01"], [f.lower() for f in files] or [""])).fetchall()}
        if not items:
            return []
        rows = cur.execute("SELECT c.chunk_id FROM chunks c JOIN items i ON i.item_id = c.item_id AND i.ctag = c.ctag "
                           "WHERE c.item_id = ANY(%s) ORDER BY c.item_id, c.ordinal LIMIT %s",
                           (sorted(items), limit)).fetchall()
    return [r[0] for r in rows]


def item_texts(oid: str, item_ids: set[str], limit: int = 2000) -> dict[str, str]:
    """The current text of each document, its chunks in reading order, as far as this user can read it (RLS)."""
    from dr.db import pg
    if not item_ids:
        return {}
    try:
        with pg.as_principal(oid) as cur:
            rows = cur.execute("SELECT c.item_id, c.text FROM chunks c JOIN items i ON i.item_id = c.item_id AND "
                               "i.ctag = c.ctag WHERE c.item_id = ANY(%s) ORDER BY c.item_id, c.ordinal LIMIT %s",
                               (sorted(item_ids), limit)).fetchall()
    except Exception:            # no database (unit tests on stubs): the cited passages alone are the evidence
        return {}
    out: dict[str, list[str]] = {}
    for it, text in rows:
        out.setdefault(it, []).append(text)
    return {it: "\n".join(ts) for it, ts in out.items()}


def item_chunks(oid: str, item_id: str, limit: int = 400) -> list[int]:
    """All current chunks, in reading order, of one document the user picked (RLS: none if not readable
    or not usable with AI)."""
    from dr.db import pg
    with pg.as_principal(oid) as cur:
        rows = cur.execute("SELECT c.chunk_id FROM chunks c JOIN items i ON i.item_id = c.item_id AND i.ctag = c.ctag "
                           "WHERE c.item_id = %s ORDER BY c.ordinal LIMIT %s", (item_id, limit)).fetchall()
    return [r[0] for r in rows]


# Summary of a picked document (BRD mục 3 #5). The instruction is fixed here, never taken from the client and
# never holding the file name, so no user- or uploader-written text reaches the model outside the
# <untrusted_document> blocks; the input guard (meant for typed questions) is therefore not run on it.
DOC_SUMMARY_Q = {
    "vi": ("Tóm tắt đầy đủ tài liệu này theo đúng thứ tự của tài liệu, nêu mọi nội dung chính (các bên liên quan, "
           "mục đích, số liệu, ngày tháng, điều khoản và nghĩa vụ, quyết định, kết luận), không bỏ sót phần nào."),
    "en": ("Summarise this document in full, in the document's order, stating every main point (parties, purpose, "
           "figures, dates, terms and obligations, decisions, conclusions), leaving no part out."),
}
DOC_PLAN = intent.Plan("summary", 60, 60, 48, 12, False, False)   # one part: every chunk of it, up to 12 points
DOC_PART_CHARS = 4000    # characters of one part: small enough that 12 points cover it
SUMMARY_PARTS = 6        # a longer document is summarised in at most this many consecutive parts (one model call each)


def summary_parts(sizes: list[tuple[int, int, int]], budget: int, max_sentences: int) -> list[list[int]]:
    """sizes: (chunk_id, characters, sentences) in reading order -> consecutive runs of chunks, each small
    enough to be read whole by one model call, at most SUMMARY_PARTS runs of about equal length."""
    if not sizes:
        return []
    chars, sents = sum(s[1] for s in sizes), sum(s[2] for s in sizes)
    k = min(SUMMARY_PARTS, max(1, -(-chars // max(1, budget)), -(-sents // max(1, max_sentences))))
    runs, cur, used = [], [], 0
    for cid, n, _ in sizes:
        if cur and used + n > chars * (len(runs) + 1) / k and len(runs) < k - 1:
            runs.append(cur)
            cur = []
        cur.append(cid)
        used += n
    return runs + [cur]


def summarize_document(tenant: FakeTenant, index: SearchIndex, oid: str, roles: list[str], item_id: str,
                       deps: Deps, lang: str = "vi", on_step: Callable | None = None) -> dict:
    """The whole picked document, nothing left out: each consecutive part is summarised, verified and
    live-checked like any answer, and the points are joined in reading order with their sources."""
    from dr.models.llm import split_sentences
    question = DOC_SUMMARY_Q.get(lang, DOC_SUMMARY_Q["vi"])
    ids = item_chunks(oid, item_id)
    texts = gates.fetch_passages(oid, ids)
    runs = summary_parts([(c, len(texts[c]["text"]), len(split_sentences(texts[c]["text"]))) for c in ids if c in texts],
                         DOC_PART_CHARS, DOC_PLAN.sentences) or [None]
    results = []
    for k, run in enumerate(runs, 1):
        if len(runs) > 1 and on_step:
            on_step({"step": f"Tóm tắt phần {k}/{len(runs)}", "ok": True, "ms": 0})
        r = ask(tenant, index, oid, roles, question, deps, on_step=on_step, item_id=item_id, part=run)
        if r["refused"] and r.get("message") != lang_mod.tr(NEUTRAL_REFUSAL, r.get("lang", lang)):
            return r                     # blocked, unavailable, retry…: no partial summary is released
        results.append(r)
    good = [r for r in results if not r["refused"] and r["claims"]]
    if len(results) == 1 or not good:
        return good[0] if good else results[0]
    claims, cites, number = [], [], {}
    for r in good:                       # citations renumbered across parts, the same sentence cited once
        remap = {}
        for c in r["citations"]:
            key = (c["item_id"], c.get("chunk_id"), c.get("quote"))
            if key not in number:
                number[key] = len(cites) + 1
                cites.append({**c, "n": number[key]})
            remap[c["n"]] = number[key]
        claims += [{**cl, "refs": [remap[n] for n in cl["refs"] if n in remap]} for cl in r["claims"]]
    trace = [s for k, r in enumerate(results, 1)
             for s in [{"step": f"Tóm tắt phần {k}/{len(runs)}", "ok": True, "ms": 0}] + r["trace"]]
    return {**good[-1], "claims": claims, "citations": cites, "trace": trace, "parts": len(runs)}


def spread(seq: list, n: int) -> list:
    """n items evenly spaced over seq, first and last included, in order: a long document is read at
    its beginning, middle and end instead of its first pages only."""
    seq = list(seq)
    if n <= 0 or len(seq) <= n:
        return seq
    if n == 1:
        return seq[:1]
    return [seq[round(k * (len(seq) - 1) / (n - 1))] for k in range(n)]


def sheet_chunks(oid: str, item_id: str, sheet: str, limit: int = 60) -> list[int]:
    """All current chunks of one spreadsheet sheet, in reading order, that this user can read (RLS)."""
    from dr.db import pg
    with pg.as_principal(oid) as cur:
        rows = cur.execute("SELECT c.chunk_id FROM chunks c JOIN items i ON i.item_id = c.item_id AND i.ctag = c.ctag "
                           "WHERE c.item_id = %s AND c.locator LIKE %s ORDER BY c.ordinal LIMIT %s",
                           (item_id, sheet.replace("%", r"\%").replace("_", r"\_") + "!%", limit)).fetchall()
    return [r[0] for r in rows]


_BOILERPLATE = re.compile(r"(^|[.!?]\s)\s*(pham vi chia se|phan loai|scope of sharing|classification)\s*:")


MAX_SENTENCE_CHARS = 400        # a merged table row can run to thousands of characters


def _clip(sentence: str, question: str = "") -> str:
    """A long sentence cut at word boundaries; still a substring of the passage, so quotes verify. A merged table
    row is cut around what the question asks (its column label and the value after it), not at its beginning:
    the first window holding most of the question's key terms, started a little before the first of them."""
    if len(sentence) <= MAX_SENTENCE_CHARS:
        return sentence
    start = 0
    terms = intent.key_terms(question)
    if terms:
        # words (start, end, key term or None); a window of words starting at word i, two pointers over them
        words = [(m.start(), m.end(), next(iter(intent.key_terms(m.group(0))), None))
                 for m in re.finditer(r"\S+", sentence)]
        best, first, j, count = 0, 0, 0, {}
        for i, (a, _, _) in enumerate(words):
            while j < len(words) and words[j][1] <= a + MAX_SENTENCE_CHARS:
                if words[j][2] in terms:
                    count[words[j][2]] = count.get(words[j][2], 0) + 1
                j += 1
            if len(count) > best:
                best, first = len(count), i
            t = words[i][2]
            if t in count:
                count[t] -= 1
                if not count[t]:
                    del count[t]
        if best:
            # the earliest window with the most key terms, started at its first key term: a label and the value
            # after it stay together
            start = next(a for a, _, t in words[first:] if t in terms)
            back = sentence.rfind(" ", 0, max(0, start - 60))
            start = back + 1 if back >= 0 and start - back < 120 else start
    cut = sentence[start:start + MAX_SENTENCE_CHARS]
    if start + MAX_SENTENCE_CHARS < len(sentence) and " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut


FOCUS_EXTRA = 4      # sentences kept beyond the n best (neighbours, one per passage, the question's codes)


def must_keep(question: str, sents: list[tuple[int, int, str]], ranked: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sentences (passage, sentence) to keep beside the n best, most useful first: the one naming a code or
    figure of the question (SH09, 2024), the sentence after and before each of the two best, and each passage's
    best sentence (a passage that was selected is never sent empty)."""
    have = {(i, j) for i, j, _ in sents}
    text = {(i, j): s for i, j, s in sents}
    rank = {k: r for r, k in enumerate(ranked)}
    out: list[tuple[int, int]] = []
    anchors = [t for t in verify.codes(question, set()) if any(ch.isdigit() for ch in t)]
    anchors += [d for d, _ in verify.numbers_with_digits(question) if len(re.sub(r"\D", "", d)) >= 3]
    if anchors:
        hit = [k for k in ranked if any(f" {verify.norm(a)} " in f" {verify.norm(text[k])} " for a in anchors)]
        out += hit[:2]
    for i, j in ranked[:2]:
        out += [k for k in ((i, j + 1), (i, j - 1)) if k in have]
    best: dict[int, tuple[int, int]] = {}
    for k in ranked:
        best.setdefault(k[0], k)
    out += sorted(best.values(), key=lambda k: rank[k])
    return list(dict.fromkeys(out))


def focus_sentences(question: str, llm_in: list[dict], deps: Deps, trace: Trace, n: int | None = None,
                    keep_order_only: bool = False, queries: list[str] | None = None,
                    budget: int | None = None) -> list[dict]:
    """Keep only the n sentences the reranker scores highest (in their original order). The kept
    text is a subset of each passage, so quotes still verify against the full passage; passages
    left with no sentence are not sent. keep_order_only: a whole document is summarised, so
    sentences spread over all of it are kept in reading order instead (as many as the budget holds)."""
    from dr.models.llm import split_sentences
    n = settings.max_sentences if n is None else n
    if not n or not deps.rerank:
        return llm_in
    sents, seen = [], set()
    for i, p in enumerate(llm_in):
        for j, s in enumerate(split_sentences(p["text"])):
            key = verify.norm(s)
            # boilerplate footers ("Phạm vi chia sẻ…", "Phân loại…") and repeats carry nothing to answer from
            if key in seen or _BOILERPLATE.search(unidecode(s).lower()):
                continue
            seen.add(key)
            sents.append((i, j, _clip(s, question)))
    if keep_order_only:
        avg = sum(len(s) for _, _, s in sents) / max(1, len(sents))
        ranked = spread([(i, j) for i, j, _ in sents], min(n, max(1, int(budget // avg))) if budget and avg else n)
    else:
        texts = [s for _, _, s in sents]
        scores = deps.rerank(question, texts)
        for extra in queries or []:              # several-part question: best match over the parts
            scores = [max(a, b) for a, b in zip(scores, deps.rerank(extra, texts))]
        ranked = [(i, j) for (i, j, _), _ in sorted(zip(sents, scores), key=lambda x: -x[1])]
    # best sentences first, up to n sentences and a character budget (prompt reading is the slow half)
    length = {(i, j): len(s) for i, j, s in sents}
    keep, used = set(), 0
    for key in ranked[:n]:
        if budget and keep and used + length[key] > budget:
            continue
        keep.add(key)
        used += length[key]
    if not keep_order_only:
        # the answer often sits just next to the best match: a value on the line after its label (OCR, tables),
        # in a passage the reranker liked less, or in the one sentence naming the unit/figure the question names
        for key in must_keep(question, sents, ranked):
            if len(keep) >= n + FOCUS_EXTRA:
                break
            if key not in keep:
                keep.add(key)
                used += length[key]
    out = []
    for i, p in enumerate(llm_in):
        kept = [s for (pi, j, s) in sents if pi == i and (pi, j) in keep]
        if kept:
            # a blank line between kept sentences: a clipped one has no final stop, and the prompt's
            # line unwrapping would otherwise glue it to the next kept sentence (not adjacent in the
            # document), giving a quote that fails verification although the answer was right
            out.append({**p, "text": "\n\n".join(kept)})
    trace.add("Chọn câu liên quan trong các đoạn (rerank theo câu)", True, sentences=f"{len(keep)}/{len(sents)}",
              passages=len(out), chars=used)
    return out


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
        deps: Deps, scope_site: str | None = None, on_step: Callable | None = None,
        history: list[conversation.Turn] | None = None, item_id: str | None = None,
        part: list[int] | None = None) -> dict:
    trace = Trace(on_step=on_step)
    if item_id and question not in DOC_SUMMARY_Q.values():
        question = DOC_SUMMARY_Q["vi"]            # a picked document only ever gets the fixed instruction
    question = guard.strip_controls(question).strip()[:1000]
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
    if item_id:
        qvec = None
        trace.add("Lớp đầu vào – câu lệnh tóm tắt cố định của hệ thống (không có chữ người dùng)", True)
    elif settings.input_guard:
        clean_q = guard.clean(question)
        qvec = deps.embed_query(clean_q) if deps.embed_query else None
        v = guard.inspect(question, qvec, deps.embed_many)
        recap_ok = bool(history) and conversation.is_recap(question) and not v.rules \
            and bool(conversation.cited_chunks(history))
        trace.add("Lớp đầu vào – chuẩn hóa, luật chống prompt injection, bộ phân loại", not v.blocked or recap_ok,
                  rules=v.rules, score=v.score, normalized=v.changed, recap=recap_ok or None)
        # "Tổng hợp lại" reads like prompt extraction to the classifier (0.8–0.9), but a recap never sends
        # the question's words to the model (it re-reads cited chunks), so only a rule hit blocks it
        if v.blocked and not recap_ok:
            return refuse(BLOCKED_MESSAGE, kind="input_blocked",
                           extra={"rules": v.rules, "score": v.score})
        question = clean_q
    else:
        qvec = deps.embed_query(question) if deps.embed_query else None
    # ---- conversation context: "tổng hợp lại" re-reads what this conversation cited; a follow-up is
    # rewritten into a standalone question (the rewrite passes the input guard like a typed question)
    asked, recap_chunks, context_chunks = question, [], []
    if history:
        if conversation.is_recap(question) and conversation.cited_chunks(history):
            recap_chunks = conversation.cited_chunks(history)
            question = ("Tổng hợp các nội dung đã trao đổi: " if lang == "vi" else "Summary of what was discussed: ") + \
                "; ".join(t.standalone for t in history)[:600]
            trace.add("Tổng hợp cuộc trò chuyện → đọc lại các đoạn đã trích", True, turns=len(history),
                      chunks=len(recap_chunks))
        elif deps.rewrite and conversation.needs_context(question):
            trace.stage("context")
            rw = guard.strip_controls(deps.rewrite(question, conversation.context_text(history))).strip()[:500]
            if rw and rw != question:
                rvec = deps.embed_query(rw) if deps.embed_query else None
                blocked = settings.input_guard and guard.inspect(rw, rvec, deps.embed_many).blocked
                if not blocked:
                    question, qvec = (guard.clean(rw) if settings.input_guard else rw), rvec
            context_chunks = conversation.cited_chunks(history, last=1)
            trace.add("Câu hỏi nối tiếp → viết lại theo ngữ cảnh cuộc trò chuyện", True,
                      rewritten=question != asked, standalone=question[:200])
    # ---- a question about another investor group is answered from shared documents only
    other = audience.other_groups_only(oid, question)

    def out_of_scope() -> dict:
        r = refuse(OUT_OF_SCOPE_MESSAGE, kind="out_of_scope", extra={"groups": other})
        r["out_of_scope"] = True
        return r

    def nothing_found(**kw) -> dict:
        return out_of_scope() if other else refuse(NEUTRAL_REFUSAL, **kw)
    if other:
        trace.add("Câu hỏi về nhóm nhà đầu tư khác → chỉ dùng tài liệu chung", True, groups=other)

    # ---- sensitive topics (BRD BR-08): not answered by the AI; the asker is pointed to a person
    topics = review.topics_of(question)
    is_staff = "Staff.AI" in set(g.detail.get("roles_mirror", []))
    if other and topics:
        return out_of_scope()      # another group's sensitive matter: nothing anyone here could release
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
    # ---- the question that is searched and read: its core (a preface is dropped), English terms
    # glossed in Vietnamese, and for a several-part question each part on its own
    q_core = intent.core_question(question)
    if lang == "vi" and accents.unaccented(q_core):
        q_core = accents.restore(q_core)          # "Dinh gia noi bo" -> "Định giá nội bộ" (shared-site vocabulary)
    glossed = (lambda t: intent.expand_en(t)) if lang == "en" else (lambda t: t)
    q_search = glossed(q_core)
    if q_search != question:
        trace.add("Câu hỏi dùng để tìm", True, core=q_core[:200], glossed=q_search != q_core)
        if deps.embed_query:
            qvec = deps.embed_query(q_search)
    # ---- what kind of answer the question asks for (fact / summary / compare / list / full text)
    plan = intent.plan_for(question)
    may_summarise = settings.answer_mode != "role" or bool(
        {"Investor.AI.Summarize", "Staff.AI"} & set(g.detail.get("roles_mirror", [])))
    if not may_summarise:
        plan = intent.PLANS["full"]                       # BRD v1.4 BR-04: no summarize role -> quotes only
    codes, files_named = intent.named_documents(question)
    whole_doc = document_chunks(oid, codes, files_named) if (codes or files_named) and plan.intent != "fact" else []
    if (codes or files_named) and not whole_doc and plan.intent == "fact" and re.search(
            r"noi (ve )?(noi dung )?gi|about what|what does", unidecode(question).lower()):
        plan = intent.PLANS["summary"]
        whole_doc = document_chunks(oid, codes, files_named)
    if item_id:                                  # a document the user picked to summarise (BRD mục 3 #5)
        if not may_summarise:
            trace.add("Vai trò không có quyền tóm tắt (BR-04)", False)
            return refuse(NO_SUMMARY_ROLE_MESSAGE, kind="no_summary_role")
        plan, whole_doc = DOC_PLAN, part or item_chunks(oid, item_id)
        if not whole_doc:
            return nothing_found()
    if recap_chunks:
        plan, whole_doc = intent.PLANS["summary"], recap_chunks
    parts = [glossed(p) for p in intent.sub_questions(q_core)] if not whole_doc and not plan.verbatim else []
    if parts and plan.intent == "fact":
        plan = intent.PLANS["multi"]
    trace.add("Phân loại câu hỏi", True, intent=plan.intent, named_document=bool(whole_doc), parts=len(parts))

    trace.stage("search")
    versions: dict[int, list[int]] = {}      # representative chunk -> other copies / versions of its text
    if whole_doc:
        hits = [(c, 1.0) for c in whole_doc]
        trace.add("Đọc toàn bộ tài liệu được chọn (RLS)" if item_id else "Đọc toàn bộ tài liệu được nêu tên (RLS)",
                  True, chunks=len(hits))
    else:
        # a several-part question searches the whole question AND each part: on the evaluation set the
        # answer passages reached the model for 9/13 parts this way, 7/13 whole-question only, 8/13 parts only
        part_hits: dict[str, list] = {}
        for qq in [q_search] + parts:
            v = qvec if qq == q_search else (deps.embed_query(qq) if deps.embed_query else None)
            k = max(settings.rerank_top, plan.passages * 3) if qq == q_search else max(16, settings.rerank_top // 2)
            if getattr(index, "in_db", False):
                part_hits[qq], info = index.search_as(oid, qq, v, k=k, site=scope_site)
            else:
                part_hits[qq], info = index.search(set(allowed), qq, v, k=k), {}
            for rep, others in info.pop("versions", {}).items():     # other versions: for the conflict check
                versions.setdefault(rep, []).extend(others)
        hits, have = [], set()
        for hs in part_hits.values():
            hits += [h for h in hs if h[0] not in have and not have.add(h[0])]
        # a follow-up also considers what the previous answer cited (still filtered by RLS and reranked)
        hits += [(c, 0.0) for c in context_chunks if c not in have and not have.add(c)]
        trace.add("Tìm kiếm lai BM25 + vector (RLS ngay trong câu truy vấn)", True, hits=len(hits),
                  parts=len(parts), **info)
    passages = gates.fetch_passages(oid, [cid for cid, _ in hits])
    order = [cid for cid, _ in hits if cid in passages]
    if other:
        # never answer a question about group X from the asker's own group documents
        own = len(order)
        order = [c for c in order if passages[c]["site_id"] not in audience.group_sites()]
        trace.add("Bỏ tài liệu riêng của nhóm mình khỏi câu hỏi về nhóm khác", True, kept=len(order),
                  dropped=own - len(order))
        if not order:
            return out_of_scope()

    top_rerank = None
    if deps.rerank and order and not whole_doc and parts:
        # each part ranks its own candidates; the lists are interleaved so every part gets passages
        allowed_order = set(order)
        weight = rank_weights(order, passages)
        ranked = []
        for qq in [q_search] + parts:
            cand = [c for c, _ in part_hits[qq] if c in allowed_order]
            sc = [s * weight[c] for s, c in
                  zip(deps.rerank(qq, [_with_context(passages[c]) for c in cand]) if cand else [], cand)]
            ranked.append([c for _, c in sorted(zip(sc, cand), key=lambda x: -x[0])])
            top_rerank = max([top_rerank or 0.0, *sc]) if sc else top_rerank
        order, seen_o = [], set()
        for row in zip(*[r + [None] * (max(map(len, ranked)) - len(r)) for r in ranked]):
            for c in row:
                if c is not None and c not in seen_o:
                    seen_o.add(c)
                    order.append(c)
        trace.add("Rerank bge-reranker-v2-m3 theo từng phần", True, parts=len(parts),
                  top_score=round(top_rerank, 3) if top_rerank is not None else None)
    elif deps.rerank and order and not whole_doc:
        weight = rank_weights(order, passages)
        scores = [s * weight[c] for s, c in
                  zip(deps.rerank(q_search, [_with_context(passages[c]) for c in order]), order)]
        top_rerank = max(scores) if scores else None
        for c, s in zip(order, scores):
            passages[c]["rerank"] = s
        order = [c for _, c in sorted(zip(scores, order), key=lambda x: -x[0])]
        trace.add("Rerank bge-reranker-v2-m3", True, top_score=round(max(scores), 3) if scores else None)

    # ---- a question over several rows of a table (extreme, comparison, total) whose best match is a
    # spreadsheet row: the whole sheet is read, not five scattered rows (RLS on every chunk as usual)
    if not whole_doc and order and intent.TABLE_Q.search(unidecode(q_search).lower()):
        top = passages[order[0]]
        m = re.match(r"(.+?)!A\d+", top["locator"] or "")
        if m:
            ids = sheet_chunks(oid, top["item_id"], m.group(1))
            if 1 < len(ids) <= 40:
                passages.update(gates.fetch_passages(oid, [c for c in ids if c not in passages]))
                ids = [c for c in ids if c in passages]
                order = ids + [c for c in order if c not in set(ids)]
                plan = intent.PLANS["table"]
                trace.add("Câu hỏi trên bảng → đọc cả sheet", True, sheet=m.group(1), chunks=len(ids))

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
    trace.stage("live")
    chosen: list[str] = []
    dropped_live: dict[str, str] = {}
    transient = False
    i = 0
    max_files = max(settings.max_files, plan.passages)
    while len(chosen) < max_files and i < len(files):
        batch = files[i:i + (max_files - len(chosen))]
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

    n_pass = settings.max_passages if plan.intent == "fact" else plan.passages
    if whole_doc:
        selected = spread([c for c in order if passages[c]["item_id"] in set(chosen)], 60)
    else:
        selected = select_passages(order, passages, set(chosen), n_pass, plan.per_file)
    if not selected:
        return nothing_found()
    sel_passages = {c: passages[c] for c in selected}
    flagged = [c for c in selected if passages[c]["injection_flag"]]
    if flagged:
        trace.add("Đoạn bị gắn cờ prompt injection (vẫn bọc là dữ liệu)", True, chunks=len(flagged))

    # ---- LLM
    # Full-text questions get the source sentences themselves: the model just picks sentence ids.
    verbatim = plan.verbatim
    llm_call = deps.llm_quotes if verbatim and deps.llm_quotes else deps.llm
    llm_in = [{"chunk_id": c, "text": passages[c]["text"], "source": _source(passages[c])} for c in selected]
    n_sent = settings.max_sentences if plan.intent == "fact" else plan.sentences
    llm_in = focus_sentences(q_search, llm_in, deps, trace, n=n_sent, keep_order_only=bool(whole_doc),
                             queries=parts, budget=settings.prompt_chars_fact if plan.intent == "fact"
                             else settings.prompt_chars_wide)
    trace.stage("llm")
    q_llm = q_search
    if parts:                                    # name every part, so a comparison is not misread
        q_llm += "\nCác phần cần trả lời: " + "; ".join(f"({k}) {p}" for k, p in enumerate(parts, 1))
    # smallest / largest over the rows of a sheet: arithmetic, done on the rows themselves (the model
    # copied the right figure under the wrong row's name); the answer cites the row and is verified as usual
    det = None
    if plan.intent == "table":
        rows_in = [{"chunk_id": c, "text": sel_passages[c]["text"]} for c in selected]
        det = tables.extreme(q_search, rows_in) or tables.compare(q_search, rows_in)
    if det:
        trace.add("Bảng: lớn nhất/nhỏ nhất hoặc so sánh tính trực tiếp trên các dòng (không qua LLM)", True,
                  rows=len(det[0]["claims"]))
    # a document number, a plot, a tax code: looked up in the fact index (facts.py) instead of read by the
    # model from a long OCR page. Facts come under RLS, their files are live-checked like any passage, and the
    # answer cites the source lines and is verified as usual. Several fitting values are all given.
    if not det and not whole_doc and plan.intent in ("fact", "multi"):
        found = facts.lookup(oid, q_search)
        fps = gates.fetch_passages(oid, [r["chunk_id"] for r in found]) if found else {}
        live = gates.live_check(tenant, oid, {p["item_id"]: p["ctag"] for p in fps.values()}) if fps else {}
        found = [r for r in found if r["chunk_id"] in fps and live[fps[r["chunk_id"]]["item_id"]][0]]
        if found:
            labels, claims = {}, []
            for k, r in enumerate(found, 1):
                labels[f"F{k}"] = r["chunk_id"]
                sel_passages[r["chunk_id"]] = fps[r["chunk_id"]]
                cites = [{"doc": f"F{k}", "quote": q} for q in r["quotes"]]
                # a project or code the question names ('MONTALP') that the fact's own passage does not: the line
                # of the same document naming it is cited too (the plot is in clause 2.2, the project on page 1),
                # so the answer shows why the document is about it and passes the named-code check honestly
                for line, p in facts.naming_lines(oid, q_search, r["item_id"], fps[r["chunk_id"]]["text"]):
                    labels[f"F{k}N{p['chunk_id']}"] = p["chunk_id"]
                    sel_passages[p["chunk_id"]] = p
                    cites.append({"doc": f"F{k}N{p['chunk_id']}", "quote": line})
                claims.append({"text": facts.claim_for(r), "citations": cites})
            det = ({"claims": claims, "no_answer": False}, labels)
            trace.add("Chỉ mục dữ kiện: trả lời bằng tra cứu (không qua LLM)", True, facts=len(claims))
    if det:
        raw, labels = det
    else:
        try:
            raw, labels = _call(llm_call, q_llm, llm_in, lang=lang, style=plan.intent, max_claims=plan.claims)
        except Exception as e:                       # model timeout or outage: say so, never guess
            trace.add(f"LLM {settings.llm_model} không phản hồi", False, error=type(e).__name__)
            return refuse(RETRY_MESSAGE, kind="llm_unavailable")
        from dr.models import llm as _llm_mod
        trace.add(f"LLM {settings.llm_model} ({'chọn câu nguyên văn theo mã' if llm_call is deps.llm_quotes else 'JSON có ràng buộc'}"
                  f" · {plan.intent})", True, raw_claims=len(raw.get("claims", [])), passages=len(llm_in),
                  **(_llm_mod.last_stats() if llm_call in (getattr(_llm_mod, "answer_json", None),
                                                           getattr(_llm_mod, "answer_quotes", None)) else {}))
        if settings.vote > 1:
            runs = [(raw, labels)]
            for k in range(1, settings.vote):
                try:
                    runs.append(_call(llm_call, q_llm, llm_in, lang=lang, style=plan.intent, max_claims=plan.claims,
                                      sample=k))
                except Exception:
                    pass
            (raw, labels), agree = vote(runs, sel_passages, question)
            trace.add(f"Bỏ phiếu {len(runs)} lần trả lời", True, agree=agree)

    # ---- deterministic verification
    kept, dropped = verify.check(raw.get("claims", []), labels, sel_passages, question)
    trace.add("Kiểm chứng tất định (trích dẫn nguyên văn, con số)", True, kept=len(kept), dropped=len(dropped),
              dropped_reasons=[r for _, r in dropped])
    if not kept and len(llm_in) > FOCUSED_PASSAGES and plan.intent == "fact" and (
            top_rerank is None or top_rerank >= RETRY_MIN_RERANK):
        # The local model sometimes misses a fact that is there (long context, GPU non-determinism):
        # when the reranker found a strong match, retry once on the top passages only.
        focus = llm_in[:FOCUSED_PASSAGES]
        try:
            raw, labels = _call(llm_call, q_llm, focus, lang=lang, style=plan.intent, max_claims=plan.claims)
        except Exception as e:
            trace.add(f"LLM {settings.llm_model} không phản hồi (lần thử lại)", False, error=type(e).__name__)
            raw, labels = {"claims": []}, {}
        kept, dropped2 = verify.check(raw.get("claims", []), labels,
                                      {p["chunk_id"]: sel_passages[p["chunk_id"]] for p in focus}, question)
        dropped += dropped2
        trace.add(f"Thử lại có trọng tâm ({FOCUSED_PASSAGES} đoạn đầu) + kiểm chứng", True, kept=len(kept),
                  dropped_reasons=[r for _, r in dropped2])
    if not kept and not det and settings.llm_fallback and settings.llm_fallback != settings.llm_model:
        # nothing of the small model's answer held up: the larger model reads the same passages once
        try:
            raw, labels = _call(llm_call, q_llm, llm_in, lang=lang, style=plan.intent, max_claims=plan.claims,
                                model=settings.llm_fallback)
            kept, dropped3 = verify.check(raw.get("claims", []), labels, sel_passages, question)
            dropped += dropped3
            trace.add(f"Hỏi model dự phòng {settings.llm_fallback} + kiểm chứng", True, kept=len(kept),
                      dropped_reasons=[r for _, r in dropped3])
        except Exception as e:
            trace.add(f"Model dự phòng {settings.llm_fallback} không phản hồi", False, error=type(e).__name__)
    # ---- relevance (short answers): a verified sentence can still answer another question
    # (asked for the fee, the lock-up sentence of the same term sheet); drop such claims.
    # Calibrated on the fact set: the reranker alone also dropped right answers (0.003 for a correct
    # fee claim), so a claim is kept when the reranker OR the question's key terms vouch for it.
    # A question about another investor group is answered from shared documents only when the answer
    # really addresses it (both signals), otherwise the polite out-of-scope message is better than a
    # loosely related line ("room" in "Data Room" vs "foreign ownership room").
    if (plan.relevance or other) and deps.rerank and kept and settings.relevance_min > 0:
        # the cited documents' place (company › project › folder) is part of what the claim is about: a poster
        # line "Thu nhập 50tr mỗi tháng" answers a question about the Léman Parking Lot job ad only through it
        texts = [" ".join([cl.text, *(c.quote for c in cl.citations),
                           *dict.fromkeys(sel_passages[c.chunk_id].get("context", "") for c in cl.citations)])
                 for cl in kept]
        rel = deps.rerank(q_search, texts)
        ovl = [intent.term_overlap(q_search, t) for t in texts]
        # the cited documents themselves (whole text, folders, file name; read under RLS) must hold the question's
        # key terms: the claim's own words cannot vouch for it
        docs = item_texts(oid, {sel_passages[c.chunk_id]["item_id"] for cl in kept for c in cl.citations})
        ev = [intent.evidence_overlap(q_search, [" ".join([docs.get(p["item_id"], p["text"]), p.get("context") or "",
                                                           p.get("path") or ""])
                                                 for p in (sel_passages[c.chunk_id] for c in cl.citations)])
              for cl in kept]
        ok = [((r >= settings.relevance_min and o >= settings.relevance_overlap) if other else
               (r >= settings.relevance_min or o >= settings.relevance_overlap)) and e >= settings.relevance_evidence
              for r, o, e in zip(rel, ovl, ev)]
        kept = [cl for cl, k in zip(kept, ok) if k]
        trace.add("Kiểm tra đúng trọng tâm câu hỏi", True, dropped=ok.count(False),
                  scores=[round(r, 3) for r in rel], overlap=[round(o, 2) for o in ovl],
                  evidence=[round(e, 2) for e in ev])
    # NLI is a secondary signal; a verbatim answer IS its quotes, so there is nothing to score
    if (deps.nli or deps.nli_many) and kept and not verbatim:
        trace.stage("verify")
        pairs = [(" ".join(c.quote for c in cl.citations), cl.text) for cl in kept]
        scores = deps.nli_many(pairs) if deps.nli_many else [deps.nli(a, b) for a, b in pairs]
        for cl, sc in zip(kept, scores):
            cl.nli = round(sc, 3)
        trace.add("NLI mDeBERTa (tín hiệu phụ)", True, scores=[cl.nli for cl in kept])

    # ---- documents that disagree: another version of the same unit gives another number. Every value is
    # shown with its source and date instead of one picked silently (two B4 floor plans: 52.55 / 52.88 m²).
    found_conflicts = []
    if kept and not verbatim and plan.intent in ("fact", "table", "multi"):
        live = set(chosen)
        cands = {c: passages[c] for c in order if passages[c]["item_id"] in live}
        # the other versions of the passages the answer cites (grouped away by the search) are compared too;
        # they are fetched under RLS and their files are live-checked with the cited ones below
        extra_ids = [v for cl in kept for c in cl.citations for v in versions.get(c.chunk_id, [])]
        for c, p in gates.fetch_passages(oid, extra_ids).items():
            passages[c] = p
            cands[c] = p
        extra = []
        for cl in kept[:2]:
            src = sel_passages[cl.citations[0].chunk_id] if cl.citations else None
            for cf in conflicts.find(q_search, cl.text, [c.quote for c in cl.citations],
                                     {c.chunk_id for c in cl.citations}, cands):
                other = passages[cf.chunk_id]
                d_src, d_oth = (conflicts.doc_date(src["name"]) if src else None), conflicts.doc_date(other["name"])
                when = (" – bản mới hơn" if d_src and d_oth and d_oth > d_src else
                        " – bản cũ hơn" if d_src and d_oth and d_oth < d_src else "")
                sel_passages[cf.chunk_id] = other
                extra.append(verify.Claim(f"Lưu ý: tài liệu khác ghi {cf.value} ({other['name']}{_date_note(other)}{when}).",
                                          [verify.Citation(cf.chunk_id, cf.quote)], None))
                found_conflicts.append({"value": cf.value, "item_id": other["item_id"], "name": other["name"]})
        if extra:
            kept += extra
            trace.add("Phát hiện tài liệu ghi số liệu khác nhau", True, conflicts=len(extra))

    # ---- gate 2 again on cited files, gate 4 again
    # cited file -> the version its passages were indexed from (a conflicting passage is cited without having
    # been among the selected ones, so the version is read from the cited passage itself)
    cited_versions = {sel_passages[c.chunk_id]["item_id"]: sel_passages[c.chunk_id]["ctag"]
                      for cl in kept for c in cl.citations}
    cited_items = set(cited_versions)
    res2 = gates.live_check(tenant, oid, cited_versions)
    failed2 = {f for f, (ok, _) in res2.items() if not ok}
    if failed2:
        kept = [cl for cl in kept if not any(sel_passages[c.chunk_id]["item_id"] in failed2 for c in cl.citations)]
    g2 = gates.principal_gate(oid, roles)
    trace.add("Cổng 2 + 4 – kiểm tra lại trước khi trả lời", g2.ok,
              cited_files=len(cited_items), failed=len(failed2))
    if not g2.ok:
        return refuse(UNAVAILABLE_MESSAGE)
    if not kept:
        return nothing_found(extra={"llm_no_answer": raw.get("no_answer"), "dropped": [r for _, r in dropped]})

    # ---- sensitive content in the answer itself (the question may have dodged the keywords)
    notice = None
    if not is_staff and settings.sensitive_mode == "contact":
        if plan.intent != "fact" and len(kept) > 1:
            # a summary or list keeps its other points; only the sensitive ones are left out
            per = [review.answer_topics(cl.text) for cl in kept]
            if any(per) and not all(per):
                cut = sorted({t for ts in per for t in ts})
                kept = [cl for cl, ts in zip(kept, per) if not ts]
                notice = (f"Một số nội dung nhạy cảm đã được lược bỏ; để được hỗ trợ phần này, bạn hãy liên hệ trực tiếp "
                          f"{settings.sensitive_contact}." if lang == "vi" else
                          f"Some sensitive content was left out; for that part, please contact {settings.sensitive_contact_en} directly.")
                trace.add("Lược bỏ ý chạm chủ đề nhạy cảm", True, topics=cut, removed=sum(1 for ts in per if ts))
        # what the answer asserts (in full-text mode the claims are the quotes themselves); a quote that
        # merely sits next to a price in the same sentence does not make a share-count answer sensitive
        out_topics = review.answer_topics(" ".join(cl.text for cl in kept))
        if out_topics:
            msg = (f"Nội dung này hơi nhạy cảm, bạn hãy liên hệ trực tiếp {settings.sensitive_contact} để được hỗ trợ."
                   if lang == "vi" else
                   f"This topic is sensitive. Please contact {settings.sensitive_contact_en} directly for assistance.")
            trace.add("Câu trả lời chạm chủ đề nhạy cảm → không phát hành, chuyển người liên hệ", True, topics=out_topics)
            r = refuse(msg, kind="sensitive_redirect", extra={"topics": out_topics, "answer_side": True})
            r["sensitive"] = True
            return r

    # ---- full-text answers show the source sentences themselves, verbatim
    if settings.answer_mode == "role" and not (
            set(g2.detail.get("roles_mirror", [])) & {"Investor.AI.Summarize", "Staff.AI"}):
        verbatim = True                                  # roles may have changed while answering
    if verbatim:
        quoted, seen_q = [], set()
        for cl in kept:
            for c in cl.citations:
                if c.quote not in seen_q:
                    seen_q.add(c.quote)
                    quoted.append(verify.Claim(f"“{c.quote}”", [c], None))
        kept = quoted
        trace.add("Trả câu trích nguyên văn", True, quotes=len(kept))

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
                              "crop": crop_for(p["ocr_page"], quote) if p["ocr"] and settings.tenant_mode != "m365" else None})
            refs.append(cite_index[key])
        # numbers in the claim or its quotes that only the VLM read (second OCR reader disagreed)
        doubt = sorted({n for c in cl.citations for n in sel_passages[c.chunk_id].get("ocr_doubt", [])
                        if n in cl.text or n in c.quote})
        claims_out.append({"text": cl.text, "refs": sorted(set(refs)), "nli": cl.nli, "ocr_doubt": doubt,
                           "uncertain": bool(doubt) or (cl.nli is not None and cl.nli < settings.nli_threshold)})
    if settings.mask_pii:      # after verification (quotes were checked against the real text)
        masked_kinds: set[str] = set()
        for cl, c in zip(kept, claims_out):
            # whose number it is is said by the cited passage ("Hotline: 0909…"), not by the claim's own words
            allow = pii.org_numbers("\n".join(sel_passages[x.chunk_id]["text"] for x in cl.citations))
            c["text"], k = pii.mask(c["text"], allow)
            masked_kinds.update(k)
        for c in cites:
            c["quote"], k = pii.mask(c["quote"], pii.org_numbers(sel_passages[c["chunk_id"]]["text"]))
            masked_kinds.update(k)
        if masked_kinds:
            trace.add("Che thông tin cá nhân trong câu trả lời", True, kinds=sorted(masked_kinds))
    answer_text = "\n".join(c["text"] for c in claims_out)
    seq = audit.append(oid, "answer", {
        "question": question,
        "asked": asked if asked != question else None,
        "allowed_chunks": n_allowed,
        "files_checked": len(chosen) + len(dropped_live),
        "files_dropped_live": len(dropped_live),
        "cited": [{"item_id": c["item_id"], "locator": c["locator"], "chunk_id": c["chunk_id"]} for c in cites],
        "versions": {f: cited_versions[f] for f in cited_items},
        "answer_sha256": hashlib.sha256(answer_text.encode()).hexdigest(),
        "dropped_claims": [r for _, r in dropped],
    })
    trace.add("Ghi nhật ký (chuỗi hash)", True, audit_seq=seq)
    result = {"refused": False, "message": None, "claims": claims_out, "citations": cites, "trace": trace.steps,
              "audit_seq": seq, "lang": lang, "mode": plan.intent, "verbatim": verbatim, "notice": notice,
              "standalone_question": question if question != asked and not item_id else None, "recap": bool(recap_chunks),
              "conflicts": found_conflicts}
    # ---- sensitive questions (BR-08): investors get the answer only after a reviewer approves it
    if topics and not is_staff and settings.sensitive_mode == "review":
        trace.add("Câu hỏi nhạy cảm → bản nháp chờ người duyệt", True, topics=topics)
        return review.hold(oid, question, lang, topics, result, lang_mod.tr(review.HOLD_MESSAGE, lang))
    return result
