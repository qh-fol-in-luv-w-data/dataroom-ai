"""On-topic check: a verified claim about something the data room does not hold is not released. The model
copies the question's project name into its claim, so the reranker and the claim's own words vouch for it;
the cited documents themselves must hold the question's key terms."""
from dr.core import answer, intent
from tests.test_gates import env  # noqa: F401


def figure_llm(question, passages, lang="vi"):
    """A model that answers any revenue question from the passage holding a revenue figure, naming the
    question's subject in its claim (what qwen3 did on the out-of-scope questions)."""
    labels = {f"D{i}": p["chunk_id"] for i, p in enumerate(passages, start=1)}
    for label, p in zip(labels, passages):
        if "1.250" in p["text"]:
            subject = question.split(" có ")[0] if " có " in question else "Doanh thu"
            return {"claims": [{"text": f"{subject}: doanh thu năm 2025 là 1.250 tỷ đồng.",
                                "citations": [{"doc": label, "quote": "Doanh thu năm 2025 là 1.250 tỷ đồng."}]}],
                    "no_answer": False}, labels
    return {"claims": [], "no_answer": True}, labels


DEPS = answer.Deps(rerank=lambda q, texts: [1.0] * len(texts), llm=figure_llm)


def _step(res):
    return next((s for s in res["trace"] if s["step"].startswith("Kiểm tra đúng trọng tâm")), None)


def test_evidence_overlap():
    q = "Dự án Sakura Riverside Đà Lạt có doanh thu năm 2025 là bao nhiêu?"
    assert intent.evidence_overlap(q, ["Báo cáo chung. Doanh thu năm 2025 là 1.250 tỷ đồng."]) < 0.7
    assert intent.evidence_overlap(q, ["Sakura Riverside Đà Lạt – báo cáo: doanh thu năm 2025 là 1.250 tỷ."]) == 1.0


def test_question_about_a_project_the_room_does_not_hold_is_not_answered(env):
    tenant, _, ix = env
    res = answer.ask(tenant, ix, "inv-b1", ["Investor.AI"],
                     "Dự án Sakura Riverside Đà Lạt có doanh thu năm 2025 là bao nhiêu?", DEPS)
    st = _step(res)
    assert st and st["dropped"] == 1 and res["refused"]


def test_question_the_cited_document_answers_is_kept(env):
    tenant, _, ix = env
    res = answer.ask(tenant, ix, "inv-b1", ["Investor.AI"], "Doanh thu năm 2025 trong báo cáo chung là bao nhiêu?", DEPS)
    st = _step(res)
    assert st and st["dropped"] == 0 and not res["refused"]


def echoing_llm(question, passages, lang="vi"):
    """Says the question again unless told not to (what qwen3:4b did on 7 + 13 mock-test questions)."""
    labels = {f"D{i}": p["chunk_id"] for i, p in enumerate(passages, start=1)}
    for label, p in zip(labels, passages):
        if "1.250" in p["text"]:
            quote = "Doanh thu năm 2025 là 1.250 tỷ đồng."
            text = ("Doanh thu năm 2025 là 1.250 tỷ đồng." if "chép lại câu hỏi" in question
                    else "Doanh thu năm 2025 trong báo cáo chung là.")
            return {"claims": [{"text": text, "citations": [{"doc": label, "quote": quote}]}], "no_answer": False}, labels
    return {"claims": [], "no_answer": True}, labels


def test_answer_that_only_repeats_the_question_is_asked_again(env):
    tenant, _, ix = env
    res = answer.ask(tenant, ix, "inv-b1", ["Investor.AI"], "Doanh thu năm 2025 trong báo cáo chung là bao nhiêu?",
                     answer.Deps(llm=echoing_llm))
    assert any(s["step"].startswith("Thử lại vì câu trả lời lặp câu hỏi") for s in res["trace"])
    assert not res["refused"] and "1.250" in res["claims"][0]["text"]


def test_name_terms_are_the_capitalised_words_after_the_first():
    assert intent.name_terms("Dự án Sakura Riverside Đà Lạt có doanh thu bao nhiêu?") == {"sakura", "riverside", "lat"}
    assert intent.name_terms("Doanh thu năm 2025 là bao nhiêu?") == set()
    texts = ["Báo cáo Sakura Riverside Đà Lạt 2025", "Báo cáo dự án khác"]
    assert intent.name_overlap("Dự án Sakura Riverside Đà Lạt có doanh thu bao nhiêu?", texts) == 1.0
    assert intent.name_overlap("Dự án Sakura Riverside Đà Lạt có doanh thu bao nhiêu?", texts[1:]) == 0.0
    assert intent.name_overlap("Doanh thu năm 2025 là bao nhiêu?", texts[1:]) == 1.0      # no name: nothing to check


def test_question_naming_a_project_no_cited_document_mentions_is_not_answered(env):
    """Most key terms of the question are in the shared report (evidence 5/6), but not the project it names."""
    tenant, _, ix = env
    res = answer.ask(tenant, ix, "inv-b1", ["Investor.AI"],
                     "Doanh thu năm 2025 trong báo cáo chung của Sakura là bao nhiêu?", DEPS)
    st = _step(res)
    assert st and st["dropped"] == 1 and res["refused"]
