from dr.config import settings
from dr.ingest import ocr_md

MD = """# a.pdf

## Trang 1

HỢP ĐỒNG MUA BÁN

Bên A | Bên B
Công ty X | Ông Y

## Trang 2

_(ảnh không có chữ, bỏ qua)_

Chữ trong ảnh (OCR toàn ảnh):

_(không đọc được chữ)_
"""


def test_pages_tables_and_placeholders():
    doc = ocr_md.parse(MD, image=False)
    assert [(b.locator, b.kind) for b in doc.blocks] == [("Trang 1", "text"), ("Trang 1", "table")]
    assert all(b.ocr for b in doc.blocks) and doc.converter == ocr_md.CONVERTER


def test_image_without_text_has_no_blocks():
    assert ocr_md.parse("# b.jpg\n\n## Trang 1\n\n_(ảnh không có chữ, bỏ qua)_\n", image=True).blocks == []


def test_decoding_loop_is_cut_when_chunked():
    from dr.ingest.chunker import chunk
    doc = ocr_md.parse("## Trang 1\n\n" + "http://a.vn " * 30 + "\n", image=True)
    chunks = chunk(doc.blocks)
    assert chunks[0].text.count("http://a.vn") == 2 and chunks[0].locator == "Ảnh"


def test_latex_units_become_plain_text():
    from dr.ingest.ocr import clean_math
    assert clean_math("| PS1 | 303.09  $ m^{2} $ | 321.56  $ m^{{2}} $") == "| PS1 | 303.09 m² | 321.56 m² "
    assert clean_math("26.4 m $ ^{2} $/28.8") == "26.4 m² /28.8"
    assert clean_math("ống $ \\Phi 300 $, 3 $ \\pm $ 0.2") == "ống Φ 300 , 3 ± 0.2"
    assert clean_math("$ \\underline{\\text{Don vi}} $") == " Don vi "
    assert clean_math("font hỏng $¤1+2£$ giữ nguyên, giá 5$ và 7$") == "font hỏng $¤1+2£$ giữ nguyên, giá 5$ và 7$"


def test_exported_markdown_reads_back():
    md = "# a.pdf\n\n<!-- đọc bằng: pdfium-text -->\n\n## Trang 1 – Trang 2\n\nĐiều 1. Giá bán\n"
    doc = ocr_md.parse(md, image=False)
    assert [(b.locator, b.text) for b in doc.blocks] == [("Trang 1 – Trang 2", "Điều 1. Giá bán")]


def test_text_layer_markdown_is_not_ocr():
    assert ocr_md.is_ocr("# a.jpg\n\n## Trang 1\n\nCHỮ OCR")                                 # GPU server output
    assert ocr_md.is_ocr("# a.pdf\n\n<!-- đọc bằng: PaddleOCR-VL-1.6 -->\n\n## Trang 1\n\nx")
    assert not ocr_md.is_ocr("# a.pdf\n\n<!-- đọc bằng: pdfium-text -->\n\n## Trang 1\n\nx")
    assert not ocr_md.is_ocr("# a.pdf\n\n<!-- đọc bằng: pdfium-text+PaddleOCR-VL-1.6 -->\n\n## Trang 1\n\nx")


def test_find_exact_nfd_and_shortened(tmp_path, monkeypatch):
    import unicodedata
    (tmp_path / "05. Thị trường" / "MẶT BẰ~").mkdir(parents=True)
    (tmp_path / "05. Thị trường" / "MẶT BẰ~" / "CAN DIEN H~.jpg.md").write_text("x")
    nfd = unicodedata.normalize("NFD", "Pháp lý")
    (tmp_path / nfd).mkdir()
    (tmp_path / nfd / "hợp đồng.pdf.md").write_text("y")
    monkeypatch.setattr(settings, "ocr_md_dir", str(tmp_path))
    monkeypatch.setattr(ocr_md, "_index", None)
    assert ocr_md.find("Pháp lý", "hợp đồng.pdf").read_text() == "y"
    assert ocr_md.find("05. Thị trường/MẶT BẰNG CĂN HỘ", "CAN DIEN HINH S-01.jpg").read_text() == "x"
    assert ocr_md.find("05. Thị trường/MẶT BẰNG CĂN HỘ", "CAN DIEN HINH S-01.png") is None
    assert ocr_md.find("Khác", "hợp đồng.pdf") is None
