"""Scan clean-up before OCR, using only models already on disk (PP-OCRv5 det + latin rec).

Real data-room scans are rotated, photographed on a desk, faxed, low resolution, stained
or stamped over. Each step is cheap and only fires when the page needs it:

1. page detection + perspective correction (phone photos of a page on a desk)
2. illumination flattening (shadows, folds, coffee stains, yellowed paper)
3. upscaling of low-resolution pages
4. orientation 0/90/180/270 (text-box shape, then recognition confidence upright vs flipped)
5. deskew (median angle of detected text lines)

(No fax despeckling: it erases the 1–2 px separators inside numbers.)

Then a second, independent reader (PP-OCRv5 latin) reads every line. It cannot read
Vietnamese diacritics well but reads digits reliably, so numbers that both engines agree on
are trusted and numbers only the VLM produced are flagged as uncertain (see ocr.py).
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger("preprocess")
_lock = threading.Lock()
_det = None
_rec = None
MIN_WIDTH = 1500          # A4 at ~180 dpi; smaller pages are upscaled


def _models():
    global _det, _rec
    if _det is None:
        from paddleocr import TextDetection, TextRecognition
        _det = TextDetection(model_name="PP-OCRv5_mobile_det")
        _rec = TextRecognition(model_name="latin_PP-OCRv5_mobile_rec")
    return _det, _rec


@dataclass
class Line:
    text: str
    score: float
    box: tuple[int, int, int, int]       # x0, y0, x1, y1 in the prepared page


@dataclass
class Prepared:
    image: Image.Image
    steps: list[str] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)


# ------------------------------------------------------------------ geometry / photometry
def _order(pts: np.ndarray) -> np.ndarray:
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def unwarp_page(rgb: np.ndarray) -> np.ndarray | None:
    """If the page is a lighter quadrilateral on a darker background, warp it flat."""
    h, w = rgb.shape[:2]
    scale = 1000 / max(h, w)
    small = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (7, 7), 0)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    area = cv2.contourArea(c) / (small.shape[0] * small.shape[1])
    if not 0.25 < area < 0.97:                       # no separate page region: already a flat scan
        return None
    # Only a photo has a desk around the page: the outer frame must be clearly darker than the
    # page. Folds, shadows and stains on a flat scan also split the paper, but its frame is paper.
    band = max(4, min(gray.shape) // 40)
    frame = np.concatenate([gray[:band].ravel(), gray[-band:].ravel(), gray[:, :band].ravel(), gray[:, -band:].ravel()])
    page_mask = np.zeros_like(gray)
    cv2.drawContours(page_mask, [c], -1, 255, -1)
    if np.median(frame) > 0.75 * np.median(gray[page_mask > 0]):
        return None
    quad = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
    if len(quad) != 4:
        quad = cv2.boxPoints(cv2.minAreaRect(c))
    src = _order(quad.reshape(-1, 2).astype(np.float32) / scale)
    wd = int(max(np.linalg.norm(src[0] - src[1]), np.linalg.norm(src[3] - src[2])))
    ht = int(max(np.linalg.norm(src[0] - src[3]), np.linalg.norm(src[1] - src[2])))
    if wd < 300 or ht < 300:
        return None
    dst = np.array([[0, 0], [wd - 1, 0], [wd - 1, ht - 1], [0, ht - 1]], dtype=np.float32)
    return cv2.warpPerspective(rgb, cv2.getPerspectiveTransform(src, dst), (wd, ht),
                               flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def flatten_light(rgb: np.ndarray) -> np.ndarray | None:
    """Divide by the estimated paper background when lighting is uneven (keeps red seals)."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    k = max(31, (min(gray.shape) // 20) | 1)
    bg = cv2.medianBlur(cv2.resize(gray, None, fx=0.25, fy=0.25), k // 4 | 1)
    if np.percentile(bg, 95) - np.percentile(bg, 5) < 35:
        return None
    bg = cv2.resize(bg, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    out = np.clip(rgb.astype(np.float32) / np.maximum(bg[..., None], 1) * 245, 0, 255)
    return out.astype(np.uint8)


def rotate(rgb: np.ndarray, deg: float) -> np.ndarray:
    if deg % 360 == 0:
        return rgb
    if deg % 90 == 0:
        return np.ascontiguousarray(np.rot90(rgb, k=int(deg // 90) % 4))
    h, w = rgb.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(rgb, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT,
                          borderValue=(255, 255, 255))


# ------------------------------------------------------------------ text-model based steps
def _detect(rgb: np.ndarray, max_side: int = 1600) -> list[np.ndarray]:
    det, _ = _models()
    scale = min(1.0, max_side / max(rgb.shape[:2]))
    img = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    res = list(det.predict(img))[0].json["res"]
    return [np.asarray(p, dtype=np.float32) / scale for p, s in zip(res["dt_polys"], res["dt_scores"]) if s > 0.5]


def _crops(rgb: np.ndarray, polys: list[np.ndarray]) -> tuple[list[np.ndarray], list[tuple]]:
    out, boxes = [], []
    h, w = rgb.shape[:2]
    for p in polys:
        x0, y0 = np.maximum(p.min(0).astype(int) - 2, 0)
        x1, y1 = np.minimum(p.max(0).astype(int) + 2, [w, h])
        if x1 - x0 > 4 and y1 - y0 > 4:
            out.append(rgb[y0:y1, x0:x1])
            boxes.append((int(x0), int(y0), int(x1), int(y1)))
    return out, boxes


def _recognise(crops: list[np.ndarray]) -> list[tuple[str, float]]:
    if not crops:
        return []
    _, rec = _models()
    return [(r.json["res"]["rec_text"], float(r.json["res"]["rec_score"])) for r in rec.predict(crops)]


def orientation(rgb: np.ndarray) -> int:
    """Angle (0/90/180/270) to pass to rotate() so the text becomes upright."""
    polys = _detect(rgb, 1200)
    if len(polys) < 3:
        return 0
    wide = [p for p in polys if np.ptp(p[:, 0]) > 1.5 * np.ptp(p[:, 1])]
    tall = [p for p in polys if np.ptp(p[:, 1]) > 1.5 * np.ptp(p[:, 0])]
    base = 0
    if len(tall) > len(wide):                       # text runs vertically: page is on its side
        base = 90
        rgb = rotate(rgb, 90)
        polys = _detect(rgb, 1200)
    longest = sorted(polys, key=lambda p: -np.ptp(p[:, 0]))[:12]
    crops, _ = _crops(rgb, longest)
    if not crops:
        return base
    up = np.mean([s for _, s in _recognise(crops)])
    down = np.mean([s for _, s in _recognise([c[::-1, ::-1].copy() for c in crops])])
    flip = 180 if down > up + 0.08 else 0
    return (base + flip) % 360


def skew_angle(rgb: np.ndarray) -> float:
    angles = []
    for p in _detect(rgb):
        (x0, y0), (x1, y1) = p[0], p[1]
        if x1 - x0 > 80:
            angles.append(np.degrees(np.arctan2(y1 - y0, x1 - x0)))
    return float(np.median(angles)) if len(angles) >= 3 else 0.0


def read_lines(rgb: np.ndarray) -> list[Line]:
    polys = sorted(_detect(rgb), key=lambda p: (round(float(p[:, 1].mean()) / 20), float(p[:, 0].min())))
    crops, boxes = _crops(rgb, polys)
    return [Line(t, s, b) for (t, s), b in zip(_recognise(crops), boxes) if t.strip()]


# ------------------------------------------------------------------ entry point
def prepare(img: Image.Image, with_lines: bool = True) -> Prepared:
    rgb = np.asarray(img.convert("RGB"))
    steps: list[str] = []
    with _lock:
        # No despeckling: on 100-dpi faxes the thousands/decimal separators *are* 1–2 px dots,
        # and erasing them turned 12.345 into 12345 (measured: 13/16 → 5/16 numbers correct).
        for name, fn in (("nắn phẳng ảnh chụp", unwarp_page), ("cân sáng", flatten_light)):
            try:
                out = fn(rgb)
            except Exception:
                log.exception("%s failed", name)
                out = None
            if out is not None:
                rgb, _ = out, steps.append(name)
        if rgb.shape[1] < MIN_WIDTH and rgb.shape[0] < MIN_WIDTH * 1.6:
            f = MIN_WIDTH / rgb.shape[1]
            rgb = cv2.resize(rgb, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
            steps.append(f"phóng to ×{f:.1f}")
        rot = orientation(rgb)
        if rot:
            # np.rot90 turns counter-clockwise: rotate back by the detected clockwise angle
            rgb = rotate(rgb, rot)
            steps.append(f"xoay {rot}°")
        ang = skew_angle(rgb)
        if 0.4 < abs(ang) < 15:
            rgb = rotate(rgb, ang)
            steps.append(f"chỉnh nghiêng {ang:+.1f}°")
        lines = read_lines(rgb) if with_lines else []
    return Prepared(Image.fromarray(rgb), steps, lines)
