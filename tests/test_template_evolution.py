#!/usr/bin/env python3
"""Tests for template_evolution.py — at least 12 tests."""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure we can import the module
import sys
sys.path.insert(0, str(Path(__file__).parent))

import template_evolution as te


class _TempDBMixin:
    """Mixin that sets up a temp DB with task_outcomes table and patches DB_PATH."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db_path = Path(self._tmp.name)

        # Create schema
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                task_type TEXT NOT NULL,
                model TEXT,
                expected TEXT,
                actual TEXT,
                success INTEGER NOT NULL,
                gap_analysis TEXT,
                notes TEXT,
                timestamp TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()

        # Patch DB_PATH
        self._db_patcher = patch.object(te, 'DB_PATH', self._db_path)
        self._db_patcher.start()

    def tearDown(self):
        self._db_patcher.stop()
        os.unlink(self._tmp.name)

    def _insert_outcomes(self, rows):
        """Insert rows: list of (task_type, success, gap_analysis, notes)."""
        conn = sqlite3.connect(str(self._db_path))
        for task_type, success, gap, notes in rows:
            conn.execute(
                "INSERT INTO task_outcomes (task_type, success, gap_analysis, notes) VALUES (?,?,?,?)",
                (task_type, int(success), gap, notes),
            )
        conn.commit()
        conn.close()


class TestAnalyzeTemplateEffectiveness(_TempDBMixin, unittest.TestCase):
    """Tests for analyze_template_effectiveness."""

    def test_returns_correct_format(self):
        """analyze returns dict with all required keys."""
        # Patch stats file to have some data
        fake_stats = {"stats": {"by_task_type": {"coding": {"total": 5, "success": 4, "fail": 1}}}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            result = te.analyze_template_effectiveness("coding")

        self.assertIsInstance(result, dict)
        required_keys = {"task_type", "total", "success", "failure", "success_rate", "common_failures", "suggestions"}
        self.assertEqual(set(result.keys()), required_keys)
        self.assertEqual(result["task_type"], "coding")

    def test_success_rate_calculation(self):
        """Success rate is correctly computed."""
        fake_stats = {"stats": {"by_task_type": {"coding": {"total": 10, "success": 8, "fail": 2}}}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            result = te.analyze_template_effectiveness("coding")

        self.assertEqual(result["total"], 10)
        self.assertEqual(result["success"], 8)
        self.assertEqual(result["failure"], 2)
        self.assertAlmostEqual(result["success_rate"], 0.8, places=2)

    def test_merges_stats_and_db(self):
        """Merges data from agent-stats.json and DB, taking the larger counts."""
        # Stats says 5 total, DB has 8 rows
        fake_stats = {"stats": {"by_task_type": {"coding": {"total": 5, "success": 4, "fail": 1}}}}
        self._insert_outcomes([
            ("coding", True, None, None),
            ("coding", True, None, None),
            ("coding", True, None, None),
            ("coding", True, None, None),
            ("coding", True, None, None),
            ("coding", True, None, None),
            ("coding", False, "missing imports", "依赖缺失"),
            ("coding", False, "timeout", "超时了"),
        ])
        with patch.object(te, '_load_stats', return_value=fake_stats):
            result = te.analyze_template_effectiveness("coding")

        # DB has 8 total (6 success, 2 fail) > stats 5 total
        self.assertEqual(result["total"], 8)
        self.assertEqual(result["success"], 6)
        self.assertEqual(result["failure"], 2)

    def test_no_data_graceful(self):
        """Returns zeros and empty lists when no data exists."""
        fake_stats = {"stats": {"by_task_type": {}}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            result = te.analyze_template_effectiveness("nonexistent")

        self.assertEqual(result["total"], 0)
        self.assertEqual(result["success"], 0)
        self.assertEqual(result["failure"], 0)
        self.assertEqual(result["success_rate"], 0.0)
        self.assertEqual(result["common_failures"], [])

    def test_extracts_failure_reasons_from_db(self):
        """Common failures are extracted from gap_analysis and notes."""
        self._insert_outcomes([
            ("coding", False, "timeout slow", "超时了"),
            ("coding", False, "format wrong", "格式错误"),
            ("coding", True, None, None),
        ])
        fake_stats = {"stats": {"by_task_type": {}}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            result = te.analyze_template_effectiveness("coding")

        self.assertIn("超时", result["common_failures"])
        self.assertIn("格式错误", result["common_failures"])


class TestSuggestImprovements(_TempDBMixin, unittest.TestCase):
    """Tests for suggest_improvements."""

    def test_low_success_rate_suggests_split(self):
        """Success rate < 0.7 triggers split suggestion."""
        # 10 tasks, 5 success, 5 fail → 50%
        self._insert_outcomes([("coding", i < 5, None, None) for i in range(10)])
        fake_stats = {"stats": {"by_task_type": {"coding": {"total": 10, "success": 5, "fail": 5}}}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            suggestions = te.suggest_improvements("coding")

        self.assertTrue(any("拆分" in s for s in suggestions))

    def test_timeout_failure_suggests_time_constraint(self):
        """Timeout failures trigger time constraint suggestion."""
        self._insert_outcomes([
            ("coding", False, "timeout", "超时"),
            ("coding", True, None, None),
        ])
        fake_stats = {"stats": {"by_task_type": {}}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            suggestions = te.suggest_improvements("coding")

        self.assertTrue(any("5分钟" in s for s in suggestions))

    def test_format_failure_suggests_format_spec(self):
        """Format errors trigger format specification suggestion."""
        self._insert_outcomes([
            ("coding", False, "format wrong", "格式错误"),
            ("coding", True, None, None),
        ])
        fake_stats = {"stats": {"by_task_type": {}}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            suggestions = te.suggest_improvements("coding")

        self.assertTrue(any("格式" in s for s in suggestions))

    def test_dependency_failure_suggests_listing_deps(self):
        """Dependency missing triggers dependency listing suggestion."""
        self._insert_outcomes([
            ("coding", False, "missing imports", "依赖缺失"),
            ("coding", True, None, None),
        ])
        fake_stats = {"stats": {"by_task_type": {}}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            suggestions = te.suggest_improvements("coding")

        self.assertTrue(any("依赖" in s for s in suggestions))

    def test_file_not_found_suggests_path_check(self):
        """File not found triggers path verification suggestion."""
        self._insert_outcomes([
            ("coding", False, "file not_found", "文件未找到"),
            ("coding", True, None, None),
        ])
        fake_stats = {"stats": {"by_task_type": {}}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            suggestions = te.suggest_improvements("coding")

        self.assertTrue(any("路径" in s for s in suggestions))

    def test_high_success_many_constraints_suggests_simplify(self):
        """High success rate + many constraints suggests simplification."""
        # All success
        self._insert_outcomes([("coding", True, None, None) for _ in range(20)])
        fake_stats = {"stats": {"by_task_type": {"coding": {"total": 20, "success": 20, "fail": 0}}}}
        # Mock constraint count > 5
        with patch.object(te, '_load_stats', return_value=fake_stats), \
             patch.object(te, '_count_template_constraints', return_value=8):
            suggestions = te.suggest_improvements("coding")

        self.assertTrue(any("精简" in s for s in suggestions))

    def test_no_data_returns_no_data_message(self):
        """No data returns a helpful message."""
        fake_stats = {"stats": {"by_task_type": {}}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            suggestions = te.suggest_improvements("nonexistent")

        self.assertEqual(len(suggestions), 1)
        self.assertIn("无历史数据", suggestions[0])

    def test_not_executed_suggests_force_prompt(self):
        """'未执行' failure triggers force-execution suggestion."""
        self._insert_outcomes([
            ("coding", False, "no_result", "只输出意图没写代码"),
            ("coding", True, None, None),
        ])
        fake_stats = {"stats": {"by_task_type": {}}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            suggestions = te.suggest_improvements("coding")

        self.assertTrue(any("立即开始" in s or "强制执行" in s for s in suggestions))


class TestEvolveReport(_TempDBMixin, unittest.TestCase):
    """Tests for evolve_report."""

    def test_returns_markdown(self):
        """Report is valid Markdown with expected headers."""
        fake_stats = {"stats": {"by_task_type": {
            "coding": {"total": 5, "success": 4, "fail": 1},
            "research": {"total": 3, "success": 3, "fail": 0},
        }}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            report = te.evolve_report()

        self.assertIsInstance(report, str)
        self.assertIn("# 模板进化报告", report)
        self.assertIn("## 总览", report)
        self.assertIn("## 详细分析", report)
        self.assertIn("### coding", report)
        self.assertIn("### research", report)

    def test_report_includes_table(self):
        """Report includes a summary table."""
        fake_stats = {"stats": {"by_task_type": {
            "coding": {"total": 10, "success": 8, "fail": 2},
        }}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            report = te.evolve_report()

        self.assertIn("| 任务类型 |", report)
        self.assertIn("| coding |", report)

    def test_empty_report(self):
        """Report handles no data gracefully."""
        fake_stats = {"stats": {"by_task_type": {}}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            report = te.evolve_report()

        self.assertIn("暂无任务数据", report)

    def test_report_includes_suggestions_for_failures(self):
        """Report includes suggestions when there are failures."""
        self._insert_outcomes([
            ("coding", False, "timeout", "超时"),
            ("coding", False, "format wrong", "格式错误"),
            ("coding", True, None, None),
        ])
        fake_stats = {"stats": {"by_task_type": {"coding": {"total": 3, "success": 1, "fail": 2}}}}
        with patch.object(te, '_load_stats', return_value=fake_stats):
            report = te.evolve_report()

        self.assertIn("改进建议", report)


class TestHelpers(unittest.TestCase):
    """Tests for internal helper functions."""

    def test_extract_failure_reasons_empty(self):
        """Empty outcomes returns empty list."""
        self.assertEqual(te._extract_failure_reasons([]), [])

    def test_extract_failure_reasons_all_success(self):
        """All-success outcomes returns empty list."""
        outcomes = [{"success": 1, "gap_analysis": None, "notes": None}]
        self.assertEqual(te._extract_failure_reasons(outcomes), [])

    def test_load_stats_missing_file(self):
        """Missing stats file returns empty dict."""
        with patch.object(te, 'STATS_PATH', Path("/nonexistent/path.json")):
            result = te._load_stats()
        self.assertEqual(result, {})


class TestCLI(_TempDBMixin, unittest.TestCase):
    """Tests for CLI entry points."""

    def test_cli_analyze(self):
        """CLI analyze outputs valid JSON."""
        fake_stats = {"stats": {"by_task_type": {"coding": {"total": 5, "success": 4, "fail": 1}}}}
        with patch.object(te, '_load_stats', return_value=fake_stats), \
             patch('sys.argv', ['template_evolution.py', 'analyze', 'coding']):
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                te.main()
            output = buf.getvalue()
            data = json.loads(output)
            self.assertEqual(data["task_type"], "coding")

    def test_cli_report(self):
        """CLI report outputs markdown."""
        fake_stats = {"stats": {"by_task_type": {"coding": {"total": 3, "success": 2, "fail": 1}}}}
        with patch.object(te, '_load_stats', return_value=fake_stats), \
             patch('sys.argv', ['template_evolution.py', 'report']):
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                te.main()
            output = buf.getvalue()
            self.assertIn("模板进化报告", output)


if __name__ == "__main__":
    unittest.main()
