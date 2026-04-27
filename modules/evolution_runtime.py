#!/usr/bin/env python3
"""
Evolution Runtime — 统一进化运行时。

职责：
- 统一事件日志（所有操作可追溯）
- 心跳/cron 入口

注意（2026-04-14 架构收口）：
- Proposal 状态机已统一到 proposal_lifecycle_manager.py（唯一真源）
- 本模块不再管理 proposal 状态或 legacy evolution_changes 写入
- 所有 proposal 状态操作委托给 proposal_lifecycle_manager

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

from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path, module_dir, module_workspace

_workspace = ensure_workspace_on_path()
_modules = module_dir()
ensure_xmemory_on_path()

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


def _ensure_schema():
    db = get_db()
    db.executescript(_SCHEMA)
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


# ============ Proposal Queries (delegated to proposal_lifecycle_manager) ============

def get_pending_proposals() -> list[dict]:
    """Get all proposals waiting for approval or execution.

    Delegates to proposal_lifecycle_manager (single source of truth).
    """
    try:
        from proposal_lifecycle_manager import list_proposals
        return list_proposals(status="pending_review")
    except ImportError:
        return []


def get_stale_changes(hours: int = 48) -> list[dict]:
    """Find proposals stuck in experimenting without verification.

    Delegates to proposal_lifecycle_manager.
    """
    try:
        from proposal_lifecycle_manager import list_proposals
        return list_proposals(status="experimenting")
    except ImportError:
        return []


# ============ Heartbeat Entry Point ============
# NOTE (2026-04-27): heartbeat_check is a legacy entry that partially duplicates
# evolution_orchestrator.heartbeat(). New callers should use the orchestrator
# which has full signal routing, bridge ingestion, and goal updates.
# This function is kept for backward CLI compatibility only.

def heartbeat_check() -> dict:
    """Run periodic evolution health checks. DEPRECATED for new callers.
    
    Use evolution_orchestrator.heartbeat() instead — it includes:
    - Capability detection + signal routing
    - External learning bridge ingestion from gather.py JSONL
    - Auto goal progress updates
    - Task outcome auto-recording
    - Controlled-loop router recommendations
    """
    _ensure_schema()
    actions = []

    # Redirect to orchestrator for comprehensive check
    try:
        from evolution_orchestrator import heartbeat as orch_heartbeat
        return orch_heartbeat()
    except Exception as e:
        actions.append(f"Orchestrator redirect failed: {e}")

    # 1. Check for stale proposals
    stale = get_stale_changes(hours=48)
    if stale:
        actions.append(f"Found {len(stale)} stale proposals (stuck in experimenting)")
        for s in stale[:3]:
            title = s.get('title', '?')
            print(f"  ⚠️ Stale: #{s.get('proposal_id', '?')} — {title[:50]}")

    # 2. Auto-validate pending verifications via causal_validator
    try:
        from causal_validator import validate_all_pending
        results = validate_all_pending()
        if results:
            verdicts = [r["verdict"] for r in results]
            actions.append(f"Validated {len(results)} changes: {', '.join(verdicts)}")
            # Transition via proposal_lifecycle_manager (canonical entry)
            try:
                from proposal_lifecycle_manager import transition
                for r in results:
                    if r["verdict"] in ("effective", "ineffective", "uncertain"):
                        target_status = "validated" if r["verdict"] == "effective" else "failed"
                        transition(r["change_id"], target_status,
                                  actor="evolution_runtime",
                                  reason=f"Auto-validated: {r['verdict']}")
            except ImportError:
                actions.append("proposal_lifecycle_manager unavailable for transition")
    except Exception as e:
        actions.append(f"Validation error: {e}")

    # 3. Route curated external-learning evidence into proposal candidates.
    try:
        from proposal_bridge import scan_pending_observations
        scan_result = scan_pending_observations()
        if scan_result["processed"] > 0:
            actions.append(
                f"Processed {scan_result['processed']} learning evidence items "
                f"(proposals={scan_result.get('proposals_created', 0)}, "
                f"attached={scan_result.get('evidence_attached', 0)})"
            )
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

    # pending
    sub.add_parser("pending", help="List pending proposals")

    # stale
    p_stale = sub.add_parser("stale", help="Find stale proposals")
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

    elif args.command == "pending":
        proposals = get_pending_proposals()
        if not proposals:
            print("No pending proposals")
        for p in proposals:
            status = p.get('status', '?')
            pid = p.get('proposal_id', '?')
            title = p.get('title', '?')
            print(f"  [{status}] #{pid}: {title[:50]}")

    elif args.command == "stale":
        stale = get_stale_changes(hours=args.hours)
        if not stale:
            print(f"No stale proposals (>{args.hours}h)")
        for s in stale:
            pid = s.get('proposal_id', '?')
            title = s.get('title', '?')
            print(f"  ⚠️ #{pid}: {title[:50]}")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
