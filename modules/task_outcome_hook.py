#!/usr/bin/env python3
"""
Task Outcome Hook — 任务结果自动记录。

职责：
- 提供轻量 API，在每次任务完成后记录结果
- 自动写入 task_outcomes 表（供 feedback_loop、capability_model、causal_validator 消费）
- 同时写入 observations 表（供记忆检索）
- 支持从 OpenClaw 主 agent 的工作流中调用

用法：
    from task_outcome_hook import record, record_success, record_failure

    # 完整记录
    record("coding", "minimax", True, "子Agent完成代码修改", notes="一次通过")

    # 快捷方式
    record_success("coding", "opus", "完成 schema 修复")
    record_failure("research", "minimax", "搜索超时", notes="API 429")
"""
from __future__ import annotations

import sys
import json
from datetime import datetime
from pathlib import Path

_modules = Path(__file__).parent
_workspace = _modules.parent
for p in [str(_workspace), str(_modules)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from runtime_config import XMEMORY_PATH
    if str(XMEMORY_PATH) not in sys.path:
        sys.path.insert(0, str(XMEMORY_PATH))
except ImportError:
    pass

from db_common import get_db


def record(
    task_type: str,
    model: str,
    success: bool,
    description: str = "",
    notes: str = "",
    tags: str = "",
    critic_score: int = None,
    write_observation: bool = True,
) -> dict:
    """Record a task outcome.

    Args:
        task_type: coding, research, file_ops, deploy, exploration, external_learning, etc.
        model: Which model executed (opus, minimax, kimi, etc.)
        success: Whether the task succeeded
        description: What the task was about
        notes: Additional context (error messages, retry info, etc.)
        tags: Comma-separated tags
        critic_score: Optional quality score (0-100)
        write_observation: Also write to observations table for memory retrieval

    Returns:
        {"outcome_id": int, "observation_id": int|None, "message": str}
    """
    db = get_db()
    try:
        # Write to task_outcomes
        cursor = db.execute(
            """INSERT INTO task_outcomes
               (task_type, model, success, description, notes, tags, critic_score)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (task_type, model, int(success), description, notes, tags, critic_score),
        )
        db.commit()
        outcome_id = cursor.lastrowid
    except Exception as e:
        return {"outcome_id": None, "observation_id": None, "message": f"Failed: {e}"}
    finally:
        db.close()

    # Optionally write to observations for memory retrieval
    obs_id = None
    if write_observation:
        try:
            from memory_governor import add_observation as gov_add
            status_str = "✅ 成功" if success else "❌ 失败"
            result = gov_add(
                type="task_outcome",
                title=f"[{task_type}/{model}] {status_str}: {description[:80]}",
                narrative=f"Task: {description}\nNotes: {notes}" if notes else description,
                source="task_outcome_hook",
                tags=f"outcome,{task_type},{model},{'success' if success else 'failure'},{tags}".rstrip(","),
                task_type=task_type,
                origin_module="task_outcome_hook",
                origin_ref=f"outcome_{outcome_id}",
            )
            if result.get("success") and result.get("action") == "created":
                obs_id = result["observation_id"]
        except Exception:
            # Fallback: direct write without governor
            try:
                from memory_store import add_observation
                obs_id = add_observation(
                    type="task_outcome",
                    title=f"[{task_type}/{model}] {'成功' if success else '失败'}: {description[:80]}",
                    narrative=description,
                    source="task_outcome_hook",
                    tags=f"outcome,{task_type},{model}",
                    task_type=task_type,
                )
            except Exception:
                pass

    return {
        "outcome_id": outcome_id,
        "observation_id": obs_id,
        "message": f"Recorded: {task_type}/{model} {'success' if success else 'failure'}",
    }


def record_success(
    task_type: str,
    model: str,
    description: str = "",
    notes: str = "",
    tags: str = "",
    critic_score: int = None,
) -> dict:
    """Shortcut for recording a successful task."""
    return record(task_type, model, True, description, notes, tags, critic_score)


def record_failure(
    task_type: str,
    model: str,
    description: str = "",
    notes: str = "",
    tags: str = "",
    critic_score: int = None,
) -> dict:
    """Shortcut for recording a failed task."""
    return record(task_type, model, False, description, notes, tags, critic_score)


# ============ Batch & Query ============

def get_recent(limit: int = 20, task_type: str = None) -> list[dict]:
    """Get recent task outcomes."""
    db = get_db()
    try:
        if task_type:
            rows = db.execute(
                "SELECT * FROM task_outcomes WHERE task_type = ? ORDER BY created_at DESC LIMIT ?",
                (task_type, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM task_outcomes ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def get_stats() -> dict:
    """Get task outcome statistics."""
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM task_outcomes").fetchone()[0]
        success = db.execute("SELECT COUNT(*) FROM task_outcomes WHERE success = 1").fetchone()[0]
        by_type = {}
        for r in db.execute(
            """SELECT task_type, COUNT(*) as total, SUM(success) as wins
               FROM task_outcomes GROUP BY task_type ORDER BY total DESC"""
        ).fetchall():
            rate = round(r["wins"] / r["total"] * 100, 1) if r["total"] > 0 else 0
            by_type[r["task_type"]] = {
                "total": r["total"],
                "success": r["wins"],
                "rate": rate,
            }
        by_model = {}
        for r in db.execute(
            """SELECT model, COUNT(*) as total, SUM(success) as wins
               FROM task_outcomes GROUP BY model ORDER BY total DESC"""
        ).fetchall():
            rate = round(r["wins"] / r["total"] * 100, 1) if r["total"] > 0 else 0
            by_model[r["model"]] = {
                "total": r["total"],
                "success": r["wins"],
                "rate": rate,
            }
        return {
            "total": total,
            "success": success,
            "failure": total - success,
            "success_rate": round(success / max(total, 1) * 100, 1),
            "by_type": by_type,
            "by_model": by_model,
        }
    finally:
        db.close()


# ============ CLI ============

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Task Outcome Hook")
    sub = parser.add_subparsers(dest="command")

    p_record = sub.add_parser("record", help="Record a task outcome")
    p_record.add_argument("task_type")
    p_record.add_argument("model")
    p_record.add_argument("success", type=int, choices=[0, 1])
    p_record.add_argument("--desc", default="")
    p_record.add_argument("--notes", default="")
    p_record.add_argument("--tags", default="")

    sub.add_parser("stats", help="Show statistics")

    p_recent = sub.add_parser("recent", help="Show recent outcomes")
    p_recent.add_argument("--limit", type=int, default=10)
    p_recent.add_argument("--type", default=None)

    args = parser.parse_args()

    if args.command == "record":
        r = record(args.task_type, args.model, bool(args.success), args.desc, args.notes, args.tags)
        print(f"{'✅' if args.success else '❌'} {r['message']} (id={r['outcome_id']})")

    elif args.command == "stats":
        s = get_stats()
        print(f"Total: {s['total']} (success: {s['success_rate']}%)")
        if s['by_type']:
            print("\nBy type:")
            for t, v in s['by_type'].items():
                print(f"  {t}: {v['total']} ({v['rate']}%)")
        if s['by_model']:
            print("\nBy model:")
            for m, v in s['by_model'].items():
                print(f"  {m}: {v['total']} ({v['rate']}%)")

    elif args.command == "recent":
        for r in get_recent(limit=args.limit, task_type=args.type):
            icon = "✅" if r["success"] else "❌"
            print(f"  {icon} [{r['created_at']}] {r['task_type']}/{r['model']}: {r['description'][:50]}")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
