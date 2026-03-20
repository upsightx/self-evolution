#!/usr/bin/env python3
"""
Self-evolution Scheduler & Orchestrator.

Provides:
- Scheduler: heartbeat-based periodic task scheduling
- Orchestrator: unified entry point wiring all modules together

CLI:
    python3 orchestrator.py heartbeat
    python3 orchestrator.py status
    python3 orchestrator.py event <task_type> <model> <success|fail> [description]

Zero external dependencies. Pure stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent          # memory/structured/
MEMORY_DIR = BASE_DIR.parent                        # memory/
HEARTBEAT_STATE = MEMORY_DIR / "heartbeat-state.json"

# ── Schedule Config ──────────────────────────────────────────────────────────

SCHEDULE = {
    "feedback_analysis":    {"interval_hours": 24,  "fn": "run_feedback_analysis"},
    "auto_memory":          {"interval_hours": 24,  "fn": "run_auto_memory"},
    "model_routing_update": {"interval_hours": 168, "fn": "run_model_routing"},
    "memory_lru":           {"interval_hours": 168, "fn": "run_memory_lru"},
}


# ══════════════════════════════════════════════════════════════════════════════
# Scheduler
# ══════════════════════════════════════════════════════════════════════════════

class Scheduler:
    """Heartbeat-based periodic task scheduler.

    Reads/writes timestamps in heartbeat-state.json under a
    "scheduler" key to avoid colliding with existing fields.
    """

    def __init__(self, state_path: str | None = None):
        self._state_path = Path(state_path) if state_path else HEARTBEAT_STATE

    def _load(self) -> dict:
        if self._state_path.exists():
            with open(self._state_path, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save(self, data: dict):
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def should_run(self, task_name: str, interval_hours: int) -> bool:
        """Check whether *task_name* is due based on elapsed time."""
        data = self._load()
        sched = data.get("scheduler", {})
        last_run = sched.get(task_name)
        if last_run is None:
            return True
        try:
            last_ts = datetime.fromisoformat(last_run)
        except (ValueError, TypeError):
            return True
        elapsed_hours = (datetime.now() - last_ts).total_seconds() / 3600
        return elapsed_hours >= interval_hours

    def mark_done(self, task_name: str):
        """Record that *task_name* just ran."""
        data = self._load()
        sched = data.setdefault("scheduler", {})
        sched[task_name] = datetime.now().isoformat()
        self._save(data)

    def next_run_info(self) -> list[dict]:
        """Return schedule status for every configured task."""
        data = self._load()
        sched = data.get("scheduler", {})
        info = []
        for name, cfg in SCHEDULE.items():
            last_run = sched.get(name)
            if last_run:
                try:
                    last_ts = datetime.fromisoformat(last_run)
                    elapsed_h = (datetime.now() - last_ts).total_seconds() / 3600
                    remaining_h = max(0, cfg["interval_hours"] - elapsed_h)
                except (ValueError, TypeError):
                    remaining_h = 0
            else:
                remaining_h = 0
            info.append({
                "task": name,
                "interval_hours": cfg["interval_hours"],
                "last_run": last_run,
                "remaining_hours": round(remaining_h, 1),
                "due": remaining_h <= 0,
            })
        return info


# ══════════════════════════════════════════════════════════════════════════════
# Orchestrator
# ══════════════════════════════════════════════════════════════════════════════

class Orchestrator:
    """Unified entry point that wires all self-evolution modules together."""

    def __init__(self, state_path: str | None = None):
        self.scheduler = Scheduler(state_path)

    # ── scheduled task runners ───────────────────────────────────────────

    def run_scheduled_tasks(self) -> dict:
        """Run all due scheduled tasks. Returns dict of task_name -> result."""
        executed = {}
        for name, cfg in SCHEDULE.items():
            if self.scheduler.should_run(name, cfg["interval_hours"]):
                fn = getattr(self, cfg["fn"], None)
                if fn is None:
                    executed[name] = "error: runner not found"
                    continue
                try:
                    result = fn()
                    self.scheduler.mark_done(name)
                    executed[name] = {"status": "ok", "result": result}
                except Exception as e:
                    executed[name] = {"status": "error", "error": str(e)}
            else:
                executed[name] = "skipped (not due)"
        return executed

    def run_feedback_analysis(self):
        from feedback_loop import analyze_patterns
        patterns = analyze_patterns()
        return {"patterns_found": len(patterns), "patterns": patterns[:5]}

    def run_model_routing(self):
        from model_router import routing_table, load_stats
        stats = load_stats()
        table = routing_table(stats)
        return {"routing_table": table}

    def run_memory_lru(self):
        from memory_lru import suggest_archive
        suggestions = suggest_archive()
        return {"archive_suggestions": suggestions}

    def run_auto_memory(self):
        """Read today's daily log and auto-extract memories into memory.db."""
        today = datetime.now().strftime("%Y-%m-%d")
        daily_log = MEMORY_DIR / f"{today}.md"
        if not daily_log.exists():
            return {"status": "skipped", "reason": "no daily log for today"}
        text = daily_log.read_text(encoding="utf-8")
        if len(text.strip()) < 50:
            return {"status": "skipped", "reason": "daily log too short"}
        from auto_memory import auto_save
        result = auto_save(text)
        return {"status": "ok", "saved": result.get("saved", 0), "skipped_dupes": result.get("skipped", 0)}

    # ── public API ───────────────────────────────────────────────────────

    def on_agent_completed(self, task_type, model, success, description=""):
        """Called when a sub-agent finishes. Records to both stats and feedback."""
        results = {}
        try:
            from record_agent_stat import record as stat_record
            stat_record(model, task_type, success, description)
            results["record_agent_stat"] = "ok"
        except Exception as e:
            results["record_agent_stat"] = f"error: {e}"
        return results

    def on_heartbeat(self) -> dict:
        """Called on heartbeat tick. Returns dict of executed tasks."""
        return self.run_scheduled_tasks()

    def recommend_model(self, task_description: str) -> dict:
        """Recommend a model for the given task description."""
        from model_router import recommend_for_description
        return recommend_for_description(task_description)

    def search_memory(self, query: str) -> str:
        """Search the memory database."""
        from memory_db import search_with_context
        return search_with_context(query)

    def status(self) -> dict:
        """Return overall status: module health + schedule info + key metrics."""
        modules = {}
        module_checks = {
            "memory_db":         lambda: __import__("memory_db"),
            "memory_store":      lambda: __import__("memory_store"),
            "memory_retrieval":  lambda: __import__("memory_retrieval"),
            "memory_service":    lambda: __import__("memory_service"),
            "model_router":      lambda: __import__("model_router"),
            "feedback_loop":     lambda: __import__("feedback_loop"),
            "memory_lru":        lambda: __import__("memory_lru"),
            "record_agent_stat": lambda: __import__("record_agent_stat"),
        }
        for name, check in module_checks.items():
            try:
                check()
                modules[name] = "ok"
            except Exception as e:
                modules[name] = f"error: {e}"

        # Key metrics
        metrics = {}
        try:
            from memory_db import stats as db_stats
            s = db_stats()
            metrics["observations"] = s.get("observations", 0)
            metrics["decisions"] = s.get("decisions", 0)
            metrics["summaries"] = s.get("summaries", 0)
        except Exception:
            metrics["db"] = "unavailable"

        try:
            from feedback_loop import analyze_patterns
            patterns = analyze_patterns(min_samples=3)
            metrics["problematic_patterns"] = len(patterns)
            if patterns:
                worst = max(patterns, key=lambda p: p["failure_rate"])
                metrics["worst_pattern"] = f"{worst['task_type']}/{worst['model']} ({worst['failure_rate']:.0%} fail)"
        except Exception:
            metrics["feedback"] = "unavailable"

        try:
            from memory_lru import get_hot_memories, get_cold_memories
            metrics["hot_memories"] = len(get_hot_memories(limit=100))
            metrics["cold_memories"] = len(get_cold_memories(days_unused=30, limit=100))
        except Exception:
            pass

        return {
            "modules": modules,
            "metrics": metrics,
            "schedule": self.scheduler.next_run_info(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def _print_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cli():
    parser = argparse.ArgumentParser(description="Self-evolution orchestrator")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("heartbeat", help="Simulate a heartbeat tick")

    ev = sub.add_parser("event", help="Record a task completion event")
    ev.add_argument("task_type", help="Task type, e.g. coding")
    ev.add_argument("model", help="Model name, e.g. opus")
    ev.add_argument("result", choices=["success", "fail"], help="Task result")
    ev.add_argument("--description", default="", help="Optional description")

    sub.add_parser("status", help="Show module status and schedule")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    orch = Orchestrator()

    if args.command == "heartbeat":
        print("⏱  Running heartbeat...")
        result = orch.on_heartbeat()
        _print_json(result)

    elif args.command == "event":
        success = args.result == "success"
        result = orch.on_agent_completed(
            task_type=args.task_type,
            model=args.model,
            success=success,
            description=args.description,
        )
        _print_json(result)

    elif args.command == "status":
        status = orch.status()
        print("═══ Module Status ═══")
        for mod, st in status["modules"].items():
            icon = "✅" if st == "ok" else "❌"
            print(f"  {icon} {mod}: {st}")

        print("\n═══ Key Metrics ═══")
        m = status.get("metrics", {})
        if "observations" in m:
            print(f"  📊 Memory DB: {m['observations']} observations, {m['decisions']} decisions, {m['summaries']} summaries")
        if "problematic_patterns" in m:
            print(f"  ⚠️  Problematic patterns: {m['problematic_patterns']}")
            if m.get("worst_pattern"):
                print(f"     Worst: {m['worst_pattern']}")
        if "hot_memories" in m:
            print(f"  🔥 Hot memories: {m['hot_memories']} | ❄️  Cold: {m['cold_memories']}")

        print("\n═══ Schedule ═══")
        for s in status["schedule"]:
            icon = "🔴" if s["due"] else "🟢"
            last = s["last_run"][:16] if s["last_run"] else "never"
            print(f"  {icon} {s['task']}: every {s['interval_hours']}h | "
                  f"last: {last} | remaining: {s['remaining_hours']}h")


if __name__ == "__main__":
    cli()
