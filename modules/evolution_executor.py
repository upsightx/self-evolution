#!/usr/bin/env python3
"""
Evolution Executor — 把改进建议变成可回滚的小实验。

职责：
- 接收来自 feedback_loop / critic / evolver 的改进建议
- 生成最小改动方案（实验计划）
- 管理实验生命周期：创建 → 激活 → 收集结果 → 判定 → 固化或回滚
- 所有状态持久化到 SQLite

不做什么：
- 不自动改代码（Phase 1 只改模板和配置）
- 不做因果判断（交给 causal_validator）
- 不直接执行子 Agent（只记录实验计划，由调度层执行）

Phase 1 范围：
- 只支持 prompt_template 类型的实验
- A/B 版本切换（不做灰度）
- 手动或心跳触发
"""
from __future__ import annotations

import json
import sqlite3
import sys
import argparse
from datetime import datetime
from pathlib import Path

from db_common import DB_PATH, get_db

# ============ Schema ============

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    task_type TEXT NOT NULL,
    problem TEXT NOT NULL,
    proposal TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT 'prompt_template',
    risk TEXT NOT NULL DEFAULT 'low',
    status TEXT NOT NULL DEFAULT 'draft',
    baseline_snapshot TEXT,
    experiment_snapshot TEXT,
    eval_metric TEXT NOT NULL DEFAULT 'success_rate',
    min_samples INTEGER NOT NULL DEFAULT 5,
    baseline_results TEXT,
    experiment_results TEXT,
    verdict TEXT,
    verdict_confidence REAL,
    verdict_reason TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    activated_at TEXT,
    concluded_at TEXT
);
"""

# Valid status transitions
# draft → active → concluded
# draft → cancelled
# active → cancelled
VALID_STATUSES = {"draft", "active", "concluded", "cancelled"}
VALID_SOURCES = {"feedback_loop", "critic", "evolver", "manual"}
VALID_TARGETS = {"prompt_template", "workflow_rule", "model_route"}
VALID_RISKS = {"low", "medium", "high"}
VALID_VERDICTS = {"effective", "uncertain", "ineffective"}


def _ensure_table():
    """Idempotent table creation."""
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()
    db.close()


# ============ Write ============

def create_experiment(
    source: str,
    task_type: str,
    problem: str,
    proposal: str,
    target_type: str = "prompt_template",
    risk: str = "low",
    baseline_snapshot: str | None = None,
    experiment_snapshot: str | None = None,
    eval_metric: str = "success_rate",
    min_samples: int = 5,
) -> int | None:
    """Create a new experiment in draft status.

    Args:
        source: where the suggestion came from (feedback_loop/critic/evolver/manual)
        task_type: which task type this targets (coding/research/etc)
        problem: what problem was observed
        proposal: what change is proposed
        target_type: what kind of thing we're changing (prompt_template/workflow_rule/model_route)
        risk: low/medium/high
        baseline_snapshot: JSON string of the current state (e.g. old template text)
        experiment_snapshot: JSON string of the proposed new state
        eval_metric: how to measure success (default: success_rate)
        min_samples: minimum samples before concluding

    Returns:
        experiment id, or None on failure
    """
    if source not in VALID_SOURCES:
        print(f"[evolution_executor] Warning: unknown source '{source}', using 'manual'")
        source = "manual"
    if target_type not in VALID_TARGETS:
        print(f"[evolution_executor] Warning: unknown target_type '{target_type}', using 'prompt_template'")
        target_type = "prompt_template"
    if risk not in VALID_RISKS:
        risk = "low"

    _ensure_table()
    db = get_db()
    try:
        cur = db.execute(
            """INSERT INTO experiments
               (source, task_type, problem, proposal, target_type, risk,
                baseline_snapshot, experiment_snapshot, eval_metric, min_samples)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (source, task_type, problem, proposal, target_type, risk,
             baseline_snapshot, experiment_snapshot, eval_metric, min_samples),
        )
        db.commit()
        rid = cur.lastrowid
        print(f"[evolution_executor] Created experiment #{rid}: {problem[:60]}")
        return rid
    except sqlite3.Error as e:
        print(f"[evolution_executor] Error creating experiment: {e}")
        return None
    finally:
        db.close()


def activate_experiment(experiment_id: int) -> bool:
    """Move experiment from draft → active. This means we start collecting data."""
    _ensure_table()
    db = get_db()
    try:
        row = db.execute("SELECT status FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
        if not row:
            print(f"[evolution_executor] Experiment #{experiment_id} not found")
            return False
        if row["status"] != "draft":
            print(f"[evolution_executor] Experiment #{experiment_id} is '{row['status']}', can only activate from 'draft'")
            return False
        db.execute(
            "UPDATE experiments SET status = 'active', activated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), experiment_id),
        )
        db.commit()
        print(f"[evolution_executor] Activated experiment #{experiment_id}")
        return True
    except sqlite3.Error as e:
        print(f"[evolution_executor] Error: {e}")
        return False
    finally:
        db.close()


def record_result(experiment_id: int, phase: str, success: bool,
                  critic_score: float | None = None, rework: bool = False,
                  duration_s: float | None = None, notes: str | None = None) -> bool:
    """Record a single trial result for an experiment.

    Args:
        experiment_id: which experiment
        phase: 'baseline' or 'experiment'
        success: did the task succeed
        critic_score: optional quality score (0-100)
        rework: did it need rework
        duration_s: how long it took
        notes: any notes

    Results are stored as JSON arrays in baseline_results / experiment_results.
    """
    if phase not in ("baseline", "experiment"):
        print(f"[evolution_executor] Invalid phase: {phase}")
        return False

    _ensure_table()
    db = get_db()
    try:
        row = db.execute("SELECT status, baseline_results, experiment_results FROM experiments WHERE id = ?",
                         (experiment_id,)).fetchone()
        if not row:
            print(f"[evolution_executor] Experiment #{experiment_id} not found")
            return False
        if row["status"] != "active":
            print(f"[evolution_executor] Experiment #{experiment_id} is '{row['status']}', must be 'active'")
            return False

        col = "baseline_results" if phase == "baseline" else "experiment_results"
        existing = json.loads(row[col]) if row[col] else []

        entry = {
            "success": success,
            "critic_score": critic_score,
            "rework": rework,
            "duration_s": duration_s,
            "notes": notes,
            "timestamp": datetime.now().isoformat(),
        }
        existing.append(entry)

        db.execute(f"UPDATE experiments SET {col} = ? WHERE id = ?",
                   (json.dumps(existing, ensure_ascii=False), experiment_id))
        db.commit()
        return True
    except (sqlite3.Error, json.JSONDecodeError) as e:
        print(f"[evolution_executor] Error recording result: {e}")
        return False
    finally:
        db.close()


def conclude_experiment(experiment_id: int, verdict: str,
                        confidence: float, reason: str) -> bool:
    """Conclude an experiment with a verdict.

    Args:
        verdict: 'effective', 'uncertain', or 'ineffective'
        confidence: 0.0 to 1.0
        reason: human-readable explanation
    """
    if verdict not in VALID_VERDICTS:
        print(f"[evolution_executor] Invalid verdict: {verdict}")
        return False

    _ensure_table()
    db = get_db()
    try:
        row = db.execute("SELECT status FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
        if not row:
            return False
        if row["status"] != "active":
            print(f"[evolution_executor] Experiment #{experiment_id} is '{row['status']}', must be 'active'")
            return False

        db.execute(
            """UPDATE experiments SET status = 'concluded',
               verdict = ?, verdict_confidence = ?, verdict_reason = ?,
               concluded_at = ? WHERE id = ?""",
            (verdict, confidence, reason, datetime.now().isoformat(), experiment_id),
        )
        db.commit()
        print(f"[evolution_executor] Concluded #{experiment_id}: {verdict} (confidence={confidence:.2f})")
        return True
    except sqlite3.Error as e:
        print(f"[evolution_executor] Error: {e}")
        return False
    finally:
        db.close()


def cancel_experiment(experiment_id: int, reason: str = "") -> bool:
    """Cancel an experiment (from draft or active)."""
    _ensure_table()
    db = get_db()
    try:
        row = db.execute("SELECT status FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
        if not row:
            return False
        if row["status"] in ("concluded", "cancelled"):
            print(f"[evolution_executor] Experiment #{experiment_id} already '{row['status']}'")
            return False
        db.execute(
            "UPDATE experiments SET status = 'cancelled', verdict_reason = ?, concluded_at = ? WHERE id = ?",
            (reason, datetime.now().isoformat(), experiment_id),
        )
        db.commit()
        return True
    except sqlite3.Error as e:
        print(f"[evolution_executor] Error: {e}")
        return False
    finally:
        db.close()


# ============ Query ============

def get_experiment(experiment_id: int) -> dict | None:
    """Get full experiment details."""
    _ensure_table()
    db = get_db()
    row = db.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
    db.close()
    if not row:
        return None
    d = dict(row)
    # Parse JSON fields
    for f in ("baseline_results", "experiment_results"):
        if d.get(f):
            try:
                d[f] = json.loads(d[f])
            except json.JSONDecodeError:
                pass
    return d


def list_experiments(status: str | None = None, task_type: str | None = None,
                     limit: int = 20) -> list[dict]:
    """List experiments with optional filters."""
    _ensure_table()
    db = get_db()
    conditions = []
    params = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if task_type:
        conditions.append("task_type = ?")
        params.append(task_type)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)
    rows = db.execute(
        f"SELECT id, source, task_type, problem, proposal, target_type, risk, status, "
        f"verdict, verdict_confidence, created_at, concluded_at "
        f"FROM experiments{where} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_active_experiment_for_task(task_type: str) -> dict | None:
    """Get the currently active experiment for a task type, if any."""
    _ensure_table()
    db = get_db()
    row = db.execute(
        "SELECT * FROM experiments WHERE task_type = ? AND status = 'active' "
        "ORDER BY activated_at DESC LIMIT 1",
        (task_type,),
    ).fetchone()
    db.close()
    if not row:
        return None
    d = dict(row)
    for f in ("baseline_results", "experiment_results"):
        if d.get(f):
            try:
                d[f] = json.loads(d[f])
            except json.JSONDecodeError:
                pass
    return d


def pending_candidates(min_failure_rate: float = 0.3) -> list[dict]:
    """Auto-generate experiment candidates from feedback_loop patterns.

    Scans task_outcomes for task_types with failure_rate >= min_failure_rate
    and no active/draft experiment already targeting them.
    """
    _ensure_table()
    db = get_db()
    candidates = []

    try:
        # Get problematic task types from feedback_loop data
        rows = db.execute(
            """SELECT task_type, COUNT(*) as total, SUM(success) as wins
               FROM task_outcomes
               GROUP BY task_type
               HAVING total >= 3""",
        ).fetchall()

        # Get task types that already have active/draft experiments
        active_types = {
            r["task_type"]
            for r in db.execute(
                "SELECT DISTINCT task_type FROM experiments WHERE status IN ('draft', 'active')"
            ).fetchall()
        }

        for r in rows:
            total = r["total"]
            wins = r["wins"] or 0
            failure_rate = 1 - (wins / total)
            if failure_rate < min_failure_rate:
                continue
            if r["task_type"] in active_types:
                continue

            # Get recent failure gaps for context
            gaps = db.execute(
                "SELECT gap_analysis, notes FROM task_outcomes "
                "WHERE task_type = ? AND success = 0 ORDER BY timestamp DESC LIMIT 5",
                (r["task_type"],),
            ).fetchall()
            gap_texts = [g["gap_analysis"] or g["notes"] or "" for g in gaps]

            candidates.append({
                "task_type": r["task_type"],
                "failure_rate": round(failure_rate, 3),
                "sample_count": total,
                "recent_gaps": gap_texts,
            })

        candidates.sort(key=lambda x: x["failure_rate"], reverse=True)
    except sqlite3.Error as e:
        print(f"[evolution_executor] Error scanning candidates: {e}")
    finally:
        db.close()

    return candidates


def record_and_maybe_conclude(
    experiment_id: int,
    phase: str,
    success: bool,
    critic_score: float | None = None,
    rework: bool = False,
    duration_s: float | None = None,
    notes: str | None = None,
) -> dict | None:
    """Record a result AND auto-conclude if both phases have enough samples.

    This is the main entry point for the heartbeat/dispatch integration.
    Returns the validation result dict if concluded, None otherwise.
    """
    ok = record_result(experiment_id, phase, success,
                       critic_score=critic_score, rework=rework,
                       duration_s=duration_s, notes=notes)
    if not ok:
        return None

    exp = get_experiment(experiment_id)
    if not exp or exp["status"] != "active":
        return None

    baseline = exp.get("baseline_results") or []
    exp_results = exp.get("experiment_results") or []
    min_samples = exp.get("min_samples", 5)

    # Only auto-conclude when BOTH phases have enough samples
    if len(baseline) >= min_samples and len(exp_results) >= min_samples:
        from causal_validator import validate_experiment
        result = validate_experiment(exp)
        conclude_experiment(experiment_id, result.verdict, result.confidence, result.reason)
        print(f"[evolution_executor] Auto-concluded #{experiment_id}: {result.verdict} ({result.confidence:.2f})")
        return result.to_dict()

    return None


def get_or_create_experiment_for_task(
    task_type: str,
    source: str = "feedback_loop",
    problem: str = "",
    proposal: str = "",
) -> dict | None:
    """Get the active experiment for a task type, or return None.

    This is a convenience for the dispatch layer: before running a task,
    check if there's an active experiment so you know which phase to record into.
    """
    exp = get_active_experiment_for_task(task_type)
    return exp


def summary() -> dict:
    """Get a summary of all experiments."""
    _ensure_table()
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    by_status = {}
    for r in db.execute(
        "SELECT status, COUNT(*) as c FROM experiments GROUP BY status"
    ).fetchall():
        by_status[r["status"]] = r["c"]
    by_verdict = {}
    for r in db.execute(
        "SELECT verdict, COUNT(*) as c FROM experiments WHERE verdict IS NOT NULL GROUP BY verdict"
    ).fetchall():
        by_verdict[r["verdict"]] = r["c"]
    db.close()
    return {"total": total, "by_status": by_status, "by_verdict": by_verdict}


# ============ CLI ============

def _cli():
    parser = argparse.ArgumentParser(description="Evolution Executor — 进化实验管理")
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Create a new experiment")
    p_create.add_argument("--source", required=True, choices=list(VALID_SOURCES))
    p_create.add_argument("--task-type", required=True)
    p_create.add_argument("--problem", required=True)
    p_create.add_argument("--proposal", required=True)
    p_create.add_argument("--target", default="prompt_template", choices=list(VALID_TARGETS))
    p_create.add_argument("--risk", default="low", choices=list(VALID_RISKS))
    p_create.add_argument("--baseline", default=None, help="JSON snapshot of current state")
    p_create.add_argument("--experiment", default=None, help="JSON snapshot of proposed state")
    p_create.add_argument("--min-samples", type=int, default=5)

    # activate
    p_act = sub.add_parser("activate", help="Activate a draft experiment")
    p_act.add_argument("id", type=int)

    # record
    p_rec = sub.add_parser("record", help="Record a trial result")
    p_rec.add_argument("id", type=int)
    p_rec.add_argument("phase", choices=["baseline", "experiment"])
    p_rec.add_argument("success", type=int, choices=[0, 1])
    p_rec.add_argument("--critic-score", type=float, default=None)
    p_rec.add_argument("--rework", action="store_true")
    p_rec.add_argument("--duration", type=float, default=None)
    p_rec.add_argument("--notes", default=None)

    # conclude
    p_con = sub.add_parser("conclude", help="Conclude an experiment")
    p_con.add_argument("id", type=int)
    p_con.add_argument("verdict", choices=list(VALID_VERDICTS))
    p_con.add_argument("confidence", type=float)
    p_con.add_argument("reason")

    # cancel
    p_can = sub.add_parser("cancel", help="Cancel an experiment")
    p_can.add_argument("id", type=int)
    p_can.add_argument("--reason", default="")

    # get
    p_get = sub.add_parser("get", help="Get experiment details")
    p_get.add_argument("id", type=int)

    # list
    p_list = sub.add_parser("list", help="List experiments")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--task-type", default=None)
    p_list.add_argument("--limit", type=int, default=20)

    # candidates
    sub.add_parser("candidates", help="Show auto-generated experiment candidates")

    # summary
    sub.add_parser("summary", help="Show experiment summary")

    args = parser.parse_args()

    if args.command == "create":
        rid = create_experiment(
            source=args.source, task_type=args.task_type,
            problem=args.problem, proposal=args.proposal,
            target_type=args.target, risk=args.risk,
            baseline_snapshot=args.baseline, experiment_snapshot=args.experiment,
            min_samples=args.min_samples,
        )
        if rid:
            print(f"✅ Created experiment #{rid}")
        else:
            print("❌ Failed to create experiment")

    elif args.command == "activate":
        if activate_experiment(args.id):
            print(f"✅ Experiment #{args.id} activated")
        else:
            print(f"❌ Failed to activate #{args.id}")

    elif args.command == "record":
        if record_result(args.id, args.phase, bool(args.success),
                         critic_score=args.critic_score, rework=args.rework,
                         duration_s=args.duration, notes=args.notes):
            print(f"✅ Recorded {args.phase} result for #{args.id}")
        else:
            print(f"❌ Failed to record result")

    elif args.command == "conclude":
        if conclude_experiment(args.id, args.verdict, args.confidence, args.reason):
            print(f"✅ Concluded #{args.id}: {args.verdict}")
        else:
            print(f"❌ Failed to conclude #{args.id}")

    elif args.command == "cancel":
        if cancel_experiment(args.id, args.reason):
            print(f"✅ Cancelled #{args.id}")
        else:
            print(f"❌ Failed to cancel #{args.id}")

    elif args.command == "get":
        exp = get_experiment(args.id)
        if exp:
            print(json.dumps(exp, indent=2, ensure_ascii=False, default=str))
        else:
            print("Not found")

    elif args.command == "list":
        exps = list_experiments(status=args.status, task_type=args.task_type, limit=args.limit)
        if not exps:
            print("No experiments found")
        for e in exps:
            v = f" → {e['verdict']}({e['verdict_confidence']:.2f})" if e.get("verdict") else ""
            print(f"  #{e['id']} [{e['status']}] {e['task_type']}/{e['source']}: {e['problem'][:50]}{v}")

    elif args.command == "candidates":
        cands = pending_candidates()
        if not cands:
            print("No candidates (all task types healthy or already have experiments)")
        for c in cands:
            print(f"  {c['task_type']}: failure_rate={c['failure_rate']} samples={c['sample_count']}")
            for g in c["recent_gaps"][:3]:
                if g:
                    print(f"    - {g[:80]}")

    elif args.command == "summary":
        s = summary()
        print(json.dumps(s, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
