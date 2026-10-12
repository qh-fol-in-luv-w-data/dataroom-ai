"""What kind of answer the question asks for, decided from the question itself.

  fact     a figure, date, name or yes/no: short answer from the few best passages (fast path)
  summary  "tóm tắt / tổng hợp / nội dung chính / tài liệu X nói gì": wide retrieval, synthesis
  compare  "so sánh / khác nhau / bên nào…": wide retrieval across documents, each side stated
  list     "liệt kê / gồm những gì / danh sách": wide retrieval, every item found
  full     "đầy đủ / chi tiết / nguyên văn / trích": the source sentences themselves, verbatim

A question naming a document (control code KS-… or a file name) is answered from that whole
document when it asks for a summary, a list or the full text.
Each plan sets how much is read: wider plans are slower on a laptop, a few seconds on a GPU.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from unidecode import unidecode

_TERMS = {
    "full": [r"day du", r"chi tiet", r"nguyen van", r"toan van", r"trich (dan )?nguyen", r"trich (lai|ra|dan)",
             r"tung (dieu|dong|cau)", r"verbatim", r"full text", r"exact wording", r"word for word", r"in full",
             r"quote the"],
    "compare": [r"so sanh", r"khac nhau", r"giong nhau", r"khac (gi|biet)", r"chenh lech", r"ben nao", r"nhom nao",
                r"compare", r"comparison", r"difference", r"differ", r"versus", r"\bvs\b",
                r"which (group|one|side|party)"],
    "list": [r"liet ke", r"gom nhung", r"bao gom nhung", r"danh sach", r"nhung (\w+ ){0,3}nao", r"cac (\w+ ){0,3}nao",
             r"\blist\b", r"what are (all )?the", r"which (\w+ ){0,2}are"],
    "summary": [r"tom tat", r"tong hop", r"tom lai", r"khai quat", r"so luoc", r"noi dung chinh", r"y chinh",
                r"diem chinh", r"noi (ve )?(noi dung )?gi", r"de cap (den )?(nhung )?gi", r"gioi thieu",
                r"summar", r"overview", r"key points", r"main points", r"what does .{0,40} (say|cover)",
                r"what is .{0,30} about"],
}
_RX = {k: re.compile("|".join(v)) for k, v in _TERMS.items()}
_CODE = re.compile(r"\bKS-[A-Z]+-\d{4}\b")
_FILE = re.compile(r"\b[\w\-]+\.(?:pdf|docx?|xlsx?|pptx?|eml|md|html?|txt|csv|png|jpe?g)\b", re.I)


@dataclass(frozen=True)
class Plan:
    intent: str
    passages: int          # passages kept after rerank
    per_file: int          # at most this many from one file
    sentences: int         # sentences sent to the model (0 = whole passages)
    claims: int            # most claims the model may write
    verbatim: bool         # answer = source sentences themselves
    relevance: bool        # drop claims that do not address the question (short answers only)


PLANS = {
    "fact": Plan("fact", 5, 3, 14, 3, False, True),
    "summary": Plan("summary", 14, 4, 48, 8, False, False),
    "compare": Plan("compare", 16, 3, 48, 8, False, False),
    "list": Plan("list", 14, 4, 48, 10, False, False),
    "full": Plan("full", 10, 6, 40, 8, True, False),
    # several facts or a comparison in one question: each part is searched and ranked on its own
    "multi": Plan("multi", 12, 3, 36, 6, False, False),
}


def classify(question: str) -> str:
    q = re.sub(r"\s+", " ", unidecode(question).lower())
    for k in ("full", "compare", "list", "summary"):        # most specific first
        if _RX[k].search(q):
            return k
    return "fact"


def named_documents(question: str) -> tuple[list[str], list[str]]:
    """Control codes and file names the question names."""
    return _CODE.findall(question), [m.group(0) for m in _FILE.finditer(question)]


def plan_for(question: str) -> Plan:
    return PLANS[classify(question)]


# ------------------------------------------------------------------ relevance of a short answer
_STOP = set("""la cua bao nhieu nhung khong duoc cho voi trong cac nam ty dong gi nao sao co ve theo nay mot hay
neu thi tai da se dang the what which how much many is are was were for and with from that this does did of to in on
at by an as be it its ap dung tong""".split()) | {"sao", "mai", "smp", "cong", "nha", "dau", "investor",
                                                  "investors", "company"}


def key_terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", unidecode(text).lower()) if len(w) >= 3 and w not in _STOP}


def term_overlap(question: str, answer: str) -> float:
    """Share of the question's key terms that the answer (claim + its quotes) contains."""
    q = key_terms(question)
    return len(q & key_terms(answer)) / max(1, len(q))


# ------------------------------------------------------------------ the question itself
_QWORD = re.compile(r"\b(bao nhieu|la gi|nhung gi|nao|khi nao|ai|bao lau|the nao|ra sao|co .{1,60} khong|"
                    r"what|how|which|who|when|where|why|is there|are there|does|do|did|can)\b")


def _asks(text: str) -> bool:
    t = unidecode(text).lower()
    return "?" in text or bool(_QWORD.search(t))


def core_question(question: str) -> str:
    """The question without its preface. "Chị Lan bên Ban IPO dặn tôi hỏi trực tiếp: <câu hỏi>" or
    "Our committee meets next week. <question>?" -> the question itself. Retrieval and the model
    work on this; the full text still goes through the input guard, the sensitive/other-group checks
    and the audit log, so a preface can neither hide an attack nor steer the search."""
    q = question.strip()
    if ":" in q:
        head, tail = q.rsplit(":", 1)
        tail = tail.strip()
        if (len(tail) >= 12 and "?" not in head and _asks(tail)
                and not (head[-1:].isdigit() and tail[:1].isdigit())):      # not a time like 10:30
            return tail
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", q) if s.strip()]
    if len(sents) > 1:
        asks = [s for s in sents if _asks(s)]
        if asks and len(asks) < len(sents):
            return " ".join(asks)
    return q


_LEAD = re.compile(r"^\s*(so sanh|compare|doi chieu)\s+", re.I)
_VS = re.compile(r"\s+(?:voi|so voi|versus|vs\.?|with|against)\s+", re.I)
_AND = re.compile(r"\s*(?:,|;|\bva\b|\band\b|\bcung\b)\s*", re.I)


def sub_questions(question: str) -> list[str]:
    """Parts of a several-part question ("So sánh phí thu xếp nhóm A với room ngoại nhóm B",
    "Doanh thu 2025 và tổng công suất lắp đặt?"), each searched on its own so that every part gets
    passages. Split on commas/"và"/"and", and on "với/with" only after "so sánh/compare".
    A part needs two key terms; otherwise the question is not split. Parts keep the original text."""
    folded = unidecode(question).lower().rstrip(" ?.!")
    if len(folded) != len(question.rstrip(" ?.!")):          # unidecode changed lengths: no safe mapping
        return []
    orig = question.rstrip(" ?.!")
    m = _LEAD.match(folded)
    start = m.end() if m else 0
    spans = [(start, len(folded))]
    if m:
        cuts = [(x.start(), x.end()) for x in _VS.finditer(folded, start)]
        spans, pos = [], start
        for a, b in cuts:
            spans.append((pos, a))
            pos = b
        spans.append((pos, len(folded)))
    parts: list[str] = []
    for a, b in spans:
        pos = a
        for x in _AND.finditer(folded, a, b):
            parts.append(orig[pos:x.start()])
            pos = x.end()
        parts.append(orig[pos:b])
    parts = [p.strip() for p in parts if len(key_terms(p)) >= 2]
    return parts if len(parts) >= 2 else []


# English questions over Vietnamese documents: cross-lingual ranking is weak (the right passage scored
# 0.007), so the Vietnamese terms of a fixed IPO glossary are added to what is searched and ranked.
# Deterministic (no model translation: the 7B model drifted into Chinese and produced wrong answers).
GLOSSARY = [
    ("arrangement fee", "phí thu xếp"), ("lock-up", "lock-up cam kết nắm giữ"), ("lockup", "lock-up"),
    ("installed capacity", "công suất lắp đặt"), ("capacity", "công suất"), ("net revenue", "doanh thu thuần"),
    ("revenue", "doanh thu"), ("net profit", "lợi nhuận sau thuế"), ("profit after tax", "lợi nhuận sau thuế"),
    ("foreign ownership room", "room ngoại"), ("ownership room", "room ngoại"), ("foreign ownership", "sở hữu nước ngoài"),
    ("board member", "thành viên HĐQT"), ("board seat", "thành viên HĐQT"), ("board of directors", "HĐQT"),
    ("nominate", "đề cử"), ("strategic investor", "nhà đầu tư chiến lược"), ("domestic fund", "quỹ trong nước"),
    ("foreign fund", "quỹ ngoại"), ("foreign investor", "nhà đầu tư nước ngoài"), ("offering price", "giá chào bán"),
    ("offer price", "giá chào bán"), ("valuation", "định giá"), ("provision", "khoản dự phòng"),
    ("dispute", "tranh chấp"), ("contractor", "nhà thầu"), ("hedging", "bảo hiểm tỷ giá"),
    ("ceiling rate", "tỷ giá trần"), ("exchange rate", "tỷ giá"), ("fx", "tỷ giá"), ("shares", "cổ phần"),
    ("auditor", "kiểm toán"), ("audit", "kiểm toán"), ("power purchase agreement", "hợp đồng mua bán điện"),
    ("ppa", "hợp đồng mua bán điện"), ("dividend", "cổ tức"), ("listing", "niêm yết"), ("bookbuilding", "dựng sổ"),
    ("underwriter", "bảo lãnh phát hành"), ("plant", "nhà máy"), ("solar", "điện mặt trời"), ("wind", "điện gió"),
    ("debt", "nợ vay"), ("loan", "khoản vay"), ("payment", "thanh toán"), ("internal", "nội bộ"),
    ("group a", "nhóm A"), ("group b", "nhóm B"), ("group c", "nhóm C"), ("fee", "phí"),
]


def expand_en(question: str) -> str:
    """English question + the Vietnamese terms its words stand for (longest match first)."""
    q = " " + re.sub(r"[^a-z0-9\- ]", " ", question.lower()) + " "
    found: list[str] = []
    for en, vi in sorted(GLOSSARY, key=lambda x: -len(x[0])):
        if f" {en} " in q or f" {en}s " in q:
            q = q.replace(f" {en}s ", " ").replace(f" {en} ", " ")
            if vi not in found:
                found.append(vi)
    return f"{question} ({'; '.join(found)})" if found else question
