from decimal import Decimal

from dr.core.answer import select_passages
from dr.core.verify import check, quote_found, vn_numbers


def test_select_passages_skips_near_duplicates():
    sheet = "Mã kiểm soát: KS-INTERNAL-{:04d}\nBẢNG CÂN ĐỐI KẾ TOÁN | 2025 | 17.320,8"
    passages = {i: {"item_id": f"dup{i}", "text": sheet.format(i)} for i in range(1, 9)}
    passages[99] = {"item_id": "fact", "text": "Ban IPO thống nhất định giá nội bộ 9.200 tỷ đồng."}
    order = list(range(1, 9)) + [99]
    sel = select_passages(order, passages, chosen={p["item_id"] for p in passages.values()},
                          max_passages=4, max_per_file=3)
    assert 99 in sel
    assert sum(1 for c in sel if passages[c]["item_id"].startswith("dup")) == 1

P = {
    10: {"text": "Doanh thu năm 2025 đạt 1.250,5 tỷ đồng, tăng 18,2% so với năm 2024.", "ocr": False},
    11: {"text": "Tỷ giá trần bảo hiểm là 25.850 VND/USD theo thỏa thuận.", "ocr": True},
}
L = {"D1": 10, "D2": 11}


def test_vn_numbers():
    vals = vn_numbers("1.250,5 tỷ, 18,2%, 25.850 và 1,250.5 năm 2025")
    assert Decimal("1250.5") in vals[0]
    assert Decimal("18.2") in vals[1]
    assert Decimal("25850") in vals[2]
    assert Decimal("1250.5") in vals[3]
    assert Decimal("2025") in vals[4]


def test_good_claim_kept():
    kept, dropped = check([{"text": "Doanh thu 2025 là 1.250,5 tỷ đồng.",
                            "citations": [{"doc": "D1", "quote": "Doanh thu năm 2025 đạt 1.250,5 tỷ đồng"}]}], L, P)
    assert len(kept) == 1 and not dropped


def test_invented_doc_dropped():
    _, dropped = check([{"text": "X", "citations": [{"doc": "D9", "quote": "Doanh thu năm 2025 đạt"}]}], L, P)
    assert "không được cung cấp" in dropped[0][1]


def test_fabricated_quote_dropped():
    _, dropped = check([{"text": "Lợi nhuận 300 tỷ.", "citations": [{"doc": "D1", "quote": "Lợi nhuận năm 2025 đạt 300 tỷ"}]}], L, P)
    assert dropped


def test_number_mismatch_dropped():
    _, dropped = check([{"text": "Doanh thu 2025 là 1.350 tỷ đồng.",
                         "citations": [{"doc": "D1", "quote": "Doanh thu năm 2025 đạt 1.250,5 tỷ đồng"}]}], L, P)
    assert "con số" in dropped[0][1]


def test_quote_tolerates_punctuation_only_differences():
    # qwen sometimes ends a verbatim quote with a CJK full stop or drops a comma
    assert quote_found("Doanh thu năm 2025 đạt 1.250,5 tỷ đồng。", P[10]["text"], fuzzy=False)
    assert quote_found("«Doanh thu năm 2025 đạt 1.250,5 tỷ đồng tăng 18,2%»", P[10]["text"], fuzzy=False)
    # but a changed number is still rejected
    assert not quote_found("Doanh thu năm 2025 đạt 1.350,5 tỷ đồng", P[10]["text"], fuzzy=False)


def test_numbers_from_question_are_context():
    p = {12: {"text": "Doanh thu thuần | 1.842,60 | 2.315,40 | 2.786,90", "ocr": False}}
    claim = [{"text": "Doanh thu thuần năm 2025 là 2.786,9 tỷ đồng.",
              "citations": [{"doc": "D1", "quote": "Doanh thu thuần | 1.842,60 | 2.315,40 | 2.786,90"}]}]
    kept, _ = check(claim, {"D1": 12}, p, question="Doanh thu thuần năm 2025 là bao nhiêu?")
    assert len(kept) == 1
    # a number that is neither in the question nor in the quote is still rejected
    bad = [{"text": "Doanh thu thuần năm 2025 là 2.900 tỷ đồng.", "citations": claim[0]["citations"]}]
    kept, dropped = check(bad, {"D1": 12}, p, question="Doanh thu thuần năm 2025 là bao nhiêu?")
    assert not kept and "con số" in dropped[0][1]


def test_fuzzy_only_for_ocr():
    assert quote_found("Tỷ giá trần bảo hiểm là 25.850 VND/USD theo thoả thuận", P[11]["text"], fuzzy=True)
    assert not quote_found("Doanh thu năm 2025 dat 1.250,5 tỷ đồng", P[10]["text"], fuzzy=False)
