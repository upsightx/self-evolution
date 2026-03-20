#!/usr/bin/env python3
"""
data_accumulator 测试 — 至少 15 个测试用例。
使用临时文件和临时 DB，不影响真实数据。
"""
import json
import os
import sqlite3
import tempfile
import shutil
import unittest
from pathlib import Path
from datetime import datetime, timedelta

# 确保能导入
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_accumulator import (
    scan_daily_logs,
    merge_all_sources,
    backfill_stats,
    _detect_model,
    _detect_task_type,
    _detect_success,
    _parse_log_block,
    _parse_structured_entries,
    _extract_date_from_filename,
    _load_agent_stats,
    _load_task_outcomes,
    _compute_stats,
)


class TestDetectModel(unittest.TestCase):
    """测试模型名识别"""

    def test_opus(self):
        self.assertEqual(_detect_model("派 4 个 Opus 子 Agent"), "opus")

    def test_opus_lowercase(self):
        self.assertEqual(_detect_model("用 opus 模型执行"), "opus")

    def test_minimax(self):
        self.assertEqual(_detect_model("11 个 MiniMax 子 Agent"), "minimax")

    def test_sonnet(self):
        self.assertEqual(_detect_model("切换到 Sonnet 模型"), "sonnet")

    def test_glm5(self):
        self.assertEqual(_detect_model("5 个 GLM5 子 Agent"), "glm5")

    def test_glm_5_with_space(self):
        self.assertEqual(_detect_model("使用 GLM 5 模型"), "glm5")

    def test_glm_hyphen(self):
        self.assertEqual(_detect_model("GLM-5 子Agent"), "glm5")

    def test_kimi(self):
        self.assertEqual(_detect_model("Kimi 模型测试"), "kimi")

    def test_unknown(self):
        self.assertEqual(_detect_model("某个模型执行了任务"), "unknown")


class TestDetectTaskType(unittest.TestCase):
    """测试任务类型推断"""

    def test_coding(self):
        self.assertEqual(_detect_task_type("写代码实现模块"), "coding")

    def test_research(self):
        self.assertEqual(_detect_task_type("调研竞品分析"), "research")

    def test_refactor(self):
        self.assertEqual(_detect_task_type("重构优化代码"), "refactor")

    def test_file_ops(self):
        self.assertEqual(_detect_task_type("记忆压缩归档文件"), "file_ops")

    def test_skill_creation(self):
        self.assertEqual(_detect_task_type("创建skill技能"), "skill_creation")

    def test_unknown(self):
        self.assertEqual(_detect_task_type("做了一些事情"), "unknown")


class TestDetectSuccess(unittest.TestCase):
    """测试成功/失败判断"""

    def test_success_completed(self):
        self.assertTrue(_detect_success("子Agent完成任务"))

    def test_success_passed(self):
        self.assertTrue(_detect_success("全部测试通过"))

    def test_success_keyword(self):
        self.assertTrue(_detect_success("任务成功执行"))

    def test_fail_timeout(self):
        self.assertFalse(_detect_success("子Agent超时了"))

    def test_fail_rework(self):
        self.assertFalse(_detect_success("需要返工处理"))

    def test_fail_retry(self):
        self.assertFalse(_detect_success("子Agent重试中"))

    def test_fail_slacking(self):
        self.assertFalse(_detect_success("子Agent摸鱼没写代码"))

    def test_ambiguous_success_last(self):
        # 先失败后成功 → 最终成功
        self.assertTrue(_detect_success("首次失败，重试后成功"))

    def test_ambiguous_fail_last(self):
        # 先成功后失败 → 最终失败
        self.assertFalse(_detect_success("部分通过但最终失败"))

    def test_none_no_keywords(self):
        self.assertIsNone(_detect_success("子Agent执行了一些操作"))


class TestExtractDateFromFilename(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(_extract_date_from_filename("2026-03-18.md"), "2026-03-18")

    def test_no_date(self):
        self.assertEqual(_extract_date_from_filename("readme.md"), "")


class TestScanDailyLogs(unittest.TestCase):
    """测试日志扫描 — 使用临时目录"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        # 创建今天的日志
        with open(os.path.join(self.tmpdir, f"{today}.md"), "w") as f:
            f.write(f"""# {today} 日志

## 子Agent执行
- 4 个 Opus 子 Agent 并行，全部一次通过
- 模块写代码实现完成
- MiniMax 子Agent 调研任务失败，需要重试
""")

        # 创建昨天的日志
        with open(os.path.join(self.tmpdir, f"{yesterday}.md"), "w") as f:
            f.write(f"""# {yesterday} 日志

## 开发
- 派 Opus 子Agent 重构代码，一次通过成功
- GLM5 子Agent 写代码测试通过
""")

        # 创建一个非日期文件（应被忽略）
        with open(os.path.join(self.tmpdir, "readme.md"), "w") as f:
            f.write("# README\nThis is not a daily log.")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_scan_finds_records(self):
        records = scan_daily_logs(days=30, memory_dir=self.tmpdir)
        self.assertGreater(len(records), 0)

    def test_scan_ignores_non_date_files(self):
        records = scan_daily_logs(days=30, memory_dir=self.tmpdir)
        sources = {r["source"] for r in records}
        self.assertFalse(any("readme" in s for s in sources))

    def test_scan_extracts_model(self):
        records = scan_daily_logs(days=30, memory_dir=self.tmpdir)
        models = {r["model"] for r in records}
        self.assertIn("opus", models)

    def test_scan_extracts_success(self):
        records = scan_daily_logs(days=30, memory_dir=self.tmpdir)
        successes = [r for r in records if r["success"]]
        failures = [r for r in records if not r["success"]]
        self.assertGreater(len(successes), 0)
        self.assertGreater(len(failures), 0)

    def test_scan_respects_days_limit(self):
        # 创建一个 60 天前的日志
        old_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        with open(os.path.join(self.tmpdir, f"{old_date}.md"), "w") as f:
            f.write("Opus 子Agent 完成任务成功")
        records = scan_daily_logs(days=30, memory_dir=self.tmpdir)
        dates = {r["date"] for r in records}
        self.assertNotIn(old_date, dates)

    def test_scan_returns_correct_structure(self):
        records = scan_daily_logs(days=30, memory_dir=self.tmpdir)
        if records:
            r = records[0]
            self.assertIn("model", r)
            self.assertIn("task_type", r)
            self.assertIn("success", r)
            self.assertIn("date", r)
            self.assertIn("source", r)


class TestParseStructuredEntries(unittest.TestCase):
    """测试结构化模式提取"""

    def test_batch_pattern(self):
        text = "5 个 Opus 子 Agent 并行，全部一次通过，写代码完成"
        records = _parse_structured_entries(text, "2026-03-18", "test")
        self.assertEqual(len(records), 5)
        for r in records:
            self.assertEqual(r["model"], "opus")
            self.assertTrue(r["success"])

    def test_batch_failure(self):
        text = "3 个 MiniMax 子Agent 执行调研任务失败"
        records = _parse_structured_entries(text, "2026-03-18", "test")
        self.assertEqual(len(records), 3)
        for r in records:
            self.assertEqual(r["model"], "minimax")
            self.assertFalse(r["success"])


class TestLoadAgentStats(unittest.TestCase):
    """测试 agent-stats.json 加载"""

    def test_load_valid(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "stats": {
                    "recent": [
                        {"time": "2026-03-18T10:00:00", "model": "opus",
                         "task_type": "coding", "success": True, "label": "test"},
                        {"time": "2026-03-17T09:00:00", "model": "minimax",
                         "task_type": "research", "success": False, "label": "fail"},
                    ]
                }
            }, f)
            path = f.name

        try:
            records = _load_agent_stats(path)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["model"], "opus")
            self.assertTrue(records[0]["success"])
            self.assertEqual(records[1]["model"], "minimax")
            self.assertFalse(records[1]["success"])
        finally:
            os.unlink(path)

    def test_load_missing_file(self):
        records = _load_agent_stats("/nonexistent/path.json")
        self.assertEqual(records, [])


class TestLoadTaskOutcomes(unittest.TestCase):
    """测试 task_outcomes 表加载"""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE task_outcomes (
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
        conn.execute(
            "INSERT INTO task_outcomes (task_id, task_type, model, success, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            ("t1", "coding", "opus", 1, "2026-03-18 10:00:00")
        )
        conn.execute(
            "INSERT INTO task_outcomes (task_id, task_type, model, success, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            ("t2", "research", "minimax", 0, "2026-03-17 09:00:00")
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_load_records(self):
        records = _load_task_outcomes(self.db_path)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["model"], "opus")
        self.assertTrue(records[0]["success"])
        self.assertEqual(records[0]["date"], "2026-03-18")

    def test_load_missing_db(self):
        records = _load_task_outcomes("/nonexistent/db.sqlite")
        self.assertEqual(records, [])


class TestComputeStats(unittest.TestCase):
    """测试统计计算"""

    def test_basic_stats(self):
        records = [
            {"model": "opus", "task_type": "coding", "success": True},
            {"model": "opus", "task_type": "coding", "success": True},
            {"model": "opus", "task_type": "coding", "success": False},
            {"model": "minimax", "task_type": "research", "success": True},
        ]
        by_model, by_task, by_mt = _compute_stats(records)

        self.assertEqual(by_model["opus"]["total"], 3)
        self.assertEqual(by_model["opus"]["success"], 2)
        self.assertAlmostEqual(by_model["opus"]["rate"], 0.667, places=2)

        self.assertEqual(by_task["coding"]["total"], 3)
        self.assertEqual(by_task["research"]["total"], 1)

        self.assertEqual(by_mt["opus:coding"]["total"], 3)
        self.assertEqual(by_mt["minimax:research"]["total"], 1)

    def test_empty_records(self):
        by_model, by_task, by_mt = _compute_stats([])
        self.assertEqual(by_model, {})
        self.assertEqual(by_task, {})
        self.assertEqual(by_mt, {})


class TestMergeAllSources(unittest.TestCase):
    """测试合并去重"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

        # 创建 agent-stats.json
        self.stats_path = os.path.join(self.tmpdir, "agent-stats.json")
        with open(self.stats_path, "w") as f:
            json.dump({
                "stats": {
                    "by_model": {},
                    "by_task_type": {},
                    "recent": [
                        {"time": "2026-03-18T10:00:00", "model": "opus",
                         "task_type": "coding", "success": True, "label": "test1"},
                    ]
                }
            }, f)

        # 创建 memory.db
        self.db_path = os.path.join(self.tmpdir, "memory.db")
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE task_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT, task_type TEXT NOT NULL, model TEXT,
                expected TEXT, actual TEXT, success INTEGER NOT NULL,
                gap_analysis TEXT, notes TEXT,
                timestamp TEXT DEFAULT (datetime('now'))
            )
        """)
        # 这条和 agent-stats 重复（同日期、同模型、同类型、同结果）
        conn.execute(
            "INSERT INTO task_outcomes (task_id, task_type, model, success, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            ("t1", "coding", "opus", 1, "2026-03-18 10:00:00")
        )
        # 这条不重复
        conn.execute(
            "INSERT INTO task_outcomes (task_id, task_type, model, success, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            ("t2", "research", "minimax", 0, "2026-03-17 09:00:00")
        )
        conn.commit()
        conn.close()

        # 创建日志目录（空的，不产生日志记录）
        self.memory_dir = os.path.join(self.tmpdir, "memory_logs")
        os.makedirs(self.memory_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_dedup(self):
        result = merge_all_sources(
            stats_path=self.stats_path,
            db_path=self.db_path,
            memory_dir=self.memory_dir,
        )
        # agent_stats: 1 (opus/coding/True)
        # task_outcomes: 1 new (minimax/research/False), 1 dup skipped
        self.assertEqual(result["total_records"], 2)
        self.assertEqual(result["sources"]["agent_stats"], 1)
        self.assertEqual(result["sources"]["task_outcomes"], 1)

    def test_stats_structure(self):
        result = merge_all_sources(
            stats_path=self.stats_path,
            db_path=self.db_path,
            memory_dir=self.memory_dir,
        )
        self.assertIn("total_records", result)
        self.assertIn("by_model", result)
        self.assertIn("by_task_type", result)
        self.assertIn("by_model_task", result)
        self.assertIn("sources", result)

    def test_by_model_has_rate(self):
        result = merge_all_sources(
            stats_path=self.stats_path,
            db_path=self.db_path,
            memory_dir=self.memory_dir,
        )
        for model_stats in result["by_model"].values():
            self.assertIn("rate", model_stats)
            self.assertIn("total", model_stats)
            self.assertIn("success", model_stats)


class TestBackfill(unittest.TestCase):
    """测试回填功能"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

        # agent-stats.json（初始只有1条）
        self.stats_path = os.path.join(self.tmpdir, "agent-stats.json")
        with open(self.stats_path, "w") as f:
            json.dump({
                "stats": {
                    "by_model": {"opus": {"total": 1, "success": 1, "fail": 0}},
                    "by_task_type": {"coding": {"total": 1, "success": 1, "fail": 0}},
                    "recent": [
                        {"time": "2026-03-18T10:00:00", "model": "opus",
                         "task_type": "coding", "success": True, "label": "existing"},
                    ]
                },
                "updated": "2026-03-18"
            }, f)

        # memory.db 有新记录
        self.db_path = os.path.join(self.tmpdir, "memory.db")
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE task_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT, task_type TEXT NOT NULL, model TEXT,
                expected TEXT, actual TEXT, success INTEGER NOT NULL,
                gap_analysis TEXT, notes TEXT,
                timestamp TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "INSERT INTO task_outcomes (task_id, task_type, model, success, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            ("t2", "research", "minimax", 0, "2026-03-17 09:00:00")
        )
        conn.commit()
        conn.close()

        # 空日志目录
        self.memory_dir = os.path.join(self.tmpdir, "logs")
        os.makedirs(self.memory_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_dry_run_no_write(self):
        result = backfill_stats(
            dry_run=True,
            stats_path=self.stats_path,
            db_path=self.db_path,
            memory_dir=self.memory_dir,
        )
        self.assertGreater(result["new_records"], 0)

        # 验证文件未被修改
        with open(self.stats_path) as f:
            data = json.load(f)
        self.assertEqual(len(data["stats"]["recent"]), 1)  # 仍然只有1条

    def test_apply_writes(self):
        result = backfill_stats(
            dry_run=False,
            stats_path=self.stats_path,
            db_path=self.db_path,
            memory_dir=self.memory_dir,
        )
        self.assertGreater(result["new_records"], 0)

        # 验证文件已更新
        with open(self.stats_path) as f:
            data = json.load(f)
        self.assertGreater(len(data["stats"]["recent"]), 1)

    def test_apply_updates_by_model(self):
        backfill_stats(
            dry_run=False,
            stats_path=self.stats_path,
            db_path=self.db_path,
            memory_dir=self.memory_dir,
        )
        with open(self.stats_path) as f:
            data = json.load(f)
        # minimax 应该被添加到 by_model
        self.assertIn("minimax", data["stats"]["by_model"])
        self.assertEqual(data["stats"]["by_model"]["minimax"]["total"], 1)
        self.assertEqual(data["stats"]["by_model"]["minimax"]["fail"], 1)

    def test_backfill_dedup(self):
        # 第一次回填
        r1 = backfill_stats(
            dry_run=False,
            stats_path=self.stats_path,
            db_path=self.db_path,
            memory_dir=self.memory_dir,
        )
        # 第二次回填 — 应该全部跳过
        r2 = backfill_stats(
            dry_run=False,
            stats_path=self.stats_path,
            db_path=self.db_path,
            memory_dir=self.memory_dir,
        )
        self.assertEqual(r2["new_records"], 0)
        self.assertGreater(r2["duplicates_skipped"], 0)

    def test_backfill_missing_stats_file(self):
        result = backfill_stats(
            dry_run=True,
            stats_path="/nonexistent/stats.json",
            db_path=self.db_path,
            memory_dir=self.memory_dir,
        )
        self.assertIn("error", result)


class TestParseLogBlock(unittest.TestCase):
    """测试文本块解析"""

    def test_success_block(self):
        block = """## 开发任务
- Opus 子Agent 写代码完成
- 测试全部通过"""
        records = _parse_log_block(block, "2026-03-18", "test.md")
        self.assertGreater(len(records), 0)
        self.assertTrue(records[0]["success"])

    def test_failure_block(self):
        block = """## 问题
- MiniMax 子Agent 执行超时失败"""
        records = _parse_log_block(block, "2026-03-18", "test.md")
        self.assertGreater(len(records), 0)
        self.assertFalse(records[0]["success"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
