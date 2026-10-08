"""Sensitive-question review (BRD BR-08): Draft → Reviewer → released answer.

- A question touching a sensitive topic (valuation, offering price, allocation, promised
  returns, forecasts, disputes…) from an investor is answered and verified as usual, but the
  answer is stored as a draft instead of being shown.
- A reviewer may open a draft only if they can themselves read *every* file it cites; otherwise
  the draft would leak another group's documents to the reviewer.
- Approve / edit / reject are audited. When the asker opens an approved answer, the cited files
  are live-checked again *as the asker*: claims whose source the asker can no longer read are
  dropped (permissions may have changed while the draft waited).

Topics: DEFAULT_TOPICS, overridable by data/tenant/sensitive_topics.json
({"topic_id": {"label": "...", "terms": ["folded term", ...]}}).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from psycopg.types.json import Jsonb
from unidecode import unidecode

from dr import audit
from dr.config import settings
from dr.db import pg
from dr.security import pii

HOLD_MESSAGE = ("Câu hỏi thuộc nhóm cần Ban IPO xem xét trước khi trả lời. "
                "Câu trả lời sẽ hiển thị tại đây sau khi được duyệt.")

DEFAULT_TOPICS = {
    "dinh_gia": {"label": "Định giá / giá trị doanh nghiệp",
                 "terms": ["dinh gia", "valuation", "gia tri doanh nghiep", "enterprise value", "ev/ebitda", "p/e",
                           "company worth", "fair value"]},
    "gia_chao_ban": {"label": "Giá chào bán / khoảng giá",
                     "terms": ["gia chao ban", "offering price", "offer price", "gia phat hanh", "khoang gia",
                               "price range"]},
    "phan_bo": {"label": "Phân bổ cổ phần",
                "terms": ["phan bo", "allocation", "allotment", "duoc mua bao nhieu", "uu tien mua"]},
    "cam_ket_loi_nhuan": {"label": "Cam kết lợi nhuận / cổ tức",
                          "terms": ["cam ket loi nhuan", "loi nhuan dam bao", "guaranteed return", "chac chan tang",
                                    "co tuc du kien", "expected dividend", "dividend forecast"]},
    "du_bao": {"label": "Dự báo / kế hoạch tài chính",
               "terms": ["du bao", "forecast", "projection", "ke hoach loi nhuan", "guidance"]},
    "tranh_chap": {"label": "Tranh chấp / kiện tụng",
                   "terms": ["tranh chap", "kien tung", "litigation", "lawsuit", "khieu kien", "du phong tranh chap",
                             "dispute", "arbitration", "trong tai", "legal claim"]},
}


@lru_cache(maxsize=1)
def _topics() -> dict:
    f = settings.tenant_dir / "sensitive_topics.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return DEFAULT_TOPICS


def topics_of(question: str) -> list[str]:
    q = " " + re.sub(r"\s+", " ", unidecode(question).lower()) + " "
    return [tid for tid, t in _topics().items() if any(term in q for term in t["terms"])]


def topic_labels(ids: list[str]) -> list[str]:
    return [_topics().get(t, {}).get("label", t) for t in ids]


def hold(oid: str, question: str, lang: str, topics: list[str], result: dict, message: str) -> dict:
    items = sorted({c["item_id"] for c in result["citations"]})
    with pg.admin() as c:
        did = c.execute("INSERT INTO review_drafts(oid, question, lang, topics, answer, cited_items) "
                        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING draft_id",
                        (oid, pii.mask(question)[0], lang, topics, Jsonb(result), items)).fetchone()[0]
        c.commit()
    audit.append(oid, "draft_created", {"draft_id": did, "topics": topics, "answer_seq": result.get("audit_seq"),
                                        "cited_items": items})
    return {"refused": False, "pending_review": True, "draft_id": did, "message": message,
            "topics": topic_labels(topics), "claims": [], "citations": [], "trace": result["trace"],
            "audit_seq": result.get("audit_seq"), "lang": lang}


# ------------------------------------------------------------------ asker side
def _released(tenant, oid: str, answer: dict) -> dict:
    """The approved answer as the asker may see it *now*: cited files re-checked live as the asker."""
    from dr.core import gates
    cites = answer["citations"]
    ok_items = set()
    if cites:
        # compare with the version the draft quoted: a newer version withdraws the claim
        res = gates.live_check(tenant, oid, {c["item_id"]: c.get("ctag") or _ctag(c["item_id"]) for c in cites})
        ok_items = {i for i, (ok, _) in res.items() if ok}
    keep = {c["n"] for c in cites if c["item_id"] in ok_items}
    claims = [cl for cl in answer["claims"] if set(cl["refs"]) <= keep]
    return {**answer, "claims": claims, "citations": [c for c in cites if c["n"] in keep],
            "withdrawn": len(answer["claims"]) - len(claims)}


def _ctag(item_id: str) -> str:
    with pg.admin() as c:
        r = c.execute("SELECT ctag FROM items WHERE item_id=%s", (item_id,)).fetchone()
    return r[0] if r else ""


def my_drafts(tenant, oid: str) -> list[dict]:
    with pg.admin() as c:
        rows = c.execute("SELECT draft_id, question, lang, topics, status, note, edited, answer, created_at, decided_at "
                         "FROM review_drafts WHERE oid=%s ORDER BY draft_id DESC LIMIT 50", (oid,)).fetchall()
    out = []
    for did, q, lang, topics, status, note, edited, answer, created, decided in rows:
        d = {"draft_id": did, "question": q, "lang": lang, "topics": topic_labels(topics), "status": status,
             "edited": edited, "created_at": created.isoformat(), "decided_at": decided.isoformat() if decided else None}
        if status == "approved":
            d["answer"] = _released(tenant, oid, answer)
        elif status == "rejected":
            d["note"] = note
        out.append(d)
    return out


# ------------------------------------------------------------------ reviewer side
def _can_view(tenant, reviewer: str, items: list[str]) -> list[str]:
    """Cited files the reviewer cannot read themselves (empty = may view the draft)."""
    return [i for i in items if not tenant.sp_can_read(reviewer, i)]


def queue(tenant, reviewer: str, status: str = "pending") -> list[dict]:
    with pg.admin() as c:
        rows = c.execute("SELECT draft_id, oid, question, lang, topics, status, answer, cited_items, created_at, "
                         "reviewer, note FROM review_drafts WHERE status=%s ORDER BY draft_id LIMIT 100",
                         (status,)).fetchall()
    out = []
    for did, oid, q, lang, topics, st, answer, items, created, rv, note in rows:
        blocked = _can_view(tenant, reviewer, items)
        u = getattr(tenant, "users", {}).get(oid, {})
        d = {"draft_id": did, "asker": {"oid": oid, "name": u.get("name", oid), "org": u.get("org", "")},
             "question": q, "lang": lang, "topics": topic_labels(topics), "status": st,
             "created_at": created.isoformat(), "visible": not blocked, "reviewer": rv, "note": note}
        if blocked:
            d["reason"] = f"Bạn không có quyền đọc {len(blocked)}/{len(items)} tài liệu được trích dẫn"
        else:
            d["answer"] = {k: answer[k] for k in ("claims", "citations", "mode", "lang")}
        out.append(d)
    return out


def decide(tenant, reviewer: str, draft_id: int, action: str, claims: list[str] | None = None,
           note: str | None = None) -> dict:
    if action not in ("approve", "reject"):
        raise ValueError("action phải là approve hoặc reject")
    with pg.admin() as c:
        row = c.execute("SELECT oid, status, answer, cited_items FROM review_drafts WHERE draft_id=%s FOR UPDATE",
                        (draft_id,)).fetchone()
        if not row:
            raise LookupError("Không có bản nháp này")
        asker, status, answer, items = row
        if status != "pending":
            raise ValueError(f"Bản nháp đã ở trạng thái {status}")
        if _can_view(tenant, reviewer, items):
            raise PermissionError("Bạn không có quyền đọc mọi tài liệu mà bản nháp trích dẫn")
        edited = False
        if action == "approve" and claims is not None:
            if len(claims) != len(answer["claims"]):
                raise ValueError("Số ý chỉnh sửa không khớp bản nháp")
            for cl, txt in zip(answer["claims"], claims):
                txt = (txt or "").strip()
                if txt and txt != cl["text"]:
                    cl["text"], cl["edited"], edited = pii.mask(txt)[0], True, True
            answer["claims"] = [cl for cl in answer["claims"] if cl["text"].strip()]
        c.execute("UPDATE review_drafts SET status=%s, reviewer=%s, note=%s, edited=%s, answer=%s, "
                  "decided_at=now() WHERE draft_id=%s",
                  ("approved" if action == "approve" else "rejected", reviewer, (note or "")[:1000] or None,
                   edited, Jsonb(answer), draft_id))
        c.commit()
    audit.append(reviewer, "draft_" + ("approved" if action == "approve" else "rejected"),
                 {"draft_id": draft_id, "asker": asker, "edited": edited, "note": (note or "")[:300]})
    return {"draft_id": draft_id, "status": "approved" if action == "approve" else "rejected", "edited": edited}
