#!/usr/bin/env python3
"""
Causal Validator — 归因验证器。

职责：
- 验证进化提案（proposals）是否真正有效
- 对比变更前后的任务成功率
- 输出归因结论：effective / uncertain / ineffective

数据源（优先级）：
1. proposals 表（proposal_lifecycle_manager 管理，唯一真源）
2. evolution_changes 表（legacy 只读兼容，不写回）

归因规则：
- effective: 变更后成功率提升 ≥ 15%，且样本数 ≥ 5
- ineffective: 变更后成功率下降或无显著变化（< 5% 提升）
- uncertain: 样本数不足（< 5）或变化幅度在 5-15% 之间
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from db_common import get_db

# Minimum samples for verification
MIN_SAMPLES = 5

# Significance thresholds
EFFECTIVE_THRESHOLD = 0.15
UNCERTAIN_THRESHOLD = 0.05

# Verdicts
VERDICT_EFFECTIVE = "effective"
VERDICT_INEFFECTIVE = "ineffective"
VERDICT_UNCERTAIN = "uncertain"
VERDICT_PENDING = "pending"


def _get_baseline_success_rate(task_type: str, before_time: str) -> tuple[float, int]:
    """Get baseline success rate before a change. Looks at 20 most recent outcomes."""
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
    """Get success rate after a change."""
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
    """Update goal progress for goals related to this task_type."""
    try:
        import sys
        modules_path = Path(__file__).parent
        if str(modules_path) not in sys.path:
            sys.path.insert(0, str(modules_path))
        from goal_tree import list_goals, update_goal

        goals = list_goals(status="active")
        updated = False
        for goal in goals:
            linked_types = goal.get("linked_task_types", [])
            if isinstance(linked_types, str):
                linked_types = [t.strip() for t in linked_types.split(",") if t.strip()]

            matched = False
            if linked_types and task_type in linked_types:
                matched = True

            if not matched:
                metric = goal.get("metric", "").lower()
                task_lower = task_type.lower()
                synonyms = {
                    "coding": ["coding", "code", "programming", "dev"],
                    "research": ["research", "study", "analysis"],
                    "exploration": ["exploration", "explore", "discover"],
                    "deploy": ["deploy", "deployment", "release"],
                    "external_learning": ["learning", "study", "knowledge"],
                }
                keywords = synonyms.get(task_lower, [task_lower])
                if any(kw in metric for kw in keywords):
                    matched = True

            if matched:
                target_val = goal.get("target_value", 100)
                increment = improvement * target_val
                new_value = min(goal.get("current_value", 0) + increment, target_val)
                if update_goal(goal["id"], current_value=round(new_value, 1)):
                    print(f"[causal_validator] Updated goal #{goal['id']}: {goal['current_value']:.1f} → {new_value:.1f}")
                    updated = True
        return updated
    except Exception as e:
        print(f"[causal_validator] Goal update error: {e}")
        return False


# ============ Proposal-based validation (primary) ============

def _get_proposals_pending_validation() -> list[dict]:
    """Get proposals in 'experimenting' status that need validation."""
    db = get_db()
    try:
        rows = db.execute(
            """SELECT proposal_id, category, created_at, updated_at
               FROM proposals WHERE status = 'experimenting'
               ORDER BY created_at ASC"""
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        db.close()


def _update_proposal_verdict(proposal_id: str, verdict: str, evidence: dict) -> bool:
    """Write verdict back to proposals via lifecycle manager."""
    try:
        from proposal_lifecycle_manager import transition, attach_evidence
        attach_evidence(proposal_id, "causal_validation",
                       json.dumps(evidence, default=str),
                       description=f"verdict={verdict}")
        if verdict == VERDICT_EFFECTIVE:
            transition(proposal_id, "validated", actor="causal_validator",
                      reason=f"Effective: +{evidence.get('improvement', 0):.0%}")
            return True
        elif verdict == VERDICT_INEFFECTIVE:
            # State machine allows experimenting → failed (not rejected)
            transition(proposal_id, "failed", actor="causal_validator",
                      reason=f"Ineffective: {evidence.get('improvement', 0):+.0%}")
            return True
        # pending/uncertain: stay in experimenting
        return True
    except Exception as e:
        print(f"[causal_validator] Proposal update error: {e}")
        return False


def validate_proposal(proposal_id: str, auto_update_goal: bool = True) -> dict:
    """Validate a single proposal by comparing pre/post success rates."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)
        ).fetchone()
        if not row:
            return {"change_id": proposal_id, "verdict": "uncertain", "message": "Proposal not found"}

        task_type = row["category"] or "unknown"
        applied_at = row["updated_at"] or row["created_at"]

        baseline_rate, baseline_samples = _get_baseline_success_rate(task_type, applied_at)
        post_rate, post_samples = _get_post_success_rate(task_type, applied_at)
        improvement = post_rate - baseline_rate

        if post_samples < MIN_SAMPLES:
            verdict = VERDICT_PENDING
            message = f"Need more samples: {post_samples}/{MIN_SAMPLES}"
        elif baseline_samples < 3:
            verdict = VERDICT_UNCERTAIN
            message = f"Insufficient baseline: {baseline_samples} pre-change samples"
        elif improvement >= EFFECTIVE_THRESHOLD:
            verdict = VERDICT_EFFECTIVE
            message = f"Improved: {baseline_rate:.0%} → {post_rate:.0%} (+{improvement:.0%})"
        elif improvement >= UNCERTAIN_THRESHOLD:
            verdict = VERDICT_UNCERTAIN
            message = f"Marginal: {baseline_rate:.0%} → {post_rate:.0%} (+{improvement:.0%})"
        else:
            verdict = VERDICT_INEFFECTIVE
            message = f"No improvement: {baseline_rate:.0%} → {post_rate:.0%} ({improvement:+.0%})"

        evidence = {
            "verdict": verdict, "baseline_rate": round(baseline_rate, 3),
            "post_rate": round(post_rate, 3), "improvement": round(improvement, 3),
            "baseline_samples": baseline_samples, "post_samples": post_samples,
        }

        # Write verdict to proposals table (not evolution_changes)
        if verdict != VERDICT_PENDING:
            _update_proposal_verdict(proposal_id, verdict, evidence)

        # Log event
        try:
            from evolution_runtime import log_event
            log_event("validation_completed", proposal_id, evidence)
        except Exception:
            pass

        # Auto-update goal
        goal_updated = False
        if auto_update_goal and verdict == VERDICT_EFFECTIVE and improvement > 0:
            goal_updated = _update_goal_progress_for_task_type(task_type, improvement)

        print(f"[causal_validator] Proposal #{proposal_id}: {verdict} — {message}")
        return {
            "change_id": proposal_id, "task_type": task_type, "verdict": verdict,
            "baseline_rate": round(baseline_rate, 3), "post_rate": round(post_rate, 3),
            "baseline_samples": baseline_samples, "post_samples": post_samples,
            "improvement": round(improvement, 3), "goal_updated": goal_updated,
            "message": message,
        }
    except Exception as e:
        return {"change_id": proposal_id, "verdict": "uncertain", "message": str(e)}
    finally:
        db.close()


# ============ Legacy compat (read-only) ============

def _get_legacy_pending() -> list[dict]:
    """Read pending changes from legacy evolution_changes (read-only, no writes)."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT change_id, task_type, applied_at FROM evolution_changes WHERE status = 'applied'"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        db.close()


# ============ Unified API ============

def validate_change(change_id: str, auto_update_goal: bool = True) -> dict:
    """Validate a change/proposal. Checks proposals table first, then legacy."""
    db = get_db()
    try:
        # Check proposals first
        row = db.execute("SELECT proposal_id FROM proposals WHERE proposal_id = ?", (change_id,)).fetchone()
        if row:
            db.close()
            return validate_proposal(change_id, auto_update_goal)

        # Legacy fallback: read from evolution_changes but do NOT write back
        row = db.execute("SELECT * FROM evolution_changes WHERE change_id = ?", (change_id,)).fetchone()
        if not row:
            return {"change_id": change_id, "verdict": "uncertain", "message": "Not found in proposals or legacy"}

        task_type = row["task_type"]
        applied_at = row["applied_at"]
        baseline_rate, baseline_samples = _get_baseline_success_rate(task_type, applied_at)
        post_rate, post_samples = _get_post_success_rate(task_type, applied_at)
        improvement = post_rate - baseline_rate

        if post_samples < MIN_SAMPLES:
            verdict = VERDICT_PENDING
            message = f"Need more samples: {post_samples}/{MIN_SAMPLES}"
        elif baseline_samples < 3:
            verdict = VERDICT_UNCERTAIN
            message = f"Insufficient baseline: {baseline_samples} samples"
        elif improvement >= EFFECTIVE_THRESHOLD:
            verdict = VERDICT_EFFECTIVE
            message = f"Improved: {baseline_rate:.0%} → {post_rate:.0%} (+{improvement:.0%})"
        elif improvement >= UNCERTAIN_THRESHOLD:
            verdict = VERDICT_UNCERTAIN
            message = f"Marginal: {baseline_rate:.0%} → {post_rate:.0%} (+{improvement:.0%})"
        else:
            verdict = VERDICT_INEFFECTIVE
            message = f"No improvement: {baseline_rate:.0%} → {post_rate:.0%} ({improvement:+.0%})"

        # NOTE: intentionally NOT writing back to evolution_changes (legacy read-only)
        print(f"[causal_validator] Legacy #{change_id}: {verdict} — {message}")
        return {
            "change_id": change_id, "task_type": task_type, "verdict": verdict,
            "baseline_rate": round(baseline_rate, 3), "post_rate": round(post_rate, 3),
            "baseline_samples": baseline_samples, "post_samples": post_samples,
            "improvement": round(improvement, 3), "goal_updated": False,
            "message": message,
        }
    except Exception as e:
        return {"change_id": change_id, "verdict": "uncertain", "message": str(e)}
    finally:
        db.close()


def validate_all_pending(auto_update_goal: bool = True) -> list[dict]:
    """Validate all pending proposals + legacy changes."""
    results = []

    # 1. Proposals in 'experimenting' status (primary)
    for p in _get_proposals_pending_validation():
        results.append(validate_proposal(p["proposal_id"], auto_update_goal))

    # 2. Legacy evolution_changes still 'applied' (read-only)
    for c in _get_legacy_pending():
        # Skip if already validated via proposals
        if any(r["change_id"] == c["change_id"] for r in results):
            continue
        results.append(validate_change(c["change_id"], auto_update_goal))

    return results


def get_verification_report() -> dict:
    """Summary report combining proposals + legacy data."""
    db = get_db()
    try:
        # Primary: proposals with validation evidence
        proposal_count = 0
        by_status = {}
        try:
            for r in db.execute(
                "SELECT status, COUNT(*) as c FROM proposals GROUP BY status"
            ).fetchall():
                by_status[r["status"]] = r["c"]
                proposal_count += r["c"]
        except Exception:
            pass

        # Legacy: evolution_changes (read-only stats)
        legacy_count = 0
        by_verdict = {}
        try:
            legacy_count = db.execute("SELECT COUNT(*) FROM evolution_changes").fetchone()[0]
            for r in db.execute(
                "SELECT verdict, COUNT(*) as c FROM evolution_changes WHERE verdict IS NOT NULL GROUP BY verdict"
            ).fetchall():
                by_verdict[r["verdict"]] = r["c"]
        except Exception:
            pass

        # Recent proposals
        recent = []
        try:
            rows = db.execute(
                "SELECT proposal_id, category, status, created_at FROM proposals ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            recent = [dict(r) for r in rows]
        except Exception:
            pass

        return {
            "total_proposals": proposal_count,
            "proposal_statuses": by_status,
            "legacy_changes": legacy_count,
            "legacy_verdicts": by_verdict,
            "recent": recent,
        }
    finally:
        db.close()


# ============ CLI ============

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="Causal Validator")
    sub = parser.add_subparsers(dest="command")

    p_validate = sub.add_parser("validate", help="Validate a change/proposal")
    p_validate.add_argument("change_id", nargs="?", default=None)
    sub.add_parser("report", help="Verification report")
    sub.add_parser("pending", help="List items waiting for samples")

    args = parser.parse_args()

    if args.command == "validate":
        if args.change_id:
            result = validate_change(args.change_id)
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            results = validate_all_pending()
            if not results:
                print("No pending items to validate")
            for r in results:
                icon = {"effective": "✅", "ineffective": "❌", "uncertain": "❓", "pending": "⏳"}.get(r["verdict"], "•")
                print(f"  {icon} [{r['verdict']}] #{r['change_id']}: {r['message']}")

    elif args.command == "report":
        report = get_verification_report()
        print(f"Proposals: {report['total_proposals']}")
        for s, c in report["proposal_statuses"].items():
            print(f"  {s}: {c}")
        if report["legacy_changes"]:
            print(f"\nLegacy changes: {report['legacy_changes']} (read-only)")
            for v, c in report["legacy_verdicts"].items():
                print(f"  {v}: {c}")
        for p in report["recent"][:10]:
            print(f"  • #{p['proposal_id']}: {p['category']} → {p['status']}")

    elif args.command == "pending":
        proposals = _get_proposals_pending_validation()
        legacy = _get_legacy_pending()
        if not proposals and not legacy:
            print("No items waiting for validation")
        for p in proposals:
            print(f"  ⏳ [proposal] #{p['proposal_id']}: {p['category']}")
        for c in legacy:
            print(f"  ⏳ [legacy]   #{c['change_id']}: {c['task_type']}")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
