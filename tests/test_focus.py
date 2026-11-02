"""Sentence focus: the n sentences the reranker likes best, plus the few the answer usually sits in."""
from dr.core.answer import Deps, Trace, focus_sentences
from tests.test_gates import env  # noqa: F401,E402


def _deps(scores: dict[str, float]) -> Deps:
    """A reranker stub: each sentence's score by a word it holds (0 otherwise)."""
    def rerank(q, texts):
        return [max([v for k, v in scores.items() if k in t] or [0.0]) for t in texts]
    return Deps(rerank=rerank)


def _kept(out: list[dict]) -> str:
    return "\n".join(p["text"] for p in out)


def test_value_on_the_line_after_its_label_is_kept():
    # OCR: the label and its value on two lines; the reranker likes the label only
    p = [{"chunk_id": 1, "text": "Tổng mức đầu tư của dự án được phê duyệt như sau.\n"
                                 "Giá trị: 1.250.000.000.000 đồng theo quyết định.\n"
                                 "Phần còn lại nói về tiến độ thi công của nhà thầu.\n"
                                 "Ghi chú về các hạng mục phụ trợ khác của công trình."}]
    out = focus_sentences("Tổng mức đầu tư là bao nhiêu?", p, _deps({"Tổng mức": 0.9, "tiến độ": 0.5}), Trace(), n=1)
    assert "1.250.000.000.000" in _kept(out)


def test_every_selected_passage_keeps_its_best_sentence():
    a = {"chunk_id": 1, "text": "Câu A một rất liên quan đến câu hỏi. Câu A hai cũng liên quan đến câu hỏi. "
                                "Câu A ba vẫn liên quan đến câu hỏi."}
    b = {"chunk_id": 2, "text": "Câu B một ít liên quan đến câu hỏi hơn. Câu B hai không liên quan gì lắm."}
    out = focus_sentences("câu hỏi", [a, b], _deps({"A một": 0.9, "A hai": 0.8, "A ba": 0.7, "B một": 0.2}),
                          Trace(), n=2)
    assert any(p["chunk_id"] == 2 and "B một" in p["text"] for p in out)


def test_sentence_naming_the_questions_code_is_kept():
    p = [{"chunk_id": 1, "text": "Bảng giá các căn hộ đợt 1 năm 2024 của dự án.\nCăn SH09 có giá 4.899.895.000 đồng.\n"
                                 "Căn SH10 có giá 5.120.000.000 đồng.\nChính sách thanh toán theo tiến độ xây dựng."}]
    out = focus_sentences("Giá căn SH09 là bao nhiêu?", p, _deps({"Bảng giá": 0.9, "SH10": 0.6, "Chính sách": 0.5}),
                          Trace(), n=2)
    assert "4.899.895.000" in _kept(out)


def test_extras_are_few():
    text = " ".join(f"Câu số {k} của tài liệu về dự án SH09 năm 2024." for k in range(1, 40))
    out = focus_sentences("Dự án SH09 năm 2024?", [{"chunk_id": 1, "text": text}], _deps({"Câu": 0.5}), Trace(), n=5)
    assert len(_kept(out).split("\n\n")) <= 5 + 4


def test_long_table_row_is_cut_around_what_the_question_asks():
    # a merged table row runs far past the 400-character cut; the asked column sits at its end
    cells = [f"Hạng mục phụ số {k}: {k * 1000} đồng" for k in range(1, 40)]
    row = " | ".join(cells + ["Tổng giá trị quyết toán: 9.876.543.210 đồng"])
    out = focus_sentences("Tổng giá trị quyết toán là bao nhiêu?", [{"chunk_id": 1, "text": row}],
                          _deps({"Hạng mục": 0.5}), Trace(), n=3)
    kept = _kept(out)
    assert "9.876.543.210" in kept and len(kept) <= 400 and kept in row     # still a substring: quotes verify
    # with nothing of the question in it, the row keeps its beginning as before
    out = focus_sentences("Ai ký biên bản?", [{"chunk_id": 1, "text": row}], _deps({"Hạng mục": 0.5}), Trace(), n=3)
    assert _kept(out).startswith("Hạng mục phụ số 1:")


def test_expand_top_file_offers_its_other_chunks(env, monkeypatch):
    """DR_EXPAND_TOP_FILE: the best file's other chunks reach the model (here c1 has a second chunk)."""
    from dr.config import settings
    from dr.core import answer
    from dr.db import pg
    tenant, _, ix = env
    with pg.admin() as c:
        site, ctag = c.execute("SELECT site_id, ctag FROM items WHERE item_id = 'c1'").fetchone()
        c.execute("INSERT INTO chunks(item_id, site_id, ctag, ordinal, locator, text, text_folded, converter, tsv, tlen) "
                  "VALUES ('c1', %s, %s, 1, 'Trang 2', 'Lợi nhuận sau thuế năm 2025 là 210 tỷ đồng.', "
                  "'loi nhuan sau thue nam 2025 la 210 ty dong.', 'text', ''::tsvector, 9)", (site, ctag))
        c.commit()
    seen = {}

    def llm(question, passages, lang="vi"):
        seen["texts"] = [p["text"] for p in passages]
        return {"claims": [], "no_answer": True}, {}
    monkeypatch.setattr(settings, "expand_top_file", 10)
    answer.ask(tenant, ix, "inv-b1", ["Investor.AI"], "Doanh thu năm 2025 trong báo cáo chung là bao nhiêu?",
               answer.Deps(llm=llm))
    assert any("210 tỷ" in t for t in seen["texts"])
