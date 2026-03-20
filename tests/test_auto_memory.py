#!/usr/bin/env python3
"""Tests for auto_memory.py — at least 15 tests covering all requirements."""

import os
import sys
import tempfile
import unittest

# Ensure the module directory is on the path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_memory import extract_memories, auto_save, _is_duplicate, _classify_observation


class TestExtractObservations(unittest.TestCase):
    """Test observation extraction patterns and classification."""

    def test_pattern_faxian(self):
        text = "我发现了这个API需要先初始化才能调用成功"
        result = extract_memories(text)
        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(result["observations"][0]["narrative"], "这个API需要先初始化才能调用成功")

    def test_pattern_yuanlai(self):
        text = "原来：飞书的token有效期只有两个小时需要定期刷新"
        result = extract_memories(text)
        self.assertEqual(len(result["observations"]), 1)
        self.assertIn("飞书的token", result["observations"][0]["narrative"])

    def test_pattern_zhuyidao(self):
        text = "注意到了系统在高并发下会出现连接池耗尽的问题"
        result = extract_memories(text)
        self.assertEqual(len(result["observations"]), 1)
        self.assertIn("连接池耗尽", result["observations"][0]["narrative"])

    def test_pattern_xuedao(self):
        text = "学到了Python的dataclass可以自动生成比较方法"
        result = extract_memories(text)
        self.assertEqual(len(result["observations"]), 1)
        self.assertIn("dataclass", result["observations"][0]["narrative"])

    def test_pattern_jiaoxun(self):
        text = "教训是：不要在生产环境直接执行未经测试的SQL语句"
        result = extract_memories(text)
        self.assertEqual(len(result["observations"]), 1)
        self.assertIn("生产环境", result["observations"][0]["narrative"])

    def test_pattern_jingyan(self):
        text = "经验是：部署前一定要先在staging环境验证一遍完整流程"
        result = extract_memories(text)
        self.assertEqual(len(result["observations"]), 1)

    def test_pattern_jielun(self):
        text = "结论是：使用连接池比每次新建连接性能提升了三倍以上"
        result = extract_memories(text)
        self.assertEqual(len(result["observations"]), 1)

    def test_pattern_queren(self):
        text = "确认了这个方案在大数据量下依然能保持稳定的响应时间"
        result = extract_memories(text)
        self.assertEqual(len(result["observations"]), 1)

    def test_classify_bugfix(self):
        text = "发现了这个bug是因为并发写入导致数据竞争的错误"
        result = extract_memories(text)
        self.assertEqual(result["observations"][0]["type"], "bugfix")

    def test_classify_discovery(self):
        text = "发现了SQLite的WAL模式可以显著提升并发读取性能"
        result = extract_memories(text)
        self.assertEqual(result["observations"][0]["type"], "discovery")

    def test_classify_lesson(self):
        text = "教训是：永远不要信任用户输入必须做好参数校验和过滤"
        result = extract_memories(text)
        self.assertEqual(result["observations"][0]["type"], "lesson")

    def test_classify_lesson_jingyan(self):
        text = "经验是：写代码之前先写测试用例可以大幅减少返工次数"
        result = extract_memories(text)
        self.assertEqual(result["observations"][0]["type"], "lesson")

    def test_classify_change_default(self):
        text = "确认了新版本的接口已经支持批量操作可以一次处理多条"
        result = extract_memories(text)
        self.assertEqual(result["observations"][0]["type"], "change")

    def test_classify_bugfix_by_content(self):
        """Bug keyword in content (not trigger) should still classify as bugfix."""
        text = "确认了这次失败是因为网络超时导致请求没有正确发送出去"
        result = extract_memories(text)
        self.assertEqual(result["observations"][0]["type"], "bugfix")


class TestExtractDecisions(unittest.TestCase):
    """Test decision extraction patterns."""

    def test_pattern_jueding(self):
        text = "决定了以后所有的配置文件都使用YAML格式来统一管理"
        result = extract_memories(text)
        self.assertEqual(len(result["decisions"]), 1)
        self.assertIn("YAML格式", result["decisions"][0]["decision"])

    def test_pattern_xuanze(self):
        text = "选择了使用PostgreSQL替代MySQL作为主数据库方案"
        result = extract_memories(text)
        self.assertEqual(len(result["decisions"]), 1)

    def test_pattern_gaiyong(self):
        text = "改用了Redis作为缓存层来解决频繁查询数据库的性能问题"
        result = extract_memories(text)
        self.assertEqual(len(result["decisions"]), 1)

    def test_pattern_huancheng(self):
        text = "换成了Docker Compose来管理多个服务的部署和编排"
        result = extract_memories(text)
        self.assertEqual(len(result["decisions"]), 1)

    def test_pattern_buzai(self):
        text = "不再使用全局变量来传递状态改为依赖注入的方式来解耦"
        result = extract_memories(text)
        self.assertEqual(len(result["decisions"]), 1)

    def test_pattern_yihou(self):
        text = "以后：所有的API接口都要加上限流和熔断保护机制"
        result = extract_memories(text)
        self.assertEqual(len(result["decisions"]), 1)

    def test_pattern_congxianzaiqi(self):
        text = "从现在起，每次发布前都要跑完整的回归测试套件确保质量"
        result = extract_memories(text)
        self.assertEqual(len(result["decisions"]), 1)


class TestTitleGeneration(unittest.TestCase):
    """Test title generation from content."""

    def test_title_short_content(self):
        text = "发现了短内容但是刚好超过十个字符的限制"
        result = extract_memories(text)
        title = result["observations"][0]["title"]
        self.assertTrue(len(title) <= 23)  # 20 chars + "..."

    def test_title_long_content(self):
        text = "发现了这是一段非常非常非常非常非常非常非常非常非常长的内容用来测试标题截断功能"
        result = extract_memories(text)
        title = result["observations"][0]["title"]
        self.assertTrue(title.endswith("..."))


class TestFilterAndDedup(unittest.TestCase):
    """Test content filtering and deduplication."""

    def test_skip_short_content(self):
        """Content shorter than 10 chars should be skipped."""
        text = "发现了太短了"
        result = extract_memories(text)
        self.assertEqual(len(result["observations"]), 0)

    def test_empty_text(self):
        result = extract_memories("")
        self.assertEqual(result["observations"], [])
        self.assertEqual(result["decisions"], [])

    def test_none_text(self):
        result = extract_memories(None)
        self.assertEqual(result["observations"], [])
        self.assertEqual(result["decisions"], [])

    def test_no_match(self):
        text = "今天天气不错，适合出去走走散散心放松一下"
        result = extract_memories(text)
        self.assertEqual(len(result["observations"]), 0)
        self.assertEqual(len(result["decisions"]), 0)

    def test_dedup_same_content(self):
        """Same content appearing twice should only be extracted once."""
        text = "发现了这个问题的根本原因是内存泄漏导致的。后来又发现了这个问题的根本原因是内存泄漏导致的。"
        result = extract_memories(text)
        self.assertEqual(len(result["observations"]), 1)

    def test_is_duplicate_similar(self):
        self.assertTrue(_is_duplicate("API需要初始化才能调用", ["API需要初始化才能正常调用"], threshold=0.7))

    def test_is_duplicate_different(self):
        self.assertFalse(_is_duplicate("Redis缓存配置", ["Docker部署方案"], threshold=0.7))


class TestMultipleExtractions(unittest.TestCase):
    """Test extracting multiple items from one text."""

    def test_mixed_observations_and_decisions(self):
        text = """今天的工作总结：
        发现了飞书API的rate limit是每秒五次需要做好限流控制。
        决定了以后所有外部API调用都要加上重试机制和指数退避。
        学到了Python的asyncio可以显著提升IO密集型任务的性能。
        """
        result = extract_memories(text)
        self.assertGreaterEqual(len(result["observations"]), 2)
        self.assertGreaterEqual(len(result["decisions"]), 1)


class TestAutoSave(unittest.TestCase):
    """Test auto_save with temporary database."""

    def setUp(self):
        """Set up a temporary database for testing."""
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        # Point memory_db to temp database
        os.environ["SELF_EVOLUTION_DB"] = self.tmp_db.name
        # Re-import to pick up new DB path
        import memory_db
        import importlib
        importlib.reload(memory_db)
        memory_db.init_db()

    def tearDown(self):
        os.environ.pop("SELF_EVOLUTION_DB", None)
        try:
            os.unlink(self.tmp_db.name)
        except OSError:
            pass

    def test_dry_run_no_write(self):
        text = "发现了dry run模式下不应该写入任何数据到数据库中"
        result = auto_save(text, dry_run=True)
        self.assertEqual(result["saved"]["observations"], 0)
        self.assertEqual(result["saved"]["decisions"], 0)
        self.assertEqual(len(result["extracted"]["observations"]), 1)

    def test_auto_save_writes(self):
        text = "发现了auto_save函数能够正确地将提取的记忆写入数据库"
        result = auto_save(text, dry_run=False)
        self.assertEqual(result["saved"]["observations"], 1)

        # Verify it's actually in the DB
        import memory_db
        obs = memory_db.search("auto_save")
        self.assertGreaterEqual(len(obs), 1)

    def test_auto_save_dedup(self):
        """Second save of same content should be skipped as duplicate."""
        text = "发现了重复内容应该被自动去重不会重复写入数据库中"
        result1 = auto_save(text, dry_run=False)
        self.assertEqual(result1["saved"]["observations"], 1)

        result2 = auto_save(text, dry_run=False)
        self.assertEqual(result2["saved"]["observations"], 0)
        self.assertEqual(result2["skipped_duplicates"], 1)

    def test_auto_save_decisions(self):
        text = "决定了使用SQLite作为嵌入式数据库因为零依赖且性能足够"
        result = auto_save(text, dry_run=False)
        self.assertEqual(result["saved"]["decisions"], 1)

        import memory_db
        decs = memory_db.search_decisions("SQLite")
        self.assertGreaterEqual(len(decs), 1)

    def test_auto_save_empty(self):
        result = auto_save("", dry_run=False)
        self.assertEqual(result["saved"]["observations"], 0)
        self.assertEqual(result["saved"]["decisions"], 0)
        self.assertEqual(result["skipped_duplicates"], 0)


if __name__ == "__main__":
    unittest.main()
