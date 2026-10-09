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
