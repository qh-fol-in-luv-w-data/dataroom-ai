"""Accuracy methods behind DR_* flags (dr/config.py): number meaning, document kind, vote."""
from dr.config import settings
from dr.core import answer, doctype, verify


def test_unbound_flags_a_figure_read_under_another_meaning():
    assert verify.unbound("Căn studio có giá chỉ từ 600 triệu.", ["Ngân sách dự kiến 600 triệu cho đợt mở bán"], []) \
        == ("giá", "ngân sách")
    assert verify.unbound("Thu nhập 3.000 USD mỗi tháng.", ["Bên B cam kết thuê 3.000 USD/tháng"], []) \
        == ("thu nhập", "tiền thuê")


def test_unbound_keeps_same_or_unknown_meaning():
    assert verify.unbound("Thu nhập 50 triệu mỗi tháng.", ["Thu nhập lên tới 50tr/tháng"], []) is None
    assert verify.unbound("Căn studio giá chỉ từ 1,4 tỷ.", ["Sở hữu căn studio chỉ từ 1,4 tỷ"], []) is None
    assert verify.unbound("Tổng cộng 110.000.000 đồng.", ["Ngân sách 110.000.000"], []) is None   # claim says nothing
    assert verify.unbound("Giá 1,4 tỷ.", ["Căn studio 1,4 tỷ"], []) is None                       # quote says nothing
    # the words before the previous figure belong to that figure
    assert verify.unbound("Diện tích 52,55 m2, giá 1,4 tỷ.", ["DT thông thủy 52,55 m2 giá bán 1,4 tỷ"], []) is None


def test_check_drops_unbound_claim_only_when_flag_on(monkeypatch):
    claims = [{"text": "Căn studio có giá 600 triệu.", "citations": [{"doc": "D1", "quote": "Ngân sách dự kiến 600 triệu đồng"}]}]
    passages = {1: {"text": "Ngân sách dự kiến 600 triệu đồng cho chiến dịch."}}
    monkeypatch.setattr(settings, "binding", False)
    assert len(verify.check(claims, {"D1": 1}, passages)[0]) == 1
    monkeypatch.setattr(settings, "binding", True)
    kept, dropped = verify.check(claims, {"D1": 1}, passages)
    assert not kept and "gắn sai nghĩa" in dropped[0][1]


def test_doctype_from_name_then_folders():
    assert doctype.classify("/sites/a/Shared Documents/Tuyển dụng/Léman", "Cyber Sale 4.0.jpg") == "tin tuyển dụng"
    assert doctype.classify("/sites/a/Shared Documents/Pháp lý", "Hợp đồng PCCC.pdf") == "hợp đồng"
    assert doctype.classify("/sites/a/Shared Documents/x", "Bảng giá Léman.xlsx") == "bảng giá"
    assert doctype.classify("/sites/a/Shared Documents/x", "IMG_0042.jpg") == ""


def test_vote_takes_the_answer_most_samples_agree_on(monkeypatch):
    monkeypatch.setattr(settings, "binding", False)   # with binding on, the "600 triệu" sample fails verification
    passages = {1: {"text": "Giá 1,4 tỷ. Ngân sách 600 triệu."}}

    def run(fig, quote):
        return {"claims": [{"text": f"Giá {fig}.", "citations": [{"doc": "D1", "quote": quote}]}]}, {"D1": 1}
    runs = [run("600 triệu", "Ngân sách 600 triệu"), run("1,4 tỷ", "Giá 1,4 tỷ"), run("1,4 tỷ", "Giá 1,4 tỷ")]
    (raw, _), agree = answer.vote(runs, passages, "Giá bao nhiêu?")
    assert agree == 2 and "1,4" in raw["claims"][0]["text"]
    (raw, _), agree = answer.vote(runs[:2], passages, "Giá bao nhiêu?")   # a tie: the first (temperature 0) sample
    assert agree == 1 and "600" in raw["claims"][0]["text"]
