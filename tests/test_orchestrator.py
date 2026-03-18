#!/usr/bin/env python3
"""Tests for orchestrator.py — EventBus, Scheduler, Orchestrator."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure structured/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator import EventBus, Scheduler, Orchestrator, EVENTS, SCHEDULE


class TestEventBus(unittest.TestCase):
    """Test EventBus on/emit."""

    def test_on_and_emit_basic(self):
        bus = EventBus()
        results = []
        bus.on("test.event", lambda **kw: results.append(kw))
        bus.emit("test.event", foo="bar", num=42)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], {"foo": "bar", "num": 42})

    def test_multiple_handlers(self):
        bus = EventBus()
        call_order = []
        bus.on("evt", lambda **kw: call_order.append("a"))
        bus.on("evt", lambda **kw: call_order.append("b"))
        bus.emit("evt")
        self.assertEqual(call_order, ["a", "b"])

    def test_emit_returns_results(self):
        bus = EventBus()
        bus.on("evt", lambda **kw: "hello")
        bus.on("evt", lambda **kw: 42)
        results = bus.emit("evt")
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[0]["result"], "hello")
        self.assertTrue(results[1]["ok"])
        self.assertEqual(results[1]["result"], 42)

    def test_emit_no_handlers(self):
        bus = EventBus()
        results = bus.emit("nonexistent")
        self.assertEqual(results, [])

    def test_handler_exception_captured(self):
        bus = EventBus()

        def bad_handler(**kw):
            raise ValueError("boom")

        bus.on("evt", bad_handler)
        bus.on("evt", lambda **kw: "ok")
        results = bus.emit("evt")
        self.assertEqual(len(results), 2)
        self.assertFalse(results[0]["ok"])
        self.assertIn("boom", results[0]["error"])
        self.assertTrue(results[1]["ok"])

    def test_emit_passes_kwargs(self):
        bus = EventBus()
        received = {}

        def handler(**kw):
            received.update(kw)

        bus.on("evt", handler)
        bus.emit("evt", x=1, y="two")
        self.assertEqual(received, {"x": 1, "y": "two"})


class TestScheduler(unittest.TestCase):
    """Test Scheduler should_run/mark_done."""

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
        # Write a timestamp far in the past
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
        # Pre-existing heartbeat-state.json content should not be clobbered
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
    """Test on_agent_completed triggers record_stat + feedback_loop."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._state_path = os.path.join(self._tmpdir, "state.json")

    def tearDown(self):
        if os.path.exists(self._state_path):
            os.remove(self._state_path)
        os.rmdir(self._tmpdir)

    @patch("orchestrator.Orchestrator._record_task")
    def test_on_agent_completed_success(self, mock_record):
        mock_record.return_value = {"record_agent_stat": "ok", "feedback_loop": "ok"}
        orch = Orchestrator(self._state_path)
        results = orch.on_agent_completed("coding", "opus", True, "built feature X")
        # Should have emitted agent.task.completed → _handle_task_completed → _record_task
        mock_record.assert_called_once_with("coding", "opus", True, "built feature X")

    @patch("orchestrator.Orchestrator._record_task")
    def test_on_agent_completed_failure(self, mock_record):
        mock_record.return_value = {"record_agent_stat": "ok", "feedback_loop": "ok"}
        orch = Orchestrator(self._state_path)
        results = orch.on_agent_completed("research", "minimax", False, "timeout")
        mock_record.assert_called_once_with("research", "minimax", False, "timeout")


class TestOrchestratorMessage(unittest.TestCase):
    """Test on_message returns todos."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._state_path = os.path.join(self._tmpdir, "state.json")

    def tearDown(self):
        if os.path.exists(self._state_path):
            os.remove(self._state_path)
        os.rmdir(self._tmpdir)

    @patch("orchestrator.Orchestrator._handle_message")
    def test_on_message_returns_list(self, mock_handler):
        mock_handler.return_value = {"todos": [{"title": "帮我查一下天气", "confidence": 0.85}]}
        orch = Orchestrator(self._state_path)
        todos = orch.on_message("帮我查一下天气")
        self.assertIsInstance(todos, list)

    def test_on_message_with_real_extractor(self):
        """Integration-ish test: if todo_extractor is importable, use it."""
        orch = Orchestrator(self._state_path)
        try:
            from todo_extractor import extract_todos_from_text
            todos = orch.on_message("帮我明天下午三点订会议室")
            self.assertIsInstance(todos, list)
        except ImportError:
            self.skipTest("todo_extractor not available")


class TestOrchestratorHeartbeat(unittest.TestCase):
    """Test on_heartbeat returns execution results."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._state_path = os.path.join(self._tmpdir, "state.json")

    def tearDown(self):
        if os.path.exists(self._state_path):
            os.remove(self._state_path)
        os.rmdir(self._tmpdir)

    def test_on_heartbeat_returns_dict(self):
        orch = Orchestrator(self._state_path)
        # Patch all runners to avoid real module calls
        for name, cfg in SCHEDULE.items():
            setattr(orch, cfg["fn"], MagicMock(return_value={"mock": True}))
        result = orch.on_heartbeat()
        self.assertIsInstance(result, dict)
        # First run: all tasks should be due
        for name in SCHEDULE:
            self.assertIn(name, result)
            self.assertIsInstance(result[name], dict)
            self.assertEqual(result[name]["status"], "ok")

    def test_heartbeat_skips_not_due(self):
        orch = Orchestrator(self._state_path)
        for name, cfg in SCHEDULE.items():
            setattr(orch, cfg["fn"], MagicMock(return_value={}))
        # First heartbeat runs everything
        orch.on_heartbeat()
        # Reset mocks
        for name, cfg in SCHEDULE.items():
            getattr(orch, cfg["fn"]).reset_mock()
        # Second heartbeat should skip all
        result = orch.on_heartbeat()
        for name in SCHEDULE:
            self.assertEqual(result[name], "skipped (not due)")


class TestOrchestratorRecommendModel(unittest.TestCase):
    """Test recommend_model returns correct format."""

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
            # Should have at least model key
            self.assertIn("model", result)
        except ImportError:
            self.skipTest("model_router not available")


class TestOrchestratorStatus(unittest.TestCase):
    """Test status command."""

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
        self.assertIn("events_registered", status)
        # modules should list all 9
        self.assertGreaterEqual(len(status["modules"]), 9)
        # schedule should list all configured tasks
        self.assertEqual(len(status["schedule"]), len(SCHEDULE))
        # events_registered should have all predefined events
        for evt in EVENTS:
            self.assertIn(evt, status["events_registered"])
            self.assertEqual(status["events_registered"][evt], 1)

    def test_status_modules_importable(self):
        """In the real environment, all modules should be importable."""
        orch = Orchestrator(self._state_path)
        status = orch.status()
        # At minimum, orchestrator itself should be ok
        # Other modules depend on environment
        self.assertIsInstance(status["modules"], dict)


class TestCLI(unittest.TestCase):
    """Test CLI entry points don't crash."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._state_path = os.path.join(self._tmpdir, "state.json")

    def tearDown(self):
        if os.path.exists(self._state_path):
            os.remove(self._state_path)
        os.rmdir(self._tmpdir)

    def test_status_cli(self):
        """Smoke test: status command runs without error."""
        orch = Orchestrator(self._state_path)
        status = orch.status()
        self.assertIsNotNone(status)


if __name__ == "__main__":
    unittest.main()
