import pytest

from dr import audit
from dr.config import NEUTRAL_REFUSAL
from dr.connector.sync import Connector
from dr.core import answer
from dr.core.index import SearchIndex
from dr.core.pgindex import PgSearchIndex, tsv_literal
from dr.db import pg
from dr.ingest.chunker import fold
from dr.tenant.service import FakeTenant
from tests.mini_tenant import Clock, make_tenant


def stub_llm(question, passages):
    """Quote the first passage verbatim (first 40 chars)."""
    labels = {f"D{i}": p["chunk_id"] for i, p in enumerate(passages, start=1)}
    q = passages[0]["text"][:40]
    return {"claims": [{"text": "Theo tài liệu: " + q.split(".")[0], "citations": [{"doc": "D1", "quote": q}]}],
            "no_answer": False}, labels


DEPS = answer.Deps(embed_query=None, rerank=None, llm=stub_llm, nli=None)


@pytest.fixture(params=["memory", "pg"])
def env(db, tmp_path, request):
    """Every gate test runs against both search engines: the in-memory index (fed with
    RLS-allowed ids) and the in-database one (RLS inside the search query)."""
    clock = Clock()
    tenant = FakeTenant(make_tenant(tmp_path), group_lag=60)  # real clock for feed ages
    conn = Connector(tenant)
    conn.full_resync()
    with pg.admin() as c:
        for iid, site, ctag in c.execute("SELECT item_id, site_id, ctag FROM items").fetchall():
            text = tenant.download(iid).decode()
            c.execute("INSERT INTO chunks(item_id, site_id, ctag, ordinal, locator, text, text_folded, converter, "
                      "tsv, tlen) VALUES (%s,%s,%s,0,'Đầu văn bản',%s,%s,'text',%s::tsvector,%s)",
                      (iid, site, ctag, text, fold(text), *tsv_literal(text)))
            c.execute("UPDATE items SET status='indexed', chunk_count=1 WHERE item_id=%s", (iid,))
        c.commit()
    ix = SearchIndex() if request.param == "memory" else PgSearchIndex()
    ix.refresh()
    return tenant, conn, ix


def items_cited(res):
    return {c["item_id"] for c in res["citations"]}


def test_group_a_question(env):
    tenant, _, ix = env
    res = answer.ask(tenant, ix, "inv-a1", ["Investor.AI"], "phí thu xếp nhóm A", DEPS)
    assert not res["refused"] and items_cited(res) <= {"a1", "a2", "c1"}


def test_b_cannot_get_a(env):
    tenant, _, ix = env
    res = answer.ask(tenant, ix, "inv-b1", ["Investor.AI"], "phí thu xếp nhóm A KS-GRPA-0001", DEPS)
    assert not items_cited(res) & {"a1", "a2", "i1"}


def test_no_role_refused(env):
    tenant, _, ix = env
    res = answer.ask(tenant, ix, "inv-noai", [], "doanh thu 2025", DEPS)
    assert res["refused"] and "chưa được cấp quyền" in res["message"]


def test_corrupted_mirror_blocked_by_live_check(env):
    tenant, _, ix = env
    with pg.admin() as c:  # inject a fake grant into the mirror: B can "read" A's file
        c.execute("INSERT INTO item_reader VALUES ('a1','inv-b1','group','FAKE')")
        c.commit()
    res = answer.ask(tenant, ix, "inv-b1", ["Investor.AI"], "Thỏa thuận nhóm A phí thu xếp", DEPS)
    assert "a1" not in items_cited(res)
    step = next(s for s in res["trace"] if s["step"].startswith("Cổng 2"))
    assert step["dropped"] >= 1


def test_stale_feed_refused(env):
    tenant, _, ix = env
    with pg.admin() as c:
        c.execute("UPDATE feed_status SET last_ok = now() - interval '10 minutes' WHERE feed='entra'")
        c.commit()
    res = answer.ask(tenant, ix, "inv-a1", ["Investor.AI"], "doanh thu", DEPS)
    assert res["refused"]


def test_excluded_never_used(env):
    tenant, _, ix = env
    res = answer.ask(tenant, ix, "inv-a1", ["Investor.AI"], "Tài liệu bị loại khỏi AI KS-COMMON-0002", DEPS)
    assert "x1" not in items_cited(res)


def test_focused_retry_when_llm_finds_nothing(env, monkeypatch):
    tenant, _, ix = env
    calls = []

    def picky_llm(question, passages):
        calls.append(len(passages))
        if len(passages) > 2:          # simulates a small model lost in many passages
            return {"claims": [], "no_answer": True}, {}
        return stub_llm(question, passages)

    monkeypatch.setattr(answer, "FOCUSED_PASSAGES", 2)
    res = answer.ask(tenant, ix, "staff-1", ["Staff.AI"], "thỏa thuận phí thu xếp cam kết bảo lãnh",
                     answer.Deps(llm=picky_llm))
    assert calls[0] > 2 and calls[-1] == 2
    assert not res["refused"]


def test_audit_chain_and_tamper(env):
    tenant, _, ix = env
    for q in ("doanh thu", "phí thu xếp", "bảo lãnh"):
        answer.ask(tenant, ix, "inv-ab", ["Investor.AI"], q, DEPS)
    assert audit.verify()["ok"]
    with pg.admin() as c:
        c.execute("UPDATE audit SET payload = jsonb_set(payload, '{question}', '\"sửa\"') WHERE seq=2")
        c.commit()
    v = audit.verify()
    assert not v["ok"] and v["first_bad_seq"] == 2
