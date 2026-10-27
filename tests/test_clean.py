from dr.ingest.chunker import chunk
from dr.ingest.clean import clean_text, table_records
from dr.ingest.parsers import Block


def test_controls_html_markdown_and_runs():
    t = clean_text("Số: ..............\x03 ngày <br>tháng **12**\n\n\n\nMã 0000000000000 ---------- hết")
    assert t == "Số: ... ngày\ntháng 12\n\nMã 000… --- hết"


def test_broken_font_line_is_dropped_vietnamese_kept():
    t = clean_text("Hợp đồng mua bán căn hộ\n¤£¦¢»«¤£¦\nGiá: 1.250.000.000 đ")
    assert t == "Hợp đồng mua bán căn hộ\nGiá: 1.250.000.000 đ"


def test_reader_loop_and_latex():
    assert clean_text("diện tích 52.55 $ m^{2} $ " + "Page30 " * 12).startswith("diện tích 52.55 m² Page30 Page30 …")


def test_ocr_table_becomes_records_with_misaligned_first_cell():
    t = ("KÍ HIỆU | LOẠI CĂN HỘ | DIỆN TÍCH THÔNG THỦY | DIỆN TÍCH XÂY DỰNG\n"
         " | PS1 | 303.09 m² | 321.56 m²\n | PS2 | 276.6 m² | 293.2 m²")
    assert table_records(t) == ("LOẠI CĂN HỘ: PS1; DIỆN TÍCH THÔNG THỦY: 303.09 m²; DIỆN TÍCH XÂY DỰNG: 321.56 m²\n"
                                "LOẠI CĂN HỘ: PS2; DIỆN TÍCH THÔNG THỦY: 276.6 m²; DIỆN TÍCH XÂY DỰNG: 293.2 m²")


def test_row_with_a_lost_cell_stays_raw_others_become_records():
    t = "STT | MÃ CĂN | DIỆN TÍCH\n1 | S-01 | 26.4\n2 | S-02 28.1\n3 | S-03 | 28.2"
    assert table_records(t) == "STT: 1; MÃ CĂN: S-01; DIỆN TÍCH: 26.4\n2 | S-02 28.1\nSTT: 3; MÃ CĂN: S-03; DIỆN TÍCH: 28.2"


TYPED = ["Căn hộ B4 có diện tích xây dựng 56 m². Căn hộ A6 nằm ở tầng 17."] * 80 + \
        ["Hợp đồng mua bán căn hộ giữa chủ đầu tư và khách hàng."] * 80 + \
        ["Tạm dừng thi công khi có sự cố, cản trở giao thông."] * 3 + ["Nhà thầu sử dụng vật tư."] * 80


def test_ocr_tone_marks_learned_from_typed_text():
    from dr.ingest import ocr_accents
    ocr_accents.learn(TYPED)
    try:
        assert ocr_accents.fix("CẢN HỘ B4 có DIỆN TÍCH XẤY DỰNG 56 m²") == "CĂN HỘ B4 có DIỆN TÍCH XÂY DỰNG 56 m²"
        assert ocr_accents.fix("HỘP ĐÔNG mua bán, chủ đấu tư") == "HỢP ĐỒNG mua bán, chủ đầu tư"
        # real words stay: 'tạm dụng' is never typed although 'dụng' is commoner than 'dừng'; 'cản trở' is typed
        assert ocr_accents.fix("tạm dừng thi công, cản trở giao thông") == "tạm dừng thi công, cản trở giao thông"
        assert ocr_accents.fix("Căn A6: 63.41 m², mã SH09") == "Căn A6: 63.41 m², mã SH09"     # numbers, codes
    finally:
        ocr_accents.reset()


def test_poster_label_and_value_lines_are_joined():
    from dr.ingest.clean import join_label_lines
    assert join_label_lines("GIẢI NHẤT\n1 lượng vàng 9999\nGIẢI NHÌ\nIphone 13") == \
        "GIẢI NHẤT: 1 lượng vàng 9999\nGIẢI NHÌ\nIphone 13"
    assert join_label_lines("CĂN S-08\n28.4 m²/31.2 m²\nĐÔNG-NAM") == "CĂN S-08: 28.4 m²/31.2 m²\nĐÔNG-NAM"
    assert join_label_lines("Điều 1. Giá bán.\n2. Thanh toán") == "Điều 1. Giá bán.\n2. Thanh toán"


def test_table_without_header_is_left_alone():
    t = "1 | S-01 | 26.4\n2 | S-02 | 28.1\n3 | S-03 | 28.2"
    assert table_records(t) == t


def test_page_header_kept_on_first_page_only():
    blocks = [Block(f"CÔNG TY MINH CHÂU\nNội dung trang {i}", f"Trang {i}") for i in range(1, 5)]
    text = "\n".join(c.text for c in chunk(blocks, max_chars=10_000))
    assert text.count("CÔNG TY MINH CHÂU") == 1 and all(f"Nội dung trang {i}" in text for i in range(1, 5))


def test_only_ocr_tables_are_rewritten():
    t = "Tên | Giá | Ghi chú\nA | 10 | x\nB | 20 | y"
    assert chunk([Block(t, "Trang 1", "table", ocr=False)])[0].text == t
    assert chunk([Block(t, "Trang 1", "table", ocr=True)])[0].text == "Tên: A; Giá: 10; Ghi chú: x\nTên: B; Giá: 20; Ghi chú: y"
