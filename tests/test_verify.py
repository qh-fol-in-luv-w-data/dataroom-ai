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


def test_number_must_match_in_digits_and_value():
    passages = {1: {"chunk_id": 1, "text": "CHIẾN BINH CYBER SALE 4.0\nThu nhập 50tr mỗi tháng"}}
    invented = {"text": "Thu nhập lên đến 4.000 USD/tháng.",
                "citations": [{"doc": "D1", "quote": "CHIẾN BINH CYBER SALE 4.0"}]}
    kept, dropped = check([invented], {"D1": 1}, passages, "Cyber Sale 4.0 hứa thu nhập bao nhiêu?")
    assert not kept and "con số" in dropped[0][1]
    right = {"text": "Thu nhập 50tr mỗi tháng.", "citations": [{"doc": "D1", "quote": "Thu nhập 50tr mỗi tháng"}]}
    assert check([right], {"D1": 1}, passages, "")[0]


def test_same_number_other_separators_still_matches():
    passages = {1: {"chunk_id": 1, "text": "Diện tích thông thủy: 52,55 m²; giá 5.433.003.576 đồng"}}
    claim = {"text": "Diện tích 52,55 m², giá 5.433.003.576 đồng.",
             "citations": [{"doc": "D1", "quote": "Diện tích thông thủy: 52,55 m²; giá 5.433.003.576 đồng"}]}
    assert check([claim], {"D1": 1}, passages, "")[0]


def test_table_row_claim_may_use_header_units_but_not_another_rows_name():
    """A scanned table names its units/columns (MW, COD) in the header row only."""
    table = {20: {"text": "Nhà máy | Tỉnh | Công suất (MW) | COD\nĐMT Ninh Phước 1 | Ninh Thuận | 150 | 2019\n"
                          "Điện gió Thuận Nam GJDC | Ninh Thuận | 88 | 2021", "ocr": True, "kind": "table"}}
    row = "ĐMT Ninh Phước 1 | Ninh Thuận | 150 | 2019"
    ok = [{"text": "ĐMT Ninh Phước 1 có công suất 150 MW, COD năm 2019.", "citations": [{"doc": "D1", "quote": row}]}]
    kept, dropped = check(ok, {"D1": 20}, table)
    assert len(kept) == 1 and not dropped
    other = [{"text": "GJDC có công suất 150 MW.", "citations": [{"doc": "D1", "quote": row}]}]   # another row's name
    kept, dropped = check(other, {"D1": 20}, table)
    assert not kept and "GJDC" in dropped[0][1]
    plain = {21: {**table[20], "kind": "text"}}                       # not a table: header rule does not apply
    kept, dropped = check(ok, {"D1": 21}, plain)
    assert not kept


# ---- named codes (SH09, GJDC): only real codes, matched against the passage's text AND its file
def test_company_type_abbreviations_are_not_codes():
    p = {1: {"chunk_id": 1, "text": "CÔNG TY TNHH TM DV SAO MAI\nĐịa chỉ: 12 Lê Lợi"},
         2: {"chunk_id": 2, "text": "Vốn điều lệ của công ty là 5.000.000.000 đồng."}}
    claim = {"text": "Vốn điều lệ là 5.000.000.000 đồng.",
             "citations": [{"doc": "D2", "quote": "Vốn điều lệ của công ty là 5.000.000.000 đồng."}]}
    kept, dropped = check([claim], {"D1": 1, "D2": 2}, p, "Công ty TNHH TM DV Sao Mai có vốn điều lệ bao nhiêu?")
    assert kept and not dropped


def test_unaccented_word_from_a_file_name_is_not_a_code():
    # the question copies an upper-case, unaccented file name ("BIEN BAN GIAO NHAN"); "giao" is an ordinary word
    p = {1: {"chunk_id": 1, "text": "Số căn hộ bên mua đã nhận: 12 căn."},
         2: {"chunk_id": 2, "text": "Kế hoạch giao hàng tháng 3."}}
    claim = {"text": "Bên mua đã nhận 12 căn hộ.", "citations": [{"doc": "D1", "quote": "Số căn hộ bên mua đã nhận: 12 căn"}]}
    kept, dropped = check([claim], {"D1": 1, "D2": 2}, p, "Theo BIEN BAN GIAO NHAN, bao nhiêu căn hộ được bàn giao?")
    assert kept and not dropped


def test_named_code_may_come_from_the_cited_passages_file_name():
    p = {1: {"chunk_id": 1, "text": "Đơn giá thi công: 1.250.000 đồng/m2.", "name": "PVC - Bao gia thi cong.pdf",
             "path": "/sites/x/Du an/PVC/PVC - Bao gia thi cong.pdf"},
         2: {"chunk_id": 2, "text": "Ống PVC loại D90 và phụ kiện.", "name": "Vat tu.xlsx", "path": "/sites/x/Vat tu.xlsx"}}
    claim = {"text": "Đơn giá thi công là 1.250.000 đồng/m2.",
             "citations": [{"doc": "D1", "quote": "Đơn giá thi công: 1.250.000 đồng/m2."}]}
    kept, dropped = check([claim], {"D1": 1, "D2": 2}, p, "Đơn giá thi công trong báo giá PVC là bao nhiêu?")
    assert kept and not dropped
    # the same figure cited from a file that is not about PVC at all is still refused
    p[1] = {**p[1], "name": "Bao gia.pdf", "path": "/sites/x/Bao gia.pdf"}
    kept, dropped = check([claim], {"D1": 1, "D2": 2}, p, "Đơn giá thi công trong báo giá PVC là bao nhiêu?")
    assert not kept and "PVC" in dropped[0][1]


def test_trailing_hyphen_of_a_file_code_is_dropped():
    p = {1: {"chunk_id": 1, "text": "Giá trị quyết toán: 3.420.000.000 đồng.", "name": "TTCU-03 Quyet toan.pdf"},
         2: {"chunk_id": 2, "text": "Danh mục hồ sơ TTCU-01, TTCU-02."}}
    claim = {"text": "Giá trị quyết toán là 3.420.000.000 đồng.",
             "citations": [{"doc": "D1", "quote": "Giá trị quyết toán: 3.420.000.000 đồng."}]}
    kept, dropped = check([claim], {"D1": 1, "D2": 2}, p, "Giá trị quyết toán của hồ sơ TTCU- là bao nhiêu?")
    assert kept and not dropped
    assert all("TTCU-" not in r for _, r in dropped)


def test_hyphenated_code_named_by_the_question_is_enforced():
    p = {1: {"chunk_id": 1, "text": "Hợp đồng CTG-01: giá trị 2.100.000.000 đồng."},
         2: {"chunk_id": 2, "text": "Hợp đồng CTG-02: giá trị 1.800.000.000 đồng."}}
    wrong = {"text": "Giá trị hợp đồng CTG-01 là 1.800.000.000 đồng.",
             "citations": [{"doc": "D2", "quote": "Hợp đồng CTG-02: giá trị 1.800.000.000 đồng."}]}
    kept, dropped = check([wrong], {"D1": 1, "D2": 2}, p, "Giá trị hợp đồng CTG-01 là bao nhiêu?")
    assert not kept and "CTG-01" in dropped[0][1]
    right = {"text": "Giá trị hợp đồng CTG-01 là 2.100.000.000 đồng.",
             "citations": [{"doc": "D1", "quote": "Hợp đồng CTG-01: giá trị 2.100.000.000 đồng."}]}
    assert check([right], {"D1": 1, "D2": 2}, p, "Giá trị hợp đồng CTG-01 là bao nhiêu?")[0]


def test_claim_may_use_a_name_from_its_cited_file():
    p = {1: {"chunk_id": 1, "text": "Tổng mức đầu tư: 450 tỷ đồng.", "name": "Bao cao.pdf",
             "context": "CT Group › LEMAN PLAZA › Bao cao.pdf"},
         2: {"chunk_id": 2, "text": "Tòa LEMAN PLAZA cao 30 tầng."}}
    claim = {"text": "Tổng mức đầu tư LEMAN PLAZA là 450 tỷ đồng.",
             "citations": [{"doc": "D1", "quote": "Tổng mức đầu tư: 450 tỷ đồng."}]}
    kept, dropped = check([claim], {"D1": 1, "D2": 2}, p, "Tổng mức đầu tư là bao nhiêu?")
    assert kept and not dropped


# ---- a claim that only says the question again answers nothing
def test_claim_repeating_the_question_is_dropped():
    p = {1: {"chunk_id": 1, "text": "Chủ đầu tư dự án Sao Mai Riverside là Công ty CP Sao Mai Land. Dự án khởi công năm 2023."}}
    q = "Chủ đầu tư dự án Sao Mai Riverside là ai?"
    echo = {"text": "Chủ đầu tư dự án Sao Mai Riverside là.",
            "citations": [{"doc": "D1", "quote": "Chủ đầu tư dự án Sao Mai Riverside là Công ty CP Sao Mai Land."}]}
    kept, dropped = check([echo], {"D1": 1}, p, q)
    assert not kept and "lặp lại câu hỏi" in dropped[0][1]
    right = {"text": "Chủ đầu tư dự án Sao Mai Riverside là Công ty CP Sao Mai Land.",
             "citations": echo["citations"]}
    assert check([right], {"D1": 1}, p, q)[0]


def test_restating_the_question_with_the_figure_is_an_answer():
    p = {1: {"chunk_id": 1, "text": "Hotline dự án Sao Mai Riverside: 1900 6868."}}
    claim = {"text": "Hotline của dự án Sao Mai Riverside là 1900 6868.",
             "citations": [{"doc": "D1", "quote": "Hotline dự án Sao Mai Riverside: 1900 6868."}]}
    assert check([claim], {"D1": 1}, p, "Hotline của dự án Sao Mai Riverside là gì?")[0]


def test_yes_no_answer_may_repeat_the_question():
    p = {1: {"chunk_id": 1, "text": "Dự án Sao Mai Riverside có hồ bơi tràn bờ trên tầng thượng."}}
    claim = {"text": "Dự án Sao Mai Riverside có hồ bơi.",
             "citations": [{"doc": "D1", "quote": "Dự án Sao Mai Riverside có hồ bơi tràn bờ trên tầng thượng."}]}
    assert check([claim], {"D1": 1}, p, "Dự án Sao Mai Riverside có hồ bơi không?")[0]


def test_leading_zeros_do_not_change_a_number():
    p = {1: {"chunk_id": 1, "text": "Thời hạn bảo hành là 05 năm kể từ ngày bàn giao."}}
    claim = {"text": "Thời hạn bảo hành là 5 năm.",
             "citations": [{"doc": "D1", "quote": "Thời hạn bảo hành là 05 năm kể từ ngày bàn giao."}]}
    assert check([claim], {"D1": 1}, p, "Thời hạn bảo hành là bao lâu?")[0]
    # but a decimal is not its digits without the zero: 0,5 năm is not 5 năm
    p2 = {1: {"chunk_id": 1, "text": "Thời hạn bảo hành là 0,5 năm kể từ ngày bàn giao."}}
    bad = {"text": "Thời hạn bảo hành là 5 năm.",
           "citations": [{"doc": "D1", "quote": "Thời hạn bảo hành là 0,5 năm kể từ ngày bàn giao."}]}
    kept, dropped = check([bad], {"D1": 1}, p2, "Thời hạn bảo hành là bao lâu?")
    assert not kept and "con số" in dropped[0][1]
