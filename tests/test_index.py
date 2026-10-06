import numpy as np

from dr.core.index import SearchIndex, tokens


def _vec(seed):
    v = np.random.default_rng(seed).normal(size=8).astype(np.float32)
    return v / np.linalg.norm(v)


ROWS = [
    (1, "a1", "GRP-A", "Phí thu xếp cho nhóm quỹ trong nước là 0,85%", _vec(1)),
    (2, "a2", "GRP-A", "Cam kết lock-up 12 tháng đối với cổ đông", _vec(2)),
    (3, "b1", "GRP-B", "Phí thu xếp cho quỹ ngoại được miễn", _vec(3)),
    (4, "c1", "COMMON", "Doanh thu năm 2025 đạt 1.250,5 tỷ đồng", _vec(4)),
]


def test_never_returns_disallowed_ids():
    ix = SearchIndex()
    ix.build(ROWS)
    res = ix.search({1, 4}, "phí thu xếp", _vec(3))
    assert {c for c, _ in res} <= {1, 4}
    assert res[0][0] == 1


def test_unaccented_query_matches():
    ix = SearchIndex()
    ix.build(ROWS)
    assert ix.search({1, 2, 3, 4}, "doanh thu nam 2025")[0][0] == 4


def test_partition_statistics_isolated():
    ix = SearchIndex()
    ix.build(ROWS)
    before = ix.parts["GRP-A"].bm25.idf.copy()
    ix.build(ROWS + [(5, "b2", "GRP-B", "phí thu xếp phí thu xếp phí", _vec(5))])
    assert ix.parts["GRP-A"].bm25.idf == before


def test_tokens():
    assert "phi_thu" in tokens("Phí thu xếp")
