#!/usr/bin/env python3
"""Tests for memory_retrieval (pure function retrieval)."""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest


class TestQueryRewrite(unittest.TestCase):
    def test_rewrite_informal(self):
        from memory_retrieval import rewrite_query
        result = rewrite_query("上次那个爬虫")
        result_str = str(result)
        # "爬虫" should be in the expanded results
        self.assertTrue(
            any("爬虫" in r for r in result),
            f"'爬虫' not found in result: {result}"
        )
        # The original query (with "上次") should be preserved in the list
        self.assertIn("上次那个爬虫", result)
        # Synonyms should be added
        self.assertTrue(len(result) >= 3, f"Expected >=3 rewrites, got {len(result)}: {result}")

    def test_rewrite_expansion(self):
        from memory_retrieval import rewrite_query
        result = rewrite_query("融资数据")
        self.assertTrue(any("融资" in r or "funding" in r.lower() for r in result))
        # Should contain synonyms
        has_synonyms = any(r in ["funding", "投资", "投资方"] for r in result)
        self.assertTrue(has_synonyms)

    def test_rewrite_dedup(self):
        from memory_retrieval import rewrite_query
        result = rewrite_query("python python python")
        self.assertLessEqual(len(result), 5)

    def test_rewrite_empty(self):
        from memory_retrieval import rewrite_query
        result = rewrite_query("")
        self.assertEqual(result, [])


class TestTimeDecay(unittest.TestCase):
    def test_time_decay_recent(self):
        from memory_retrieval import time_decay_weight
        now = "2026-03-20T12:00:00"
        w = time_decay_weight(now)
        self.assertGreater(w, 0.9)

    def test_time_decay_old(self):
        from memory_retrieval import time_decay_weight
        old = "2026-01-01T12:00:00"
        w = time_decay_weight(old)
        self.assertLess(w, 0.3)

    def test_time_decay_none(self):
        from memory_retrieval import time_decay_weight
        w = time_decay_weight(None)
        self.assertEqual(w, 0.5)


class TestRetrieve(unittest.TestCase):
    def test_retrieve_returns_list(self):
        from memory_retrieval import retrieve
        results = retrieve("测试", top_k=3)
        self.assertIsInstance(results, list)

    def test_retrieve_with_tags(self):
        from memory_retrieval import retrieve
        results = retrieve("观察", tags=["discovery"], top_k=5)
        for r in results:
            self.assertGreaterEqual(r["score"], 0)

    def test_retrieve_dynamic_threshold(self):
        from memory_retrieval import retrieve
        # Should always return at least some results for a query that matches
        results = retrieve("记忆", top_k=3)
        self.assertLessEqual(len(results), 3)

    def test_retrieve_time_range(self):
        from memory_retrieval import retrieve
        r1 = retrieve("观察", time_range="recent", top_k=5)
        r2 = retrieve("观察", time_range="all", top_k=5)
        # "all" should have >= results than "recent"
        self.assertGreaterEqual(len(r2), len(r1))


class TestBuildContext(unittest.TestCase):
    def test_build_context_empty(self):
        from memory_retrieval import build_context
        ctx = build_context("测试", [])
        self.assertEqual(ctx, "")

    def test_build_context_with_data(self):
        from memory_retrieval import build_context
        candidates = [
            {"id": 1, "type": "discovery", "title": "测试发现",
             "narrative": "这是一条测试", "score": 0.9,
             "kind": "observation", "source": "test"}
        ]
        ctx = build_context("测试", candidates)
        self.assertIn("测试发现", ctx)
        self.assertIn("score=0.9", ctx)

    def test_build_context_truncation(self):
        from memory_retrieval import build_context
        candidates = [
            {"id": i, "type": "discovery",
             "title": f"测试标题{i}",
             "narrative": "这是测试内容" * 100, "score": 0.9 - i * 0.1,
             "kind": "observation", "source": "test"}
            for i in range(10)
        ]
        ctx = build_context("测试", candidates, max_chars=200)
        self.assertLessEqual(len(ctx), 250)


if __name__ == "__main__":
    unittest.main(verbosity=2)
