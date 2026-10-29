"""DR_BINDING (dr/core/verify.py unbound): a figure must keep its meaning between the claim and its quote."""
from dr.config import settings
from dr.core import verify


def test_unbound_flags_a_figure_read_under_another_meaning():
    assert verify.unbound("Cổ phiếu có giá chỉ từ 600 triệu.", ["Ngân sách dự kiến 600 triệu cho đợt chào bán"], []) \
        == ("giá", "ngân sách")
    assert verify.unbound("Thu nhập 3.000 USD mỗi tháng.", ["Bên B cam kết thuê 3.000 USD/tháng"], []) \
        == ("thu nhập", "tiền thuê")


def test_unbound_keeps_same_or_unknown_meaning():
    assert verify.unbound("Thu nhập 50 triệu mỗi tháng.", ["Thu nhập lên tới 50tr/tháng"], []) is None
    assert verify.unbound("Giá chào bán chỉ từ 1,4 tỷ.", ["Gói đầu tư chỉ từ 1,4 tỷ"], []) is None
    assert verify.unbound("Tổng cộng 110.000.000 đồng.", ["Ngân sách 110.000.000"], []) is None   # claim says nothing
    assert verify.unbound("Giá 1,4 tỷ.", ["Gói đầu tư 1,4 tỷ"], []) is None                       # quote says nothing
    # the words before the previous figure belong to that figure
    assert verify.unbound("Diện tích 52,55 m2, giá 1,4 tỷ.", ["Diện tích 52,55 m2 giá bán 1,4 tỷ"], []) is None
    # a figure the question gives is context, not checked
    assert verify.unbound("Giá 600 triệu.", ["Ngân sách 600 triệu"], verify.numbers_with_digits("600 triệu")) is None


def test_check_drops_unbound_claim_only_when_flag_on(monkeypatch):
    claims = [{"text": "Cổ phiếu có giá 600 triệu.", "citations": [{"doc": "D1", "quote": "Ngân sách dự kiến 600 triệu đồng"}]}]
    passages = {1: {"text": "Ngân sách dự kiến 600 triệu đồng cho chiến dịch."}}
    monkeypatch.setattr(settings, "binding", False)
    assert len(verify.check(claims, {"D1": 1}, passages)[0]) == 1
    monkeypatch.setattr(settings, "binding", True)
    kept, dropped = verify.check(claims, {"D1": 1}, passages)
    assert not kept and "gắn sai nghĩa" in dropped[0][1]
