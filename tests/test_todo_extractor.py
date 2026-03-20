"""
Tests for todo_extractor.py
运行: python3 -m pytest test_todo_extractor.py -v
或:   python3 test_todo_extractor.py
"""

import os
import sys
import tempfile
import unittest

# 确保能 import 同目录模块
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from todo_extractor import extract_todos_from_text


class TestTodoExtractor(unittest.TestCase):
    """待办提取核心测试"""

    def _extract(self, text, pending_content=""):
        """辅助：创建临时 pending-tasks.md 并提取"""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        ) as f:
            f.write(pending_content or "# 待处理任务\n\n## 待处理\n（暂无）\n")
            f.flush()
            path = f.name
        try:
            return extract_todos_from_text(text, pending_tasks_path=path)
        finally:
            os.unlink(path)

    # ---- 明确承诺类 (0.8+) ----

    def test_help_me(self):
        """'帮我...' 应提取，confidence >= 0.8"""
        todos = self._extract("帮我查一下红杉的投资人")
        self.assertEqual(len(todos), 1)
        self.assertGreaterEqual(todos[0]['confidence'], 0.8)
        self.assertIn("查一下红杉的投资人", todos[0]['title'])

    def test_i_will_handle(self):
        """'好的我来处理这个bug' 应提取，confidence >= 0.8"""
        todos = self._extract("好的我来处理这个bug")
        self.assertEqual(len(todos), 1)
        self.assertGreaterEqual(todos[0]['confidence'], 0.8)
        self.assertIn("处理这个bug", todos[0]['title'])

    def test_i_will(self):
        """'我会...' 应提取"""
        todos = self._extract("我会把报告发给你")
        self.assertEqual(len(todos), 1)
        self.assertGreaterEqual(todos[0]['confidence'], 0.8)

    def test_remember(self):
        """'记得...' 应提取"""
        todos = self._extract("记得给客户回邮件")
        self.assertEqual(len(todos), 1)
        self.assertGreaterEqual(todos[0]['confidence'], 0.8)

    def test_dont_forget(self):
        """'别忘了...' 应提取"""
        todos = self._extract("别忘了提交周报")
        self.assertEqual(len(todos), 1)
        self.assertGreaterEqual(todos[0]['confidence'], 0.8)

    # ---- 时间约定类 (0.7-0.8) ----

    def test_tomorrow_with_time_hint(self):
        """'我明天去开会' 应提取，time_hint='明天'"""
        todos = self._extract("我明天去开会")
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0]['time_hint'], "明天")

    def test_next_week(self):
        """'下周一开评审会' 应提取，time_hint 含下周"""
        todos = self._extract("下周一开评审会")
        self.assertEqual(len(todos), 1)
        self.assertIn("下周", todos[0]['time_hint'])

    def test_tonight(self):
        """'今晚整理一下代码' 应提取"""
        todos = self._extract("今晚整理一下代码")
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0]['time_hint'], "今晚")

    # ---- 计划讨论类 (0.6-0.7) ----

    def test_need_to(self):
        """'需要整理一下文档' 应提取，confidence 0.6-0.7"""
        todos = self._extract("需要整理一下文档")
        self.assertEqual(len(todos), 1)
        self.assertGreaterEqual(todos[0]['confidence'], 0.6)
        self.assertLessEqual(todos[0]['confidence'], 0.7)

    def test_should(self):
        """'应该更新一下依赖' 应提取"""
        todos = self._extract("应该更新一下依赖")
        self.assertEqual(len(todos), 1)
        self.assertGreaterEqual(todos[0]['confidence'], 0.6)
        self.assertLessEqual(todos[0]['confidence'], 0.7)

    def test_plan_to(self):
        """'打算重构这个模块' 应提取"""
        todos = self._extract("打算重构这个模块")
        self.assertEqual(len(todos), 1)
        self.assertGreaterEqual(todos[0]['confidence'], 0.6)

    # ---- 不应提取 ----

    def test_weather_excluded(self):
        """'今天天气不错' 不应提取"""
        todos = self._extract("今天天气不错")
        self.assertEqual(len(todos), 0)

    def test_greeting_excluded(self):
        """寒暄不应提取"""
        for text in ["你好", "谢谢", "哈哈", "好的", "收到", "了解"]:
            todos = self._extract(text)
            self.assertEqual(len(todos), 0, f"'{text}' should not be extracted")

    def test_short_text_excluded(self):
        """太短的内容不应提取"""
        todos = self._extract("帮我看")  # title 只有 "看"，太短
        self.assertEqual(len(todos), 0)

    # ---- 去重 ----

    def test_dedup_with_existing(self):
        """跟 pending-tasks.md 中已有的重复待办不应提取"""
        pending = "# 待处理任务\n\n## 待处理\n- 查一下红杉的投资人\n"
        todos = self._extract("帮我查一下红杉的投资人", pending_content=pending)
        self.assertEqual(len(todos), 0)

    def test_dedup_within_batch(self):
        """同一批文本中重复的待办只提取一次"""
        text = "帮我查一下红杉的投资人\n帮我查一下红杉的投资人"
        todos = self._extract(text)
        self.assertEqual(len(todos), 1)

    def test_similar_dedup(self):
        """相似度 > 0.7 的待办应去重"""
        pending = "# 待处理任务\n\n## 待处理\n- 查红杉的投资人信息\n"
        todos = self._extract("帮我查一下红杉的投资人", pending_content=pending)
        self.assertEqual(len(todos), 0)

    # ---- 多行提取 ----

    def test_multiline(self):
        """多行文本应分别提取"""
        text = """帮我查一下红杉的投资人
今天天气不错
需要整理一下文档
好的"""
        todos = self._extract(text)
        self.assertEqual(len(todos), 2)
        titles = [t['title'] for t in todos]
        self.assertTrue(any("红杉" in t for t in titles))
        self.assertTrue(any("整理" in t for t in titles))

    # ---- 标题截断 ----

    def test_title_truncation(self):
        """超长标题应截断到30字"""
        long_text = "帮我把这个非常非常非常非常非常非常非常非常非常非常非常非常长的任务处理一下"
        todos = self._extract(long_text)
        self.assertEqual(len(todos), 1)
        self.assertLessEqual(len(todos[0]['title']), 30)

    # ---- 边界情况 ----

    def test_empty_text(self):
        """空文本不应提取"""
        todos = self._extract("")
        self.assertEqual(len(todos), 0)

    def test_no_pending_file(self):
        """pending-tasks.md 不存在时也能正常工作"""
        todos = extract_todos_from_text(
            "帮我查一下红杉的投资人",
            pending_tasks_path="/tmp/nonexistent_pending_tasks.md"
        )
        self.assertEqual(len(todos), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
