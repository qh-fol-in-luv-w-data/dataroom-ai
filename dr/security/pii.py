"""Personal data masking (Vietnamese identifiers), for questions, answers and the audit log.

Only identifiers of *people* are masked: CCCD/CMND, passport numbers, mobile phones, e-mail
addresses. Company data an investor legitimately needs — tax codes (MST), company bank
accounts, landline/fax numbers of offices, amounts — is left alone. A mobile-looking number
is read in its context: an organisation's line (hotline, tổng đài, chi nhánh, công ty…) is
kept, a person's (Ông/Bà/Anh/Chị + name, giám đốc, người đại diện…) and one with no context
are masked; the nearer of the two kinds of words decides.
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


# whose line a phone number is, from the words around it (case-insensitive unless noted)
_ORG = re.compile(r"(?i)\b(?:công ty|cty|ctcp|tnhh|tập đoàn|ngân hàng|chi nhánh|hotline|hot line|tổng đài|cskh|"
                  r"chăm sóc khách hàng|fax|mst|mã số thuế|website|web|www|văn phòng|trụ sở|showroom|sàn giao dịch|"
                  r"phòng kinh doanh|phòng bán hàng|ban quản lý|bql|nhà mẫu|tel)\b|\bCN\b|\b[\w-]+\.(?:vn|com)\b")
_PERSON = re.compile(r"(?i)\b(?:họ tên|họ và tên|người đại diện|cccd|cmnd|căn cước|ngày sinh|giám đốc|chức vụ|"
                     r"nhân viên|chuyên viên|trưởng phòng|phó phòng|cá nhân|người liên hệ)\b")
# a title and a capitalised name; Bà Rịa, Bà Chiểu, Bà Điểm are places
_TITLE = re.compile(r"(?i)\b(?:ông|bà|anh|chị|mr|mrs|ms)\.?\s+(?!rịa|chiểu|điểm\b)(\w)")
_BRANCH_MST = re.compile(r"-\d{3}(?!\d)")            # 0312345678-001: a branch's tax code


def _person_marks(s: str) -> list[int]:
    """End positions of the words that make a number a person's: a title followed by a capitalised name."""
    out = [m.end() for m in _PERSON.finditer(s)]
    out += [m.end() for m in _TITLE.finditer(s) if m.group(1).isupper()]
    return out


def phone_context(text: str, a: int, b: int, window: int = 80) -> str:
    """'org', 'person' or '' for the number at text[a:b]: the nearest such word before it decides; with none
    before, a word right after it ('0909… (hotline)')."""
    pre = text[max(0, a - window):a]
    org = [m.end() for m in _ORG.finditer(pre)]
    per = _person_marks(pre)
    if org or per:
        return "person" if max(per, default=-1) >= max(org, default=-1) else "org"
    post = text[b:b + 25]
    if _person_marks(post):
        return "person"
    return "org" if _ORG.search(post) else ""


def _phones(text: str):
    """(match, context) for each mobile-looking number that is not a tax code or account number."""
    for m in PATTERNS["di_dong"].finditer(text):
        if _NOT_PHONE.search(text[max(0, m.start() - 30): m.start()]) or _BRANCH_MST.match(text, m.end()):
            continue
        yield m, phone_context(text, m.start(), m.end())


def org_numbers(text: str) -> set[str]:
    """Digits of the mobile-looking numbers the text gives as an organisation's (never also as a person's):
    a claim citing this text may show them although the claim itself does not say whose they are."""
    org, person = set(), set()
    for m, ctx in _phones(text):
        (org if ctx == "org" else person).add(re.sub(r"\D", "", m.group(0)))
    return org - person


def find(text: str, allow: frozenset[str] | set[str] = frozenset()) -> list[tuple[str, int, int]]:
    hits = []
    for kind, rx in PATTERNS.items():
        if kind == "di_dong":
            for m, ctx in _phones(text):
                if ctx == "org" or (ctx != "person" and re.sub(r"\D", "", m.group(0)) in allow):
                    continue
                hits.append((kind, m.start(), m.end()))
            continue
        for m in rx.finditer(text):
            g = 1 if rx.groups else 0
            if kind == "cccd" and _NOT_PHONE.search(text[max(0, m.start(g) - 30): m.start(g)]):
                continue
            hits.append((kind, m.start(g), m.end(g)))
    hits.sort(key=lambda h: (h[1], -h[2]))
    merged: list[tuple[str, int, int]] = []
    for h in hits:
        if merged and h[1] < merged[-1][2]:
            continue
        merged.append(h)
    return merged


def mask(text: str, allow: frozenset[str] | set[str] = frozenset()) -> tuple[str, list[str]]:
    """(masked text, kinds found). allow: digits of numbers its source gives as an organisation's (org_numbers)."""
    if not text:
        return text, []
    hits = find(text, allow)
    out, last = [], 0
    for kind, a, b in hits:
        out += [text[last:a], _mask(text[a:b])]
        last = b
    out.append(text[last:])
    return "".join(out), sorted({LABEL[k] for k, _, _ in hits})
