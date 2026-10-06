import psycopg
import pytest

from dr.config import settings
from dr.db import pg


@pytest.fixture()
def two_items(db):
    with pg.admin() as c:
        for i in ("it1", "it2"):
            c.execute("INSERT INTO items(item_id, site_id, path, name, ext, ctag, etag, ai_use) "
                      "VALUES (%s,'S','/x',%s,'txt','c1','e1','Allowed')", (i, i))
            c.execute("INSERT INTO chunks(item_id, site_id, ctag, ordinal, locator, text, text_folded, converter) "
                      "VALUES (%s,'S','c1',0,'p1','secret '||%s,'secret','test')", (i, i))
        c.execute("INSERT INTO item_reader VALUES ('it1','u1','group','G')")
        c.commit()


def test_unknown_principal_sees_nothing(two_items):
    with pg.as_principal("nobody") as cur:
        assert cur.execute("SELECT count(*) FROM items").fetchone()[0] == 0
        assert cur.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0


def test_principal_sees_only_granted(two_items):
    with pg.as_principal("u1") as cur:
        assert [r[0] for r in cur.execute("SELECT item_id FROM items")] == ["it1"]
        assert [r[0] for r in cur.execute("SELECT text FROM chunks")] == ["secret it1"]


def test_no_identity_sees_nothing(two_items):
    with pg.as_principal(None) as cur:
        assert cur.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0


def test_app_query_cannot_read_memberships(db):
    with psycopg.connect(settings.dsn("app_query")) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM memberships")


def test_excluded_or_stale_chunks_hidden(two_items):
    with pg.admin() as c:
        c.execute("UPDATE items SET ai_use='Excluded' WHERE item_id='it1'")
        c.commit()
    with pg.as_principal("u1") as cur:
        assert cur.execute("SELECT count(*) FROM items").fetchone()[0] == 1  # still visible as an item
        assert cur.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0  # but not to the AI
    with pg.admin() as c:
        c.execute("UPDATE items SET ai_use='Allowed', ctag='c2' WHERE item_id='it1'")
        c.commit()
    with pg.as_principal("u1") as cur:
        assert cur.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0  # old version
