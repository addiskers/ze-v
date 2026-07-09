"""Test bootstrap: isolate DATA_DIR to a temp dir BEFORE any app module is imported
(store.py / eo_db.py resolve their paths at import time), and put the app dir on
sys.path so tests import modules exactly like the app does."""

import os
import sys
import tempfile

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# Never let tests touch a real data dir.
_TMP_DATA = tempfile.mkdtemp(prefix="eo-tests-data-")
os.environ["DATA_DIR"] = _TMP_DATA

import pytest  # noqa: E402


@pytest.fixture()
def fresh_eo_db(tmp_path, monkeypatch):
    """A brand-new eo.db for this test only; restores the module connection after."""
    import eo_db
    old_conn, old_path = eo_db._conn, eo_db._DB_PATH
    if old_conn is not None:
        try:
            old_conn.close()
        except Exception:
            pass
    monkeypatch.setattr(eo_db, "_DB_PATH", str(tmp_path / "eo.db"))
    eo_db._conn = None
    yield eo_db
    if eo_db._conn is not None:
        try:
            eo_db._conn.close()
        except Exception:
            pass
    eo_db._conn = None
    eo_db._DB_PATH = old_path
