#!/usr/bin/env python3
"""Tests for memory_service (orchestration layer)."""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest


class TestExtractTags(unittest.TestCase):
    def test_task_type_detection(self):
        from memory_service import extract_tags
        tags = extract_tags("写一个Python爬虫程序", task_type="coding")
        self.assertIn("coding", tags)

    def test_model_detection(self):
        from memory_service import extract_tags
        tags = extract_tags("Kimi在融资任务上表现更好", task_type="research")
        self.assertIn("kimi", tags)
        self.assertIn("research", tags)

    def test_tech_keywords(self):
        from memory_service import extract_tags
        tags = extract_tags("使用Docker部署到服务器，GitHub Actions自动化", task_type="coding")
        self.assertIn("docker", tags)
        self.assertIn("github", tags)

    def test_max_tags(self):
        from memory_service import extract_tags
        long_content = "python javascript typescript rust go docker kubernetes " * 5
        tags = extract_tags(long_content)
        self.assertLessEqual(len(tags), 10)

    def test_dedup(self):
        from memory_service import extract_tags
        tags = extract_tags("python python python python", task_type="coding")
        self.assertEqual(len([t for t in tags if t == "python"]), 1)

    def test_word_boundary_latin(self):
        from memory_service import extract_tags
        # "monty python" should NOT match "python" as a tech keyword
        # because "python" appears as part of "monty python" — but actually
        # \bpython\b will match since "python" is a separate word here
        tags = extract_tags("I love monty python comedy shows")
        # "python" IS a separate word here, so it will match
        # But "gopher" in "gopher protocol" should not match "go"
        tags2 = extract_tags("the gopher protocol is old")
        self.assertNotIn("go", tags2)

    def test_cjk_substring(self):
        from memory_service import extract_tags
        tags = extract_tags("这个融资项目很有前景")
        self.assertIn("research", tags)


class TestRemember(unittest.TestCase):
    def test_remember_auto_tags(self):
        from memory_service import remember
        result = remember(
            content="Python爬虫抓取GitHub Trending数据，使用FastAPI提供API",
            type="discovery",
        )
        self.assertIsNotNone(result.get("id"))
        self.assertIsInstance(result["tags"], list)
        self.assertIn("python", result["tags"])

    def test_remember_merge_tags(self):
        from memory_service import remember
        result = remember(
            content="Kimi在融资任务上表现更好",
            type="decision",
            tags=["融资", "kimi"],
        )
        self.assertIn("kimi", result["tags"])

    def test_remember_no_title(self):
        from memory_service import remember
        result = remember(content="这是一条很长的记忆内容" * 10, type="observation")
        self.assertLessEqual(len(result["title"]), 43)  # 40 + "..."


class TestRecall(unittest.TestCase):
    def test_recall_returns_string(self):
        from memory_service import recall
        ctx = recall("测试", top_k=3)
        self.assertIsInstance(ctx, str)

    def test_recall_includes_memory_label(self):
        from memory_service import recall
        ctx = recall("观察", top_k=3)
        if ctx:
            self.assertTrue(ctx.startswith("[Relevant Memory]"))


class TestReflect(unittest.TestCase):
    def test_reflect_returns_dict(self):
        from memory_service import reflect
        result = reflect()
        self.assertIsInstance(result, dict)
        self.assertIn("new_insights", result)
        self.assertIn("tags_frequency", result)
        self.assertIn("total_recent", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
