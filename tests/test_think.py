"""DR_THINK: qwen3 reasons before answering only for the answer styles it names."""
import json

from dr.config import settings
from dr.models import llm


class _Resp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": json.dumps({"claims": [], "no_answer": True}), "thinking": "…"}}


def _sent(monkeypatch, think: str, style: str) -> dict:
    seen = {}

    def post(url, timeout, json):
        seen.update(json)
        seen["_timeout"] = timeout
        return _Resp(json)
    monkeypatch.setattr(llm.httpx, "post", post)
    monkeypatch.setattr(settings, "think", think)
    monkeypatch.setattr(settings, "answer_cache", 0)
    llm.answer_json("Giá căn 2PN là bao nhiêu?", [{"chunk_id": 1, "text": "Căn 2PN giá 2,1 tỷ.", "source": "x"}],
                    style=style)
    return seen


def test_thinking_only_for_the_named_styles(monkeypatch):
    off = _sent(monkeypatch, "", "fact")
    assert off["think"] is False
    on = _sent(monkeypatch, "fact,multi", "fact")
    assert on["think"] is True and on["options"]["num_predict"] > off["options"]["num_predict"]
    assert on["_timeout"] > off["_timeout"]
    assert _sent(monkeypatch, "fact", "summary")["think"] is False


def test_memo_keeps_thinking_and_plain_answers_apart(monkeypatch):
    p = [{"chunk_id": 1, "text": "Căn 2PN giá 2,1 tỷ.", "source": "x"}]
    monkeypatch.setattr(settings, "think", "")
    plain = llm._key("summary:fact:3", "q", p, "vi")
    monkeypatch.setattr(settings, "think", "fact")
    assert llm._key("summary:fact:3", "q", p, "vi") != plain
