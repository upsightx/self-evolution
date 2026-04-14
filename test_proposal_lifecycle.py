import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import proposal_lifecycle_manager as plm


class TestProposalLifecycleManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "proposal-test.db"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _get_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evolution_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT,
                entity_id TEXT,
                detail TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
        return conn

    def test_create_and_transition_use_proposals_table(self):
        with patch.object(plm, "get_db", side_effect=self._get_db), \
             patch.object(plm, "_log_event"):
            created = plm.create_proposal(
                proposal_id="prop_test_001",
                title="Test Proposal",
                summary="Summary",
                initial_status="draft",
            )
            self.assertTrue(created["success"])

            advanced = plm.transition("prop_test_001", "pending_review", actor="test")
            self.assertTrue(advanced["success"])

            proposal = plm.get_proposal("prop_test_001")
            self.assertEqual(proposal["status"], "pending_review")
            self.assertEqual(len(proposal["transitions"]), 2)

            db = self._get_db()
            try:
                rows = db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
                self.assertEqual(rows, 1)
            finally:
                db.close()

    def test_invalid_transition_is_rejected(self):
        with patch.object(plm, "get_db", side_effect=self._get_db), \
             patch.object(plm, "_log_event"):
            plm.create_proposal(
                proposal_id="prop_test_002",
                title="Test Proposal",
                summary="Summary",
                initial_status="draft",
            )
            result = plm.transition("prop_test_002", "released", actor="test")
            self.assertFalse(result["success"])
            self.assertIn("Invalid transition", result["message"])


if __name__ == "__main__":
    unittest.main()
