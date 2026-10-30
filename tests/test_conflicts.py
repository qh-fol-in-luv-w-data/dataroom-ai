from datetime import date

from dr.core import conflicts

Q = "Căn hộ B4 dự án C.T Plaza Nguyên Hồng có diện tích thông thủy bao nhiêu?"
CLAIM = "Diện tích thông thủy căn B4 là 52.55 m²."
QUOTE = "Diện tích thông thủy: 52.55 m²"
PASSAGES = {
    1: {"text": "CĂN HỘ B4\nDiện tích xây dựng: 55.78 m²\nDiện tích thông thủy: 52.55 m²"},
    2: {"text": "CĂN HỘ B4\nDiện tích xây dựng: 56.72 m²\nDiện tích thông thủy: 52.88 m²\nPhòng ngủ 01 10.03 m²"},
    3: {"text": "CĂN HỘ A6\nDiện tích thông thủy: 63.41 m²"},
    4: {"text": "LOẠI CĂN HỘ: B4; DIỆN TÍCH THÔNG THỦY: 52.55 m²\nLOẠI CĂN HỘ: B5; DIỆN TÍCH THÔNG THỦY: 60.1 m²"},
}


def test_other_version_of_the_same_unit_is_reported():
    found = conflicts.find(Q, CLAIM, [QUOTE], {1}, PASSAGES)
    assert [(c.chunk_id, c.value) for c in found] == [(2, "52.88")]
    assert found[0].quote == "Diện tích thông thủy: 52.88 m²"


def test_other_units_and_other_measures_are_not_conflicts():
    found = conflicts.find(Q, CLAIM, [QUOTE], {1, 2}, PASSAGES)
    assert found == []          # A6 is another unit, B5's row names B5, 'xây dựng' is another measure


def test_measure_not_asked_about_is_not_checked():
    claim = "Phòng ngủ 01 10.03 m²"
    assert conflicts.find(Q, claim, [claim], {1}, PASSAGES) == []       # the question asks for usable area


def test_no_unit_code_no_check():
    assert conflicts.find("Giá bán căn hộ là bao nhiêu?", "Giá 1,4 tỷ.", ["Giá 1,4 tỷ"], set(), PASSAGES) == []


def test_dates_in_file_names():
    assert conflicts.doc_date("CF-PTT-CTPlazaNH-Layout mat bang tong the-23.03.2018.jpg") == date(2018, 3, 23)
    assert conflicts.doc_date("TTCU - HĐ cung cap Busway 23.06.22.pdf") == date(2022, 6, 23)
    assert conflicts.doc_date("CF-CQ9-DIYAS_Bao thu-07062023.jpg") == date(2023, 6, 7)
    assert conflicts.doc_date("BanXD-KH_update 20210618.pdf") == date(2021, 6, 18)
    assert conflicts.doc_date("Artboard 9.png") is None and conflicts.doc_date("SH09 99.99.99.pdf") is None


def test_source_weight():
    assert conflicts.source_weight("05. Thị trường", "REJECTED_CF_PTT_LEMAN.pdf") == 0.5
    assert conflicts.source_weight("05. Thị trường", "Bảng giá - bản cũ.xlsx") == 0.5
    assert conflicts.source_weight("03. Pháp lý/3.2 Hợp đồng", "HĐ Busway.pdf") == 1.1
    assert conflicts.source_weight("05. Thị trường", "[signed]TTCU-To trinh.pdf") == 1.1
    assert conflicts.source_weight("05. Thị trường", "poster.jpg") == 1.0


def test_older_versions_of_the_same_file_name():
    names = {"a": "Bang gia SH 01.03.2023.pdf", "b": "Bang gia SH 15.06.2024.pdf", "c": "Bang gia SH (1).pdf",
             "d": "HDMB can A6 v1.docx", "e": "HDMB can A6 v2 final.docx", "f": "Quy che.pdf", "g": "Quy che.pdf"}
    old = conflicts.older_versions(names)
    assert old == {"a", "d"}          # c has no date: not comparable; f/g the same name, no version


def test_rank_weights_prefer_the_latest_version():
    from dr.core.answer import rank_weights
    passages = {1: {"item_id": "a", "name": "Bang gia SH 01.03.2023.pdf", "path": ""},
                2: {"item_id": "b", "name": "Bang gia SH 15.06.2024.pdf", "path": ""},
                3: {"item_id": "x", "name": "Ban nhap ke hoach.pdf", "path": ""}}
    w = rank_weights([1, 2, 3], passages)
    assert w[2] == 1.0 and w[1] < 1.0
    assert w[3] == 0.5                 # a draft keeps its own weight
