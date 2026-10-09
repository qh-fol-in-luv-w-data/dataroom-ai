"""BRD v1.4 features: bilingual answers, quote-only mode, sensitive-question review,
document search and answer feedback — through the real API with the stub LLM."""
from dr.core import lang
from dr.gateway import app as appmod
from tests.test_api import client, login  # noqa: F401  (fixture)


def test_language_detection():
    assert lang.detect("Doanh thu thuần năm 2025 là bao nhiêu?") == "vi"
    assert lang.detect("doanh thu nam 2025 la bao nhieu") == "vi"
    assert lang.detect("What was the net revenue in 2025?") == "en"
    assert lang.detect("Cho mình hỏi arrangement fee của nhóm A là bao nhiêu?") == "vi"


def test_english_question_gets_english_refusal_and_answer(client):
    r = client.post("/api/chat", headers=login(client, "inv-noai"),
                    json={"question": "What is the arrangement fee for group A?"}).json()
    assert r["refused"] and r["lang"] == "en" and r["message"].startswith("Your account has not been granted")
    r = client.post("/api/chat", headers=login(client, "staff-1"),
                    json={"question": "What is the arrangement fee for group A?"}).json()
    assert not r["refused"] and r["lang"] == "en"


def test_answer_style_follows_the_question(client):
    h = login(client, "inv-a1")
    r = client.post("/api/chat", headers=h, json={"question": "phí thu xếp nhóm A"}).json()
    assert r["mode"] == "fact" and not r["verbatim"] and not r["claims"][0]["text"].startswith("“")
    r = client.post("/api/chat", headers=h, json={"question": "Trích nguyên văn phí thu xếp nhóm A"}).json()
    assert r["mode"] == "full" and r["verbatim"] and all(c["text"].startswith("“") for c in r["claims"])
    r = client.post("/api/chat", headers=h, json={"question": "Tóm tắt thỏa thuận nhóm A KS-GRPA-0001"}).json()
    assert r["mode"] == "summary" and any(s["step"] == "Đọc toàn bộ tài liệu được nêu tên (RLS)" for s in r["trace"])


def test_role_based_quote_mode_still_available(client, monkeypatch):
    """BRD v1.4 BR-04 behaviour, kept behind DR_ANSWER_MODE=role."""
    from dr.config import settings
    monkeypatch.setattr(settings, "answer_mode", "role")
    r = client.post("/api/chat", headers=login(client, "inv-a1"), json={"question": "phí thu xếp nhóm A"}).json()
    assert r["verbatim"] and all(c["text"].startswith("“") for c in r["claims"])
    r = client.post("/api/chat", headers=login(client, "staff-1"), json={"question": "phí thu xếp nhóm A"}).json()
    assert not r["verbatim"] and not r["claims"][0]["text"].startswith("“")


def test_named_document_is_read_only_within_permissions(client):
    # inv-b1 names a group A document: RLS finds nothing, so it is not read
    r = client.post("/api/chat", headers=login(client, "inv-b1"),
                    json={"question": "Tóm tắt tài liệu KS-GRPA-0001"}).json()
    assert not any(c["site_id"] == "GRP-A" for c in r["citations"])
    assert not any(s["step"] == "Đọc toàn bộ tài liệu được nêu tên (RLS)" for s in r["trace"])


def test_sensitive_question_points_to_contact(client):
    r = client.post("/api/chat", headers=login(client, "inv-a1"),
                    json={"question": "Định giá phí thu xếp nhóm A thế nào?"}).json()
    assert r["refused"] and r["sensitive"] and "Trần Kim Chung" in r["message"] and not r["claims"]
    r = client.post("/api/chat", headers=login(client, "inv-a1"),
                    json={"question": "What is the expected offering price?"}).json()
    assert r["sensitive"] and r["message"].startswith("This topic is sensitive")


def test_sensitive_question_goes_through_review(client, monkeypatch):
    from dr.config import settings
    monkeypatch.setattr(settings, "sensitive_mode", "review")
    ha, rev, rx = login(client, "inv-a1"), login(client, "rev-1"), login(client, "rev-x")
    r = client.post("/api/chat", headers=ha, json={"question": "Định giá phí thu xếp nhóm A thế nào?"}).json()
    assert r["pending_review"] and not r["claims"] and "Định giá" in r["topics"][0]
    did = r["draft_id"]
    assert client.get("/api/my/drafts", headers=ha).json()[0]["status"] == "pending"
    # investors are not reviewers
    assert client.get("/api/review/drafts", headers=ha).status_code == 403
    # a reviewer who cannot read the cited files sees nothing and cannot decide
    q = client.get("/api/review/drafts", headers=rx).json()
    assert q[0]["draft_id"] == did and not q[0]["visible"] and "answer" not in q[0]
    assert client.post(f"/api/review/drafts/{did}", headers=rx, json={"action": "approve"}).status_code == 403
    # a reviewer with access approves with an edit
    q = client.get("/api/review/drafts", headers=rev).json()
    assert q[0]["visible"] and q[0]["answer"]["claims"]
    n = len(q[0]["answer"]["claims"])
    d = client.post(f"/api/review/drafts/{did}", headers=rev,
                    json={"action": "approve", "claims": ["Đã được Ban IPO hiệu đính."] + [""] * (n - 1)}).json()
    assert d["status"] == "approved" and d["edited"]
    mine = client.get("/api/my/drafts", headers=ha).json()[0]
    assert mine["status"] == "approved" and mine["answer"]["claims"][0]["text"] == "Đã được Ban IPO hiệu đính."
    assert client.post(f"/api/review/drafts/{did}", headers=rev, json={"action": "reject"}).status_code == 400
    # the asker loses access later: the approved answer is withdrawn when opened again
    t = appmod.S.tenant
    t.remove_member("DR-INV-A", "inv-a1")
    appmod.S.connector.poll_once()
    t.now = lambda: 10 ** 12                       # SharePoint has applied the removal too
    mine = client.get("/api/my/drafts", headers=ha).json()[0]
    assert mine["answer"]["claims"] == [] and mine["answer"]["withdrawn"] >= 1


def test_staff_sensitive_question_is_answered_directly(client):
    r = client.post("/api/chat", headers=login(client, "staff-1"),
                    json={"question": "Định giá nội bộ KS-INTERNAL-0001"}).json()
    assert not r.get("pending_review") and not r["refused"]


def test_search_respects_permissions(client):
    a = client.get("/api/search", headers=login(client, "inv-a1"), params={"q": "KS-GRPA-0001 phí thu xếp"}).json()
    assert "a1" in {x["item_id"] for x in a["results"]} and a["results"][0]["snippet"]
    b = client.get("/api/search", headers=login(client, "inv-b1"), params={"q": "KS-GRPA-0001 phí thu xếp"}).json()
    ids = {x["item_id"] for x in b["results"]}
    assert not ids & {"a1", "a2", "i1"} and "x1" not in ids          # other group, internal, AI-excluded
    no = client.get("/api/search", headers=login(client, "inv-noai"), params={"q": "phí"}).json()
    assert no["refused"] and not no["results"]


def test_feedback_only_on_own_answers(client):
    ha, hb = login(client, "inv-a1"), login(client, "inv-b1")
    r = client.post("/api/chat", headers=ha, json={"question": "phí thu xếp nhóm A"}).json()
    assert client.post("/api/feedback", headers=ha, json={"audit_seq": r["audit_seq"], "rating": "up"}).json()["ok"]
    assert client.post("/api/feedback", headers=hb, json={"audit_seq": r["audit_seq"], "rating": "down"}).status_code == 404


def test_sensitive_topics_cover_english_wording():
    from dr.core import review
    for q in ["How much is the provision for the contractor dispute?", "Is there any arbitration?",
              "What is the company worth?", "Dự phòng tranh chấp với nhà thầu là bao nhiêu?"]:
        assert review.topics_of(q), q
    for q in ["What was the net revenue in 2025?", "Tổng công suất lắp đặt là bao nhiêu MW?"]:
        assert not review.topics_of(q), q
