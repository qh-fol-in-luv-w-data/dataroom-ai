from dr.core import tables, verify

SHEET = [
    {"chunk_id": 1, "text": "[Sheet CGI] SO SÁNH AGENCY\nSTT: 1; TÊN: BNF; GIAI ĐOẠN 2 › TỔNG (23 HÌNH): 322.000.000; "
                            "GIAI ĐOẠN 1 › TỔNG + VAT: 139.320.000"},
    {"chunk_id": 2, "text": "[Sheet CGI] SO SÁNH AGENCY\nSTT: 5; TÊN: GJDC; GIAI ĐOẠN 2 › TỔNG (23 HÌNH): 299.000.000; "
                            "GIAI ĐOẠN 1 › TỔNG + VAT: 116.640.000"},
    {"chunk_id": 3, "text": "[Sheet CGI] SO SÁNH AGENCY\nSTT: 6; TÊN: EZ; GIAI ĐOẠN 2 › TỔNG (23 HÌNH): 368.000.000; "
                            "GIAI ĐOẠN 1 › TỔNG + VAT: 253.800.000"},
]


def _answer(q):
    raw, labels = tables.extreme(q, SHEET)
    kept, dropped = verify.check(raw["claims"], labels, {p["chunk_id"]: p for p in SHEET}, q)
    return raw["claims"][0]["text"], kept, labels["T1"]


def test_smallest_picks_the_row_and_the_asked_column():
    text, kept, cid = _answer("Agency nào có chi phí giai đoạn 2 (tổng 23 hình) thấp nhất?")
    assert "GJDC" in text and "299.000.000" in text and cid == 2 and kept      # passes the normal verifier


def test_largest():
    text, kept, cid = _answer("Agency nào có tổng + VAT giai đoạn 1 cao nhất?")
    assert "EZ" in text and "253.800.000" in text and cid == 3 and kept


def test_not_a_table_extreme():
    assert tables.extreme("Chi phí của GJDC là bao nhiêu?", SHEET) is None


def test_figure_under_another_rows_name_is_dropped():
    passages = {p["chunk_id"]: p for p in SHEET}
    claim = {"text": "EZ có chi phí giai đoạn 2 là 299.000.000.",
             "citations": [{"doc": "D2", "quote": SHEET[1]["text"].split("\n")[1]}]}
    kept, dropped = verify.check([claim], {"D2": 2}, passages, "agency nào rẻ nhất")
    assert not kept and "EZ" in dropped[0][1]


def test_compare_two_named_rows():
    raw, labels = tables.compare("So sánh tổng + VAT giai đoạn 1 của BNF và EZ", SHEET)
    texts = " ".join(c["text"] for c in raw["claims"])
    assert "139.320.000" in texts and "253.800.000" in texts and "116.640.000" not in texts
    kept, _ = verify.check(raw["claims"], labels, {p["chunk_id"]: p for p in SHEET}, "so sánh BNF và EZ")
    assert len(kept) == 2


def test_subject_named_in_question_may_be_absent_from_quote():
    passages = {1: {"chunk_id": 1, "text": "MÃ SẢN PHẨM | SH09\nGIÁ BÁN CHÍNH THỨC CHƯA VAT | 4.899.895.000"}}
    claim = {"text": "Giá bán căn SH09 là 4.899.895.000.",
             "citations": [{"doc": "D1", "quote": "GIÁ BÁN CHÍNH THỨC CHƯA VAT | 4.899.895.000"}]}
    kept, _ = verify.check([claim], {"D1": 1}, passages, "Giá bán chính thức căn SH09 là bao nhiêu?")
    assert kept


def test_answer_for_a_named_unit_must_come_from_a_passage_about_it():
    passages = {1: {"chunk_id": 1, "text": "MÃ SẢN PHẨM | SH09\nGIÁ BÁN CHÍNH THỨC CHƯA VAT | 4.899.895.000"},
                2: {"chunk_id": 2, "text": "Tổng giá trị hợp đồng là 38.934.903.118,32 đồng."}}
    wrong = {"text": "Tổng giá trị hợp đồng căn SH09 là 38.934.903.118,32.",
             "citations": [{"doc": "D2", "quote": "Tổng giá trị hợp đồng là 38.934.903.118,32 đồng."}]}
    kept, dropped = verify.check([wrong], {"D1": 1, "D2": 2}, passages, "Tổng giá trị hợp đồng căn SH09?")
    assert not kept and "SH09" in dropped[0][1]
