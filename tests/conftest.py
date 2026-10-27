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


@pytest.fixture(autouse=True)
def _ocr_accents_without_db():
    """OCR tone-mark correction learns from the database's typed chunks; tests that do not set up a room
    start it with nothing learned (no correction) instead of reaching for a database."""
    from dr.ingest import ocr_accents
    ocr_accents.learn([])
    yield
    ocr_accents.reset()


@pytest.fixture()
def db(_cluster):
    pg.reset_all()
    yield
    pg.reset_all()
