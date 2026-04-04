#!/usr/bin/env python3
"""
Causal Validator — 归因验证器。

职责：
- 验证进化变更是否真正有效
- 对比变更前后的任务成功率
- 输出归因结论：effective / uncertain / ineffective

工作原理：
1. 查询 evolution_changes 表中待验证的变更
2. 收集变更后该 task_type 的执行记录
3. 对比变更前后的成功率（需要足够样本）
4. 判定归因结论并写回数据库

归因规则：
- effective: 变更后成功率提升 ≥ 15%，且样本数 ≥ 5
- ineffective: 变更后成功率下降或无显著变化（< 5% 提升）
- uncertain: 样本数不足（< 5）或变化幅度在 5-15% 之间
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from db_common import get_db, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS evolution_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id TEXT NOT NULL UNIQUE,
    task_type TEXT NOT NULL,
    suggestion TEXT NOT NULL,
    target_file TEXT NOT NULL,
    change_description TEXT,
    status TEXT NOT NULL DEFAULT 'applied',
    applied_at TEXT DEFAULT (datetime('now')),
    verified_at TEXT,
    verdict TEXT,
    backup_path TEXT
);
"""


def _ensure_table():
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()
    db.close()


# Minimum samples for verification
MIN_SAMPLES = 5

# Significance thresholds
EFFECTIVE_THRESHOLD = 0.15  # 15% improvement
UNCERTAIN_THRESHOLD = 0.05  # 5% improvement

# Verdicts
VERDICT_EFFECTIVE = "effective"
VERDICT_INEFFECTIVE = "ineffective"
VERDICT_UNCERTAIN = "uncertain"
VERDICT_PENDING = "pending"  # Not enough samples yet


def _get_baseline_success_rate(task_type: str, before_time: str) -> tuple[float, int]:
    """Get the baseline success rate before a change was applied.

    Looks at the 20 most recent task outcomes before the change.

    Returns:
        (success_rate, sample_count)
    """
    db = get_db()
    try:
        rows = db.execute(
            """SELECT success FROM task_outcomes
               WHERE task_type = ? AND created_at < ?
               ORDER BY created_at DESC LIMIT 20""",
            (task_type, before_time),
        ).fetchall()

        if not rows:
            return 0.0, 0

        successes = sum(1 for r in rows if r["success"])
        return successes / len(rows), len(rows)
    finally:
        db.close()


def _get_post_success_rate(task_type: str, after_time: str) -> tuple[float, int]:
    """Get the success rate after a change was applied.

    Looks at all task outcomes after the change.

    Returns:
        (success_rate, sample_count)
    """
    db = get_db()
    try:
        rows = db.execute(
            """SELECT success FROM task_outcomes
               WHERE task_type = ? AND created_at >= ?
               ORDER BY created_at DESC""",
            (task_type, after_time),
        ).fetchall()

        if not rows:
            return 0.0, 0

        successes = sum(1 for r in rows if r["success"])
        return successes / len(rows), len(rows)
    finally:
        db.close()


def _update_goal_progress_for_task_type(task_type: str, improvement: float) -> bool:
    """Update goal progress for goals related to this task_type.

    Maps task_type to goal metrics and increments current_value proportionally.

    Returns:
        True if any goal was updated
    """
    # Map task types to goal metric patterns
    goal_metric_map = {
        "coding": "coding_success_rate",
        "research": "research_success_rate",
        "exploration": "exploration",
        "deploy": "deploy",
    }

    target_metric = goal_metric_map.get(task_type)
    if not target_metric:
        return False

    try:
        # Add modules to path
        import sys
        modules_path = Path(__file__).parent
        if str(modules_path) not in sys.path:
            sys.path.insert(0, str(modules_path))

        from goal_tree import list_goals, update_goal

        # Find goals with matching metric
        goals = list_goals(status="active")
        updated = False

        for goal in goals:
            metric = goal.get("metric", "")
            if target_metric.lower() in metric.lower():
                # Increase current_value by improvement * target_value
                target_val = goal.get("target_value", 100)
                increment = improvement * target_val
                new_value = min(goal.get("current_value", 0) + increment, target_val)

                if update_goal(goal["id"], current_value=round(new_value, 1)):
                    print(f"[causal_validator] Updated goal #{goal['id']} ({goal['title']}): "
                          f"{goal['current_value']:.1f} → {new_value:.1f}")
                    updated = True

        return updated

    except Exception as e:
        print(f"[causal_validator] Goal update error: {e}")
        return False


def validate_change(change_id: str, auto_update_goal: bool = True) -> dict:
    """Validate a single evolution change.

    Args:
        change_id: The change ID to validate
        auto_update_goal: If True and verdict is 'effective', auto-update related goal progress

    Returns:
        {
            "change_id": str,
            "task_type": str,
            "verdict": "effective" | "ineffective" | "uncertain",
            "baseline_rate": float,
            "post_rate": float,
            "baseline_samples": int,
            "post_samples": int,
            "improvement": float,
            "goal_updated": bool,
            "message": str,
        }
    """
    db = get_db()

    try:
        row = db.execute(
            "SELECT * FROM evolution_changes WHERE change_id = ?",
            (change_id,),
        ).fetchone()

        if not row:
            return {
                "change_id": change_id,
                "task_type": "",
                "verdict": "uncertain",
                "baseline_rate": 0,
                "post_rate": 0,
                "baseline_samples": 0,
                "post_samples": 0,
                "improvement": 0,
                "message": f"Change {change_id} not found",
            }

        task_type = row["task_type"]
        applied_at = row["applied_at"]

        # Get baseline (before change)
        baseline_rate, baseline_samples = _get_baseline_success_rate(task_type, applied_at)

        # Get post-change rate
        post_rate, post_samples = _get_post_success_rate(task_type, applied_at)

        # Calculate improvement
        improvement = post_rate - baseline_rate

        # Determine verdict
        if post_samples < MIN_SAMPLES:
            verdict = VERDICT_PENDING
            message = f"Waiting for more samples: {post_samples}/{MIN_SAMPLES} (need {MIN_SAMPLES - post_samples} more)"
        elif improvement >= EFFECTIVE_THRESHOLD:
            verdict = VERDICT_EFFECTIVE
            message = f"Success rate improved: {baseline_rate:.0%} → {post_rate:.0%} (+{improvement:.0%})"
        elif improvement >= UNCERTAIN_THRESHOLD:
            verdict = VERDICT_UNCERTAIN
            message = f"Marginal improvement: {baseline_rate:.0%} → {post_rate:.0%} (+{improvement:.0%})"
        else:
            verdict = VERDICT_INEFFECTIVE
            message = f"No significant improvement: {baseline_rate:.0%} → {post_rate:.0%} ({improvement:+.0%})"

        # Update database
        db.execute(
            """UPDATE evolution_changes
               SET status = 'verified', verdict = ?, verified_at = ?
               WHERE change_id = ?""",
            (verdict, datetime.now().isoformat(), change_id),
        )
        db.commit()

        # Auto-update goal progress if effective
        goal_updated = False
        if auto_update_goal and verdict == "effective" and improvement > 0:
            try:
                goal_updated = _update_goal_progress_for_task_type(task_type, improvement)
            except Exception as e:
                print(f"[causal_validator] ⚠️ Goal update failed: {e}")

        print(f"[causal_validator] Change #{change_id}: {verdict}")
        print(f"  {message}")
        print(f"  Baseline: {baseline_rate:.0%} (n={baseline_samples})")
        print(f"  Post:     {post_rate:.0%} (n={post_samples})")
        if goal_updated:
            print(f"  ✅ Goal progress updated")

        return {
            "change_id": change_id,
            "task_type": task_type,
            "verdict": verdict,
            "baseline_rate": round(baseline_rate, 3),
            "post_rate": round(post_rate, 3),
            "baseline_samples": baseline_samples,
            "post_samples": post_samples,
            "improvement": round(improvement, 3),
            "goal_updated": goal_updated,
            "message": message,
        }

    except Exception as e:
        return {
            "change_id": change_id,
            "task_type": "",
            "verdict": "uncertain",
            "baseline_rate": 0,
            "post_rate": 0,
            "baseline_samples": 0,
            "post_samples": 0,
            "improvement": 0,
            "message": f"Validation error: {e}",
        }
    finally:
        db.close()


def validate_all_pending(auto_update_goal: bool = True) -> list[dict]:
    """Validate all pending (applied but not verified) changes.

    Args:
        auto_update_goal: If True, auto-update goal progress for effective changes

    Returns:
        List of validation results
    """
    db = get_db()

    try:
        pending = db.execute(
            "SELECT change_id FROM evolution_changes WHERE status = 'applied'"
        ).fetchall()

        results = []
        for row in pending:
            result = validate_change(row["change_id"], auto_update_goal=auto_update_goal)
            results.append(result)

        return results

    finally:
        db.close()


def get_verification_report() -> dict:
    """Get a summary report of all verified changes.

    Returns:
        {
            "total_changes": int,
            "effective": int,
            "ineffective": int,
            "uncertain": int,
            "changes": list,
        }
    """
    _ensure_table()
    db = get_db()

    try:
        total = db.execute("SELECT COUNT(*) FROM evolution_changes").fetchone()[0]
        by_verdict = {}
        for r in db.execute(
            "SELECT verdict, COUNT(*) as c FROM evolution_changes WHERE verdict IS NOT NULL GROUP BY verdict"
        ).fetchall():
            by_verdict[r["verdict"]] = r["c"]

        changes = db.execute(
            "SELECT * FROM evolution_changes ORDER BY applied_at DESC LIMIT 20"
        ).fetchall()

        return {
            "total_changes": total,
            "effective": by_verdict.get("effective", 0),
            "ineffective": by_verdict.get("ineffective", 0),
            "uncertain": by_verdict.get("uncertain", 0),
            "pending": by_verdict.get("pending", 0),
            "changes": [dict(c) for c in changes],
        }

    finally:
        db.close()


# ============ CLI ============

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Causal Validator")
    sub = parser.add_subparsers(dest="command")

    # validate
    p_validate = sub.add_parser("validate", help="Validate a change")
    p_validate.add_argument("change_id", nargs="?", default=None)

    # report
    sub.add_parser("report", help="Verification report")

    # pending
    sub.add_parser("pending", help="List changes waiting for more samples")

    args = parser.parse_args()

    if args.command == "validate":
        if args.change_id:
            result = validate_change(args.change_id)
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            results = validate_all_pending()
            if not results:
                print("No pending changes to validate")
            for r in results:
                icon = {"effective": "✅", "ineffective": "❌", "uncertain": "❓", "pending": "⏳"}.get(r["verdict"], "•")
                print(f"  {icon} [{r['verdict']}] #{r['change_id']}: {r['message']}")

    elif args.command == "report":
        report = get_verification_report()
        print(f"Total Changes: {report['total_changes']}")
        print(f"  ✅ Effective: {report['effective']}")
        print(f"  ❌ Ineffective: {report['ineffective']}")
        print(f"  ❓ Uncertain: {report['uncertain']}")
        print(f"  ⏳ Pending: {report.get('pending', 0)}")
        print()
        for c in report["changes"][:10]:
            status = c.get("verdict", "pending")
            icon = {"effective": "✅", "ineffective": "❌", "uncertain": "❓", "pending": "⏳", None: "🟡"}.get(status, "•")
            print(f"  {icon} #{c['change_id']}: {c['task_type']} → {c.get('verdict', 'pending')}")

    elif args.command == "pending":
        db = get_db()
        try:
            pending = db.execute(
                """SELECT change_id, task_type, applied_at FROM evolution_changes
                   WHERE status = 'applied' ORDER BY applied_at DESC"""
            ).fetchall()
            if not pending:
                print("No changes waiting for samples")
            else:
                print(f"Changes waiting for more samples:")
                for p in pending:
                    # Count post-change samples
                    post_count = db.execute(
                        "SELECT COUNT(*) as c FROM task_outcomes WHERE task_type = ? AND created_at >= ?",
                        (p["task_type"], p["applied_at"])
                    ).fetchone()["c"]
                    remaining = max(0, MIN_SAMPLES - post_count)
                    print(f"  ⏳ #{p['change_id']}: {p['task_type']} ({post_count}/{MIN_SAMPLES} samples, need {remaining} more)")
        finally:
            db.close()

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
