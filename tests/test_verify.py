from decimal import Decimal

from dr.core.verify import check, quote_found, vn_numbers

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


def test_fuzzy_only_for_ocr():
    assert quote_found("Tỷ giá trần bảo hiểm là 25.850 VND/USD theo thoả thuận", P[11]["text"], fuzzy=True)
    assert not quote_found("Doanh thu năm 2025 dat 1.250,5 tỷ đồng", P[10]["text"], fuzzy=False)
