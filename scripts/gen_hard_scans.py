#!/usr/bin/env python3
"""Generate realistically HARD synthetic scans of Vietnamese IPO data-room documents + ground truth.

Used to measure OCR accuracy on numbers (amounts, capacities, percents, dates, codes) and on
Vietnamese diacritics. Each doc gets one primary degradation kind (cycling through KINDS) and
optionally one light extra effect (EXTRAS). Output: image files (png / jpg / image-only pdf) and
truth.json in out_dir.

truth.json conventions:
  numbers[].text   exact string drawn on the page (number part only: "48,75" is drawn as "48,75 MW",
                   "12,5" as "12,5%"); page is 1-based.
  rotation         degrees the page content was rotated COUNTER-clockwise (PIL convention); rotate the
                   image clockwise by that amount to make it upright.
  covered          a seal / signature / coffee stain overlaps the number.
  phrases          exact clean-print Vietnamese phrases on the page (not covered by any overlay).

Usage: .venv/bin/python scripts/gen_hard_scans.py [--out data/eval/hard_scans] [--n 40] [--seed 7]
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
HAND_FONTS = ["/System/Library/Fonts/Noteworthy.ttc", "/System/Library/Fonts/MarkerFelt.ttc"]
W, H, M, DPI = 1654, 2339, 150, 200          # A4 @ 200 dpi before degradation
KINDS = ["rot90", "rot180", "rot270", "skew", "phone_photo", "fax", "low_res", "stamp_over_numbers",
         "handwriting", "multi_page_table", "two_column", "fold_stain"]
EXTRAS = ["fold_stain", "speckle", "light_skew", "stamp", "blur"]
FIXED_FMT = {"phone_photo": "jpg", "fax": "png", "low_res": "jpg", "multi_page_table": "pdf"}
COMPANY = "CÔNG TY CỔ PHẦN NĂNG LƯỢNG SAO MAI"
PARTNERS = ["Công ty TNHH Xây lắp Điện Miền Trung", "Tổng công ty Điện lực miền Nam",
            "Công ty CP Thiết bị Điện Phương Nam", "Công ty TNHH Năng lượng Xanh Quy Nhơn",
            "Công ty Mua bán điện", "Công ty CP Tư vấn Xây dựng Điện 4",
            "Công ty TNHH Kỹ thuật Hưng Thịnh", "Công ty CP Cơ khí Lắp máy Sông Đà"]
PLANTS = ["Nhà máy điện mặt trời Sao Mai 2", "Nhà máy điện gió Sao Mai Bạc Liêu",
          "Nhà máy thủy điện Đắk Pô Kô", "Trạm biến áp 110 kV Sao Mai"]
PEOPLE = ["Nguyễn Văn Hùng", "Trần Thị Thu Hà", "Lê Quốc Bảo", "Phạm Minh Đức", "Võ Thị Ngọc Ánh",
          "Đặng Hữu Phước", "Huỳnh Tấn Lộc", "Bùi Thị Mỹ Duyên"]

_F: dict = {}


def font(size: int, hand: bool = False) -> ImageFont.FreeTypeFont:
    if (size, hand) not in _F:
        path = next((p for p in HAND_FONTS if Path(p).exists()), FONT_PATH) if hand else FONT_PATH
        _F[(size, hand)] = ImageFont.truetype(path, size)
    return _F[(size, hand)]


# ------------------------------------------------------------------ Vietnamese number formats
def vn_int(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def vn_dec(x: float, d: int = 2) -> str:
    return f"{x:,.{d}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def vn_date(r: random.Random, y0: int = 2024, y1: int = 2026) -> str:
    return f"{r.randint(1, 28):02d}/{r.randint(1, 12):02d}/{r.randint(y0, y1)}"


def money(r: random.Random, lo: float, hi: float, step: int = 1000) -> int:
    return r.randrange(int(lo) // step, int(hi) // step) * step


def mst(r: random.Random) -> str:
    return f"{r.choice(['0', '4', '3'])}{r.randint(100000000, 999999999)}"


class N(str):
    """Key number: recorded in truth."""


class P(str):
    """Clean-print phrase: recorded in truth (diacritic accuracy)."""


def wrap(text: str, f, width: float) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if f.getlength(t) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def lowfreq(nrng, h: int, w: int, cells: int = 8, lo: float = 0.6, hi: float = 1.0) -> np.ndarray:
    g = cv2.resize(nrng.random((cells, cells)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    return lo + (hi - lo) * np.clip(g, 0, 1)


def multiply(img: Image.Image, layer: Image.Image, pos) -> None:
    """Subtractive-ink composite of an RGBA layer onto img (black text stays black under red seal)."""
    x, y = int(pos[0]), int(pos[1])
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + layer.width, img.width), min(y + layer.height, img.height)
    if x1 <= x0 or y1 <= y0:
        return
    base = np.asarray(img.crop((x0, y0, x1, y1)), np.float32)
    lay = np.asarray(layer, np.float32)[y0 - y:y1 - y, x0 - x:x1 - x]
    a = lay[..., 3:] / 255
    out = base * (1 - a + a * lay[..., :3] / 255)
    img.paste(Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)), (x0, y0))


def hand_text(img: Image.Image, x: float, ymid: float, text: str, size: int, r: random.Random, color=None):
    """Blue-ink handwriting: per-char jitter in size/rotation/position, slant, tilted baseline."""
    color = color or (r.randint(15, 40), r.randint(30, 60), r.randint(130, 175))
    lw, lh = int(font(size, True).getlength(text) * 1.3 + size * 2), int(size * 2.4)
    lay = Image.new("L", (lw, lh), 0)
    cx = size * 0.5
    for ch in text:
        s = int(size * r.uniform(0.86, 1.14))
        fc = font(s, True)
        g = Image.new("L", (s * 2, s * 2), 0)
        ImageDraw.Draw(g).text((s, s), ch, font=fc, fill=255, anchor="mm")
        g = g.rotate(r.uniform(-9, 9), resample=Image.BICUBIC)
        lay.paste(255, (int(cx + fc.getlength(ch) / 2 - s + r.uniform(-2, 2)),
                        int(lh / 2 - s + r.uniform(-0.09, 0.09) * size)), g)
        cx += fc.getlength(ch) * r.uniform(0.9, 1.08)
    sh = r.uniform(0.12, 0.3)
    lay = lay.transform(lay.size, Image.AFFINE, (1, sh, -sh * lh / 2, 0, 1, 0), resample=Image.BICUBIC)
    rot = lay.rotate(r.uniform(-3.5, 3.5), resample=Image.BICUBIC, expand=True)
    ox, oy = int(x - size * 0.5 - (rot.width - lw) / 2), int(ymid - rot.height / 2)
    alpha = rot.point(lambda v: int(v * 0.93))
    img.paste(Image.new("RGB", rot.size, color), (ox, oy), alpha)
    bb = rot.getbbox() or (0, 0, 1, 1)
    return (ox + bb[0], oy + bb[1], ox + bb[2], oy + bb[3])


def seal(r: random.Random, nrng, text: str = COMPANY, d: int | None = None) -> Image.Image:
    """Red round seal with circular text and a star; uneven, semi-transparent ink."""
    d = d or r.randint(330, 390)
    a = Image.new("L", (d, d), 0)
    dr = ImageDraw.Draw(a)
    dr.ellipse([6, 6, d - 6, d - 6], outline=255, width=9)
    dr.ellipse([int(d * .2), int(d * .2), d - int(d * .2), d - int(d * .2)], outline=255, width=3)
    fs = int(d * 0.07)
    rad, n = d / 2 - 14 - fs * 0.85, len(text)
    for i, ch in enumerate(text):
        ang = -150 + 300 * i / (n - 1)
        g = Image.new("L", (fs * 2, fs * 2), 0)
        ImageDraw.Draw(g).text((fs, fs), ch, font=font(fs), fill=255, anchor="mm")
        g = g.rotate(-ang, resample=Image.BICUBIC)
        t = math.radians(ang)
        a.paste(255, (int(d / 2 + rad * math.sin(t) - fs), int(d / 2 - rad * math.cos(t) - fs)), g)
    R = d * 0.12
    pts = [(d / 2 + (R if k % 2 == 0 else R * 0.4) * math.cos(math.radians(-90 + 36 * k)),
            d / 2 - d * 0.03 + (R if k % 2 == 0 else R * 0.4) * math.sin(math.radians(-90 + 36 * k))) for k in range(10)]
    dr.polygon(pts, fill=255)
    dr.text((d / 2, d / 2 + R + 4), "SAO MAI", font=font(int(d * 0.055)), fill=255, anchor="mt")
    al = np.asarray(a, np.float32) / 255 * r.uniform(0.62, 0.85) * lowfreq(nrng, d, d, 6, 0.45, 1.0)
    col = (r.randint(185, 225), r.randint(15, 45), r.randint(30, 60))
    rgba = np.dstack([np.full((d, d), c, np.float32) for c in col] + [al * 255])
    return Image.fromarray(rgba.astype(np.uint8), "RGBA").rotate(r.uniform(-25, 25), resample=Image.BICUBIC)


def signature(r: random.Random, w: int = 360, h: int = 150) -> Image.Image:
    a = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(a)
    f1, A, B, ph = r.uniform(4, 8), r.uniform(12, 24), r.uniform(25, 45), r.uniform(0, 6)
    pts = [(25 + t * (w - 80) + A * math.sin(f1 * 2 * math.pi * t + ph),
            h * 0.45 + B * math.cos(f1 * 2 * math.pi * t) * (0.6 + 0.4 * math.sin(3 * t + ph)))
           for t in (i / 240 for i in range(240))]
    dr.line(pts, fill=255, width=3, joint="curve")
    dr.line([(10, h * 0.82), (w * 0.5, h * 0.7 + r.uniform(-12, 12)), (w - 10, h * 0.6)], fill=255, width=3)
    rgba = Image.new("RGBA", (w, h), (r.randint(15, 35), r.randint(30, 50), r.randint(130, 170), 0))
    rgba.putalpha(a.point(lambda v: int(v * 0.9)))
    return rgba


# ------------------------------------------------------------------------------------- page
class Page:
    def __init__(self, r: random.Random, nrng, hand: bool = False):
        self.r, self.nrng, self.hand = r, nrng, hand
        self.img = Image.new("RGB", (W, H), "white")
        self.d = ImageDraw.Draw(self.img)
        self.ink = (r.randint(5, 35),) * 3
        self.y = M
        self.nums: list[dict] = []
        self.phrases: list[tuple] = []
        self.shapes: list[tuple] = []          # overlays that may cover text: ("disk",cx,cy,R)|("rect",box)

    def put(self, x, y, segs, size=28, bold=False, center=False, right=False, hand_p=0.45) -> float:
        segs = [segs] if isinstance(segs, str) else segs
        f = font(size)
        if center or right:
            tot = sum(f.getlength(s) for s in segs)
            x = x - tot / 2 if center else x - tot
        for s in segs:
            if isinstance(s, N) and self.hand and hand_p and (
                    not any(n["handwritten"] for n in self.nums) or self.r.random() < hand_p):
                for xx in range(int(x), int(x + f.getlength(s) + 30), 9):       # dotted form field
                    self.d.ellipse([xx, y + size + 9, xx + 2, y + size + 11], fill=self.ink)
                box = hand_text(self.img, x + 6, y + size * 0.55, s, int(size * 1.25), self.r)
                self.nums.append(dict(text=str(s), box=box, handwritten=True))
                x = max(box[2] + 6, x + f.getlength(s) + 30)
                continue
            sw = 1 if bold else 0
            self.d.text((x, y), s, font=f, fill=self.ink, stroke_width=sw, stroke_fill=self.ink)
            box = self.d.textbbox((x, y), s, font=f, stroke_width=sw)
            if isinstance(s, N):
                self.nums.append(dict(text=str(s), box=box, handwritten=False))
            elif isinstance(s, P):
                self.phrases.append((str(s), box))
            x += f.getlength(s)
        return x

    def line(self, segs, size=28, bold=False, align="left", x=M, gap=1.6, **kw):
        xx = {"left": x, "center": W / 2, "right": W - M}[align]
        self.put(xx, self.y, segs, size, bold, center=align == "center", right=align == "right", **kw)
        self.y += int(size * gap)
        assert self.y < H - 40, "page overflow"

    def para(self, text, size=26, x=M, width=W - 2 * M):
        for ln in wrap(text, font(size), width):
            self.line(ln, size, x=x, gap=1.5)
        self.y += 6

    def table(self, cols, rows, header=None, size=22, rh=44, x0=M, width=W - 2 * M, hand_p=0.2):
        xs = [x0]
        for c in cols:
            xs.append(xs[-1] + c * width / sum(cols))
        for ri, row in enumerate(([header] if header else []) + rows):
            hdr, y = bool(header) and ri == 0, self.y
            if hdr:
                self.d.rectangle([xs[0], y, xs[-1], y + rh], fill=(222, 222, 222))
            for ci, cell in enumerate(row):
                self.d.rectangle([xs[ci], y, xs[ci + 1], y + rh], outline=self.ink, width=2)
                ty = y + (rh - size) // 2 - 3
                if cell and (isinstance(cell, N) or (cell[:1].isdigit() and not hdr)):
                    self.put(xs[ci + 1] - 10, ty, [cell], size, right=True, hand_p=hand_p)
                elif cell:
                    self.put(xs[ci] + 8, ty, [cell], size, bold=hdr or cell.isupper(), hand_p=0)
            self.y += rh
            assert self.y < H - 40, "table overflow"
        self.y += 24


def header(pg: Page, code: str, left=("CÔNG TY CỔ PHẦN", "NĂNG LƯỢNG SAO MAI")):
    y, lx, rx = pg.y, M + 270, W - M - 300
    pg.put(lx, y, left[0], 25, True, center=True)
    pg.put(lx, y + 36, left[1], 25, True, center=True)
    pg.put(lx, y + 82, ["Số: ", N(code)], 25, center=True, hand_p=0)
    pg.put(rx, y, "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", 25, True, center=True)
    pg.put(rx, y + 36, [P("Độc lập - Tự do - Hạnh phúc")], 25, center=True)
    pg.d.line([rx - 140, y + 74, rx + 140, y + 74], fill=pg.ink, width=2)
    pg.y = y + 128
    d, m, yy = vn_date(pg.r, 2025, 2026).split("/")
    pg.line(f"Bình Định, ngày {d} tháng {m} năm {yy}", 24, align="right", gap=2.4)


def sign_block(pg: Page, left="ĐẠI DIỆN BÊN A", right="ĐẠI DIỆN BÊN B", seal_right=True):
    r, y = pg.r, pg.y + 10
    for i, (title, x) in enumerate(((left, M + 280), (right, W - M - 300))):
        if not title:
            continue
        pg.put(x, y, title, 25, True, center=True)
        pg.put(x, y + 34, "(Ký, ghi rõ họ tên)", 21, center=True)
        multiply(pg.img, signature(r), (x - 170 + r.randint(-20, 20), y + 70))
        if i == 1 and seal_right:
            multiply(pg.img, seal(r, pg.nrng), (x - 300 + r.randint(-20, 20), y + 20))
        pg.put(x, y + 235, r.choice(PEOPLE), 25, True, center=True)
    pg.y = y + 290


# ------------------------------------------------------------------------------- documents
def doc_bienban(r, nrng, hand):
    pg = Page(r, nrng, hand)
    header(pg, f"{r.randint(1, 999):04d}/BB-SM")
    plant, partner = r.choice(PLANTS), r.choice(PARTNERS)
    pg.line(P("BIÊN BẢN NGHIỆM THU"), 40, True, "center", gap=1.4)
    pg.line(P("Xác nhận công suất và đưa vào vận hành thương mại"), 27, align="center", gap=2.2)
    pg.line(["Công trình: ", P(plant)], 27)
    pg.line(["Căn cứ Hợp đồng EPC số ", N(f"{r.randint(10, 99)}/2024/HĐ-EPC"), " ký ngày ",
             N(vn_date(r, 2023, 2024)), ";"], 27)
    pg.para(f"Hôm nay, tại công trường, chúng tôi gồm đại diện Chủ đầu tư là Công ty Cổ phần Năng lượng "
            f"Sao Mai và đại diện Nhà thầu {partner} đã tiến hành kiểm tra, đo đếm thực tế và thống nhất "
            f"các nội dung sau:")
    dc = r.uniform(40, 120)
    ac = dc * r.uniform(0.78, 0.86)
    pg.line(["1. Công suất lắp đặt (DC): ", N(vn_dec(dc, 3)), " MWp"])
    pg.line(["2. Công suất xác nhận (AC): ", N(vn_dec(ac, 2)), " MW"])
    pg.line(["3. Sản lượng chạy thử 72 giờ: ", N(vn_int(ac * 72000 * r.uniform(.5, .8))), " kWh"])
    pg.line(["4. Hệ số hiệu suất (PR): ", N(vn_dec(r.uniform(76, 86), 1)), "%"])
    pg.line(["5. Giá trị khối lượng nghiệm thu: ", N(vn_int(money(r, 2e10, 9e11, 1000))), " đồng"])
    pg.line(["6. Ngày vận hành thương mại (COD): ", N(vn_date(r, 2025, 2026))], gap=2.0)
    pg.line([P("Kết luận: Đồng ý nghiệm thu"), " và đưa công trình vào khai thác sử dụng."], 27, gap=2.4)
    sign_block(pg, "ĐẠI DIỆN NHÀ THẦU", "ĐẠI DIỆN CHỦ ĐẦU TƯ")
    return "Biên bản nghiệm thu", [pg]


def doc_hoadon(r, nrng, hand):
    pg = Page(r, nrng, hand)
    d = vn_date(r, 2025, 2026)
    dd, mm, yy = d.split("/")
    pg.line(P("HÓA ĐƠN GIÁ TRỊ GIA TĂNG"), 40, True, "center", gap=1.4)
    pg.line(P("(Bản thể hiện của hóa đơn điện tử)"), 24, align="center", gap=1.5)
    pg.line(f"Ngày {dd} tháng {mm} năm {yy}", 25, align="center")
    pg.line(["Ký hiệu: ", N(f"1C{yy[2:]}T{r.choice('ABMS')}{r.choice('ABMS')}"), "      Số: ",
             N(f"{r.randint(1, 99999):08d}")], 28, align="right", gap=2.0, hand_p=0)
    pg.line(["Đơn vị bán hàng: ", P(COMPANY)], 25, True)
    pg.line(["Mã số thuế: ", N(mst(r))], 25)
    pg.line("Địa chỉ: Số 18 Lê Duẩn, phường Quy Nhơn, tỉnh Gia Lai", 25)
    pg.line(["Số tài khoản: ", N(str(r.randint(10 ** 13, 10 ** 14 - 1))),
             " tại Ngân hàng TMCP Đầu tư và Phát triển Việt Nam"], 25, gap=2.0)
    pg.line(["Đơn vị mua hàng: ", r.choice(PARTNERS)], 25, True)
    pg.line(["Mã số thuế: ", N(mst(r))], 25)
    pg.line("Hình thức thanh toán: Chuyển khoản", 25, gap=2.0)
    items = [(f"Điện năng bán ra tháng {mm}/{yy}", "kWh", r.randint(800_000, 9_000_000), r.uniform(1500, 2100)),
             ("Phí công suất phản kháng", "kVArh", r.randint(10_000, 400_000), r.uniform(150, 400)),
             ("Dịch vụ phụ trợ hệ thống", "tháng", 1, money(r, 5e6, 9e7))]
    rows, sub = [], 0
    for i, (name, unit, q, p) in enumerate(items[:r.randint(2, 3)]):
        amt = round(q * p)
        sub += amt
        rows.append([str(i + 1), name, unit, N(vn_int(q)), N(vn_dec(p, 2) if p < 10000 else vn_int(p)), N(vn_int(amt))])
    pg.table([0.6, 4.2, 0.9, 1.7, 1.5, 2.3], rows, ["STT", "Tên hàng hóa, dịch vụ", "ĐVT", "Số lượng",
                                                     "Đơn giá", "Thành tiền"])
    vat = r.choice([8, 10])
    tax = round(sub * vat / 100)
    pg.line(["Cộng tiền hàng: ", N(vn_int(sub))], 26, align="right")
    pg.line(["Thuế suất GTGT: ", N(str(vat)), "%      Tiền thuế GTGT: ", N(vn_int(tax))], 26, align="right")
    pg.line(["Tổng cộng tiền thanh toán: ", N(vn_int(sub + tax))], 27, True, "right", gap=2.4)
    sign_block(pg, "NGƯỜI MUA HÀNG", "NGƯỜI BÁN HÀNG")
    return "Hóa đơn giá trị gia tăng", [pg]


def table_pages(r, nrng, hand, n_pages, intro, cols, hdr, rows, carry, outro, size=21):
    caps = [21] + [33] * (n_pages - 2) + [len(rows)] if n_pages > 1 else [len(rows)]
    pages, i, repeat = [], 0, r.random() < 0.5
    for p, cap in enumerate(caps):
        pg = Page(r, nrng, hand)
        if p == 0:
            intro(pg)
        else:
            pg.line(f"Trang {p + 1}/{n_pages} (tiếp theo)", 22, align="right")
        body = rows[i:i + cap] if p < n_pages - 1 else rows[i:]
        if p > 0:
            body = [carry(i, "Số trang trước chuyển sang")] + body
        i += cap
        if p < n_pages - 1:
            body = body + [carry(i, "Cộng chuyển sang trang sau")]
        pg.table(cols, body, hdr if (p == 0 or repeat) else None, size=size, rh=42)
        if p == n_pages - 1:
            outro(pg)
        pages.append(pg)
    return pages


def doc_congno(r, nrng, hand, n_pages=1):
    n = r.randint(9, 12) if n_pages == 1 else 21 + 33 * (n_pages - 2) + r.randint(10, 15)
    asof = vn_date(r, 2025, 2025)
    rows, cum = [], [0]
    for k in range(n):
        amt = money(r, 5e6, 9e10, 1000)
        cum.append(cum[-1] + amt)
        rows.append([str(k + 1), r.choice(PARTNERS), N(f"{r.randint(1, 99999):08d}"), N(vn_date(r, 2024, 2025)),
                     N(vn_int(amt))])

    def intro(pg):
        header(pg, f"{r.randint(1, 999):04d}/BK-TCKT")
        pg.line(P("BẢNG KÊ CÔNG NỢ PHẢI THU KHÁCH HÀNG"), 36, True, "center", gap=1.5)
        pg.line(["Tính đến ngày ", N(asof)], 26, align="center")
        pg.line(P("Đơn vị tính: đồng"), 23, align="right")

    def outro(pg):
        pg.line(["Tổng số dư phải thu: ", N(vn_int(cum[-1])), " đồng"], 26, True)
        pg.line([P("Ghi chú: Số liệu đã được đối chiếu"), " với sổ chi tiết công nợ."], 24, gap=2.0)
        sign_block(pg, "NGƯỜI LẬP BIỂU", "KẾ TOÁN TRƯỞNG", seal_right=False)

    pages = table_pages(r, nrng, hand, n_pages, intro, [0.7, 4.3, 1.8, 1.7, 2.4],
                        ["STT", "Khách hàng", "Số hóa đơn", "Ngày HĐ", "Số tiền"], rows,
                        lambda i, lab: ["", lab.upper(), "", "", N(vn_int(cum[i]))], outro)
    return "Bảng kê công nợ phải thu", pages


def doc_saoke(r, nrng, hand, n_pages=1):
    n = r.randint(10, 13) if n_pages == 1 else 21 + 33 * (n_pages - 2) + r.randint(10, 15)
    acct, bal0 = str(r.randint(10 ** 13, 10 ** 14 - 1)), money(r, 1e9, 9e10, 1)
    descs = ["Thu tiền điện EVN", "Trả lãi vay HĐTD", "Thanh toán NCC thiết bị", "Phí dịch vụ ngân hàng",
             "Nộp thuế GTGT", "Thu tiền bán CCDC", "Chi lương tháng", "Hoàn ứng nhà thầu"]
    rows, bal, tot = [], [bal0], [0, 0]
    day, mon, yr = 1, r.randint(1, 12), r.randint(2025, 2026)
    for k in range(n):
        day = min(28, day + (r.random() < 0.4))
        amt = money(r, 1e6, 6e9, 1)
        credit = r.random() < 0.45 or bal[-1] < amt
        tot[credit] += amt
        bal.append(bal[-1] + (amt if credit else -amt))
        rows.append([N(f"{day:02d}/{mon:02d}/{yr}"), N(f"FT{yr % 100}{r.randint(10 ** 7, 10 ** 8 - 1)}"),
                     r.choice(descs), "" if credit else N(vn_int(amt)), N(vn_int(amt)) if credit else "",
                     N(vn_int(bal[-1]))])

    def intro(pg):
        pg.line(P("NGÂN HÀNG TMCP ĐẦU TƯ VÀ PHÁT TRIỂN VIỆT NAM"), 28, True, "center", gap=1.3)
        pg.line("Chi nhánh Bình Định", 25, align="center", gap=2.0)
        pg.line(P("SAO KÊ TÀI KHOẢN"), 40, True, "center", gap=1.8)
        pg.line(["Chủ tài khoản: ", COMPANY], 25)
        pg.line(["Số tài khoản: ", N(acct), "      Loại tiền: VND"], 25)
        pg.line(["Từ ngày ", N(f"01/{mon:02d}/{yr}"), " đến ngày ", N(f"28/{mon:02d}/{yr}")], 25)
        pg.line(["Số dư đầu kỳ: ", N(vn_int(bal0))], 25, True, gap=2.0)

    def outro(pg):
        pg.line(["Tổng phát sinh nợ: ", N(vn_int(tot[0])), "      Tổng phát sinh có: ", N(vn_int(tot[1]))], 24)
        pg.line(["Số dư cuối kỳ: ", N(vn_int(bal[-1]))], 25, True)
        pg.line(P("Sao kê có giá trị xác nhận số dư tài khoản"), 23, gap=2.0)
        sign_block(pg, "", "GIAO DỊCH VIÊN", seal_right=r.random() < 0.6)

    pages = table_pages(r, nrng, hand, n_pages, intro, [1.6, 2.0, 3.0, 2.1, 2.1, 2.3],
                        ["Ngày GD", "Số bút toán", "Diễn giải", "Ghi nợ", "Ghi có", "Số dư"], rows,
                        lambda i, lab: ["", "", lab.capitalize()[:18], "", "", N(vn_int(bal[i]))], outro, size=20)
    return "Sao kê tài khoản", pages


def doc_hopdong(r, nrng, hand):
    pg = Page(r, nrng, hand)
    kind = r.choice(["MUA BÁN THIẾT BỊ", "THI CÔNG XÂY LẮP", "TƯ VẤN GIÁM SÁT"])
    header(pg, f"{r.randint(1, 999):04d}/2025/HĐ-SM")
    pg.line(P(f"HỢP ĐỒNG {kind}"), 38, True, "center", gap=1.4)
    pg.line(f"(Trích trang {r.randint(3, 5)}/{r.randint(12, 18)})", 22, align="center", gap=2.0)
    total, vat = money(r, 5e9, 9e11, 1_000_000), r.choice([8, 10])
    pg.line(P("Điều 3. Giá trị hợp đồng"), 28, True)
    pg.line(["3.1. Tổng giá trị hợp đồng: ", N(vn_int(total)), " đồng (đã bao gồm thuế GTGT ", N(str(vat)), "%)."], 26)
    pg.para("3.2. Giá trị hợp đồng là trọn gói, không thay đổi trong suốt thời gian thực hiện, trừ trường hợp "
            "có phát sinh khối lượng được hai bên thống nhất bằng văn bản.")
    pg.line(P("Điều 4. Tạm ứng và thanh toán"), 28, True)
    adv = r.choice([10, 15, 20, 30])
    pg.line(["4.1. Tạm ứng ", N(str(adv)), "% giá trị hợp đồng, tương đương ", N(vn_int(total * adv // 100)), " đồng,"], 26)
    pg.line(f"trong vòng {r.choice([7, 10, 15])} ngày làm việc kể từ ngày ký hợp đồng.", 26)
    pg.line(["4.2. Thanh toán đợt 2: ", N(str(r.choice([60, 65, 70]))), "% sau nghiệm thu, hạn chót ngày ",
             N(vn_date(r, 2025, 2026)), "."], 26)
    pg.line(["4.3. Giữ lại bảo hành: ", N(r.choice(["2,5", "5", "7,5"])), "% giá trị quyết toán."], 26, gap=2.0)
    pg.line(P("Điều 5. Phạt vi phạm và bồi thường"), 28, True)
    pg.line(["5.1. Lãi chậm thanh toán: ", N(vn_dec(r.choice([0.03, 0.05]), 2)), "%/ngày trên số tiền chậm trả."], 26)
    pg.line(["5.2. Mức phạt vi phạm: ", N(r.choice(["8", "12,5"])), "% giá trị phần nghĩa vụ bị vi phạm."], 26)
    pg.para("5.3. Bên vi phạm có nghĩa vụ bồi thường toàn bộ thiệt hại thực tế phát sinh cho bên bị vi phạm "
            "theo quy định của Bộ luật Dân sự và Luật Thương mại.")
    pg.line(P("Điều 6. Hiệu lực hợp đồng"), 28, True)
    pg.line(["Hợp đồng có hiệu lực từ ngày ", N(vn_date(r, 2025, 2025)), " đến hết ngày ",
             N(vn_date(r, 2027, 2028)), "."], 26, gap=2.2)
    sign_block(pg, "ĐẠI DIỆN BÊN A", "ĐẠI DIỆN BÊN B")
    return f"Hợp đồng {kind.lower()}", [pg]


def doc_giaycn(r, nrng, hand):
    pg = Page(r, nrng, hand)
    header(pg, f"{r.randint(1, 9999):04d}/ĐKKD", left=("SỞ TÀI CHÍNH TỈNH GIA LAI", "PHÒNG ĐĂNG KÝ KINH DOANH"))
    cap = r.randint(300, 2500) * 1_000_000_000
    pg.line(P("GIẤY CHỨNG NHẬN ĐĂNG KÝ DOANH NGHIỆP"), 36, True, "center", gap=1.4)
    pg.line(P("CÔNG TY CỔ PHẦN"), 30, True, "center", gap=1.6)
    pg.line(["Mã số doanh nghiệp: ", N(mst(r))], 28, True, "center")
    pg.line(["Đăng ký lần đầu: ngày ", N(vn_date(r, 2008, 2012))], 25, align="center")
    pg.line(["Đăng ký thay đổi lần thứ ", N(str(r.randint(5, 19))), ": ngày ", N(vn_date(r, 2024, 2026))],
            25, align="center", gap=2.2)
    pg.line(P("1. Tên công ty"), 27, True)
    pg.line(["Tên công ty viết bằng tiếng Việt: ", COMPANY], 25)
    pg.line("Tên viết tắt: SAO MAI ENERGY JSC", 25, gap=2.0)
    pg.line(P("2. Địa chỉ trụ sở chính"), 27, True)
    pg.line("Số 18 Lê Duẩn, phường Quy Nhơn, tỉnh Gia Lai, Việt Nam", 25, gap=2.0)
    pg.line(P("3. Vốn điều lệ"), 27, True)
    pg.line(["Vốn điều lệ: ", N(vn_int(cap)), " đồng"], 25)
    pg.line(["Mệnh giá cổ phần: ", N("10.000"), " đồng       Tổng số cổ phần: ", N(vn_int(cap // 10000))], 25, gap=2.0)
    pg.line(P("4. Người đại diện theo pháp luật"), 27, True)
    pg.line(["Họ và tên: ", r.choice(PEOPLE), "      Chức danh: Tổng Giám đốc"], 25)
    pg.line(["Sinh ngày: ", N(vn_date(r, 1965, 1985)), "      Số định danh cá nhân: ",
             N(f"0{r.randint(10 ** 10, 10 ** 11 - 1)}")], 25, gap=2.2)
    sign_block(pg, "", "TRƯỞNG PHÒNG", seal_right=False)
    multiply(pg.img, seal(r, nrng, "PHÒNG ĐĂNG KÝ KINH DOANH - TỈNH GIA LAI"), (W - M - 600, pg.y - 300))
    return "Giấy chứng nhận đăng ký doanh nghiệp", [pg]


def doc_twocol(r, nrng, hand):
    pg = Page(r, nrng, hand)
    yr = r.choice([2024, 2025])
    header(pg, f"{r.randint(1, 999):04d}/BC-SM")
    pg.line(P("BÁO CÁO TÓM TẮT KẾT QUẢ HOẠT ĐỘNG"), 36, True, "center", gap=1.4)
    pg.line(f"Năm tài chính {yr} (số liệu hợp nhất)", 25, align="center", gap=2.0)
    colw, gut = (W - 2 * M - 70) / 2, 70
    rev = r.randint(800_000, 2_500_000)
    left = [P("I. Chỉ tiêu tài chính"),
            f"Năm {yr}, Công ty ghi nhận doanh thu tăng trưởng nhờ sản lượng điện thương phẩm tăng và giá "
            f"bán bình quân ổn định theo hợp đồng mua bán điện dài hạn.",
            ["Doanh thu thuần: ", N(vn_int(rev)), " triệu đồng"],
            ["Lợi nhuận sau thuế: ", N(vn_int(rev * r.uniform(.12, .3))), " triệu đồng"],
            ["Tổng tài sản: ", N(vn_int(rev * r.uniform(3, 5))), " triệu đồng"],
            ["Vốn chủ sở hữu: ", N(vn_int(rev * r.uniform(1.2, 2))), " triệu đồng"],
            ["ROE: ", N(vn_dec(r.uniform(8, 18), 1)), "%    EPS: ", N(vn_int(r.randint(1200, 4200))), " đồng"],
            "Hệ số nợ trên vốn chủ sở hữu được kiểm soát trong ngưỡng cam kết với các tổ chức tín dụng."]
    right = [P("II. Chỉ tiêu vận hành"),
             "Các nhà máy vận hành an toàn, không xảy ra sự cố nghiêm trọng; công tác bảo dưỡng định kỳ được "
             "thực hiện đúng kế hoạch.",
             ["Tổng công suất: ", N(vn_dec(r.uniform(200, 450), 1)), " MW"],
             ["Sản lượng điện: ", N(vn_dec(r.uniform(300, 900), 2)), " triệu kWh"],
             ["Số giờ vận hành: ", N(vn_int(r.randint(1800, 4200))), " giờ"],
             ["Hệ số công suất: ", N(vn_dec(r.uniform(15, 45), 1)), "%"],
             ["Tỷ lệ khả dụng: ", N(vn_dec(r.uniform(96, 99.8), 2)), "%"],
             "Kế hoạch năm tiếp theo: hoàn thành đầu tư mở rộng và đưa vào vận hành giai đoạn 2."]
    y0, ends = pg.y + 10, []
    for x, items in ((M, left), (M + colw + gut, right)):
        pg.y = y0
        for it in items:
            if isinstance(it, P):
                pg.line(it, 27, True, x=x)
            elif isinstance(it, str):
                pg.para(it, 24, x=x, width=colw)
            else:
                pg.line(it, 25, x=x)
        ends.append(pg.y)
    pg.d.line([M + colw + gut / 2, y0, M + colw + gut / 2, max(ends)], fill=pg.ink, width=2)
    pg.y = max(ends) + 40
    pg.line([P("Nơi nhận: Hội đồng quản trị"), "; Ban kiểm soát; Lưu VT."], 22, gap=2.4)
    sign_block(pg, "", "TỔNG GIÁM ĐỐC")
    return "Báo cáo tóm tắt kết quả hoạt động", [pg]


SINGLE = [doc_bienban, doc_hoadon, doc_congno, doc_saoke, doc_hopdong, doc_giaycn]


# ----------------------------------------------------------------------------- overlays
def coffee_stain(img: Image.Image, cx, cy, R, r, nrng):
    s = int(R * 1.3)
    yy, xx = np.mgrid[-s:s, -s:s].astype(np.float32)
    th, dist = np.arctan2(yy, xx), np.hypot(xx, yy)
    p = [r.uniform(0, 6.28) for _ in range(5)]
    rad = R * (1 + 0.05 * np.sin(3 * th + p[0]) + 0.03 * np.sin(7 * th + p[1]) + 0.015 * np.sin(13 * th + p[2]))
    rr = dist / rad
    ring = np.exp(-((rr - 1) / 0.035) ** 2) * (0.5 + 0.5 * (0.5 + 0.5 * np.sin(2 * th + p[3])))
    if r.random() < 0.5:
        ring *= np.clip(0.5 + 1.5 * np.cos(th - p[4]), 0, 1)
    alpha = np.clip(ring * 0.7 + (rr < 1) * 0.16 * lowfreq(nrng, 2 * s, 2 * s, 5, 0.4, 1.0), 0, 0.7)
    col = np.array([r.uniform(.5, .62), r.uniform(.35, .42), r.uniform(.18, .25)], np.float32)
    lay = np.dstack([np.full_like(alpha, c * 255) for c in col] + [alpha * 255]).astype(np.uint8)
    multiply(img, Image.fromarray(lay, "RGBA"), (cx - s, cy - s))


def fold(img: Image.Image, r):
    a = np.asarray(img, np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    horiz = r.random() < 0.7
    pos = (H * r.choice([1 / 3, 1 / 2, 2 / 3]) if horiz else W / 2) + r.uniform(-40, 40)
    along, across = (xx, yy) if horiz else (yy, xx)
    d = across - (pos + r.uniform(-0.02, 0.02) * along + 4 * np.sin(along / r.uniform(150, 400)))
    shade = 1 - 0.16 * np.exp(-(np.maximum(d, 0) / 40) ** 2) - 0.32 * np.exp(-(d / 3.5) ** 2) \
        + 0.05 * np.exp(-((d + 10) / 7) ** 2)
    img.paste(Image.fromarray(np.clip(a * shade[..., None], 0, 255).astype(np.uint8)))


def _hit(box, shape) -> bool:
    if shape[0] == "disk":
        _, cx, cy, R = shape
        nx, ny = min(max(cx, box[0]), box[2]), min(max(cy, box[1]), box[3])
        return math.hypot(nx - cx, ny - cy) < R
    b = shape[1]
    return min(box[2], b[2]) - max(box[0], b[0]) > 4 and min(box[3], b[3]) - max(box[1], b[1]) > 4


def overlays(pages: list[Page], kind, extra, r, nrng):
    pg = pages[0]
    printed = [n for n in pg.nums if not n["handwritten"]] or pg.nums
    if kind == "stamp_over_numbers" or extra == "stamp":
        mode = r.choice(["seal", "seal", "seal+sign", "sign"]) if kind == "stamp_over_numbers" else "seal"
        tgt = r.choice(printed)
        if "seal" in mode:
            s = seal(r, nrng)
            cx = (tgt["box"][0] + tgt["box"][2]) / 2 + r.uniform(-50, 50)
            cy = (tgt["box"][1] + tgt["box"][3]) / 2 + r.uniform(-30, 30)
            multiply(pg.img, s, (cx - s.width / 2, cy - s.height / 2))
            pg.shapes.append(("disk", cx, cy, s.width * 0.47))
        if "sign" in mode:
            t2 = r.choice(printed)
            sg = signature(r, r.randint(330, 420), r.randint(130, 170))
            x, y = t2["box"][0] - r.randint(0, 80), (t2["box"][1] + t2["box"][3]) / 2 - sg.height / 2
            multiply(pg.img, sg, (x, y))
            bb = sg.getchannel("A").getbbox()
            pg.shapes.append(("rect", (x + bb[0], y + bb[1], x + bb[2], y + bb[3])))
    if kind == "fold_stain" or extra == "fold_stain":
        for p in pages:
            fold(p.img, r)
        tgt, R, ang = r.choice(printed), r.randint(110, 180), r.uniform(0, 6.28)
        cx = int((tgt["box"][0] + tgt["box"][2]) / 2 + 0.85 * R * math.cos(ang))
        cy = int((tgt["box"][1] + tgt["box"][3]) / 2 + 0.85 * R * math.sin(ang))
        coffee_stain(pg.img, cx, cy, R, r, nrng)
        pg.shapes.append(("disk", cx, cy, R * 1.08))
    if kind == "handwriting":
        hand_text(pg.img, W - M - 330, M * 0.55, "Đã kiểm tra – OK", 36, r)
        y = pg.y + 25
        if y < H - 140:
            for label, val in (("SL thực nhận:", vn_int(r.randint(1000, 60000))), ("Ngày", vn_date(r, 2025, 2026))):
                b = hand_text(pg.img, M + 40, y, label, 34, r)
                b2 = hand_text(pg.img, b[2] + 30, y, val, 36, r)
                pg.nums.append(dict(text=val, box=b2, handwritten=True))
                y += 62
    for p in pages:
        for n in p.nums:
            n["covered"] = any(_hit(n["box"], s) for s in p.shapes)
        p.phrases = [(t, b) for t, b in p.phrases if not any(_hit(b, s) for s in p.shapes)]


# ---------------------------------------------------------------------------- degradation
def scanify(img, r, nrng, tilt=True):
    a = cv2.GaussianBlur(np.asarray(img, np.float32), (0, 0), 0.6)
    tint = np.array([r.uniform(.96, 1), r.uniform(.95, .99), r.uniform(.9, .97)], np.float32)
    a *= tint * lowfreq(nrng, img.height, img.width, 6, 0.94, 1.0)[..., None]
    a += 4.5 * nrng.standard_normal(a.shape[:2], dtype=np.float32)[..., None]
    if tilt:                                                         # slight scanner-bed tilt
        rm = cv2.getRotationMatrix2D((img.width / 2, img.height / 2), r.uniform(-0.7, 0.7), 1.0)
        a = cv2.warpAffine(a, rm, (img.width, img.height), flags=cv2.INTER_CUBIC,
                           borderMode=cv2.BORDER_CONSTANT, borderValue=(242, 240, 234))
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def phone_photo(img, r, nrng):
    pw, ph = img.size
    dw, dh = int(pw * 0.92), int(ph * 0.92)
    s = r.uniform(0.76, 0.84)
    w, h, cx, cy = pw * s, ph * s, dw / 2 + r.uniform(-30, 30), dh / 2 + r.uniform(-30, 30)
    ti = r.uniform(0.02, 0.07) * w

    def j():
        return r.uniform(-0.03, 0.03) * w
    dst = np.float32([[-w / 2 + ti + j(), -h / 2 + j()], [w / 2 - ti + j(), -h / 2 + j()],
                      [w / 2 + j(), h / 2 + j()], [-w / 2 + j(), h / 2 + j()]])
    t = math.radians(r.uniform(-4, 4))
    dst = dst @ np.float32([[math.cos(t), math.sin(t)], [-math.sin(t), math.cos(t)]]) + np.float32([cx, cy])
    mx = cv2.getPerspectiveTransform(np.float32([[0, 0], [pw, 0], [pw, ph], [0, ph]]), dst.astype(np.float32))
    page = cv2.warpPerspective(np.asarray(img.convert("RGB")), mx, (dw, dh), flags=cv2.INTER_LINEAR).astype(np.float32)
    mask = cv2.warpPerspective(np.ones((ph, pw), np.float32), mx, (dw, dh))[..., None]
    col = np.float32(r.choice([(118, 84, 58), (72, 72, 78), (96, 80, 66), (140, 128, 110)]))
    desk = col * lowfreq(nrng, dh, dw, 10, 0.8, 1.1)[..., None]
    yy, xx = np.mgrid[0:dh, 0:dw].astype(np.float32)
    desk *= (1 + 0.06 * np.sin(yy / r.uniform(6, 14) + 3 * lowfreq(nrng, dh, dw, 4, 0, 1)))[..., None]
    shadow = cv2.GaussianBlur(np.roll(mask[..., 0], (18, 12), (0, 1)), (0, 0), 15)[..., None]
    comp = desk * (1 - 0.5 * shadow) * (1 - mask) + page * mask
    gx, gy = xx / dw - 0.5, yy / dh - 0.5
    light = 1 + r.uniform(-.25, .25) * gx + r.uniform(-.25, .25) * gy - 0.5 * (gx ** 2 + gy ** 2)
    blob = np.zeros((dh // 8, dw // 8), np.float32)
    cv2.ellipse(blob, (r.choice([0, dw // 8]), r.randint(0, dh // 8)), (dw // 14, dh // 20), r.uniform(0, 180),
                0, 360, 1.0, -1)
    blob = cv2.resize(cv2.GaussianBlur(blob, (0, 0), 9), (dw, dh))
    comp *= (light * (1 - r.uniform(.25, .4) * blob))[..., None] * np.float32([1.02, 1.0, 0.92])
    comp = cv2.GaussianBlur(comp, (0, 0), r.uniform(0.9, 1.4)) + nrng.normal(0, 5, comp.shape).astype(np.float32)
    return Image.fromarray(np.clip(comp, 0, 255).astype(np.uint8))


def fax(img, r, nrng):
    g = img.convert("L")
    g = g.resize((g.width // 2, g.height // 2), Image.BILINEAR)                        # ~100 dpi
    ImageDraw.Draw(g).text((20, 10), f"FAX: 0256 38{r.randint(10000, 99999)}   {vn_date(r, 2026, 2026)} "
                           f"{r.randint(7, 18):02d}:{r.randint(0, 59):02d}   TR. 01", font=font(14), fill=0)
    a = np.asarray(g, np.float32) + nrng.normal(0, 10, (g.height, g.width)).astype(np.float32)
    b = a > r.uniform(150, 175)
    sp = nrng.random(b.shape)
    b[sp < 0.004], b[sp > 0.997] = False, True
    for _ in range(r.randint(3, 6)):
        y, x0 = r.randrange(g.height), r.randrange(g.width // 2)
        b[y:y + r.choice([1, 1, 2]), x0:x0 + r.randrange(g.width // 4, g.width)] = r.random() > 0.7
    return Image.fromarray(b.astype(np.uint8) * 255).convert("1", dither=Image.Dither.NONE)


def degrade(img, kind, extra, r, nrng):
    rot = 0
    img = scanify(img, r, nrng, tilt=kind not in ("skew", "phone_photo"))
    if extra == "speckle":
        a = np.asarray(img).copy()
        m = nrng.random(a.shape[:2]) < 0.0015
        a[m] = nrng.integers(0, 90, (int(m.sum()), 1))
        img = Image.fromarray(a).filter(ImageFilter.MinFilter(3) if r.random() < 0.3 else ImageFilter.SMOOTH)
    elif extra == "blur":
        img = img.filter(ImageFilter.GaussianBlur(r.uniform(0.9, 1.4)))
    elif extra == "light_skew":
        img = img.rotate(r.choice([-1, 1]) * r.uniform(1.2, 2.5), Image.BICUBIC, expand=True, fillcolor=(250, 250, 250))
    if kind.startswith("rot"):
        rot = int(kind[3:])
        img = img.rotate(rot, expand=True)
    elif kind == "skew":
        fill = r.choice([(255, 255, 255), (r.randint(120, 190),) * 3])
        img = img.rotate(r.choice([-1, 1]) * r.uniform(4, 8), Image.BICUBIC, expand=True, fillcolor=fill)
    elif kind == "phone_photo":
        img = phone_photo(img, r, nrng)
    elif kind == "fax":
        img = fax(img, r, nrng)
    elif kind == "low_res":
        sc = r.uniform(72, 90) / DPI
        img = img.resize((int(img.width * sc), int(img.height * sc)), Image.LANCZOS)
        img = img.convert("L") if r.random() < 0.5 else img
    return img, rot


def save(imgs, path: Path, fmt, kind, r):
    if fmt == "pdf":
        ims = [im if im.mode in ("L", "RGB") else im.convert("L") for im in imgs]
        res = DPI * max(ims[0].size) / H
        ims[0].save(path, "PDF", save_all=True, append_images=ims[1:], resolution=res, quality=r.randint(55, 75))
    elif fmt == "jpg":
        q = {"phone_photo": 60, "low_res": 50}.get(kind, r.randint(62, 80))
        im = imgs[0] if imgs[0].mode in ("L", "RGB") else imgs[0].convert("L")
        im.save(path, "JPEG", quality=q)
    else:
        im = imgs[0]
        if im.mode == "RGB":   # keep seal/ink colour; palette keeps file size reasonable
            im = im.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
        im.save(path, "PNG")


def generate(out_dir: Path, n_docs: int = 40, seed: int = 7, quiet: bool = False) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    master, docs = random.Random(seed), []
    for i in range(n_docs):
        kind = KINDS[i % len(KINDS)]
        r, nrng = random.Random(master.randrange(2 ** 32)), np.random.default_rng(master.randrange(2 ** 32))
        extra = None
        if r.random() < 0.45:
            extra = r.choice([e for e in EXTRAS if e != kind and not (kind == "stamp_over_numbers" and e == "stamp")
                              and not (kind == "fold_stain" and e == "fold_stain")])
        if kind == "multi_page_table":
            title, pages = r.choice([doc_congno, doc_saoke])(r, nrng, False, n_pages=r.randint(3, 6))
        elif kind == "two_column":
            title, pages = doc_twocol(r, nrng, False)
        else:
            title, pages = r.choice(SINGLE)(r, nrng, kind == "handwriting")
        overlays(pages, kind, extra, r, nrng)
        imgs, rot = [], 0
        for pg in pages:
            im, rot = degrade(pg.img, kind, extra, r, nrng)
            imgs.append(im)
        fmt = FIXED_FMT.get(kind) or ("pdf", "png", "jpg")[(i // len(KINDS) + i) % 3]
        fname = f"hs-{i + 1:03d}-{kind}.{fmt}"
        save(imgs, out_dir / fname, fmt, kind, r)
        phrases = list(dict.fromkeys(t for pg in pages for t, _ in pg.phrases))[:4]
        docs.append(dict(file=fname, kind=kind, extra=extra, format=fmt, pages=len(pages), title=title, rotation=rot,
                         numbers=[dict(text=n["text"], page=pi + 1, handwritten=n["handwritten"],
                                       covered=n["covered"]) for pi, pg in enumerate(pages) for n in pg.nums],
                         phrases=phrases))
        if not quiet:
            d = docs[-1]
            print(f"{fname:34s} extra={str(extra):10s} pages={d['pages']} numbers={len(d['numbers'])} "
                  f"hand={sum(n['handwritten'] for n in d['numbers'])} covered={sum(n['covered'] for n in d['numbers'])}")
    truth = {"seed": seed, "docs": docs}
    (out_dir / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    return truth


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="data/eval/hard_scans")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    t = generate(Path(a.out), a.n, a.seed)
    print(f"{len(t['docs'])} docs, {sum(len(d['numbers']) for d in t['docs'])} numbers -> {a.out}/truth.json")


if __name__ == "__main__":
    main()
