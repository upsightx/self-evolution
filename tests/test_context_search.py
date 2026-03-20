#!/usr/bin/env python3
"""Tests for search_with_context and search_with_metadata."""

import os
import sys
import tempfile
import unittest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Use a temp DB for tests
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_path = _tmp.name
_tmp.close()
os.environ["SELF_EVOLUTION_DB"] = _tmp_path

import memory_db


def setUpModule():
    memory_db.init_db()
    # Seed some test data
    memory_db.add_observation("discovery", "AI Agent Architecture", narrative="Discovered new patterns for agent design")
    memory_db.add_observation("change", "Memory System Update", narrative="Updated memory system to use SQLite")
    memory_db.add_observation("bugfix", "FTS5 Search Fix", narrative="Fixed FTS5 search for CJK content")
    memory_db.add_decision("Use SQLite", "Chose SQLite over Postgres", ["PostgreSQL", "JSON files"], "Simple and portable")
    memory_db.add_decision("Python over Node", "Use Python for scripts", ["Node.js"], "Better ML ecosystem")


def tearDownModule():
    os.unlink(_tmp_path)


class TestSearchWithContext(unittest.TestCase):
    def test_returns_string(self):
        result = memory_db.search_with_context("AI")
        self.assertIsInstance(result, str)

    def test_empty_query_returns_string(self):
        result = memory_db.search_with_context("xyznonexistent999")
        self.assertIsInstance(result, str)

    def test_format_has_date_headers(self):
        result = memory_db.search_with_context("AI")
        if result:
            self.assertIn("---", result)

    def test_format_has_type_brackets(self):
        result = memory_db.search_with_context("AI")
        if result:
            self.assertIn("[", result)

    def test_max_chars_truncation(self):
        result = memory_db.search_with_context("AI", max_chars=100)
        self.assertLessEqual(len(result), 103)  # +3 for "..."

    def test_max_chars_respected_with_large_query(self):
        result = memory_db.search_with_context("", max_chars=500)
        self.assertLessEqual(len(result), 503)

    def test_top_per_group_limits_entries(self):
        result_1 = memory_db.search_with_context("AI", max_chars=99999, top_per_group=1)
        result_3 = memory_db.search_with_context("AI", max_chars=99999, top_per_group=3)
        self.assertLessEqual(len(result_1), len(result_3) + 1)


class TestSearchWithMetadata(unittest.TestCase):
    def test_returns_dict(self):
        result = memory_db.search_with_metadata("AI")
        self.assertIsInstance(result, dict)

    def test_has_required_keys(self):
        result = memory_db.search_with_metadata("AI")
        for key in ("context", "total_results", "context_chars", "truncated", "date_range"):
            self.assertIn(key, result)

    def test_context_is_string(self):
        result = memory_db.search_with_metadata("AI")
        self.assertIsInstance(result["context"], str)

    def test_total_results_is_int(self):
        result = memory_db.search_with_metadata("AI")
        self.assertIsInstance(result["total_results"], int)

    def test_context_chars_matches(self):
        result = memory_db.search_with_metadata("AI")
        self.assertEqual(result["context_chars"], len(result["context"]))

    def test_truncated_is_bool(self):
        result = memory_db.search_with_metadata("AI")
        self.assertIsInstance(result["truncated"], bool)

    def test_date_range_structure(self):
        result = memory_db.search_with_metadata("AI")
        self.assertIn("earliest", result["date_range"])
        self.assertIn("latest", result["date_range"])

    def test_truncation_detected(self):
        result = memory_db.search_with_metadata("AI", max_chars=50)
        # May or may not be truncated depending on data
        self.assertIsInstance(result["truncated"], bool)

    def test_no_results(self):
        result = memory_db.search_with_metadata("xyznonexistent999")
        self.assertEqual(result["total_results"], 0)
        self.assertEqual(result["context"], "")


if __name__ == "__main__":
    unittest.main()
