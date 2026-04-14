import unittest
from pathlib import Path


class TestLegacyEvolutionChangesReadonly(unittest.TestCase):
    def test_no_writes_to_legacy_table_outside_migration_paths(self):
        root = Path(__file__).resolve().parent / "modules"
        forbidden = (
            "INSERT INTO evolution_changes",
            "UPDATE evolution_changes",
            "DELETE FROM evolution_changes",
        )
        allowed = {
            root / "proposal_lifecycle_manager.py",
            root / "arch_audit.py",
            root / "causal_validator.py",
            root / "evolution_executor.py",
            root / "evolution_runtime.py",
        }

        hits = []
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    hits.append(f"{path.name}: {token}")

        self.assertEqual(hits, [], f"legacy evolution_changes must stay read-only: {hits}")


if __name__ == "__main__":
    unittest.main()
