"""Latency work: quote mode picks sentence ids, LLM outputs are memoised on their exact input,
and /api/chat/stream reports progress before releasing the verified answer in one block."""
import json

from dr.models import llm
from tests.test_api import client, login  # noqa: F401  (fixture)


def test_sentence_split_keeps_numbers_whole():
    s = llm.split_sentences("Phí thu xếp ở mức 0,85% tổng giá trị. Tổng 1.250.000 cổ phần; trả một lần.\nBảng 2")
    assert s == ["Phí thu xếp ở mức 0,85% tổng giá trị.", "Tổng 1.250.000 cổ phần; trả một lần. Bảng 2"]


def test_quote_mode_maps_ids_to_verbatim_sentences(monkeypatch):
    llm.clear_cache()
    ps = [{"chunk_id": 7, "text": "Câu mở đầu không liên quan gì cả. Phí thu xếp là 0,85% giá trị đăng ký.", "source": "a"}]
    calls = []
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: calls.append(a) or {"sentences": ["D1.2", "D9.9", "D1.2"],
                                                                           "no_answer": False})
    raw, labels = llm.answer_quotes("phí thu xếp?", ps)
    assert labels == {"D1": 7}
    assert raw["claims"] == [{"text": "Phí thu xếp là 0,85% giá trị đăng ký.",
                              "citations": [{"doc": "D1", "quote": "Phí thu xếp là 0,85% giá trị đăng ký."}]}]
    assert "[D1.2] Phí thu xếp" in calls[0][1]


def test_summary_mode_cites_sentence_ids(monkeypatch):
    llm.clear_cache()
    ps = [{"chunk_id": 3, "text": "Câu mở đầu không liên quan gì cả. Room ngoại cho Nhóm B được chốt ở mức 18%.", "source": "a"}]
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: {"claims": [
        {"text": "Room ngoại của Nhóm B là 18%.", "sentences": ["[D1.2]", "D7.1"]},
        {"text": "Ý không có nguồn", "sentences": []},
        {"text": "[D1.2]", "sentences": ["D1.2"]}], "no_answer": False})
    raw, labels = llm.answer_json("room ngoại nhóm B?", ps)
    assert raw["claims"][0]["citations"] == [{"doc": "D1", "quote": "Room ngoại cho Nhóm B được chốt ở mức 18%."}]
    assert raw["claims"][1]["citations"] == []         # the verifier drops it
    assert len(raw["claims"]) == 2                     # a claim that is only a sentence id is dropped
    from dr.core import verify
    kept, dropped = verify.check(raw["claims"], labels, {3: {"text": ps[0]["text"]}})
    assert [k.text for k in kept] == ["Room ngoại của Nhóm B là 18%."] and len(dropped) == 1


def test_cache_hits_only_on_identical_input(monkeypatch):
    llm.clear_cache()
    n = {"c": 0}

    def fake(*a, **k):
        n["c"] += 1
        return {"claims": [], "no_answer": True}
    monkeypatch.setattr(llm, "_chat", fake)
    ps = [{"chunk_id": 1, "text": "Nội dung A", "source": "x"}]
    llm.answer_json("Phí thu xếp là bao nhiêu?", ps)
    llm.answer_json("  phí thu xếp là bao nhiêu ", ps)                       # same question, other spacing
    assert n["c"] == 1
    llm.answer_json("Phí thu xếp là bao nhiêu?", [{**ps[0], "text": "Nội dung A (bản mới)"}])   # new version
    llm.answer_json("Phí thu xếp là bao nhiêu?", ps + [{"chunk_id": 2, "text": "B", "source": "y"}])  # other scope
    llm.answer_json("Phí thu xếp là bao nhiêu?", ps, lang="en")
    llm.answer_quotes("Phí thu xếp là bao nhiêu?", ps)                       # other mode
    assert n["c"] == 5
    out, _ = llm.answer_json("Phí thu xếp là bao nhiêu?", ps)
    out["claims"].append("x")                                                  # callers cannot poison the cache
    assert llm.answer_json("Phí thu xếp là bao nhiêu?", ps)[0]["claims"] == []


def test_stream_reports_progress_then_same_answer(client):
    h = login(client, "inv-a1")
    r = client.post("/api/chat/stream", headers=h, json={"question": "phí thu xếp nhóm A"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(x) for x in r.text.splitlines() if x.strip()]
    steps = [e["step"] for e in events if "step" in e]
    assert steps[0].startswith("Cổng 4") and any(s.startswith("LLM") for s in steps)
    assert all(set(e) <= {"step", "ok", "ms", "stage"} for e in events[:-1])   # progress carries no content
    res = events[-1]["result"]
    assert not res["refused"] and res["claims"] and res["mode"] == "fact"
    # a user from another group gets the neutral refusal through the stream as well
    rb = client.post("/api/chat/stream", headers=login(client, "inv-b1"), json={"question": "phí thu xếp nhóm A KS-GRPA-0001"})
    res_b = [json.loads(x) for x in rb.text.splitlines() if x.strip()][-1]["result"]
    assert not any(c["site_id"] == "GRP-A" for c in res_b["citations"])
    assert client.post("/api/chat/stream", json={"question": "x"}).status_code == 401


def test_model_memo_returns_copies():
    from dr.models.memo import lru
    n = {"c": 0}

    @lru(2)
    def f(q, ps):
        n["c"] += 1
        return [q, list(ps)]
    out = f("q", ["p"])
    out.append("x")
    assert f("q", ["p"]) == ["q", ["p"]] and n["c"] == 1
    f("q", ["p2"]), f("z", [])            # evicts the oldest entry
    f("q", ["p"])
    assert n["c"] == 4


def test_citation_repair_adds_the_sentence_holding_the_number():
    s = {"D1.1": "Phí thu xếp được thống nhất trong biên bản.", "D1.2": "Mức phí là 0,85% tổng giá trị đăng ký.",
         "D2.1": "Một tài liệu khác cũng có 0,85%."}
    r = llm._repair({"text": "Phí thu xếp là 0,85%.", "citations": [{"doc": "D1", "quote": s["D1.1"]}]}, s)
    assert r["citations"][-1] == {"doc": "D1", "quote": s["D1.2"]}          # same document first
    r = llm._repair({"text": "Phí thu xếp là 9,99%.", "citations": [{"doc": "D1", "quote": s["D1.1"]}]}, s)
    assert len(r["citations"]) == 1                                          # nothing invented
