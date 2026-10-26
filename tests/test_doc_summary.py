"""Summary of one document the user picks (BRD mục 3 #5, behind DR_DOC_SUMMARY), through the real API."""
import pytest

from dr.config import settings
from dr.core.answer import spread
from tests.test_api import client, login  # noqa: F401  (fixture)


def summarise(client, oid, item_id):
    return client.post("/api/chat", headers=login(client, oid),
                       json={"question": f"Tóm tắt tài liệu: {item_id}.txt", "item_id": item_id})


def test_off_by_default_phase_2(client):
    assert summarise(client, "inv-a1", "a1").status_code == 403
    assert client.get("/api/me", headers=login(client, "inv-a1")).json()["features"] == {"doc_summary": False}


@pytest.fixture()
def on(monkeypatch):
    monkeypatch.setattr(settings, "doc_summary", True)


def test_summary_reads_only_the_picked_document(client, on):
    r = summarise(client, "inv-a1", "a1").json()
    assert not r["refused"] and r["mode"] == "summary"
    assert r["citations"] and {c["item_id"] for c in r["citations"]} == {"a1"}
    assert any(s["step"] == "Đọc toàn bộ tài liệu được chọn (RLS)" for s in r["trace"])


def test_document_outside_the_ai_scope_is_not_summarised(client, on):
    for oid, item in (("inv-b1", "a1"), ("inv-a1", "i1"), ("staff-1", "x1"), ("inv-a1", "khong-co")):
        r = summarise(client, oid, item).json()
        assert r["refused"] and not r["citations"], (oid, item)


def test_spread_covers_beginning_middle_and_end():
    assert spread(range(100), 5) == [0, 25, 50, 74, 99]
    assert spread(range(3), 5) == [0, 1, 2]
    assert spread(range(10), 1) == [0]
