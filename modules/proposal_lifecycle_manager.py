#!/usr/bin/env python3
"""
Proposal Lifecycle Manager — 提案生命周期管理器。

职责：
- 提案的唯一状态真源（消灭 status/lifecycle_status 双轨）
- 强制状态转换规则
- 证据绑定
- 查询与过滤

状态机：
  draft → pending_review → approved → experimenting → validated → released
                         ↘ rejected                  ↘ failed → draft (retry)
  released → deprecated / rolled_back
  任何非终态 → cancelled

终态：released, deprecated, rejected, cancelled

设计原则：
- 这是 proposal 状态的唯一写入点
- 其他模块只能通过此模块修改 proposal 状态
- 每次状态变更自动记录事件日志
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

PROPOSALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    category TEXT DEFAULT '',
    source_type TEXT DEFAULT '',
    source_ref TEXT DEFAULT '',
    priority TEXT DEFAULT 'P1',
    target_scope TEXT DEFAULT '',
    target_module TEXT DEFAULT '',
    change_description TEXT DEFAULT '',
    expected_gain REAL DEFAULT NULL,
    risk_score REAL DEFAULT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT DEFAULT 'system',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS proposal_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (proposal_id) REFERENCES proposals(proposal_id)
);

CREATE TABLE IF NOT EXISTS proposal_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    actor TEXT DEFAULT 'system',
    reason TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (proposal_id) REFERENCES proposals(proposal_id)
);

CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposals_priority ON proposals(priority);
CREATE INDEX IF NOT EXISTS idx_proposals_created ON proposals(created_at);
CREATE INDEX IF NOT EXISTS idx_prop_evidence_pid ON proposal_evidence(proposal_id);
CREATE INDEX IF NOT EXISTS idx_prop_transitions_pid ON proposal_transitions(proposal_id);
"""

# ============ State Machine ============

VALID_TRANSITIONS = {
    "draft":          ["pending_review", "cancelled"],
    "pending_review":  ["approved", "rejected"],
    "approved":       ["experimenting", "cancelled"],
    "experimenting":  ["validated", "failed", "cancelled"],
    "validated":      ["released", "cancelled"],
    "released":       ["deprecated", "rolled_back"],
    "failed":         ["draft", "cancelled"],       # retry or give up
    "rolled_back":    ["draft", "cancelled"],       # retry or give up
    "rejected":       [],                           # terminal
    "deprecated":     [],                           # terminal
    "cancelled":      [],                           # terminal
}

TERMINAL_STATES = {"rejected", "deprecated", "cancelled"}


def _ensure_schema():
    db = get_db()
    db.executescript(PROPOSALS_SCHEMA)
    db.commit()
    db.close()


# ============ Create ============

def create_proposal(
    proposal_id: str,
    title: str,
    summary: str,
    category: str = "",
    source_type: str = "",
    source_ref: str = "",
    priority: str = "P1",
    target_scope: str = "",
    target_module: str = "",
    change_description: str = "",
    expected_gain: float = None,
    risk_score: float = None,
    created_by: str = "system",
    initial_status: str = "draft",
    evidence: list[dict] = None,
) -> dict:
    """Create a new proposal.

    Args:
        evidence: Optional list of {"type": str, "ref": str, "description": str}

    Returns:
        {"success": bool, "proposal_id": str, "message": str}
    """
    _ensure_schema()
    db = get_db()

    try:
        # Check duplicate
        existing = db.execute(
            "SELECT proposal_id FROM proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if existing:
            return {"success": False, "proposal_id": proposal_id,
                    "message": f"Proposal {proposal_id} already exists"}

        db.execute(
            """INSERT INTO proposals
               (proposal_id, title, summary, category, source_type, source_ref,
                priority, target_scope, target_module, change_description,
                expected_gain, risk_score, status, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (proposal_id, title, summary, category, source_type, source_ref,
             priority, target_scope, target_module, change_description,
             expected_gain, risk_score, initial_status, created_by),
        )

        # Record initial transition
        db.execute(
            """INSERT INTO proposal_transitions
               (proposal_id, from_status, to_status, actor, reason)
               VALUES (?, '', ?, ?, 'Created')""",
            (proposal_id, initial_status, created_by),
        )

        # Attach evidence if provided
        if evidence:
            for e in evidence:
                db.execute(
                    """INSERT INTO proposal_evidence
                       (proposal_id, evidence_type, evidence_ref, description)
                       VALUES (?, ?, ?, ?)""",
                    (proposal_id, e.get("type", ""), e.get("ref", ""), e.get("description", "")),
                )

        db.commit()

        # Log event
        _log_event("proposal_created", proposal_id, {
            "priority": priority, "source_type": source_type, "created_by": created_by,
        })

        return {"success": True, "proposal_id": proposal_id,
                "message": f"Proposal created: {proposal_id}"}

    except Exception as e:
        return {"success": False, "proposal_id": proposal_id, "message": str(e)}
    finally:
        db.close()


# ============ Transition ============

def transition(
    proposal_id: str,
    new_status: str,
    actor: str = "system",
    reason: str = "",
) -> dict:
    """Transition a proposal to a new status.

    Enforces valid transitions. Records transition history and event.

    Returns:
        {"success": bool, "old_status": str, "new_status": str, "message": str}
    """
    _ensure_schema()
    db = get_db()

    try:
        row = db.execute(
            "SELECT status FROM proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()

        if not row:
            return {"success": False, "old_status": "", "new_status": new_status,
                    "message": f"Proposal {proposal_id} not found"}

        current = row["status"]

        if current in TERMINAL_STATES:
            return {"success": False, "old_status": current, "new_status": new_status,
                    "message": f"Proposal is in terminal state: {current}"}

        valid_next = VALID_TRANSITIONS.get(current, [])
        if new_status not in valid_next:
            return {"success": False, "old_status": current, "new_status": new_status,
                    "message": f"Invalid transition: {current} → {new_status}. Valid: {valid_next}"}

        # Apply
        now = datetime.now().isoformat()
        db.execute(
            "UPDATE proposals SET status = ?, updated_at = ? WHERE proposal_id = ?",
            (new_status, now, proposal_id),
        )
        db.execute(
            """INSERT INTO proposal_transitions
               (proposal_id, from_status, to_status, actor, reason)
               VALUES (?, ?, ?, ?, ?)""",
            (proposal_id, current, new_status, actor, reason),
        )
        db.commit()

        _log_event(f"proposal_{new_status}", proposal_id, {
            "from": current, "to": new_status, "actor": actor, "reason": reason,
        })

        return {"success": True, "old_status": current, "new_status": new_status,
                "message": f"{current} → {new_status}"}

    except Exception as e:
        return {"success": False, "old_status": "", "new_status": new_status,
                "message": str(e)}
    finally:
        db.close()


# ============ Query ============

def get_proposal(proposal_id: str) -> dict | None:
    """Get full proposal with evidence and transition history."""
    _ensure_schema()
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if not row:
            return None

        result = dict(row)

        # Attach evidence
        evidence = db.execute(
            "SELECT * FROM proposal_evidence WHERE proposal_id = ? ORDER BY created_at",
            (proposal_id,),
        ).fetchall()
        result["evidence"] = [dict(e) for e in evidence]

        # Attach transition history
        transitions = db.execute(
            "SELECT * FROM proposal_transitions WHERE proposal_id = ? ORDER BY created_at",
            (proposal_id,),
        ).fetchall()
        result["transitions"] = [dict(t) for t in transitions]

        return result
    finally:
        db.close()


def list_proposals(
    status: str = None,
    priority: str = None,
    limit: int = 50,
) -> list[dict]:
    """List proposals with optional filters."""
    _ensure_schema()
    db = get_db()
    try:
        conditions = []
        params = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if priority:
            conditions.append("priority = ?")
            params.append(priority)
        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        rows = db.execute(
            f"SELECT * FROM proposals WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def get_actionable_proposals() -> list[dict]:
    """Get proposals that need action (non-terminal, non-experimenting)."""
    _ensure_schema()
    db = get_db()
    try:
        rows = db.execute(
            """SELECT * FROM proposals
               WHERE status NOT IN ('rejected', 'deprecated', 'cancelled', 'released')
               ORDER BY
                 CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
                 created_at ASC""",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


# ============ Evidence ============

def attach_evidence(
    proposal_id: str,
    evidence_type: str,
    evidence_ref: str,
    description: str = "",
) -> dict:
    """Attach evidence to a proposal."""
    _ensure_schema()
    db = get_db()
    try:
        db.execute(
            """INSERT INTO proposal_evidence
               (proposal_id, evidence_type, evidence_ref, description)
               VALUES (?, ?, ?, ?)""",
            (proposal_id, evidence_type, evidence_ref, description),
        )
        db.commit()
        return {"success": True, "message": f"Evidence attached to {proposal_id}"}
    except Exception as e:
        return {"success": False, "message": str(e)}
    finally:
        db.close()


# ============ Stats ============

def get_stats() -> dict:
    """Get proposal statistics."""
    _ensure_schema()
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
        by_status = {}
        for r in db.execute(
            "SELECT status, COUNT(*) as c FROM proposals GROUP BY status ORDER BY c DESC"
        ).fetchall():
            by_status[r["status"]] = r["c"]
        by_priority = {}
        for r in db.execute(
            "SELECT priority, COUNT(*) as c FROM proposals GROUP BY priority ORDER BY c DESC"
        ).fetchall():
            by_priority[r["priority"]] = r["c"]
        return {
            "total": total,
            "by_status": by_status,
            "by_priority": by_priority,
        }
    finally:
        db.close()


# ============ Migration: import from legacy evolution_changes ============

def migrate_from_evolution_changes() -> dict:
    """One-time migration: import proposals from legacy evolution_changes table.

    Maps old status to new status:
      pending → pending_review
      applied → experimenting
      verified + effective → released
      verified + ineffective → failed
      rolled_back → rolled_back
    """
    _ensure_schema()
    db = get_db()
    migrated = 0
    skipped = 0

    try:
        rows = db.execute("SELECT * FROM evolution_changes").fetchall()
        for r in rows:
            change_id = r["change_id"]
            # Skip if already migrated
            existing = db.execute(
                "SELECT proposal_id FROM proposals WHERE proposal_id = ?",
                (change_id,),
            ).fetchone()
            if existing:
                skipped += 1
                continue

            # Map status
            old_status = r.get("lifecycle_status") or r.get("status") or "applied"
            verdict = r.get("verdict")
            if old_status == "pending":
                new_status = "pending_review"
            elif old_status == "applied":
                new_status = "experimenting"
            elif old_status == "verified" and verdict == "effective":
                new_status = "released"
            elif old_status == "verified":
                new_status = "failed"
            elif old_status == "rolled_back":
                new_status = "rolled_back"
            else:
                new_status = "draft"

            db.execute(
                """INSERT INTO proposals
                   (proposal_id, title, summary, category, source_type, target_module,
                    change_description, status, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'migration', ?)""",
                (change_id, r["suggestion"][:100], r["suggestion"],
                 r["task_type"], "legacy", r["target_file"],
                 r.get("change_description", ""), new_status,
                 r.get("applied_at", datetime.now().isoformat())),
            )
            migrated += 1

        db.commit()
        return {"migrated": migrated, "skipped": skipped, "total_legacy": len(rows)}
    except Exception as e:
        return {"error": str(e), "migrated": migrated, "skipped": skipped}
    finally:
        db.close()


# ============ Helpers ============

def _log_event(event_type: str, proposal_id: str, detail: dict):
    """Log to evolution_runtime events if available."""
    try:
        from evolution_runtime import log_event
        log_event(event_type, proposal_id, detail)
    except Exception:
        pass


# ============ CLI ============

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Proposal Lifecycle Manager")
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Create a proposal")
    p_create.add_argument("proposal_id")
    p_create.add_argument("title")
    p_create.add_argument("--summary", default="")
    p_create.add_argument("--priority", default="P1")
    p_create.add_argument("--target-module", default="")

    # transition
    p_trans = sub.add_parser("transition", help="Transition status")
    p_trans.add_argument("proposal_id")
    p_trans.add_argument("new_status")
    p_trans.add_argument("--reason", default="")

    # get
    p_get = sub.add_parser("get", help="Get proposal details")
    p_get.add_argument("proposal_id")

    # list
    p_list = sub.add_parser("list", help="List proposals")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--priority", default=None)
    p_list.add_argument("--limit", type=int, default=20)

    # stats
    sub.add_parser("stats", help="Proposal statistics")

    # actionable
    sub.add_parser("actionable", help="List actionable proposals")

    # migrate
    sub.add_parser("migrate", help="Migrate from legacy evolution_changes")

    args = parser.parse_args()

    if args.command == "create":
        r = create_proposal(args.proposal_id, args.title,
                           summary=args.summary or args.title,
                           priority=args.priority,
                           target_module=args.target_module)
        print(f"{'✅' if r['success'] else '❌'} {r['message']}")

    elif args.command == "transition":
        r = transition(args.proposal_id, args.new_status, reason=args.reason)
        print(f"{'✅' if r['success'] else '❌'} {r['message']}")

    elif args.command == "get":
        p = get_proposal(args.proposal_id)
        if p:
            print(json.dumps(p, indent=2, ensure_ascii=False, default=str))
        else:
            print("Not found")

    elif args.command == "list":
        for p in list_proposals(status=args.status, priority=args.priority, limit=args.limit):
            icon = {"draft": "📝", "pending_review": "⏳", "approved": "✅",
                    "experimenting": "🔬", "validated": "✓", "released": "🚀",
                    "failed": "❌", "rejected": "🚫", "rolled_back": "↩️"}.get(p["status"], "•")
            print(f"  {icon} [{p['status']}] {p['proposal_id']}: {p['title'][:50]}")

    elif args.command == "stats":
        s = get_stats()
        print(f"Total: {s['total']}")
        for status, count in s["by_status"].items():
            print(f"  {status}: {count}")

    elif args.command == "actionable":
        for p in get_actionable_proposals():
            print(f"  [{p['priority']}] [{p['status']}] {p['proposal_id']}: {p['title'][:50]}")

    elif args.command == "migrate":
        r = migrate_from_evolution_changes()
        print(f"Migrated: {r.get('migrated', 0)}, Skipped: {r.get('skipped', 0)}")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
