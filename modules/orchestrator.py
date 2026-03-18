#!/usr/bin/env python3
"""
Unified Orchestrator for self-evolution modules.

Provides:
- EventBus: simple pub/sub event system
- Scheduler: heartbeat-based periodic task scheduling
- Orchestrator: main entry point wiring all modules together

CLI:
    python3 orchestrator.py heartbeat
    python3 orchestrator.py event <event_name> [--model X] [--task-type Y] [--success true/false] [--description Z]
    python3 orchestrator.py status

Zero external dependencies. Pure stdlib.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent          # memory/structured/
MEMORY_DIR = BASE_DIR.parent                        # memory/
HEARTBEAT_STATE = MEMORY_DIR / "heartbeat-state.json"

# ── Predefined Events ────────────────────────────────────────────────────────

EVENTS = [
    "agent.task.completed",
    "agent.task.failed",
    "conversation.message",
    "heartbeat.tick",
    "memory.updated",
]

# ── Schedule Config ──────────────────────────────────────────────────────────

SCHEDULE = {
    "feedback_analysis":   {"interval_hours": 24,  "fn": "run_feedback_analysis"},
    "model_routing_update": {"interval_hours": 168, "fn": "run_model_routing"},
    "memory_lru":          {"interval_hours": 168, "fn": "run_memory_lru"},
    "skill_gap_scan":      {"interval_hours": 168, "fn": "run_skill_gap_scan"},
    "decision_review":     {"interval_hours": 336, "fn": "run_decision_review"},
}


# ══════════════════════════════════════════════════════════════════════════════
# EventBus
# ══════════════════════════════════════════════════════════════════════════════

class EventBus:
    """Simple synchronous event bus."""

    def __init__(self):
        self._handlers: dict[str, list[callable]] = {}

    def on(self, event: str, handler: callable):
        """Register a handler for an event."""
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, **data) -> list:
        """Emit an event, calling all registered handlers. Returns list of results."""
        results = []
        for handler in self._handlers.get(event, []):
            hname = getattr(handler, "__name__", repr(handler))
            try:
                result = handler(**data)
                results.append({"handler": hname, "ok": True, "result": result})
            except Exception as e:
                results.append({"handler": hname, "ok": False, "error": str(e)})
        return results


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
                    last_ts = None
                    remaining_h = 0
            else:
                last_ts = None
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
        self.bus = EventBus()
        self.scheduler = Scheduler(state_path)
        self._register_handlers()

    # ── handler registration ─────────────────────────────────────────────

    def _register_handlers(self):
        self.bus.on("agent.task.completed", self._handle_task_completed)
        self.bus.on("agent.task.failed", self._handle_task_failed)
        self.bus.on("conversation.message", self._handle_message)
        self.bus.on("heartbeat.tick", self._handle_heartbeat)
        self.bus.on("memory.updated", self._handle_memory_updated)

    # ── internal event handlers ──────────────────────────────────────────

    def _handle_task_completed(self, task_type="general", model="unknown",
                                description="", **_kw):
        return self._record_task(task_type, model, True, description)

    def _handle_task_failed(self, task_type="general", model="unknown",
                             description="", **_kw):
        return self._record_task(task_type, model, False, description)

    def _record_task(self, task_type, model, success, description):
        results = {}
        # 1) record_agent_stat
        try:
            from record_agent_stat import record as stat_record
            stat_record(model, task_type, success, description)
            results["record_agent_stat"] = "ok"
        except Exception as e:
            results["record_agent_stat"] = f"error: {e}"

        # 2) feedback_loop.record_task_outcome
        try:
            from feedback_loop import record_task_outcome
            record_task_outcome(
                task_id=None,
                task_type=task_type,
                model=model,
                expected=None,
                actual=description or None,
                success=success,
                notes=description or None,
            )
            results["feedback_loop"] = "ok"
        except Exception as e:
            results["feedback_loop"] = f"error: {e}"

        return results

    def _handle_message(self, text="", **_kw):
        try:
            from todo_extractor import extract_todos_from_text
            todos = extract_todos_from_text(text)
            return {"todos": todos}
        except Exception as e:
            return {"todos": [], "error": str(e)}

    def _handle_heartbeat(self, **_kw):
        return self._run_scheduled_tasks()

    def _handle_memory_updated(self, **_kw):
        # Placeholder for future embedding refresh
        return {"embedding_update": "skipped (no embedding engine configured)"}

    # ── scheduled task runners ───────────────────────────────────────────

    def _run_scheduled_tasks(self) -> dict:
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

    def run_skill_gap_scan(self):
        from skill_discovery import generate_report
        report = generate_report()
        return {"report_length": len(report) if report else 0}

    def run_decision_review(self):
        from decision_review import get_unreviewed_decisions, generate_review_report
        pending = get_unreviewed_decisions()
        report = generate_review_report()
        return {"pending_reviews": len(pending), "report_length": len(report) if report else 0}

    # ── public API ───────────────────────────────────────────────────────

    def on_agent_completed(self, task_type, model, success, description=""):
        """Called when a sub-agent finishes."""
        event = "agent.task.completed" if success else "agent.task.failed"
        return self.bus.emit(event, task_type=task_type, model=model,
                             description=description)

    def on_message(self, text: str) -> list:
        """Called on incoming conversation message. Returns extracted todos."""
        results = self.bus.emit("conversation.message", text=text)
        for r in results:
            if r.get("ok") and isinstance(r.get("result"), dict):
                return r["result"].get("todos", [])
        return []

    def on_heartbeat(self) -> dict:
        """Called on heartbeat tick. Returns dict of executed tasks."""
        results = self.bus.emit("heartbeat.tick")
        for r in results:
            if r.get("ok") and isinstance(r.get("result"), dict):
                return r["result"]
        return {}

    def recommend_model(self, task_description: str) -> dict:
        """Recommend a model for the given task description."""
        from model_router import recommend_for_description
        return recommend_for_description(task_description)

    def get_template(self, task_type: str, **kwargs) -> str:
        """Get a sub-agent prompt template."""
        from template_manager import TemplateManager
        mgr = TemplateManager()
        return mgr.get_template(task_type, **kwargs)

    def search_memory(self, query: str, mode="hybrid") -> str:
        """Search the memory database."""
        from memory_db import search_with_context
        return search_with_context(query)

    def status(self) -> dict:
        """Return overall status: module health + schedule info."""
        modules = {}
        module_checks = {
            "memory_db":       lambda: __import__("memory_db"),
            "model_router":    lambda: __import__("model_router"),
            "feedback_loop":   lambda: __import__("feedback_loop"),
            "memory_lru":      lambda: __import__("memory_lru"),
            "skill_discovery": lambda: __import__("skill_discovery"),
            "decision_review": lambda: __import__("decision_review"),
            "record_agent_stat": lambda: __import__("record_agent_stat"),
            "todo_extractor":  lambda: __import__("todo_extractor"),
            "template_manager": lambda: __import__("template_manager"),
        }
        for name, check in module_checks.items():
            try:
                check()
                modules[name] = "ok"
            except Exception as e:
                modules[name] = f"error: {e}"

        return {
            "modules": modules,
            "schedule": self.scheduler.next_run_info(),
            "events_registered": {
                evt: len(self.bus._handlers.get(evt, []))
                for evt in EVENTS
            },
        }


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def _print_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cli():
    parser = argparse.ArgumentParser(description="Self-evolution orchestrator")
    sub = parser.add_subparsers(dest="command")

    # heartbeat
    sub.add_parser("heartbeat", help="Simulate a heartbeat tick")

    # event
    ev = sub.add_parser("event", help="Emit an event")
    ev.add_argument("event_name", help="Event name, e.g. agent.task.completed")
    ev.add_argument("--model", default="unknown")
    ev.add_argument("--task-type", default="general")
    ev.add_argument("--success", default="true")
    ev.add_argument("--description", default="")

    # status
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
        success = args.success.lower() in ("true", "1", "yes")
        print(f"📡 Emitting {args.event_name}...")
        if args.event_name in ("agent.task.completed", "agent.task.failed"):
            result = orch.on_agent_completed(
                task_type=args.task_type,
                model=args.model,
                success=(args.event_name == "agent.task.completed") and success,
                description=args.description,
            )
            _print_json(result)
        elif args.event_name == "conversation.message":
            todos = orch.on_message(args.description or "test message")
            _print_json(todos)
        else:
            result = orch.bus.emit(args.event_name)
            _print_json(result)

    elif args.command == "status":
        status = orch.status()
        print("═══ Module Status ═══")
        for mod, st in status["modules"].items():
            icon = "✅" if st == "ok" else "❌"
            print(f"  {icon} {mod}: {st}")
        print("\n═══ Schedule ═══")
        for s in status["schedule"]:
            icon = "🔴" if s["due"] else "🟢"
            last = s["last_run"][:16] if s["last_run"] else "never"
            print(f"  {icon} {s['task']}: every {s['interval_hours']}h | "
                  f"last: {last} | remaining: {s['remaining_hours']}h")
        print(f"\n═══ Event Handlers ═══")
        for evt, count in status["events_registered"].items():
            print(f"  📡 {evt}: {count} handler(s)")


if __name__ == "__main__":
    cli()
