import json
import sys
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import gen_hard_scans as g  # noqa: E402


def _check_doc(out: Path, d: dict):
    f = out / d["file"]
    assert f.exists() and f.stat().st_size > 5_000, d["file"]
    assert d["kind"] in g.KINDS and d["format"] == f.suffix[1:]
    assert d["extra"] is None or d["extra"] in g.EXTRAS
    assert d["rotation"] in (0, 90, 180, 270)
    assert len(d["numbers"]) >= 3, d["file"]
    assert all(n["text"] and 1 <= n["page"] <= d["pages"] for n in d["numbers"])
    assert 2 <= len(d["phrases"]) <= 4
    assert any(ch in "".join(d["phrases"]) for ch in "ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ"
               "ĂÂĐÊÔƠƯẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼẾỀỂỄỆỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰ")
    if d["format"] == "pdf":
        pdf = pdfium.PdfDocument(str(f))
        assert len(pdf) == d["pages"]
        for i in range(len(pdf)):
            assert pdf[i].get_textpage().get_text_range().strip() == ""
            w, h = pdf[i].get_size()
            assert 300 < w < 2000 and 300 < h < 2000                     # points, ~A4 (595x842)
    else:
        assert d["pages"] == 1
        with Image.open(f) as im:
            w, h = im.size
            assert 400 <= min(w, h) and max(w, h) <= 3000, (d["file"], im.size)
            if d["rotation"] in (90, 270):
                assert w > h


def test_generate_small(tmp_path):
    truth = g.generate(tmp_path, n_docs=6, seed=7, quiet=True)
    assert json.loads((tmp_path / "truth.json").read_text(encoding="utf-8")) == truth
    assert truth["seed"] == 7 and len(truth["docs"]) == 6
    for d in truth["docs"]:
        _check_doc(tmp_path, d)


@pytest.fixture(scope="module")
def all_kinds(tmp_path_factory):
    out = tmp_path_factory.mktemp("hs_kinds")
    return out, g.generate(out, n_docs=len(g.KINDS), seed=11, quiet=True)


def test_all_kinds_present(all_kinds):
    out, truth = all_kinds
    docs = {d["kind"]: d for d in truth["docs"]}
    assert set(docs) == set(g.KINDS)
    assert {d["format"] for d in truth["docs"]} == {"png", "jpg", "pdf"}
    for d in truth["docs"]:
        _check_doc(out, d)
    assert docs["rot90"]["rotation"] == 90 and docs["rot180"]["rotation"] == 180
    assert any(n["handwritten"] for n in docs["handwriting"]["numbers"])
    assert any(n["covered"] for n in docs["stamp_over_numbers"]["numbers"])
    assert any(n["covered"] for n in docs["fold_stain"]["numbers"])
    mp = docs["multi_page_table"]
    assert 3 <= mp["pages"] <= 6 and {n["page"] for n in mp["numbers"]} == set(range(1, mp["pages"] + 1))
    with Image.open(out / docs["fax"]["file"]) as im:
        assert im.mode == "1"


def test_deterministic(tmp_path):
    a = g.generate(tmp_path / "a", n_docs=2, seed=5, quiet=True)
    b = g.generate(tmp_path / "b", n_docs=2, seed=5, quiet=True)
    assert a == b
