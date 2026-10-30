"""Builds a ~500-question mock test on the CT Group data room, from its own chunks, with the local model only.

Three parts, written to <DR_DATA>/mocktest/mocktest_500.jsonl (one JSON object per line):
  fact  (~350) a sentence holding a figure is drawn (fixed seed, spread over document kinds); the local
               LLM writes a question and copies the answer from that one sentence; a pair is kept only when the
               answer holds a figure, is found verbatim in the sentence (normalised) and is not given away by the question;
               a question that does not name its document gets the file name in front ("Theo tài liệu “…”: …").
  perm  (~100) the same, from files a user may NOT read; asked as that user. Kept only when the answer's figures
               appear in no chunk the user may read, compared by value as the scorer compares them (1,4 tỷ =
               1.400.000.000), so any figure in the reply is a leak.
  oos   (~50)  questions about projects, people and figures that appear nowhere in the data room (checked on the
               folded text of every chunk); the answer must say nothing was found.
The answers are machine-made and not reviewed by a person. Nothing leaves the machine (Ollama + Postgres).

    DR_DATA=data/ctg DR_PGDATA=~/.dr_ctg/pgdata DR_PG_PORT=55433 python scripts/ctg_mocktest_build.py
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dr.config import settings  # noqa: E402
from dr.core import verify  # noqa: E402
from dr.core.facts import fold_same_length  # noqa: E402
from dr.db import pg  # noqa: E402
from dr.models import llm  # noqa: E402

from ctg_mocktest_eval import holds, readable_holds  # noqa: E402  (the scorer's own comparison)

SEED = 20261029
# questions per document kind (fact part); perm questions come from any kind
QUOTA = {"văn bản": 90, "scan/ảnh OCR": 110, "bảng Excel": 70, "bảng": 40, "slide": 40}
N_PERM, N_OOS = 100, 50
FACT_USER = "ctg-b"                    # Ban dự án: reads nearly every file, staff (no sensitive-topic redirect)
PERM_USERS = ["ctg-a", "ctg-c", "ctg-d", "ctg-e", "ctg-f"]

SYSTEM = (
    "Bạn soạn câu hỏi kiểm tra cho một kho tài liệu dự án bất động sản. Bạn nhận TÊN TÀI LIỆU, THƯ MỤC và MỘT CÂU "
    "trích từ tài liệu đó. Hãy viết MỘT câu hỏi tiếng Việt mà câu trích trả lời được, kèm đáp án ngắn.\n"
    "Quy tắc:\n"
    "- Đáp án là một cụm CHÉP NGUYÊN VĂN từ câu trích (một con số kèm đơn vị, một ngày, hoặc một mã số), "
    "tối đa 12 từ.\n"
    "- Câu hỏi phải tự đủ nghĩa khi hỏi trên cả kho tài liệu: nêu rõ dự án / hợp đồng / căn hộ / hạng mục / tài liệu "
    "mà câu trích nói tới (lấy từ câu trích hoặc tên tài liệu), để chỉ có một đáp án đúng.\n"
    "- Câu hỏi không được chứa đáp án.\n"
    "- Nếu câu trích không có thông tin cụ thể, bị lỗi chữ, hoặc không thể hỏi rõ ràng: trả skip = true.\n"
    "Chỉ trả JSON đúng schema."
)
SCHEMA = {"type": "object", "properties": {"skip": {"type": "boolean"}, "question": {"type": "string"},
                                          "answer": {"type": "string"}}, "required": ["skip", "question", "answer"]}

VI_LETTERS = set("aàáảãạăằắẳẵặâầấẩẫậbcdđeèéẻẽẹêềếểễệghiìíỉĩịklmnoòóỏõọôồốổỗộơờớởỡợpqrstuùúủũụưừứửữựvxyỳýỷỹỵfjwz")
_SPLIT = re.compile(r"(?<=[.;!?])\s+|\n+|\s\|\s(?=\S)")


def kind_of(ext: str, ckind: str, ocr: bool) -> str:
    if ext == "xlsx":
        return "bảng Excel"
    if ext == "pptx":
        return "slide"
    if ocr:
        return "scan/ảnh OCR"
    if ckind == "table":
        return "bảng"
    return "văn bản"


_FILEISH = re.compile(r"\.(?:pdf|jpe?g|png|gif|tiff?|svg|psd|ai|eps|indd|aep|wav|mp[34]|mov|docx?|xlsx?|pptx?|zip|rar)\b|[0-9a-f]{8}-[0-9a-f]{4}-|https?://", re.I)
_STOPWORDS = {"cf", "ptt", "ttcu", "hd", "hop", "dong", "tai", "lieu", "du", "an", "cong", "ty", "va", "cua", "cho",
              "the", "theo", "ban", "so", "ngay", "thang", "nam", "pl", "phu", "luc", "ss", "ct", "group"}


def clean_enough(s: str) -> bool:
    """Readable Vietnamese with a figure: drops broken font encodings, bare number grids and file lists."""
    if not (40 <= len(s) <= 320) or not re.search(r"\d", s) or _FILEISH.search(s):
        return False
    letters = [ch for ch in s.lower() if ch.isalpha()]
    if len(letters) < 20 or sum(ch in VI_LETTERS for ch in letters) / len(letters) < 0.97:
        return False
    words = re.findall(r"[^\W\d_]{2,}", s)
    return len(words) >= 5 and sum(ch.isdigit() for ch in s) / len(s) < 0.35


def segments(text: str) -> list[str]:
    return [s.strip(" -•|;") for s in _SPLIT.split(text) if clean_enough(s.strip(" -•|;"))]


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def title_of(name: str) -> str:
    return re.sub(r"\.\w{2,5}$", "", name).strip()


def names_document(q: str, title: str) -> bool:
    """Does the question carry at least two distinctive words of the file name (so search can find it)?"""
    words = lambda t: {w for w in re.findall(r"[a-z0-9]{2,}", fold_same_length(t)) if w not in _STOPWORDS}
    return len(words(q) & words(title)) >= 2


def make_pair(row: dict, seg: str) -> dict | None:
    prompt = (f"TÊN TÀI LIỆU: {row['name']}\nTHƯ MỤC: {row['path']}\nCÂU TRÍCH: {seg}\n")
    out = llm._chat(SYSTEM, prompt, SCHEMA, timeout=120, max_tokens=200)
    q, a = nfc(str(out.get("question", "")).strip()), nfc(str(out.get("answer", "")).strip().strip(".,;"))
    if out.get("skip") or not q or not a or len(a) > 90 or len(q) < 15:
        return None
    na, ns, nq = verify.norm(a), verify.norm(seg), verify.norm(q)
    if not na or na not in ns:                        # the answer must be copied from the sentence
        return None
    if na in nq or (digits(a) and len(digits(a)) >= 3 and digits(a) in digits(q)) or holds(a, q):
        return None                                   # the question gives the answer away (also by value: 06 = 6)
    if not holds(a, row["text"]):
        return None                                   # the scorer must find the answer in its own source chunk
    if len(na.split()) > 10 or len(a) > 0.6 * len(seg):
        return None                                   # an answer that is the whole sentence checks nothing
    if not digits(a):
        return None                                   # a figure, date or code only: scored by value, unambiguously
    if re.fullmatch(r"[\d.]+", a) and verify.norm(seg).startswith(na):
        return None                                   # a clause number ("1.10 'Khối lượng…' là …")
    if not names_document(q, row["name"]):
        # "Theo hợp đồng, …" is not answerable across 6,800 files: name the document, as a user would
        q = f"Theo tài liệu “{title_of(row['name'])}”: {q[0].lower()}{q[1:]}"
    return {"question": q, "answer": a, "quote": seg}


def candidates(cur, where: str, params: tuple) -> list[dict]:
    rows = cur.execute(
        "SELECT c.chunk_id, c.item_id, c.kind, c.ocr, c.text, i.name, i.path, i.ext FROM chunks c "
        "JOIN items i ON i.item_id = c.item_id AND i.ctag = c.ctag "
        f"WHERE c.is_current AND i.ai_use = 'Allowed' AND i.status = 'indexed' AND {where}", params).fetchall()
    keys = ("chunk_id", "item_id", "kind", "ocr", "text", "name", "path", "ext")
    return [dict(zip(keys, r)) for r in rows]


def readable_has(cur, oid: str, answer: str) -> bool:
    """Does any chunk the user may read hold the answer (its digits, or its folded words)?"""
    d = digits(answer)
    if len(d) >= 3:
        return cur.execute(
            "SELECT 1 FROM chunks c JOIN item_reader r ON r.item_id = c.item_id AND r.oid = %s "
            "WHERE c.is_current AND regexp_replace(c.text, '\\D', '', 'g') LIKE %s LIMIT 1",
            (oid, f"%{d}%")).fetchone() is not None
    return cur.execute(
        "SELECT 1 FROM chunks c JOIN item_reader r ON r.item_id = c.item_id AND r.oid = %s "
        "WHERE c.is_current AND c.text_folded LIKE %s LIMIT 1",
        (oid, f"%{fold_same_length(answer)}%")).fetchone() is not None


def draw(pool: list[dict], want: int, rng: random.Random, used_items: set[str], tag: str,
         extra=None) -> list[dict]:
    """Pairs from `pool` (shuffled), at most one per file, until `want` are kept."""
    rng.shuffle(pool)
    out, tried = [], 0
    for row in pool:
        if len(out) >= want:
            break
        if row["item_id"] in used_items:
            continue
        segs = segments(row["text"])
        if not segs:
            continue
        seg = rng.choice(segs)
        tried += 1
        pair = make_pair(row, seg)
        if not pair:
            continue
        rec = {"item_id": row["item_id"], "chunk_id": row["chunk_id"], "doc": row["name"],
               "folder": row["path"].split("/")[0], "kind": kind_of(row["ext"], row["kind"], row["ocr"]), **pair}
        if extra:
            rec = extra(rec)
            if not rec:
                continue
        used_items.add(row["item_id"])
        out.append(rec)
        print(f"  [{tag} {len(out)}/{want}, thử {tried}] {pair['question']}  → {pair['answer']}", flush=True)
    return out


# out-of-scope: projects / people that do not exist in the data room, asked like the real questions
OOS_SUBJECTS = ["dự án Sakura Riverside Đà Lạt", "dự án Hạ Long Pearl Tower", "khu đô thị Mekong Green City Cần Thơ",
                "dự án Phú Quốc Coral Bay", "tòa nhà Lotus Business Center Hải Phòng", "dự án Tây Nguyên Eco Farm",
                "khu nghỉ dưỡng Côn Đảo Blue Lagoon", "dự án Nha Trang Skyline Marina", "dự án Huế Imperial Garden",
                "khu công nghiệp Bắc Ninh Smart Park", "dự án Vũng Tàu Ocean Pearl", "dự án Quy Nhơn Sapphire Bay",
                "trung tâm thương mại Hà Giang Highland Mall", "dự án Long An Golden Delta",
                "bệnh viện quốc tế CT Medic Đà Nẵng", "trường quốc tế CT Academy Thủ Đức",
                "nhà máy điện gió Ninh Thuận CT Wind 3", "dự án Mũi Né Desert Rose"]
OOS_ASKS = ["có tổng mức đầu tư bao nhiêu?", "được khởi công vào ngày nào?", "có bao nhiêu căn hộ?",
            "có diện tích khu đất bao nhiêu hecta?", "do nhà thầu nào thi công chính?",
            "có giá bán căn hộ 2 phòng ngủ là bao nhiêu?", "có tỷ suất lợi nhuận dự kiến bao nhiêu phần trăm?",
            "đã được cấp giấy phép xây dựng số mấy?"]
OOS_OTHER = ["Giá cổ phiếu CT Group trên sàn HOSE ngày 15/03/2031 là bao nhiêu?",
             "Doanh thu năm 2035 của CT Group tại thị trường Nhật Bản là bao nhiêu?",
             "CT Group trả cổ tức bằng tiền mặt năm 2032 với tỷ lệ bao nhiêu?",
             "Số nhân viên của CT Group tại văn phòng Singapore năm 2033 là bao nhiêu?",
             "Ông Nguyễn Văn Thuận Phong giữ chức vụ gì trong CT Group?",
             "Bà Trần Thị Mộng Huyền được bổ nhiệm làm kế toán trưởng ngày nào?",
             "Hợp đồng số 999/2031/HĐ-XYZ có giá trị bao nhiêu?",
             "Lãi suất trái phiếu CT Group phát hành tại châu Âu năm 2034 là bao nhiêu?"]


def oos_questions(cur, rng: random.Random) -> list[dict]:
    qs = [f"{s[0].upper()}{s[1:]} {a}" for s in OOS_SUBJECTS for a in OOS_ASKS]
    rng.shuffle(qs)
    qs = OOS_OTHER + qs
    out = []
    for q in qs:
        if len(out) >= N_OOS:
            break
        # the distinctive name of the question must be nowhere in the data room
        key = next((s for s in OOS_SUBJECTS if s.lower() in q.lower()), None)
        names = [key.split(" ", 1)[1]] if key else re.findall(r"(?:Ông|Bà) ([^\s].+?) (?:giữ|được)|(\d{3}/\d{4}/HĐ-XYZ)|"
                                                              r"năm (20[3-9]\d)", q)
        probe = [n for t in names for n in ((t,) if isinstance(t, str) else t) if n]
        hit = any(cur.execute("SELECT 1 FROM chunks WHERE is_current AND text_folded LIKE %s LIMIT 1",
                              (f"%{fold_same_length(p)}%",)).fetchone() for p in probe)
        if not hit:
            out.append({"type": "oos", "user": FACT_USER, "question": q, "answer": "", "probe": probe})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(settings.data_dir / "mocktest" / "mocktest_500.jsonl"))
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    llm.warm()
    items: list[dict] = []
    used: set[str] = set()
    with pg.admin() as cur:
        print(f"== sự kiện (người hỏi {FACT_USER}), model {settings.llm_model}", flush=True)
        pool = candidates(cur, "c.item_id IN (SELECT item_id FROM item_reader WHERE oid = %s)", (FACT_USER,))
        by_kind: dict[str, list[dict]] = {}
        for row in pool:
            by_kind.setdefault(kind_of(row["ext"], row["kind"], row["ocr"]), []).append(row)
        for kind, want in QUOTA.items():
            items += [{"type": "fact", "user": FACT_USER, **r}
                      for r in draw(by_kind.get(kind, []), want, rng, used, kind)]

        print("== phân quyền", flush=True)
        per_user = N_PERM // len(PERM_USERS)
        for oid in PERM_USERS:
            hidden = candidates(cur, "c.item_id NOT IN (SELECT item_id FROM item_reader WHERE oid = %s)", (oid,))

            def keep(rec, oid=oid):
                # the figure must be checkable (≥3 digits or a name) and in no file the user may read
                if len(digits(rec["answer"])) < 3 and digits(rec["answer"]):
                    return None
                if readable_has(cur, oid, rec["answer"]) or readable_holds(cur, oid, rec["answer"]):
                    return None
                return {"type": "perm", "user": oid, **rec}
            items += draw(hidden, per_user, rng, used, f"quyền {oid}", keep)

        print("== ngoài phạm vi", flush=True)
        items += oos_questions(cur, rng)

    for n, it in enumerate(items, 1):
        it["id"] = f"MT{n:03d}"
    with out.open("w") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"\n{len(items)} câu → {out}")
    print(Counter((it["type"], it.get("kind", "")) for it in items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
