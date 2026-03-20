"""Tests for LLM fallback layer in todo_extractor."""

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from todo_extractor import extract_todos_from_text, extract_todos_with_llm


class TestRuleExtractSkipsLLM(unittest.TestCase):
    """When rules extract something, LLM should NOT be called."""

    @patch("todo_extractor.extract_todos_with_llm")
    def test_rule_hit_no_llm(self, mock_llm):
        results = extract_todos_from_text("帮我订一下明天的机票", use_llm=True)
        self.assertTrue(len(results) > 0)
        mock_llm.assert_not_called()


class TestLLMFallback(unittest.TestCase):
    """When rules extract nothing and use_llm=True, LLM is called."""

    @patch("todo_extractor.extract_todos_with_llm")
    def test_llm_called_when_rules_empty(self, mock_llm):
        mock_llm.return_value = [
            {"title": "推进那个事情", "confidence": 0.7, "time_hint": ""},
        ]
        # This text does NOT match any rule patterns
        results = extract_todos_from_text(
            "看看能不能把那个事情推进一下", use_llm=True
        )
        mock_llm.assert_called_once()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "推进那个事情")

    @patch("todo_extractor.extract_todos_with_llm")
    def test_llm_not_called_when_flag_false(self, mock_llm):
        results = extract_todos_from_text(
            "看看能不能把那个事情推进一下", use_llm=False
        )
        mock_llm.assert_not_called()


class TestLLMConfidenceReduction(unittest.TestCase):
    """LLM results should have confidence reduced by 0.1."""

    @patch("todo_extractor.extract_todos_with_llm")
    def test_confidence_minus_01(self, mock_llm):
        mock_llm.return_value = [
            {"title": "推进那个事情", "confidence": 0.8, "time_hint": ""},
            {"title": "整理下报告", "confidence": 0.6, "time_hint": ""},
        ]
        # Text that does NOT match any rule patterns
        results = extract_todos_from_text(
            "那个报告整理下吧，事情也推进一下",
            use_llm=True,
        )
        self.assertEqual(len(results), 2)
        self.assertAlmostEqual(results[0]["confidence"], 0.7)
        self.assertAlmostEqual(results[1]["confidence"], 0.5)

    @patch("todo_extractor.extract_todos_with_llm")
    def test_confidence_floor_zero(self, mock_llm):
        """Confidence should not go below 0."""
        mock_llm.return_value = [
            {"title": "做个测试任务", "confidence": 0.05, "time_hint": ""},
        ]
        results = extract_todos_from_text("随便聊聊吧", use_llm=True)
        self.assertEqual(len(results), 1)
        self.assertGreaterEqual(results[0]["confidence"], 0.0)


class TestLLMErrorHandling(unittest.TestCase):
    """LLM errors should degrade gracefully to empty list."""

    def test_malformed_json(self):
        """Simulate LLM returning garbage."""
        fake_resp = MagicMock()
        fake_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "this is not json array"}}]
        }).encode()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=fake_resp), patch.dict(os.environ, {"MINIMAX_API_KEY": "test_key"}):
            result = extract_todos_with_llm("测试文本")
        self.assertEqual(result, [])

    def test_network_timeout(self):
        """Simulate network timeout."""
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            result = extract_todos_with_llm("测试文本")
        self.assertEqual(result, [])

    def test_missing_title_field(self):
        """LLM returns items without required 'title' field."""
        fake_resp = MagicMock()
        fake_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": '[{"confidence": 0.8}]'}}]
        }).encode()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=fake_resp), patch.dict(os.environ, {"MINIMAX_API_KEY": "test_key"}):
            result = extract_todos_with_llm("测试文本")
        self.assertEqual(result, [])

    def test_valid_llm_response(self):
        """LLM returns a well-formed response."""
        items = [{"title": "写周报", "confidence": 0.7, "time_hint": "今天"}]
        fake_resp = MagicMock()
        fake_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps(items)}}]
        }).encode()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=fake_resp), patch.dict(os.environ, {"MINIMAX_API_KEY": "test_key"}):
            result = extract_todos_with_llm("今天要写周报")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "写周报")

    def test_markdown_fenced_json(self):
        """LLM wraps JSON in ```json ... ``` fences."""
        items = [{"title": "开会", "confidence": 0.7, "time_hint": ""}]
        content = "```json\n" + json.dumps(items) + "\n```"
        fake_resp = MagicMock()
        fake_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": content}}]
        }).encode()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=fake_resp), patch.dict(os.environ, {"MINIMAX_API_KEY": "test_key"}):
            result = extract_todos_with_llm("下午要开会")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "开会")

    def test_think_tags_stripped(self):
        """LLM wraps response in <think>...</think> reasoning tags."""
        items = [{"title": "写周报", "confidence": 0.8, "time_hint": ""}]
        content = (
            "<think>\n让我分析一下...\n这是一个待办\n</think>\n\n"
            "```json\n" + json.dumps(items) + "\n```"
        )
        fake_resp = MagicMock()
        fake_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": content}}]
        }).encode()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=fake_resp), patch.dict(os.environ, {"MINIMAX_API_KEY": "test_key"}):
            result = extract_todos_with_llm("周报要写一下")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "写周报")


class TestLLMDedup(unittest.TestCase):
    """LLM results should be deduped against pending-tasks.md."""

    @patch("todo_extractor.extract_todos_with_llm")
    def test_llm_dedup_with_existing(self, mock_llm):
        import tempfile
        mock_llm.return_value = [
            {"title": "写周报", "confidence": 0.7, "time_hint": ""},
            {"title": "全新的任务", "confidence": 0.7, "time_hint": ""},
        ]
        # Create a temp pending-tasks.md with "写周报" already in it
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("- [ ] 写周报\n")
            f.flush()
            results = extract_todos_from_text(
                "随便聊聊",
                pending_tasks_path=f.name,
                use_llm=True,
            )
        os.unlink(f.name)
        # "写周报" should be deduped, only "全新的任务" remains
        titles = [r["title"] for r in results]
        self.assertNotIn("写周报", titles)
        self.assertIn("全新的任务", titles)


@unittest.skipUnless(
    os.environ.get("RUN_INTEGRATION_TESTS"),
    "Set RUN_INTEGRATION_TESTS=1 to run real API tests",
)
class TestLLMIntegration(unittest.TestCase):
    """Integration test: real MiniMax API call."""

    def test_real_api_call(self):
        result = extract_todos_with_llm("帮我约一下明天下午3点的会议，还有记得给客户发邮件")
        self.assertIsInstance(result, list)
        # Should extract at least one todo
        self.assertGreater(len(result), 0)
        for item in result:
            self.assertIn("title", item)
            self.assertIn("confidence", item)
            self.assertIn("time_hint", item)


if __name__ == "__main__":
    unittest.main()
