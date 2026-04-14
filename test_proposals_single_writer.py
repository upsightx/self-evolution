import unittest
from pathlib import Path


class TestProposalsSingleWriter(unittest.TestCase):
    def test_only_lifecycle_manager_writes_proposals_tables(self):
        root = Path(__file__).resolve().parent / "modules"
        forbidden = (
            "INSERT INTO proposals",
            "UPDATE proposals",
            "DELETE FROM proposals",
            "INSERT INTO proposal_transitions",
            "UPDATE proposal_transitions",
            "DELETE FROM proposal_transitions",
            "INSERT INTO proposal_evidence",
            "UPDATE proposal_evidence",
            "DELETE FROM proposal_evidence",
        )
        allowed_writer = root / "proposal_lifecycle_manager.py"

        hits = []
        for path in root.glob("*.py"):
            if path == allowed_writer:
                continue
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    hits.append(f"{path.name}: {token}")

        self.assertEqual(hits, [], f"proposal tables must have a single writer: {hits}")


if __name__ == "__main__":
    unittest.main()
