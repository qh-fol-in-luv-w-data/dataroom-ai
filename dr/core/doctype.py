"""What kind of document a file is (price list, contract, budget plan, job ad…), from its folders and name.

Used when DR_DOCTYPE=1: the kind is written into each passage's source, so the model can tell a campaign budget
from a price, or a lease commitment from a promised salary. Folder and file names only: no model, no content.
"""
from __future__ import annotations

import re

from unidecode import unidecode

# first match wins, most specific first ("phụ lục hợp đồng" before "hợp đồng", "báo giá" before "giá")
KINDS: list[tuple[str, re.Pattern]] = [(kind, re.compile(rf"\b({pat})\b")) for kind, pat in [
    ("tin tuyển dụng", r"tuyen dung|recruit\w*|hiring|career"),
    ("báo giá", r"bao gia|quotation|quote"),
    ("bảng giá", r"bang gia|price ?list|gia ban|chinh sach ban hang|pricelist"),
    ("ngân sách, kế hoạch", r"ngan sach|du toan|budget|ke hoach|media ?plan|plan marketing|marketing plan"),
    ("phụ lục hợp đồng", r"phu luc"),
    ("hợp đồng", r"hop dong|hd|hdmb|contract|thoa thuan"),
    ("biên bản", r"bien ban|minutes"),
    ("văn bản pháp lý", r"cong van|quyet dinh|giay phep|giay chung nhan|to trinh|thong bao|gcn|qd|cv|phap ly"),
    ("khuyến mãi", r"khuyen mai|uu dai|qua tang|promotion|minigame|chuong trinh"),
    ("mặt bằng", r"mat bang|layout|floor ?plan|mb tang|mb can"),
    ("danh thiếp", r"danh thiep|name ?card|business card"),
    ("ấn phẩm quảng cáo", r"quang cao|poster|banner|brochure|leaflet|an pham|key ?visual|kv|artboard|social|post"),
]]


def classify(path: str, name: str) -> str:
    """The kind of the file, '' when its folders and name do not say. The file name is looked at first,
    then the folders from the innermost out."""
    for part in [name, *reversed([s for s in path.strip("/").split("/") if s])]:
        text = re.sub(r"[_\-.]+", " ", unidecode(part).lower())
        for kind, pat in KINDS:
            if pat.search(text):
                return kind
    return ""
