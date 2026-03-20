#!/usr/bin/env python3
"""Tests for orchestrator.py — Scheduler, Orchestrator."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import Scheduler, Orchestrator, SCHEDULE


class TestScheduler(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._state_path = os.path.join(self._tmpdir, "state.json")

    def tearDown(self):
        if os.path.exists(self._state_path):
            os.remove(self._state_path)
        os.rmdir(self._tmpdir)

    def test_should_run_first_time(self):
        sched = Scheduler(self._state_path)
        self.assertTrue(sched.should_run("test_task", 24))

    def test_mark_done_then_not_due(self):
        sched = Scheduler(self._state_path)
        sched.mark_done("test_task")
        self.assertFalse(sched.should_run("test_task", 24))

    def test_should_run_after_interval(self):
        sched = Scheduler(self._state_path)
        data = {"scheduler": {"test_task": (datetime.now() - timedelta(hours=25)).isoformat()}}
        with open(self._state_path, "w") as f:
            json.dump(data, f)
        self.assertTrue(sched.should_run("test_task", 24))

    def test_mark_done_persists(self):
        sched = Scheduler(self._state_path)
        sched.mark_done("my_task")
        with open(self._state_path) as f:
            data = json.load(f)
        self.assertIn("my_task", data["scheduler"])

    def test_preserves_existing_state(self):
        existing = {"lastChecks": {"calendar": 12345}, "someKey": "value"}
        with open(self._state_path, "w") as f:
            json.dump(existing, f)
        sched = Scheduler(self._state_path)
        sched.mark_done("new_task")
        with open(self._state_path) as f:
            data = json.load(f)
        self.assertEqual(data["lastChecks"]["calendar"], 12345)
        self.assertEqual(data["someKey"], "value")
        self.assertIn("new_task", data["scheduler"])

    def test_next_run_info(self):
        sched = Scheduler(self._state_path)
        sched.mark_done("feedback_analysis")
        info = sched.next_run_info()
        self.assertIsInstance(info, list)
        self.assertEqual(len(info), len(SCHEDULE))
        names = [i["task"] for i in info]
        self.assertIn("feedback_analysis", names)
        for item in info:
            if item["task"] == "feedback_analysis":
                self.assertFalse(item["due"])
                self.assertGreater(item["remaining_hours"], 0)


class TestOrchestratorAgentCompleted(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._state_path = os.path.join(self._tmpdir, "state.json")

    def tearDown(self):
        if os.path.exists(self._state_path):
            os.remove(self._state_path)
        os.rmdir(self._tmpdir)

    @patch("record_agent_stat.record")
    def test_on_agent_completed_success(self, mock_record):
        orch = Orchestrator(self._state_path)
        results = orch.on_agent_completed("coding", "opus", True, "built feature X")
        mock_record.assert_called_once_with("opus", "coding", True, "built feature X")
        self.assertEqual(results["record_agent_stat"], "ok")

    @patch("record_agent_stat.record")
    def test_on_agent_completed_failure(self, mock_record):
        orch = Orchestrator(self._state_path)
        results = orch.on_agent_completed("research", "minimax", False, "timeout")
        mock_record.assert_called_once_with("minimax", "research", False, "timeout")
        self.assertEqual(results["record_agent_stat"], "ok")


class TestOrchestratorHeartbeat(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._state_path = os.path.join(self._tmpdir, "state.json")

    def tearDown(self):
        if os.path.exists(self._state_path):
            os.remove(self._state_path)
        os.rmdir(self._tmpdir)

    def test_on_heartbeat_returns_dict(self):
        orch = Orchestrator(self._state_path)
        for name, cfg in SCHEDULE.items():
            setattr(orch, cfg["fn"], MagicMock(return_value={"mock": True}))
        result = orch.on_heartbeat()
        self.assertIsInstance(result, dict)
        for name in SCHEDULE:
            self.assertIn(name, result)
            self.assertIsInstance(result[name], dict)
            self.assertEqual(result[name]["status"], "ok")

    def test_heartbeat_skips_not_due(self):
        orch = Orchestrator(self._state_path)
        for name, cfg in SCHEDULE.items():
            setattr(orch, cfg["fn"], MagicMock(return_value={}))
        orch.on_heartbeat()
        for name, cfg in SCHEDULE.items():
            getattr(orch, cfg["fn"]).reset_mock()
        result = orch.on_heartbeat()
        for name in SCHEDULE:
            self.assertEqual(result[name], "skipped (not due)")


class TestOrchestratorRecommendModel(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._state_path = os.path.join(self._tmpdir, "state.json")

    def tearDown(self):
        if os.path.exists(self._state_path):
            os.remove(self._state_path)
        os.rmdir(self._tmpdir)

    def test_recommend_model_returns_dict(self):
        orch = Orchestrator(self._state_path)
        try:
            result = orch.recommend_model("写一个Python脚本处理CSV文件")
            self.assertIsInstance(result, dict)
            self.assertIn("model", result)
        except ImportError:
            self.skipTest("model_router not available")


class TestOrchestratorStatus(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._state_path = os.path.join(self._tmpdir, "state.json")

    def tearDown(self):
        if os.path.exists(self._state_path):
            os.remove(self._state_path)
        os.rmdir(self._tmpdir)

    def test_status_structure(self):
        orch = Orchestrator(self._state_path)
        status = orch.status()
        self.assertIn("modules", status)
        self.assertIn("schedule", status)
        self.assertGreaterEqual(len(status["modules"]), 7)
        self.assertEqual(len(status["schedule"]), len(SCHEDULE))

    def test_status_modules_importable(self):
        orch = Orchestrator(self._state_path)
        status = orch.status()
        self.assertIsInstance(status["modules"], dict)


if __name__ == "__main__":
    unittest.main()
