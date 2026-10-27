"""Fact index: labelled fields read off the documents, answered by lookup instead of by the LLM.

A 3B model handed a long OCR'd official letter missed 'S6: 1336 /Tg1-QC' (OCR for 'Số:') and answered with
the number of another letter quoted next to it; handed a sales contract it took the plot number of another
project. The fields such questions ask for are written with labels in Vietnamese documents ('Số:',
'Hợp đồng số …', 'V/v …', 'ngày … tháng … năm …', 'Thửa đất số', 'Tờ bản đồ số', 'Mã số thuế'), so they
are read off at ingest, kept with their source lines, and a question asking for one is answered from them:

- doc:  a document or contract number, with its date and subject ('V/v', 'về việc') when written next to it;
- land: a plot number and map sheet;
- tax:  a company's tax code.

Labels are matched on an accent-free copy of the text of the SAME length, so OCR spellings of the labels
('S6:', 'Thừa đât sô', 'Ma so thue') match and every value and quote is cut from the original text: the
answer cites the source lines verbatim and goes through the normal verification. A question is matched to
the facts by the words of its own subject (project, company, 'Busway', 'đính chính') against the fact's
document place, file name and subject; a date in the question must equal the fact's. When two facts fit
equally well with different values, both are answered (two Busway contracts were signed the same day).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from unidecode import unidecode

KINDS = ("doc", "land", "tax")


def fold_same_length(text: str) -> str:
    """Lowercase, accents removed, one character for one character: spans map back to the original."""
    return "".join((unidecode(ch)[:1] or " ").lower() for ch in text)


_DOCNO = re.compile(r"(?:(?<![a-z0-9])s[o6]\s*:\s*|hop dong so\s*:?\s*)"
                    r"(\d[\w.\-]*(?:\s*/\s*[\w.\-]+)+)")
_DATE = re.compile(r"ngay\s+(\d{1,2})\s+thang\s+(\d{1,2})\s+nam\s+(\d{4})|ngay\s+(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})")
_SUBJ = re.compile(r"(?:v/v|ve viec)\s*:?\s*([^\n|]{5,160})")
# where a subject line ends when the lines of a header were joined: '<Place>, ngày …', 'Kính gửi', 'Căn cứ'
_SUBJ_END = re.compile(r",\s*ngay\s+\d|\s*kinh gui|\s*can cu\b|\s*ngay\s+\d{1,2}\s+thang")


def _subject_end(text: str, f: str, start: int, end: int) -> int:
    """End of a subject in joined header lines. Before ', ngày …' the place name ('Hà Nội', 'TP. Hồ Chí Minh')
    is taken off: the capitalised words just before the comma, in the original text."""
    cut = _SUBJ_END.search(f, start, end)
    if not cut:
        return end
    pos = cut.start()
    if f[pos] == ",":
        words = list(re.finditer(r"\S+", text[start:pos]))
        while words and (words[-1].group(0)[:1].isupper() or words[-1].group(0).lower() in ("tp.", "tp")):
            words.pop()
        pos = start + (words[-1].end() if words else 0)
    return pos
_THUA = re.compile(r"thua\s*(?:dat\s*)?so\s*:?\s*(?:mot phan thua so\s*)?(\d{1,5})(?!\d)")
_TO = re.compile(r"to\s*ban\s*do\s*so\s*:?\s*(\d{1,5})(?!\d)")
_TAX = re.compile(r"(?:\bmst\b|ma so thue)\s*:?\s*(\d[\d .\-]{8,16}\d)")
_COMPANY = re.compile(r"cong ty(?:[^|:\n]|\n(?=[a-z ]{3,}))*?(?=\s*(?:dai dien|dia chi|mst|ma so thue|\||:|$))")
_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class Fact:
    kind: str
    number: str
    date: str | None = None
    subject: str | None = None
    party: str | None = None
    quotes: list[str] = field(default_factory=list)
    around: str = ""             # the text around the fact: project / company names written near it


def _date(folded: str, text: str, start: int, window: int) -> tuple[str | None, str | None]:
    """The first date written within `window` characters after `start`: (dd/mm/yyyy, the text as written)."""
    m = _DATE.search(folded, start, start + window)
    if not m:
        return None, None
    d, mo, y = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(4), m.group(5), m.group(6))
    y = y if len(y) == 4 else "20" + y
    return f"{int(d):02d}/{int(mo):02d}/{y}", text[m.start():m.end()]


def extract(text: str) -> list[Fact]:
    """The labelled fields of one chunk."""
    f = fold_same_length(text)
    out: list[Fact] = []
    for m in _DOCNO.finditer(f):
        number = re.sub(r"\s+", "", text[m.start(1):m.end(1)]).rstrip(".-")
        if not re.search(r"[^\W\d_]|\d{4}", number):        # '1/6' is a page count, not a document number
            continue
        date, date_q = _date(f, text, m.end(), 160)
        s = _SUBJ.search(f, m.end(), m.end() + 400)
        subject = s_end = None
        if s:
            s_end = _subject_end(text, f, s.start(1), s.end(1))
            subject = text[s.start(1):s_end].strip(" .;,") or None
        if not (date or subject):          # a number alone may be anything: a header has a date or a subject
            continue
        quotes = [text[m.start():m.end()].strip()] + [q for q in (date_q, text[s.start():s_end].strip() if s else None) if q]
        out.append(Fact("doc", number, date, subject, text[max(0, m.start() - 160):m.start()].strip(), quotes,
                        text[max(0, m.start() - 400):m.end() + 400]))
    th, to = _THUA.search(f), _TO.search(f)
    if th and to:
        out.append(Fact("land", text[th.start(1):th.end(1)], subject=text[to.start(1):to.end(1)],
                        quotes=[text[th.start():th.end()].strip(), text[to.start():to.end()].strip()],
                        around=text[max(0, th.start() - 600):th.end() + 300]))
    for m in _TAX.finditer(f):
        digits = re.sub(r"\D", "", text[m.start(1):m.end(1)])
        if len(digits) not in (10, 13):
            continue
        co = None
        for c in _COMPANY.finditer(f, max(0, m.start() - 250), m.start()):
            co = text[c.start():c.end()].strip(" ,;-")
        out.append(Fact("tax", text[m.start(1):m.end(1)].strip(), subject=co,
                        quotes=[text[m.start():m.end()].strip()] + ([co] if co else []),
                        around=text[max(0, m.start() - 250):m.start()]))
    return out


def descriptor(fact: Fact, context: str) -> str:
    """Words the question is matched against: the document's place, name and opening lines (where its
    project is named), the fact's subject, parties and surrounding text. A tax code is matched on the company
    written next to it only: every file of a project folder carries the project's name in its place."""
    parts = (fact.subject or fact.around,) if fact.kind == "tax" else (context, fact.subject, fact.party, fact.around)
    return " ".join(_WORD.findall(fold_same_length(" ".join(x for x in parts if x))))


# ------------------------------------------------------------------ indexing
def index_item(cur, item_id: str, context: str) -> int:
    """(Re)build the facts of one item from its current chunks; `cur` is an admin cursor."""
    cur.execute("DELETE FROM facts WHERE item_id = %s", (item_id,))
    rows = cur.execute("SELECT chunk_id, text FROM chunks WHERE item_id = %s AND is_current ORDER BY ordinal",
                       (item_id,)).fetchall()
    context = f"{context} {rows[0][1][:400]}" if rows else context     # the opening lines name the project
    n = 0
    for chunk_id, text in rows:
        for fx in extract(text):
            cur.execute("INSERT INTO facts(item_id, chunk_id, kind, number, date, subject, party, quotes, descriptor) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (item_id, chunk_id, fx.kind, fx.number, fx.date, fx.subject, fx.party, fx.quotes,
                         descriptor(fx, context)))
            n += 1
    return n


# ------------------------------------------------------------------ answering
_ASK = {
    "doc": re.compile(r"\bso hieu\b|so hop dong|hop dong so|so van ban|so cong van|so quyet dinh|so to trinh|"
                      r"mang so (hieu|nao)|so (cua|la gi)"),
    "land": re.compile(r"thua dat|to ban do"),
    "tax": re.compile(r"ma so thue|\bmst\b"),
}
# words that say what is asked, not which document: they do not identify the fact
_STOP = set("so hieu hop dong cua la gi bao nhieu nao mang ngay thang nam ve viec du an thuoc may to ban do thua dat "
            "ma thue mst va voi cho trong tai cac nhung mot duoc co khong the nay do ma o thi cong van quyet dinh "
            "trinh van ban ty tnhh phan cp jsc".split())


def asked_kind(question: str) -> str | None:
    fq = " ".join(_WORD.findall(fold_same_length(question)))
    for kind in KINDS:
        if _ASK[kind].search(fq):
            return kind
    return None


def _q_date(question: str) -> str | None:
    f = fold_same_length(question)
    d, _ = _date(f, question, 0, len(f))
    if d:
        return d
    m = re.search(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})(?!\d)", question)
    if m:
        y = m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{y}"
    return None


def match(question: str, kind: str, rows: list[dict], min_share: float = 0.6, tie: float = 0.1) -> list[dict]:
    """The facts of `kind` that the question's own subject words point to: rows [{descriptor, date, number, …}].
    Share of the question's identifying words found in the fact's descriptor; a date in the question must
    equal the fact's date. The best fact, plus any other value within `tie` of it."""
    words = {w for w in _WORD.findall(fold_same_length(question)) if w not in _STOP and len(w) > 1
             and not w.isdigit()}
    if not words:
        return []
    qd = _q_date(question) if kind == "doc" else None
    scored = []
    for r in rows:
        if qd and r.get("date") != qd:          # a date asked about: a fact with no date or another one is not it
            continue
        share = len(words & set(r["descriptor"].split())) / len(words)
        subj = set(_WORD.findall(fold_same_length(r.get("subject") or "")))
        share += 0.01 * len(words & subj)          # same document cited with several subjects: the one asked about
        if qd and r.get("date") == qd:
            share += 0.25
        scored.append((share, r))
    scored.sort(key=lambda x: -x[0])
    if not scored or scored[0][0] < min_share:
        return []
    best = scored[0][0]
    out, seen = [], set()
    for s, r in scored:
        key = (r["number"], r.get("subject") if kind == "land" else None)
        if s >= best - tie and key not in seen:
            seen.add(key)
            out.append(r)
    return out[:3]


def claim_for(r: dict) -> str:
    """The answer line. Values are written as in the source lines (the date as written, not re-formatted:
    the verifier compares the digits of every number with the quotes)."""
    if r["kind"] == "doc":
        date_q = next((q for q in r["quotes"] if fold_same_length(q).startswith("ngay")), None)
        return ("Số " + r["number"] + (f", {date_q}" if date_q else "")
                + (f" – {r['subject']}" if r.get("subject") else "") + ".")
    if r["kind"] == "land":
        return f"Thửa đất số {r['number']}, tờ bản đồ số {r['subject']}."
    return f"Mã số thuế{(' của ' + r['subject']) if r.get('subject') else ''}: {r['number']}."


_CODE = re.compile(r"\b(?=[A-Z0-9-]*[A-Z])[A-Z][A-Z0-9-]{2,}\b")


def naming_lines(oid: str, question: str, item_id: str, fact_text: str) -> list[tuple[str, dict]]:
    """For each upper-case name of the question ('MONTALP') missing from the fact's passage: a line of the
    same document that names it, with that passage (read under RLS)."""
    from dr.core import gates
    from dr.db import pg
    out = []
    for code in dict.fromkeys(_CODE.findall(question)):
        if re.search(rf"\b{re.escape(code)}\b", fact_text, re.I):
            continue
        with pg.as_principal(oid) as cur:
            row = cur.execute("SELECT chunk_id FROM chunks WHERE item_id = %s AND text ~* %s ORDER BY ordinal LIMIT 1",
                              (item_id, rf"\m{re.escape(code)}\M")).fetchone()
        if not row:
            continue
        p = gates.fetch_passages(oid, [row[0]]).get(row[0])
        m = re.search(rf"[^\n]{{0,80}}\b{re.escape(code)}\b[^\n]{{0,80}}", p["text"], re.I) if p else None
        if m:
            out.append((m.group(0).strip(), p))
    return out


def lookup(oid: str, question: str) -> list[dict]:
    """The facts the question asks for, among those the principal may read (RLS on facts follows chunks)."""
    from dr.db import pg
    kind = asked_kind(question)
    if not kind:
        return []
    with pg.as_principal(oid) as cur:
        rows = cur.execute("SELECT kind, number, date, subject, quotes, descriptor, chunk_id, item_id FROM facts "
                           "WHERE kind = %s", (kind,)).fetchall()
    cols = ("kind", "number", "date", "subject", "quotes", "descriptor", "chunk_id", "item_id")
    return match(question, kind, [dict(zip(cols, r)) for r in rows])
