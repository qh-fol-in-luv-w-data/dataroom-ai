"""Personal data masking (Vietnamese identifiers), for questions, answers and the audit log.

Only identifiers of *people* are masked: CCCD/CMND, passport numbers, mobile phones, e-mail
addresses. Company data an investor legitimately needs — tax codes (MST), company bank
accounts, landline/fax numbers of offices, amounts — is left alone.
Masking keeps the last 3 characters so a reader can still tell two values apart.
"""
from __future__ import annotations

import re

# not inside a longer number: no digit (or digit + separator) right before/after
_NB = r"(?<!\d)(?<!\d[.,/])"
_NA = r"(?!\d|[.,/]\d)"

PATTERNS: dict[str, re.Pattern] = {
    # 12-digit citizen ID (CCCD) starts with a 3-digit province code 001–096
    "cccd": re.compile(rf"{_NB}0[0-9]{{2}}[0-9]{{9}}{_NA}"),
    # 9-digit old ID card, only next to its name
    "cmnd": re.compile(r"(?i)(?:cmnd|chứng minh(?: nhân dân)?|cmt)\D{0,15}(\d{9})(?!\d)"),
    "ho_chieu": re.compile(r"(?i)(?:hộ chiếu|passport)\D{0,15}([A-Z]\d{7,8})(?!\d)"),
    # Vietnamese mobile numbers (03/05/07/08/09 + 8 digits), with optional +84 and separators
    "di_dong": re.compile(rf"{_NB}(?:\+84|0084|0)[ .-]?[35789](?:[ .-]?\d){{8}}{_NA}"),
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
}
LABEL = {"cccd": "CCCD", "cmnd": "CMND", "ho_chieu": "hộ chiếu", "di_dong": "SĐT", "email": "email"}


def _mask(value: str) -> str:
    keep = 3
    chars = [c for c in value if c.isalnum()]
    if len(chars) <= keep:
        return "•" * len(value)
    out, seen = [], 0
    total = len(chars)
    for c in value:
        if c.isalnum():
            seen += 1
            out.append(c if seen > total - keep else "•")
        else:
            out.append(c)
    return "".join(out)


# a 10-digit company tax code (MST) or account number can look like a mobile number
_NOT_PHONE = re.compile(r"(?i)(mst|mã số thuế|ma so thue|tax code|mã số doanh nghiệp|msdn|số tài khoản|stk|tài khoản|"
                        r"account|fax|số hiệu|hóa đơn|mã)\W{0,3}[^\n]{0,12}$")


def find(text: str) -> list[tuple[str, int, int]]:
    hits = []
    for kind, rx in PATTERNS.items():
        for m in rx.finditer(text):
            g = 1 if rx.groups else 0
            if kind in ("di_dong", "cccd") and _NOT_PHONE.search(text[max(0, m.start(g) - 30): m.start(g)]):
                continue
            hits.append((kind, m.start(g), m.end(g)))
    hits.sort(key=lambda h: (h[1], -h[2]))
    merged: list[tuple[str, int, int]] = []
    for h in hits:
        if merged and h[1] < merged[-1][2]:
            continue
        merged.append(h)
    return merged


def mask(text: str) -> tuple[str, list[str]]:
    """(masked text, kinds found)."""
    if not text:
        return text, []
    hits = find(text)
    out, last = [], 0
    for kind, a, b in hits:
        out += [text[last:a], _mask(text[a:b])]
        last = b
    out.append(text[last:])
    return "".join(out), sorted({LABEL[k] for k, _, _ in hits})
