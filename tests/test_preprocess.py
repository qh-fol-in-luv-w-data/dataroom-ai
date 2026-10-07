import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from dr.ingest import preprocess
from dr.ingest.chunker import chunk
from dr.ingest.ocr import cross_check, numbers_in
from dr.ingest.parsers import Block

FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
LINES = ["HỢP ĐỒNG THI CÔNG XÂY LẮP SỐ 0726/2025/HĐ-SM",
         "Tổng giá trị hợp đồng: 667.036.000.000 đồng",
         "Tạm ứng 30% giá trị hợp đồng, tương đương 200.110.800.000 đồng",
         "Thanh toán đợt 2 sau nghiệm thu, hạn chót ngày 22/09/2025",
         "Lãi chậm thanh toán 0,05% mỗi ngày trên số tiền chậm trả",
         "Hợp đồng có hiệu lực từ ngày 06/09/2025 đến 11/08/2027"]


def page() -> np.ndarray:
    img = Image.new("RGB", (1654, 2339), "white")
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, 40)
    for i, t in enumerate(LINES * 3):
        d.text((140, 200 + i * 90), t, font=f, fill="black")
    return np.asarray(img)


@pytest.mark.parametrize("deg", [0, 90, 180, 270])
def test_orientation_restores_upright_text(deg):
    turned = preprocess.rotate(page(), deg)             # a page scanned sideways / upside down
    assert preprocess.orientation(turned) == (360 - deg) % 360


def test_prepare_reads_numbers_after_rotation():
    prep = preprocess.prepare(Image.fromarray(preprocess.rotate(page(), 180)))
    assert any("xoay" in s for s in prep.steps)
    text = " ".join(ln.text for ln in prep.lines).replace(" ", "")
    assert "667.036.000.000" in text and "22/09/2025" in text


def test_unwarp_flattens_photo_of_page():
    pg_ = page()
    desk = np.full((2600, 2100, 3), (70, 60, 50), np.uint8)
    src = np.float32([[0, 0], [1653, 0], [1653, 2338], [0, 2338]])
    dst = np.float32([[300, 180], [1850, 260], [1950, 2450], [180, 2380]])
    m = cv2.getPerspectiveTransform(src, dst)
    photo = cv2.warpPerspective(pg_, m, (2100, 2600), dst=desk.copy(), borderMode=cv2.BORDER_TRANSPARENT)
    flat = preprocess.unwarp_page(photo)
    assert flat is not None
    h, w = flat.shape[:2]
    assert h > w > 1200                                     # a portrait page, not the whole photo
    for y, x in [(10, 10), (10, w - 10), (h - 10, 10), (h - 10, w - 10)]:
        assert flat[y, x].mean() > 200                      # corners are paper, the desk is cut away
    assert preprocess.unwarp_page(pg_) is None              # flat scans are left alone


def test_cross_check_flags_numbers_only_one_reader_saw():
    lines = [preprocess.Line("Tong gia tri: 667.036.000.000 dong", 0.9, (0, 0, 1, 1))]
    doubt, n = cross_check("Tổng giá trị: 667.036.000.000 đồng, tạm ứng 200.110.800.000 đồng", lines)
    assert n == 2 and doubt == ["200.110.800.000"]
    assert numbers_in("Điều 3 và 12,5% và 06/09/2025") == ["12,5", "06/09/2025"]   # ≥3 digits only


def test_chunks_carry_ocr_doubt_and_page():
    blocks = [Block("Tổng giá trị 667.036.000.000 đồng.", "Trang 1", ocr=True,
                    meta={"doubt": ["667.036.000.000", "999.999"], "page_key": "abc/p1"}),
              Block("Đoạn khác không có số.", "Trang 2", ocr=True, meta={"doubt": [], "page_key": "abc/p2"})]
    out = chunk(blocks, max_chars=40)
    first = [c for c in out if "667" in c.text][0]
    assert first.doubt == ["667.036.000.000"] and first.page_key == "abc/p1"
    assert all(not c.doubt for c in out if "667" not in c.text)
