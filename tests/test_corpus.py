import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import gen_corpus  # noqa: E402

from dr.ingest.parsers import parse  # noqa: E402
from dr.tenant.service import FakeTenant  # noqa: E402

TEXT_EXTS = {"docx", "xlsx", "pptx", "eml", "html", "csv", "md", "txt"}
SPECIAL = ["sp-encrypted", "sp-malware", "sp-excluded", "sp-version", "sp-injection", "sp-hidden-text",
           "sp-unique-1", "sp-link-c", "sp-anyone", "sp-excel-hidden", "sp-scan-table"]
SITE_CODE = {"COMMON": "COMMON", "GRP-A": "GRPA", "GRP-B": "GRPB", "GRP-C": "GRPC", "INTERNAL": "INTERNAL"}


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    out = tmp_path_factory.mktemp("corpus")
    gen_corpus.generate(out, n=60, seed=7, quiet=True)
    return out


def test_all_formats_and_files(corpus):
    t = json.loads((corpus / "tenant.json").read_text(encoding="utf-8"))
    exts = {i["ext"] for i in t["items"]}
    assert {"docx", "xlsx", "pptx", "pdf", "eml", "html", "csv", "md", "txt", "png", "jpg"} <= exts
    for i in t["items"]:
        assert (corpus / "files" / i["file"]).exists(), i["id"]
    ids = {i["id"] for i in t["items"]}
    assert set(SPECIAL) <= ids


def test_permissions(corpus):
    ft = FakeTenant(corpus)
    assert ft.sp_can_read("inv-a1", "sp-unique-1")
    assert not ft.sp_can_read("inv-ab", "sp-unique-1")
    assert not ft.sp_can_read("inv-c1", "sp-link-c")     # RAC on GRP-B blocks the link
    assert not ft.sp_can_read("inv-a1", "sp-link-c")
    assert ft.publish_version("sp-version")


def test_markers_stay_in_their_site(corpus):
    t = json.loads((corpus / "tenant.json").read_text(encoding="utf-8"))
    for i in t["items"]:
        if i["ext"] not in TEXT_EXTS or i["id"] in ("sp-malware",):
            continue
        doc = parse((corpus / "files" / i["file"]).read_bytes(), i["ext"], i["name"])
        text = "\n".join(b.text for b in doc.blocks)
        own = SITE_CODE[i["site"]]
        found = set(re.findall(r"KS-([A-Z]+)-\d{4}", text))
        assert own in found, (i["id"], i["ext"])
        assert found == {own}, (i["id"], found)
