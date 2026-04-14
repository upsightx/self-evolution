import unittest
from pathlib import Path


class TestLegacyEvolutionChangesReadersWhitelist(unittest.TestCase):
    def test_only_whitelisted_modules_touch_legacy_table(self):
        root = Path(__file__).resolve().parent / "modules"
        allowed = {
            "arch_audit.py",
            "proposal_lifecycle_manager.py",
            "learning_conversion.py",
            "causal_validator.py",
            "evolution_executor.py",
            "evolution_runtime.py",
        }

        offenders = []
        for path in root.glob("*.py"):
            if "evolution_changes" in path.read_text(encoding="utf-8") and path.name not in allowed:
                offenders.append(path.name)

        self.assertEqual(offenders, [], f"unexpected legacy-table readers: {offenders}")


if __name__ == "__main__":
    unittest.main()
