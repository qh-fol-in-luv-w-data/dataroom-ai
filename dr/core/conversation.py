"""Conversation context: follow-up questions and "summarise what we discussed".

Turns are kept on the server, per (user, conversation id), never taken from the browser: a client
could otherwise plant a fake earlier answer. A turn stores the question as asked, the standalone
question that was searched, the answer text and the chunk ids it cited.

- Follow-up ("còn dự án kia thì sao?", "nói rõ hơn ý 2"): the question is rewritten into a standalone
  one from the last turns, and the chunks those turns cited join the search candidates.
- Recap ("tổng hợp lại", "tóm tắt cuộc trò chuyện"): the chunks cited in this conversation are read
  again through the normal path (RLS, live check, LLM, verification), so a file the user lost
  access to in the meantime drops out of the recap like it would from any answer.
"""
from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from unidecode import unidecode

MAX_TURNS = 8          # kept per conversation
CONTEXT_TURNS = 3      # shown to the rewriter
TTL_SECONDS = 6 * 3600
MAX_CONVERSATIONS = 5000


@dataclass
class Turn:
    question: str
    standalone: str
    answer: str
    chunk_ids: list[int] = field(default_factory=list)
    t: float = field(default_factory=time.time)


_lock = threading.Lock()
_store: "OrderedDict[tuple[str, str], list[Turn]]" = OrderedDict()


def history(oid: str, conv_id: str | None) -> list[Turn]:
    if not conv_id:
        return []
    with _lock:
        turns = _store.get((oid, conv_id), [])
        return [t for t in turns if time.time() - t.t < TTL_SECONDS]


def remember(oid: str, conv_id: str | None, question: str, result: dict) -> None:
    """Record an answered turn (refusals are not context: nothing was shown from documents)."""
    if not conv_id or result.get("refused") or result.get("pending_review"):
        return
    turn = Turn(question=question, standalone=result.get("standalone_question") or question,
                answer="\n".join(c["text"] for c in result.get("claims", [])),
                chunk_ids=[c["chunk_id"] for c in result.get("citations", []) if c.get("chunk_id") is not None])
    with _lock:
        key = (oid, conv_id)
        turns = _store.pop(key, [])
        turns = (turns + [turn])[-MAX_TURNS:]
        _store[key] = turns
        while len(_store) > MAX_CONVERSATIONS:
            _store.popitem(last=False)


def forget(oid: str, conv_id: str) -> None:
    with _lock:
        _store.pop((oid, conv_id), None)


# ------------------------------------------------------------------ what kind of turn
_RECAP = re.compile(
    r"\b(tong hop|tom tat|tom luoc|tom) lai\b|\btom lai\b|"
    r"\b(tong hop|tom tat|nhac lai)\b.{0,30}\b(cuoc (tro chuyen|hoi thoai)|(da|vua) (hoi|trao doi|noi|tra loi)|"
    r"o tren|nay gio|tu dau|cac cau (hoi|tra loi))|"
    r"\brecap\b|\bsum+ari[sz]e\b.{0,25}\b(conversation|chat|discussion|so far|above)\b|what (we|i) (discussed|asked)",
)
# words that only make sense with an earlier turn ("it", "that project", "point 2", "and the other one?")
_FOLLOW = re.compile(
    r"\b(no|do|nay|kia|ay|tren|vua roi|luc nay|nhu vay|the con|con .{1,40} thi sao|thi sao|"
    r"chi tiet hon|ro hon|cu the hon|giai thich them|them nua|y (thu )?\d|cai (dau|thu \d|cuoi)|"
    r"du an (do|nay|kia|tren)|cong ty (do|nay|kia|tren)|file (do|nay|kia|tren)|tai lieu (do|nay|kia|tren))\b|"
    r"\b(it|its|that|those|these|they|them|the other|more detail|elaborate|what about|and the)\b",
)


def is_recap(question: str) -> bool:
    return bool(_RECAP.search(unidecode(question).lower()))


def needs_context(question: str) -> bool:
    q = unidecode(question).lower()
    return bool(_FOLLOW.search(q)) or len(re.findall(r"\w+", q)) <= 4


def context_text(turns: list[Turn]) -> str:
    """The last turns as the rewriter sees them (answers trimmed: it only needs the topic)."""
    out = []
    for k, t in enumerate(turns[-CONTEXT_TURNS:], 1):
        out.append(f"Lượt {k} – Hỏi: {t.standalone}\nLượt {k} – Đáp: {t.answer[:400]}")
    return "\n".join(out)


def cited_chunks(turns: list[Turn], last: int | None = None) -> list[int]:
    seen, out = set(), []
    for t in (turns[-last:] if last else turns):
        for c in t.chunk_ids:
            if c not in seen:
                seen.add(c)
                out.append(c)
    return out
