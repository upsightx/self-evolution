#!/usr/bin/env python3
"""Tests for search_with_context and search_with_metadata in memory_db.py.

Uses the real memory.db at the project memory.db (auto-detected)
"""

import os
import sys
import unittest

# Ensure the module is importable
sys.path.insert(0, os.path.dirname(__file__))
os.environ["SELF_EVOLUTION_DB"] = os.path.join(os.path.dirname(__file__), "memory.db")

import importlib
import memory_db
importlib.reload(memory_db)


_REAL_DB = os.path.join(os.path.dirname(__file__), "memory.db")


def setUpModule():
    """Force memory_db to use the real DB before any test in this module."""
    os.environ["SELF_EVOLUTION_DB"] = _REAL_DB
    importlib.reload(memory_db)


class TestSearchWithContext(unittest.TestCase):
    """Test search_with_context returns a formatted string."""

    def test_returns_string(self):
        result = memory_db.search_with_context("AI")
        self.assertIsInstance(result, str)

    def test_empty_query_returns_string(self):
        result = memory_db.search_with_context("xyznonexistent999")
        self.assertIsInstance(result, str)
        # No results → empty string
        self.assertEqual(result, "")

    def test_format_has_date_headers(self):
        result = memory_db.search_with_context("AI")
        if result:
            self.assertIn("---", result)

    def test_format_has_type_brackets(self):
        result = memory_db.search_with_context("AI")
        if result:
            self.assertRegex(result, r'\[.+\]')

    def test_max_chars_truncation(self):
        # Use a very small budget to force truncation
        result = memory_db.search_with_context("AI", max_chars=100)
        self.assertLessEqual(len(result), 100)

    def test_max_chars_respected_with_large_query(self):
        # Search something likely to have many results
        result = memory_db.search_with_context("", max_chars=500)
        # Empty query returns empty (search requires a query)
        # Try a broad term instead
        result = memory_db.search_with_context("a", max_chars=500)
        self.assertLessEqual(len(result), 500)

    def test_top_per_group_limits_entries(self):
        result_1 = memory_db.search_with_context("AI", max_chars=99999, top_per_group=1)
        result_3 = memory_db.search_with_context("AI", max_chars=99999, top_per_group=3)
        # With top_per_group=1, result should be <= result with top_per_group=3
        self.assertLessEqual(len(result_1), len(result_3))


class TestSearchWithMetadata(unittest.TestCase):
    """Test search_with_metadata returns correct structure."""

    def test_returns_dict(self):
        result = memory_db.search_with_metadata("AI")
        self.assertIsInstance(result, dict)

    def test_has_required_keys(self):
        result = memory_db.search_with_metadata("AI")
        for key in ("context", "total_results", "context_chars", "truncated", "date_range"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_context_is_string(self):
        result = memory_db.search_with_metadata("AI")
        self.assertIsInstance(result["context"], str)

    def test_total_results_is_int(self):
        result = memory_db.search_with_metadata("AI")
        self.assertIsInstance(result["total_results"], int)
        self.assertGreaterEqual(result["total_results"], 0)

    def test_context_chars_matches(self):
        result = memory_db.search_with_metadata("AI")
        self.assertEqual(result["context_chars"], len(result["context"]))

    def test_truncated_is_bool(self):
        result = memory_db.search_with_metadata("AI")
        self.assertIsInstance(result["truncated"], bool)

    def test_date_range_structure(self):
        result = memory_db.search_with_metadata("AI")
        dr = result["date_range"]
        self.assertIn("earliest", dr)
        self.assertIn("latest", dr)
        if dr["earliest"] and dr["latest"]:
            self.assertLessEqual(dr["earliest"], dr["latest"])

    def test_truncation_detected(self):
        # Force truncation with tiny budget
        result = memory_db.search_with_metadata("AI", max_chars=50)
        if result["total_results"] > 0:
            self.assertTrue(result["truncated"])

    def test_no_results(self):
        result = memory_db.search_with_metadata("xyznonexistent999")
        self.assertEqual(result["total_results"], 0)
        self.assertEqual(result["context"], "")
        self.assertEqual(result["context_chars"], 0)
        self.assertFalse(result["truncated"])
        self.assertIsNone(result["date_range"]["earliest"])
        self.assertIsNone(result["date_range"]["latest"])


class TestRealDatabase(unittest.TestCase):
    """Tests that verify real data exists and functions work with it."""

    def test_db_exists(self):
        self.assertTrue(os.path.exists(str(memory_db.DB_PATH)),
                        f"Database not found at {memory_db.DB_PATH}")

    def test_has_data(self):
        s = memory_db.stats()
        total = s["observations"] + s["decisions"] + s["summaries"]
        self.assertGreater(total, 0, "Database is empty")

    def test_context_with_real_data(self):
        """Search with a term likely to exist and verify output format."""
        # Try several terms to find one with results
        for term in ["AI", "决策", "学习", "memory", "skill"]:
            result = memory_db.search_with_context(term)
            if result:
                # Verify format: should have date headers
                self.assertIn("---", result)
                return
        # If none found, that's still OK - just skip
        self.skipTest("No matching records found for test terms")


if __name__ == "__main__":
    unittest.main()
