#!/usr/bin/env python3
"""
Evolution Runtime — 统一进化运行时。

职责：
- 统一事件日志（所有操作可追溯）
- Proposal 生命周期状态机
- 统一回滚协议
- 心跳/cron 入口

状态机：
  draft → pending → approved → executing → applied → verified → archived
                  ↘ rejected                ↘ rolled_back

事件类型：
  proposal_created, proposal_approved, proposal_rejected,
  change_executing, change_applied, change_failed, change_rolled_back,
  validation_started, validation_completed,
  learning_ingested, goal_updated
"""
from __future__ import annotations

import json
import sys
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


# ============ Schema ============

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evolution_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    change_id TEXT,
    detail TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_type ON evolution_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_change ON evolution_events(change_id);
CREATE INDEX IF NOT EXISTS idx_events_created ON evolution_events(created_at);
"""

# Valid status transitions
_TRANSITIONS = {
    "draft":       ["pending", "rejected"],
    "pending":     ["approved", "rejected"],
    "approved":    ["executing"],
    "executing":   ["applied", "failed"],
    "applied":     ["verified", "rolled_back"],
    "verified":    ["archived", "rolled_back"],
    "failed":      ["pending", "archived"],  # can retry
    "rolled_back": ["archived", "pending"],  # can retry
    "rejected":    ["archived"],
    "archived":    [],
}


def _ensure_schema():
    db = get_db()
    db.executescript(_SCHEMA)
    # Migrate evolution_changes if needed
    cols = {r[1] for r in db.execute("PRAGMA table_info(evolution_changes)").fetchall()}
    if cols:  # table exists
        if "lifecycle_status" not in cols:
            db.execute("ALTER TABLE evolution_changes ADD COLUMN lifecycle_status TEXT DEFAULT 'applied'")
        if "experiment_id" not in cols:
            db.execute("ALTER TABLE evolution_changes ADD COLUMN experiment_id TEXT DEFAULT NULL")
    db.commit()
    db.close()


# ============ Event Log ============

def log_event(event_type: str, change_id: str = None, detail: dict | str = None) -> int:
    """Log an evolution event.

    Args:
        event_type: One of the defined event types
        change_id: Associated change ID (optional)
        detail: Additional context (dict or string)

    Returns:
        Event ID
    """
    _ensure_schema()
    db = get_db()
    detail_str = json.dumps(detail, ensure_ascii=False, default=str) if isinstance(detail, dict) else (detail or "")
    cursor = db.execute(
        "INSERT INTO evolution_events (event_type, change_id, detail) VALUES (?, ?, ?)",
        (event_type, change_id, detail_str),
    )
    db.commit()
    eid = cursor.lastrowid
    db.close()
    return eid


def get_events(
    change_id: str = None,
    event_type: str = None,
    limit: int = 50,
) -> list[dict]:
    """Query evolution events."""
    _ensure_schema()
    db = get_db()
    conditions = []
    params = []
    if change_id:
        conditions.append("change_id = ?")
        params.append(change_id)
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    where = " AND ".join(conditions) if conditions else "1=1"
    params.append(limit)
    rows = db.execute(
        f"SELECT * FROM evolution_events WHERE {where} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_event_summary(days: int = 30) -> dict:
    """Get event summary for the last N days."""
    _ensure_schema()
    db = get_db()
    rows = db.execute(
        """SELECT event_type, COUNT(*) as cnt
           FROM evolution_events
           WHERE created_at >= datetime('now', ?)
           GROUP BY event_type ORDER BY cnt DESC""",
        (f"-{days} days",),
    ).fetchall()
    total = db.execute(
        "SELECT COUNT(*) FROM evolution_events WHERE created_at >= datetime('now', ?)",
        (f"-{days} days",),
    ).fetchone()[0]
    db.close()
    return {
        "total": total,
        "by_type": {r["event_type"]: r["cnt"] for r in rows},
        "period_days": days,
    }


# ============ Lifecycle State Machine ============

def transition(change_id: str, new_status: str, detail: str = "") -> dict:
    """Transition a proposal/change to a new lifecycle status.

    Enforces valid transitions. Logs event automatically.

    Args:
        change_id: The change to transition
        new_status: Target status
        detail: Reason or context

    Returns:
        {"success": bool, "old_status": str, "new_status": str, "message": str}
    """
    _ensure_schema()
    db = get_db()

    try:
        row = db.execute(
            "SELECT lifecycle_status, status FROM evolution_changes WHERE change_id = ?",
            (change_id,),
        ).fetchone()

        if not row:
            return {"success": False, "old_status": "", "new_status": new_status,
                    "message": f"Change {change_id} not found"}

        current = row["lifecycle_status"] or row["status"] or "applied"

        # Check valid transition
        valid_next = _TRANSITIONS.get(current, [])
        if new_status not in valid_next:
            return {"success": False, "old_status": current, "new_status": new_status,
                    "message": f"Invalid transition: {current} → {new_status}. Valid: {valid_next}"}

        # Apply transition
        db.execute(
            "UPDATE evolution_changes SET lifecycle_status = ? WHERE change_id = ?",
            (new_status, change_id),
        )

        # Also update legacy status field for backward compatibility
        legacy_map = {
            "applied": "applied",
            "verified": "verified",
            "rolled_back": "rolled_back",
            "archived": "verified",
        }
        if new_status in legacy_map:
            db.execute(
                "UPDATE evolution_changes SET status = ? WHERE change_id = ?",
                (legacy_map[new_status], change_id),
            )

        db.commit()

        # Log event
        event_map = {
            "pending": "proposal_created",
            "approved": "proposal_approved",
            "rejected": "proposal_rejected",
            "executing": "change_executing",
            "applied": "change_applied",
            "failed": "change_failed",
            "rolled_back": "change_rolled_back",
            "verified": "validation_completed",
            "archived": "proposal_archived",
        }
        event_type = event_map.get(new_status, f"status_{new_status}")
        log_event(event_type, change_id, {"from": current, "to": new_status, "detail": detail})

        print(f"[evolution_runtime] {change_id}: {current} → {new_status}")
        return {"success": True, "old_status": current, "new_status": new_status,
                "message": f"Transitioned: {current} → {new_status}"}

    except Exception as e:
        return {"success": False, "old_status": "", "new_status": new_status,
                "message": str(e)}
    finally:
        db.close()


def get_lifecycle_status(change_id: str) -> dict:
    """Get full lifecycle info for a change."""
    _ensure_schema()
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM evolution_changes WHERE change_id = ?",
            (change_id,),
        ).fetchone()
        if not row:
            return {"found": False}

        events = db.execute(
            "SELECT event_type, detail, created_at FROM evolution_events WHERE change_id = ? ORDER BY created_at ASC",
            (change_id,),
        ).fetchall()

        return {
            "found": True,
            "change_id": change_id,
            "lifecycle_status": row["lifecycle_status"] or row["status"],
            "task_type": row["task_type"],
            "suggestion": row["suggestion"],
            "target_file": row["target_file"],
            "applied_at": row["applied_at"],
            "verified_at": row["verified_at"],
            "verdict": row["verdict"],
            "history": [dict(e) for e in events],
        }
    finally:
        db.close()


# ============ Batch Operations ============

def get_pending_proposals() -> list[dict]:
    """Get all proposals waiting for approval or execution."""
    _ensure_schema()
    db = get_db()
    try:
        rows = db.execute(
            """SELECT * FROM evolution_changes
               WHERE lifecycle_status IN ('draft', 'pending', 'approved')
                  OR (lifecycle_status IS NULL AND status = 'pending')
               ORDER BY applied_at DESC""",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def get_stale_changes(hours: int = 48) -> list[dict]:
    """Find changes stuck in executing/applied without verification."""
    _ensure_schema()
    db = get_db()
    try:
        rows = db.execute(
            """SELECT * FROM evolution_changes
               WHERE (lifecycle_status IN ('executing', 'applied')
                  OR (lifecycle_status IS NULL AND status = 'applied'))
                 AND applied_at < datetime('now', ?)
               ORDER BY applied_at ASC""",
            (f"-{hours} hours",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def archive_old_changes(days: int = 90) -> int:
    """Archive verified/rolled_back changes older than N days."""
    _ensure_schema()
    db = get_db()
    try:
        cursor = db.execute(
            """UPDATE evolution_changes
               SET lifecycle_status = 'archived'
               WHERE lifecycle_status IN ('verified', 'rolled_back', 'rejected')
                 AND applied_at < datetime('now', ?)""",
            (f"-{days} days",),
        )
        count = cursor.rowcount
        db.commit()
        if count:
            log_event("batch_archive", detail={"archived_count": count, "older_than_days": days})
            print(f"[evolution_runtime] Archived {count} old changes")
        return count
    finally:
        db.close()


# ============ Heartbeat Entry Point ============

def heartbeat_check() -> dict:
    """Run periodic evolution health checks. Called from HEARTBEAT.md.

    Returns summary of actions taken.
    """
    _ensure_schema()
    actions = []

    # 1. Check for stale changes
    stale = get_stale_changes(hours=48)
    if stale:
        actions.append(f"Found {len(stale)} stale changes (>48h without verification)")
        for s in stale[:3]:
            print(f"  ⚠️ Stale: #{s['change_id']} ({s['task_type']}) applied at {s['applied_at']}")

    # 2. Auto-validate pending verifications
    try:
        from causal_validator import validate_all_pending
        results = validate_all_pending()
        if results:
            verdicts = [r["verdict"] for r in results]
            actions.append(f"Validated {len(results)} changes: {', '.join(verdicts)}")
            # Transition verified changes
            for r in results:
                if r["verdict"] in ("effective", "ineffective", "uncertain"):
                    transition(r["change_id"], "verified",
                              f"Auto-validated: {r['verdict']}")
    except Exception as e:
        actions.append(f"Validation error: {e}")

    # 3. Archive old changes
    archived = archive_old_changes(days=90)
    if archived:
        actions.append(f"Archived {archived} old changes")

    # 4. Scan for new proposals from external learning
    try:
        from proposal_bridge import scan_pending_observations
        scan_result = scan_pending_observations()
        if scan_result["processed"] > 0:
            actions.append(f"Processed {scan_result['processed']} learning items "
                         f"(P0={scan_result['p0_proposals']}, P1={scan_result['p1_candidates']})")
    except Exception as e:
        actions.append(f"Proposal scan error: {e}")

    summary = {
        "timestamp": datetime.now().isoformat(),
        "actions": actions,
        "stale_count": len(stale) if 'stale' in dir() else 0,
    }

    if actions:
        print(f"[evolution_runtime] Heartbeat: {len(actions)} actions")
        for a in actions:
            print(f"  • {a}")
    else:
        print("[evolution_runtime] Heartbeat: all clear")

    return summary


# ============ CLI ============

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Evolution Runtime")
    sub = parser.add_subparsers(dest="command")

    # heartbeat
    sub.add_parser("heartbeat", help="Run periodic health check")

    # events
    p_events = sub.add_parser("events", help="Query events")
    p_events.add_argument("--change-id", default=None)
    p_events.add_argument("--type", default=None)
    p_events.add_argument("--limit", type=int, default=20)

    # summary
    p_summary = sub.add_parser("summary", help="Event summary")
    p_summary.add_argument("--days", type=int, default=30)

    # status
    p_status = sub.add_parser("status", help="Lifecycle status of a change")
    p_status.add_argument("change_id")

    # transition
    p_trans = sub.add_parser("transition", help="Transition a change status")
    p_trans.add_argument("change_id")
    p_trans.add_argument("new_status")
    p_trans.add_argument("--detail", default="")

    # pending
    sub.add_parser("pending", help="List pending proposals")

    # stale
    p_stale = sub.add_parser("stale", help="Find stale changes")
    p_stale.add_argument("--hours", type=int, default=48)

    args = parser.parse_args()

    if args.command == "heartbeat":
        result = heartbeat_check()
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    elif args.command == "events":
        events = get_events(change_id=args.change_id, event_type=args.type, limit=args.limit)
        for e in events:
            print(f"  [{e['created_at']}] {e['event_type']} | {e.get('change_id', '-')} | {e.get('detail', '')[:60]}")

    elif args.command == "summary":
        s = get_event_summary(days=args.days)
        print(f"Events in last {s['period_days']} days: {s['total']}")
        for t, c in s["by_type"].items():
            print(f"  {t}: {c}")

    elif args.command == "status":
        info = get_lifecycle_status(args.change_id)
        if not info["found"]:
            print(f"Change {args.change_id} not found")
        else:
            print(f"Change: {info['change_id']}")
            print(f"Status: {info['lifecycle_status']}")
            print(f"Type:   {info['task_type']}")
            print(f"File:   {info['target_file']}")
            if info["history"]:
                print(f"\nHistory:")
                for h in info["history"]:
                    print(f"  [{h['created_at']}] {h['event_type']}: {h.get('detail', '')[:60]}")

    elif args.command == "transition":
        result = transition(args.change_id, args.new_status, args.detail)
        icon = "✅" if result["success"] else "❌"
        print(f"{icon} {result['message']}")

    elif args.command == "pending":
        proposals = get_pending_proposals()
        if not proposals:
            print("No pending proposals")
        for p in proposals:
            print(f"  [{p.get('lifecycle_status', p['status'])}] #{p['change_id']}: {p['task_type']} — {p['suggestion'][:50]}")

    elif args.command == "stale":
        stale = get_stale_changes(hours=args.hours)
        if not stale:
            print(f"No stale changes (>{args.hours}h)")
        for s in stale:
            print(f"  ⚠️ #{s['change_id']}: {s['task_type']} applied at {s['applied_at']}")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
