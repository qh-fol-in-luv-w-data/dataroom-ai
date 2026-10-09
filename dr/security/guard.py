"""Input security (layer 2): normalisation, injection rules and a multilingual classifier.

Everything runs locally with models already on disk:
1. normalise: NFKC (fullwidth → ASCII), strip zero-width / bidi controls, map Cyrillic and
   Greek look-alikes to Latin; analysis copies also fold accents, undo leetspeak, re-join
   spaced-out letters and decode embedded base64.
2. rules: high-precision patterns (Vietnamese with or without accents, English) for
   instruction override, prompt leaks, fake privilege, role-play jailbreaks, fake
   delimiters and bulk exfiltration.
3. classifier: logistic regression on the bge-m3 embedding of the question (the same
   vector retrieval uses, so it costs nothing extra). Trained by scripts/train_guard.py
   on data/eval/prompt_attacks/train.jsonl; weights in dr/security/guard_model.json.

The guard is defence in depth, not the permission boundary: the LLM never sees a passage
the user may not read, so a missed attack can at worst produce a wrong answer, which the
quote/number verification then has to let through as well.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from unidecode import unidecode

MODEL = Path(__file__).with_name("guard_model.json")

_INVISIBLE = re.compile("[­͏؜ᅟᅠ឴឵᠎​-‏‪-‮"
                        "⁠-⁤⁦-⁯ㅤ︀-️﻿]")
_HOMOGLYPHS = str.maketrans({
    # Cyrillic
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c",
    "т": "t", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w", "ӏ": "l",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "У": "Y", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S",
    # Greek
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u",
    "χ": "x", "Α": "A", "Β": "B", "Ε": "E", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X", "Ζ": "Z",
})
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_controls(text: str) -> str:
    """NUL and other C0 control characters carry no meaning in a question and break JSON/Postgres."""
    return _CONTROL.sub("", text)


def _chars(text: str) -> str:
    t = unicodedata.normalize("NFKC", strip_controls(text))
    t = _INVISIBLE.sub("", t).translate(_HOMOGLYPHS)
    return unicodedata.normalize("NFC", t)


def clean(text: str) -> str:
    """What the rest of the system sees: NFKC, no invisible characters, no look-alikes."""
    return re.sub(r"[ \t]+", " ", _chars(text)).strip()


def _join_spaced(t: str, min_run: int = 3) -> str:
    # "i g n o r e" / "i.g.n.o.r.e" → "ignore"
    return re.sub(rf"\b(?:\w[ .\-_*]){{{min_run},}}\w\b", lambda m: re.sub(r"[ .\-_*]", "", m.group(0)), t)


def _decoded(t: str) -> list[str]:
    out = []
    for tok in re.findall(r"[A-Za-z0-9+/]{16,}={0,2}", t):
        try:
            s = base64.b64decode(tok + "=" * (-len(tok) % 4), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if sum(ch.isprintable() for ch in s) / max(1, len(s)) > 0.9:
            out.append(s)
    for tok in re.findall(r"\b(?:[0-9a-fA-F]{2}){8,}\b", t):
        try:
            s = bytes.fromhex(tok).decode("utf-8")
            if sum(ch.isprintable() for ch in s) / max(1, len(s)) > 0.9:
                out.append(s)
        except (ValueError, UnicodeDecodeError):
            pass
    return out


def analysis_forms(text: str) -> list[str]:
    """Accent-folded lowercase variants the rules run on."""
    c = _chars(text)
    base = [c] + _decoded(c)
    forms = []
    for b in base:
        raw = unidecode(b).lower()
        f = re.sub(r"\s+", " ", raw)
        # spaced-out letters: two or more spaces separate words, single spaces separate letters
        # (short Vietnamese syllables like "b o" need min_run=1, only safe when words are double-spaced)
        run = 1 if len(re.findall(r"\S\s{2,}\S", raw)) >= 2 else 3
        spaced = " ".join(_join_spaced(seg, run) for seg in re.split(r"\s{2,}|\s*[|/]\s*", raw))
        forms += [f, _join_spaced(f), re.sub(r"\s+", " ", spaced), f.translate(_LEET)]
    return list(dict.fromkeys(forms))


# ------------------------------------------------------------------ rules
_W = r"[^.!?\n]{0,40}?"   # a few words within the same sentence
_DET = r"(moi|tat ca|cac|nhung|toan bo|het( cac)?|all|every)"
_NOUN = r"(huong dan|chi dan|chi thi|quy tac|quy dinh|lenh|rang buoc|nguyen tac|gioi han|luat|dieu kien)"
_QUAL = (r"(truoc( do| day)?|o tren|phia tren|ban dau|cua ban|cua tro ly|he thong|an|goc|da (duoc )?(cho|dat|giao|cai)|"
         r"(duoc )?cai (san|dat)|mac dinh|duoc lap trinh|duoc giao|van hanh|"
         r"bao mat|an toan|kiem duyet|phan quyen)")
RULES: dict[str, str] = {
    # verb … (determiner + rule noun) or (rule noun + "yours/system/previous") or system/prompt.
    # "bỏ qua quy tắc công bố thông tin" (a legitimate question) has neither.
    "ghi_de_chi_dan": (
        rf"\b(bo qua|phot lo|lo di|quen( di| het)?|xoa bo|huy bo|vo hieu( hoa)?|khong (can )?tuan (theo|thu)|"
        rf"dung (tuan theo|ap dung)|thoat khoi|vuot qua|(tam )?gac (lai|sang mot ben)|tam bo|bo ngoai tai|tat|go bo|"
        rf"khong (can )?(ap dung|quan tam( den)?)|thoi tuan theo)\b{_W}"
        rf"(\b(system|prompt|jailbreak)\b|\b{_DET}\s+(\w+\s+)?{_NOUN}\b|\b{_NOUN}\s+(\w+\s+)?{_QUAL}\b)"),
    "override_en": (
        rf"\b(ignore|disregard|forget|override|bypass|skip|drop|neglect|set aside|put aside)\b{_W}\b(previous|prior|above|"
        rf"earlier|all|your|these|system|safety|original|initial|built-in|preset|default)\b{_W}\b(instructions?|rules?|"
        rf"prompts?|guidelines?|directives?|guardrails?|filters?|safeguards?)\b"),
    "lo_system_prompt": (
        rf"\b(in ra|hien thi|tiet lo|cho (toi )?xem|nhac lai|lap lai|chep lai|doc to|print|reveal|show|repeat|output|"
        rf"display|leak|dump|tell me)\b{_W}\b(system ?prompt|prompt (he thong|goc|ban dau|an)|loi nhac he thong|"
        rf"chi dan (he thong|ban dau|an|goc)|huong dan (ban dau|an|goc|he thong)|quy tac (an|noi bo cua ban|cua ban)|"
        rf"(initial|hidden|original|secret) (instructions?|prompt|rules)|(instructions?|rules) (you were given|above))\b"),
    "gia_quyen": (
        rf"\b(toi la|minh la|em la|i am|i'm|im|as (an? )?|voi tu cach( la)?|dong vai( la)?)\s*(nguoi )?"
        rf"(admin|quan tri( vien)?|administrator|developer|nha phat trien|dev|root|superuser|sysadmin|"
        rf"ban ipo|ceo|cfo|kiem toan vien|auditor|nhan vien it|it admin|owner|chu so huu he thong)\b"
        rf"{_W}\b(cap|mo|cho|grant|unlock|give|show|xem|truy cap|access|bo qua|vuot)\b"),
    "gia_dinh_nhom": (
        rf"\b(gia su|coi nhu|hay xem|tu gio|assume|pretend|treat me as)\b{_W}\b(toi|minh|i|me)\b{_W}"
        rf"\b(thuoc|la thanh vien|nam trong|belong|member|in)\b{_W}\b(nhom|group|site|noi bo|internal|admin)\b"),
    "nhap_vai": (
        rf"\b(dong vai|gia vo|hoa than|nhap vai|tu gio ban (la|se)|ban bay gio la|pretend|act as|roleplay|role-play|"
        rf"you are now|from now on you)\b{_W}\b(khong (con )?(bi )?(gioi han|kiem duyet|loc|rang buoc)|unrestricted|"
        rf"uncensored|unfiltered|no (filters?|rules|restrictions|limits)|dan\b|jailbr(eak|oken)|developer mode|"
        rf"che do (nha phat trien|khong gioi han)|evil|bat chap)"),
    "gia_toan_quyen": (
        rf"\b(nhu the|nhu la|coi nhu|gia nhu|gia su|as if|as though|assume|treat)\b{_W}"
        rf"\b(toan quyen|full (access|permissions?|rights|privileges)|moi quyen|quyen (cao nhat|quan tri|admin)|"
        rf"all (access|permissions?|rights)|unrestricted access|admin (access|rights))\b"),
    "the_gia": (
        r"(<\s*/?\s*(untrusted_document|system|assistant|instructions?|im_start|im_end)\b|\[/?(system|inst)\]|"
        r"^\s*(system|he thong)\s*:|#{2,}\s*(new )?(system )?instructions?|\"role\"\s*:\s*\"system\"|"
        r"<\|(im_start|system|endoftext)\|>|end of (document|context)\.? new instructions)"),
    "trich_xuat_hang_loat": (
        rf"\b(liet ke|xuat|in|dump|list|export|copy|tai (ve|xuong)|gui (cho toi|het)|doc het|show)\b{_W}"
        rf"\b(toan bo|tat ca|het|moi|all|every|entire|whole)\b{_W}\b(tai lieu|file|du lieu|noi dung|documents?|files|data|"
        rf"contents?)\b{_W}\b(cua )?(moi|cac|tat ca)? ?(nhom|nha dau tu khac|group|investors?|noi bo|internal|site|"
        rf"other|everyone|nguoi khac)\b"),
}
_RULES = {k: re.compile(v, re.M) for k, v in RULES.items()}


def rule_hits(text: str) -> list[str]:
    forms = analysis_forms(text)
    return [name for name, rx in _RULES.items() if any(rx.search(f) for f in forms)]


# ------------------------------------------------------------------ classifier
class _Clf:
    def __init__(self):
        self.w = self.b = None
        self.threshold = 0.5
        self.segment_threshold = 1.01
        if MODEL.exists():
            d = json.loads(MODEL.read_text())
            self.w, self.b = np.asarray(d["w"], dtype=np.float32), float(d["b"])
            self.mean = np.asarray(d.get("mean", [0.0] * len(d["w"])), dtype=np.float32)
            self.threshold = float(d["threshold"])
            self.segment_threshold = float(d.get("segment_threshold", 1.01))

    def score(self, vec) -> float | None:
        if self.w is None or vec is None:
            return None
        z = float(np.dot(np.asarray(vec, dtype=np.float32) - self.mean, self.w) + self.b)
        return 1.0 / (1.0 + np.exp(-z))


_clf: _Clf | None = None


def classifier() -> _Clf:
    global _clf
    if _clf is None:
        _clf = _Clf()
    return _clf


@dataclass
class Verdict:
    blocked: bool
    cleaned: str
    rules: list[str] = field(default_factory=list)
    score: float | None = None
    changed: bool = False          # normalisation removed/replaced characters


def segments(text: str, max_n: int = 8) -> list[str]:
    """Sentences/lines of a long question: an attack buried in a long, friendly message is
    diluted in the embedding of the whole text, so each part is scored too."""
    c = clean(text)
    if len(c) < 160 and "\n" not in c:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[.!?。？！])\s+|\n+", c) if len(p.strip()) >= 12]
    return parts[:max_n] if len(parts) > 1 else []


def inspect(question: str, qvec=None, embed_many=None) -> Verdict:
    """embed_many(list[str]) -> vectors, used to score the parts of long questions."""
    c = clean(question)
    hits = rule_hits(question)
    clf = classifier()
    s = clf.score(qvec)
    seg = None
    segs = segments(question) if embed_many else []
    if segs and clf.w is not None:
        seg = max(clf.score(v) for v in embed_many(segs))
    # a single sentence out of context looks odder than a whole question: stricter threshold
    blocked = bool(hits) or (s is not None and s >= clf.threshold) or (seg is not None and seg >= clf.segment_threshold)
    top = max(x for x in (s, seg, None) if x is not None) if (s is not None or seg is not None) else None
    return Verdict(blocked, c, hits, None if top is None else round(top, 3), c != question.strip())
