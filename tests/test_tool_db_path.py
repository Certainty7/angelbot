"""Audit finding 20a: operator tools must read the configured database.

`metrics.py`, `audit_map.py` and `recall_probe.py` hardcoded `chat_history.db` in the repo root,
so an operator with `ANGEL_DB_PATH` set inspected a different file than the bot writes — and
reported numbers for a database that had stopped moving.
"""

import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class ToolDbPathTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="angel_dbpath_")
        self.db = os.path.join(self.dir, "sentinel.db")
        con = sqlite3.connect(self.db)
        con.execute("create table sentinel_marker (id integer)")
        con.commit()
        con.close()
        self._old = os.environ.get("ANGEL_DB_PATH")
        os.environ["ANGEL_DB_PATH"] = self.db
        for name in ("tools.metrics", "tools.audit_map", "tools.recall_probe"):
            sys.modules.pop(name, None)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ANGEL_DB_PATH", None)
        else:
            os.environ["ANGEL_DB_PATH"] = self._old
        for name in ("tools.metrics", "tools.audit_map", "tools.recall_probe"):
            sys.modules.pop(name, None)

    def test_metrics_reads_the_configured_database(self):
        module = importlib.import_module("tools.metrics")
        self.assertEqual(str(module.DB), self.db)

    def test_audit_map_scans_the_configured_database(self):
        module = importlib.import_module("tools.audit_map")
        tables = [name for name, _ in module.scan_tables()]
        self.assertIn("sentinel_marker", tables)

    def test_recall_probe_copies_the_configured_database(self):
        module = importlib.import_module("tools.recall_probe")
        self.assertEqual(module.source_db_path(), self.db)


if __name__ == "__main__":
    unittest.main()
