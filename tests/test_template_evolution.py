#!/usr/bin/env python3
"""Tests for template_evolution.py (thin wrapper over feedback_loop)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from template_evolution import analyze_template_effectiveness, evolve_report, suggest_improvements
from feedback_loop import record_task_outcome


def run_tests():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = tmp.name
    tmp.close()

    try:
        # Seed test data
        test_data = [
            ("t1", "coding", "opus", "clean code", "messy code", False, "missing imports"),
            ("t2", "coding", "opus", "clean code", "clean code", True, None),
            ("t3", "coding", "opus", "working tests", "tests fail", False, "wrong logic"),
            ("t4", "coding", "opus", "complete module", "partial module", False, "incomplete"),
            ("t5", "research", "minimax", "summary", "summary", True, None),
            ("t6", "research", "minimax", "analysis", "analysis", True, None),
        ]
        for tid, ttype, model, exp, act, success, notes in test_data:
            record_task_outcome(tid, ttype, model, exp, act, success, notes, db_path=db)

        # Test 1: analyze_template_effectiveness
        result = analyze_template_effectiveness("coding", db_path=db)
        assert isinstance(result, dict), "Should return dict"
        assert result["task_type"] == "coding"
        assert result["total"] == 4
        assert result["success"] == 1
        assert result["failure"] == 3
        assert 0 < result["success_rate"] < 0.5
        assert isinstance(result["common_failures"], list)
        assert isinstance(result["suggestions"], list)
        print("✓ Test 1: analyze_template_effectiveness works via wrapper")

        # Test 2: suggest_improvements (re-exported as suggest_improvements)
        suggestions = suggest_improvements("coding", db_path=db)
        assert isinstance(suggestions, list)
        assert len(suggestions) > 0
        print(f"✓ Test 2: suggest_improvements returned {len(suggestions)} suggestions")

        # Test 3: evolve_report
        report = evolve_report(db_path=db)
        assert "模板进化报告" in report
        assert "coding" in report
        assert "research" in report
        print("✓ Test 3: evolve_report generates valid markdown")

        # Test 4: no data case
        result_empty = analyze_template_effectiveness("nonexistent", db_path=db)
        assert result_empty["total"] == 0
        assert result_empty["success_rate"] == 0.0
        print("✓ Test 4: no data returns zeros gracefully")

        print("\nALL TESTS PASSED")

    finally:
        os.unlink(db)


if __name__ == "__main__":
    run_tests()
