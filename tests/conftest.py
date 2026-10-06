import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Tests use their own database in the same local cluster.
os.environ.setdefault("DR_PG_DB", "dataroom_test")

from dr.db import pg  # noqa: E402


@pytest.fixture(scope="session")
def _cluster():
    pg.ensure_cluster()
    yield


@pytest.fixture()
def db(_cluster):
    pg.reset_all()
    yield
    pg.reset_all()
