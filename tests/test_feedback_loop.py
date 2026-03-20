#!/usr/bin/env python3
"""Tests for feedback_loop.py"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from feedback_loop import (
    record_task_outcome, analyze_patterns, generate_template_improvements,
    get_task_history, analyze_template_effectiveness, evolve_report,
)


def run_tests():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = tmp.name
    tmp.close()

    try:
        test_data = [
            ("t1", "coding", "opus", "clean code", "messy code with missing imports", False, "missing imports"),
            ("t2", "coding", "opus", "clean code", "incomplete output truncated", False, "truncated result"),
            ("t3", "coding", "opus", "clean code", "clean code", True, None),
            ("t4", "coding", "opus", "working tests", "tests fail with error", False, "wrong logic"),
            ("t5", "coding", "opus", "complete module", "partial module missing functions", False, "incomplete"),
            ("t6", "coding", "opus", "documented code", "code without docs", False, "missing documentation"),
            ("t7", "summarize", "sonnet", "concise summary", "verbose rambling text", False, "too long"),
            ("t8", "summarize", "sonnet", "concise summary", "concise summary", True, None),
            ("t9", "summarize", "sonnet", "key points", "irrelevant extra details", False, "unexpected content"),
            ("t10", "summarize", "sonnet", "3 bullet points", "5 paragraphs", False, "format wrong"),
        ]

        for tid, ttype, model, exp, act, success, notes in test_data:
            rid = record_task_outcome(tid, ttype, model, exp, act, success, notes, db_path=db)
            assert rid is not None
        print("  [PASS] Inserted 10 mock records")

        # analyze_patterns
        patterns = analyze_patterns(min_samples=5, db_path=db)
        assert len(patterns) > 0
        coding_pattern = [p for p in patterns if p["task_type"] == "coding"]
        assert len(coding_pattern) == 1
        cp = coding_pattern[0]
        assert cp["failure_rate"] > 0.5
        assert cp["sample_count"] == 6
        print(f"  [PASS] analyze_patterns found pattern: {cp['pattern']} (failure_rate={cp['failure_rate']})")

        # generate_template_improvements
        imps = generate_template_improvements("coding", db_path=db)
        assert len(imps) > 0
        print(f"  [PASS] generate_template_improvements returned {len(imps)} suggestions")

        imps2 = generate_template_improvements("summarize", db_path=db)
        assert len(imps2) > 0
        print(f"  [PASS] summarize improvements: {len(imps2)} suggestions")

        # history
        all_hist = get_task_history(db_path=db)
        assert len(all_hist) == 10
        coding_hist = get_task_history(task_type="coding", db_path=db)
        assert len(coding_hist) == 6
        limited = get_task_history(limit=3, db_path=db)
        assert len(limited) == 3
        print("  [PASS] history query and filtering works correctly")

        # gap_analysis
        for r in all_hist:
            assert r["gap_analysis"] is not None
        print("  [PASS] gap_analysis computed for all records")

        # edge case
        empty_imps = generate_template_improvements("nonexistent", db_path=db)
        assert empty_imps == []
        print("  [PASS] edge case: no failures returns empty list")

        # analyze_template_effectiveness (merged from template_evolution)
        result = analyze_template_effectiveness("coding", db_path=db)
        assert result["total"] == 6
        assert result["success"] == 1
        assert result["failure"] == 5
        assert result["success_rate"] < 0.3
        assert len(result["common_failures"]) > 0
        assert len(result["suggestions"]) > 0
        print(f"  [PASS] analyze_template_effectiveness: rate={result['success_rate']:.0%}")

        # evolve_report
        report = evolve_report(db_path=db)
        assert "模板进化报告" in report
        assert "coding" in report
        print("  [PASS] evolve_report generates valid markdown")

        print("\nALL TESTS PASSED")

    finally:
        os.unlink(db)


if __name__ == "__main__":
    run_tests()
