from dr.core import facts
from dr.core.verify import check

LETTER = ("BỘ TỔNG THAM MUỖ CỰC TÁC CHIẾN CÔNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM Độc lập - Tự do - Hạnh phúc "
          "S6: 1336 /Tg1-QC V/v đính chính văn bản Hà Nội, ngày 02 tháng 6 năm 2009 Kính gửi: Công ty TNHH "
          "Thương mại dịch vụ văn hoá Minh Châu")
OTHER = "- Chẳng vấn số 1170/Tgl-QC ngày 18/5/2009 của Cục Tác chiến - Bộ Tổng Tham mưu về việc độ cao tĩnh không"
CONTRACT = ("Của Hợp đồng số 224/2022-HĐTC/MC-TYT ngày 23/06/2022 về việc Cung cấp và Thi công lắp đặt Hệ thống "
            "Busway cho Dự án CT Plaza Minh Châu")
LAND = "2.2. Đặc điểm về đất xây dựng Tòa nhà: Thừa đất số: 13 ; b) Tờ bản đồ số: 83 do Sở Tài nguyên lập"
TAX = "CÔNG TY TNHH ĐẠI LÝ THUẾ HOÀI NHƠN\nMST: 4101592575\nĐC: 35 TĂNG BẠT HỒ"


def test_ocr_label_and_values_cut_from_the_original():
    [f] = facts.extract(LETTER)
    assert (f.kind, f.number, f.date, f.subject) == ("doc", "1336/Tg1-QC", "02/06/2009", "đính chính văn bản")
    assert all(q in LETTER for q in f.quotes)                     # quotes are the original text, verbatim


def test_contract_land_and_tax():
    [c] = facts.extract(CONTRACT)
    assert (c.number, c.date) == ("224/2022-HĐTC/MC-TYT", "23/06/2022") and "Busway" in c.subject
    [land] = facts.extract(LAND)
    assert (land.kind, land.number, land.subject) == ("land", "13", "83")
    [tax] = facts.extract(TAX)
    assert tax.number == "4101592575" and "ĐẠI LÝ THUẾ HOÀI NHƠN" in tax.subject


def test_no_header_no_fact():
    assert facts.extract("Số: 25/2020 thanh toán 38.515.000") == []          # no date, no subject


def _rows(*pairs):
    out = []
    for i, (text, ctx) in enumerate(pairs):
        for f in facts.extract(text):
            out.append({"kind": f.kind, "number": f.number, "date": f.date, "subject": f.subject,
                        "quotes": f.quotes, "descriptor": facts.descriptor(f, ctx), "chunk_id": i, "item_id": str(i)})
    return out


def test_question_picks_the_letter_by_its_date_and_subject():
    rows = [r for r in _rows((LETTER, "CTY MINH CHÂU › PHÁP LÝ › Cục tác chiến"), (OTHER, "CTY MINH CHÂU › PHÁP LÝ"))
            if r["kind"] == "doc"]
    q = "Công văn của Cục Tác chiến ngày 02/6/2009 về việc đính chính văn bản, gửi Công ty Minh Châu, mang số hiệu bao nhiêu?"
    assert facts.asked_kind(q) == "doc"
    [best] = facts.match(q, "doc", rows)
    assert best["number"] == "1336/Tg1-QC"


def test_answer_line_passes_verification():
    [r] = [x for x in _rows((LETTER, "CTY MINH CHÂU")) if x["kind"] == "doc"]
    claim = {"text": facts.claim_for(r), "citations": [{"doc": "F1", "quote": q} for q in r["quotes"]]}
    kept, dropped = check([claim], {"F1": 7}, {7: {"chunk_id": 7, "text": LETTER}}, "số hiệu công văn?")
    assert kept, dropped


def test_unrelated_question_gets_no_fact():
    rows = [r for r in _rows((CONTRACT, "CTY MINH CHÂU › Busway")) if r["kind"] == "doc"]
    assert facts.match("Số hợp đồng thuê văn phòng ở Hà Nội là gì?", "doc", rows) == []
