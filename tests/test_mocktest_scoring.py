"""The CT Group mock test's scorer (scripts/ctg_mocktest_eval.py): a perm question is a leak only when its figure
is in no file the asker may read, compared by value exactly as the scorer compares the reply."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ctg_mocktest_eval import holds, readable_holds  # noqa: E402

from dr.db import pg  # noqa: E402
from tests.test_gates import env  # noqa: E402,F401


def test_holds_compares_by_value():
    assert holds("1.250.000.000.000 đồng", "Doanh thu năm 2025 là 1.250 tỷ đồng.")
    assert holds("06 tháng", "thời hạn 6 tháng")
    assert not holds("25.400", "Doanh thu năm 2025 là 1.250 tỷ đồng.")


def test_perm_figure_also_in_a_readable_file_is_no_leak(env):
    with pg.admin() as cur:
        # 1.250 tỷ is in the shared report everyone reads, written another way: a string check missed it (MT357)
        assert readable_holds(cur, "inv-b1", "1.250.000.000.000 đồng")
        # group B's guarantee rate: inv-a1 may not read it, inv-b1 may
        assert not readable_holds(cur, "inv-a1", "25.400")
        assert readable_holds(cur, "inv-b1", "25.400")
