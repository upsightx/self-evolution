#!/usr/bin/env python3
"""
Evolution Orchestrator — 进化编排器。

职责：
- 统一触发入口（消除 bridge/runtime/executor 多头触发）
- 信号接收 → 路由 → 提案创建 → 实验调度 → 发布判定
- 节流与去重（同一信号不重复处理）
- 心跳驱动的批量推进

设计原则：
- 这是进化流程的唯一大入口
- 其他模块只上报事实，由 orchestrator 决定下一步
- 所有提案通过 proposal_lifecycle_manager 管理状态
"""
from __future__ import annotations

import json
import sys
import hashlib
from datetime import datetime, timedelta
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


# ============ Signal Dedup ============

_SIGNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS evolution_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL UNIQUE,
    signal_type TEXT NOT NULL,
    source_id TEXT DEFAULT '',
    task_type TEXT DEFAULT '',
    severity REAL DEFAULT 0.5,
    recurrence_count INTEGER DEFAULT 1,
    status TEXT DEFAULT 'new',
    routed_to TEXT DEFAULT NULL,
    proposal_id TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_signals_status ON evolution_signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_type ON evolution_signals(signal_type);
"""


def _ensure_schema():
    db = get_db()
    db.executescript(_SIGNAL_SCHEMA)
    db.commit()
    db.close()


def _signal_hash(signal_type: str, source_id: str, task_type: str) -> str:
    """Generate a dedup hash for a signal."""
    raw = f"{signal_type}:{source_id}:{task_type}"
    return "sig_" + hashlib.md5(raw.encode()).hexdigest()[:12]


# ============ Signal Ingestion ============

def ingest_signal(
    signal_type: str,
    source_id: str = "",
    task_type: str = "",
    severity: float = 0.5,
    metadata: dict = None,
) -> dict:
    """Ingest a single evolution signal.

    Signal types:
      - task_failure: repeated task failures
      - learning_item: from external learning
      - memory_pattern: from capability_detector analysis
      - capability_gap: from capability_model
      - goal_gap: from goal_tree

    Returns:
        {"signal_id": str, "action": "new"|"incremented"|"duplicate", "recurrence": int}
    """
    _ensure_schema()
    db = get_db()

    signal_id = _signal_hash(signal_type, source_id, task_type)

    try:
        existing = db.execute(
            "SELECT id, recurrence_count, status FROM evolution_signals WHERE signal_id = ?",
            (signal_id,),
        ).fetchone()

        if existing:
            if existing["status"] in ("processed", "ignored"):
                return {"signal_id": signal_id, "action": "duplicate", "recurrence": existing["recurrence_count"]}

            # Increment recurrence
            new_count = existing["recurrence_count"] + 1
            db.execute(
                "UPDATE evolution_signals SET recurrence_count = ?, severity = MAX(severity, ?) WHERE signal_id = ?",
                (new_count, severity, signal_id),
            )
            db.commit()
            return {"signal_id": signal_id, "action": "incremented", "recurrence": new_count}

        # New signal
        db.execute(
            """INSERT INTO evolution_signals
               (signal_id, signal_type, source_id, task_type, severity, status)
               VALUES (?, ?, ?, ?, ?, 'new')""",
            (signal_id, signal_type, source_id, task_type, severity),
        )
        db.commit()

        _log_event("signal_ingested", signal_id, {
            "signal_type": signal_type, "source_id": source_id, "severity": severity,
        })

        return {"signal_id": signal_id, "action": "new", "recurrence": 1}

    finally:
        db.close()


def ingest_signals(signals: list[dict]) -> dict:
    """Batch ingest signals.

    Each signal dict should have: signal_type, source_id, task_type, severity (optional).
    """
    results = []
    for s in signals:
        r = ingest_signal(
            signal_type=s.get("signal_type", "unknown"),
            source_id=s.get("source_id", ""),
            task_type=s.get("task_type", ""),
            severity=s.get("severity", 0.5),
            metadata=s.get("metadata"),
        )
        results.append(r)

    new_count = sum(1 for r in results if r["action"] == "new")
    return {"total": len(signals), "new": new_count, "results": results}


# ============ Routing ============

def route_pending_signals(min_recurrence: int = 2, min_severity: float = 0.3) -> dict:
    """Route pending signals to appropriate actions.

    Routing logic:
      - severity >= 0.8 AND recurrence >= 2 → create P0 proposal
      - severity >= 0.5 AND recurrence >= 3 → create P1 proposal
      - severity >= 0.3 AND recurrence >= min_recurrence → create P2 proposal
      - else → keep as signal, wait for more evidence

    Returns:
        {"routed": int, "proposals_created": int, "kept": int}
    """
    _ensure_schema()
    db = get_db()

    try:
        signals = db.execute(
            """SELECT * FROM evolution_signals
               WHERE status = 'new' AND recurrence_count >= ?
               ORDER BY severity DESC, recurrence_count DESC""",
            (min_recurrence,),
        ).fetchall()

        routed = 0
        proposals_created = 0
        kept = 0

        for s in signals:
            severity = s["severity"]
            recurrence = s["recurrence_count"]

            # Determine priority
            if severity >= 0.8 and recurrence >= 2:
                priority = "P0"
            elif severity >= 0.5 and recurrence >= 3:
                priority = "P1"
            elif severity >= min_severity:
                priority = "P2"
            else:
                kept += 1
                continue

            # Create proposal via lifecycle manager
            proposal_id = f"evo_{s['signal_id']}_{datetime.now().strftime('%m%d')}"
            result = _create_proposal_from_signal(s, proposal_id, priority)

            if result.get("success"):
                db.execute(
                    "UPDATE evolution_signals SET status = 'processed', routed_to = 'proposal', proposal_id = ? WHERE signal_id = ?",
                    (proposal_id, s["signal_id"]),
                )
                proposals_created += 1
            else:
                db.execute(
                    "UPDATE evolution_signals SET status = 'route_failed' WHERE signal_id = ?",
                    (s["signal_id"],),
                )

            routed += 1

        db.commit()
        return {"routed": routed, "proposals_created": proposals_created, "kept": kept}

    finally:
        db.close()


def _create_proposal_from_signal(signal: dict, proposal_id: str, priority: str) -> dict:
    """Create a proposal from a routed signal."""
    try:
        from proposal_lifecycle_manager import create_proposal

        title = f"[{signal['signal_type']}] {signal['task_type'] or 'general'} improvement"
        summary = (f"Signal {signal['signal_id']}: {signal['signal_type']} "
                   f"(severity={signal['severity']}, recurrence={signal['recurrence_count']})")

        # Resolve target module
        target = ""
        try:
            from auto_evolve import _resolve_target_file
            target = _resolve_target_file(signal.get("task_type", ""), "")
        except Exception:
            pass

        return create_proposal(
            proposal_id=proposal_id,
            title=title,
            summary=summary,
            category=signal["signal_type"],
            source_type="signal",
            source_ref=signal["signal_id"],
            priority=priority,
            target_module=target,
            initial_status="draft",
            evidence=[{
                "type": "signal",
                "ref": signal["signal_id"],
                "description": summary,
            }],
        )

    except Exception as e:
        return {"success": False, "message": str(e)}


# ============ Proposal Advancement ============

def advance_proposals() -> dict:
    """Advance proposals through their lifecycle.

    - draft → pending_review (auto-advance if evidence attached)
    - pending_review → approved (auto-approve P0, P1 needs review)
    - experimenting → check experiment results

    Returns:
        {"advanced": int, "details": list}
    """
    try:
        from proposal_lifecycle_manager import list_proposals, transition, get_proposal
    except ImportError:
        return {"advanced": 0, "details": ["proposal_lifecycle_manager not available"]}

    details = []
    advanced = 0

    # 1. draft → pending_review (if has evidence)
    drafts = list_proposals(status="draft")
    for p in drafts:
        full = get_proposal(p["proposal_id"])
        if full and full.get("evidence"):
            r = transition(p["proposal_id"], "pending_review", actor="orchestrator",
                          reason="Evidence attached, advancing to review")
            if r["success"]:
                advanced += 1
                details.append(f"{p['proposal_id']}: draft → pending_review")

    # 2. pending_review → approved (auto-approve P0)
    pending = list_proposals(status="pending_review")
    for p in pending:
        if p["priority"] == "P0":
            r = transition(p["proposal_id"], "approved", actor="orchestrator",
                          reason="P0 auto-approved")
            if r["success"]:
                advanced += 1
                details.append(f"{p['proposal_id']}: pending_review → approved (P0 auto)")

    return {"advanced": advanced, "details": details}


# ============ Heartbeat ============

def heartbeat() -> dict:
    """Main orchestrator heartbeat. Called periodically.

    Steps:
    1. Collect signals from capability_detector
    2. Route pending signals to proposals
    3. Advance proposals through lifecycle
    4. Report summary

    Returns:
        Summary of actions taken
    """
    actions = []
    timestamp = datetime.now().isoformat()

    # 1. Run capability detection (replaces old feedback_loop)
    try:
        from capability_detector import detect_all
        detection = detect_all()
        
        # Ingest missing capabilities as high-severity signals
        for m in detection.get("missing", []):
            ingest_signal(
                signal_type="capability_missing",
                source_id=m.get("task_type", ""),
                task_type=m.get("task_type", ""),
                severity=1.0,
            )
        
        # Ingest struggling capabilities
        for s in detection.get("struggling", []):
            ingest_signal(
                signal_type="capability_struggling",
                source_id=f"{s.get('task_type', '')}_{s.get('model', '')}",
                task_type=s.get("task_type", ""),
                severity=1.0 - s.get("success_rate", 0.5),
            )
        
        # Ingest degradation signals
        for d in detection.get("degrading", []):
            ingest_signal(
                signal_type="capability_degrading",
                source_id=f"{d.get('task_type', '')}_{d.get('model', '')}",
                task_type=d.get("task_type", ""),
                severity=d.get("drop", 0.3),
            )
        
        n_issues = len(detection.get("missing", [])) + len(detection.get("struggling", [])) + len(detection.get("degrading", []))
        n_good = len(detection.get("reliable", [])) + len(detection.get("strengths", []))
        if n_issues or n_good:
            actions.append(f"Capability scan: {n_issues} issues, {n_good} reliable")
        if detection.get("recommendations"):
            for rec in detection["recommendations"][:3]:
                actions.append(f"  → {rec}")
    except Exception as e:
        actions.append(f"Capability detection error: {e}")

    # 3. Route signals to proposals
    try:
        route_result = route_pending_signals()
        if route_result["proposals_created"] > 0:
            actions.append(f"Created {route_result['proposals_created']} proposals from signals")
    except Exception as e:
        actions.append(f"Routing error: {e}")

    # 4. Advance proposals
    try:
        advance_result = advance_proposals()
        if advance_result["advanced"] > 0:
            actions.append(f"Advanced {advance_result['advanced']} proposals")
            for d in advance_result["details"]:
                actions.append(f"  → {d}")
    except Exception as e:
        actions.append(f"Advancement error: {e}")

    # 5. Scan external learning
    try:
        from proposal_bridge import scan_pending_observations
        scan = scan_pending_observations()
        if scan["processed"] > 0:
            actions.append(f"Processed {scan['processed']} external learning items")
    except Exception as e:
        actions.append(f"External learning scan error: {e}")

    # 6. Proactive capability building
    try:
        experiments = scan_capability_gaps()
        if experiments:
            actions.append(f"Created {len(experiments)} capability experiments")
    except Exception as e:
        actions.append(f"Capability experiment error: {e}")

    summary = {
        "timestamp": timestamp,
        "actions": actions,
        "action_count": len(actions),
    }

    if actions:
        print(f"[orchestrator] Heartbeat: {len(actions)} actions")
        for a in actions:
            print(f"  • {a}")
    else:
        print("[orchestrator] Heartbeat: all clear")

    return summary


# ============ Proactive Capability Building ============

def create_capability_experiment(
    capability_name: str,
    description: str,
    approach: str = "",
    priority: str = "P1",
) -> dict:
    """Proactively create an experiment to build a missing capability.

    Unlike reactive proposals (from failure patterns), this is triggered when
    the system detects it LACKS a capability entirely — not that it's failing,
    but that it can't even attempt certain tasks.

    Args:
        capability_name: What capability to build (e.g., "pdf_processing", "image_analysis")
        description: What the capability should do
        approach: How to build it (e.g., "install tool X", "create skill Y")
        priority: P0/P1/P2

    Returns:
        {"success": bool, "proposal_id": str, "message": str}
    """
    try:
        from proposal_lifecycle_manager import create_proposal

        proposal_id = f"cap_{capability_name}_{datetime.now().strftime('%m%d%H%M')}"
        result = create_proposal(
            proposal_id=proposal_id,
            title=f"Build capability: {capability_name}",
            summary=description,
            category="capability_building",
            source_type="proactive",
            priority=priority,
            target_scope=capability_name,
            change_description=approach or f"Research and implement {capability_name}",
            initial_status="draft",
            evidence=[{
                "type": "capability_gap",
                "ref": capability_name,
                "description": f"System lacks {capability_name} capability",
            }],
        )

        if result.get("success"):
            _log_event("capability_experiment_created", proposal_id, {
                "capability": capability_name,
                "priority": priority,
                "approach": approach[:100],
            })
            print(f"[orchestrator] 🧪 Created capability experiment: {capability_name} ({priority})")

        return result

    except Exception as e:
        return {"success": False, "proposal_id": "", "message": str(e)}


def scan_capability_gaps() -> list[dict]:
    """Scan for capability gaps and proactively create experiments.

    Checks:
    1. Task types with 0% success rate (complete inability)
    2. Task types attempted but never succeeded
    3. Known capability dimensions scoring 0

    Returns:
        List of created experiment proposals
    """
    created = []
    db = get_db()

    try:
        # Find task types with 0% success (attempted but always fail)
        zero_success = db.execute(
            """SELECT task_type, COUNT(*) as attempts, model
               FROM task_outcomes
               WHERE success = 0
               GROUP BY task_type
               HAVING attempts >= 2
                 AND task_type NOT IN (
                     SELECT task_type FROM task_outcomes WHERE success = 1
                 )"""
        ).fetchall()

        for row in zero_success:
            result = create_capability_experiment(
                capability_name=row["task_type"],
                description=f"Task type '{row['task_type']}' has {row['attempts']} attempts, 0 successes",
                approach=f"Investigate why {row['task_type']} always fails, find tools or methods to fix",
                priority="P0" if row["attempts"] >= 5 else "P1",
            )
            if result.get("success"):
                created.append(result)

    except Exception as e:
        print(f"[orchestrator] Capability gap scan error: {e}")
    finally:
        db.close()

    # Also check capability_model for zero-score dimensions
    try:
        from capability_model import get_weaknesses
        weaknesses = get_weaknesses(threshold=10.0)  # Very low threshold = near-zero capability
        for w in weaknesses[:3]:
            if w.get("score", 0) < 10 and w.get("sample_count", 0) >= 3:
                result = create_capability_experiment(
                    capability_name=w["name"],
                    description=f"Capability '{w['name']}' scores {w['score']:.0f}/100 — near zero",
                    approach=f"Build or acquire {w['name']} capability",
                    priority="P1",
                )
                if result.get("success"):
                    created.append(result)
    except Exception:
        pass

    if created:
        print(f"[orchestrator] Created {len(created)} capability experiments")

    return created


# ============ Stats ============

def get_signal_stats() -> dict:
    """Get signal statistics."""
    _ensure_schema()
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM evolution_signals").fetchone()[0]
        by_status = {}
        for r in db.execute(
            "SELECT status, COUNT(*) as c FROM evolution_signals GROUP BY status"
        ).fetchall():
            by_status[r["status"]] = r["c"]
        by_type = {}
        for r in db.execute(
            "SELECT signal_type, COUNT(*) as c FROM evolution_signals GROUP BY signal_type ORDER BY c DESC"
        ).fetchall():
            by_type[r["signal_type"]] = r["c"]
        return {"total": total, "by_status": by_status, "by_type": by_type}
    finally:
        db.close()


# ============ Helpers ============

def _log_event(event_type: str, ref_id: str, detail: dict):
    try:
        from evolution_runtime import log_event
        log_event(event_type, ref_id, detail)
    except Exception:
        pass


# ============ CLI ============

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Evolution Orchestrator")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("heartbeat", help="Run orchestrator heartbeat")

    p_signal = sub.add_parser("signal", help="Ingest a signal")
    p_signal.add_argument("signal_type")
    p_signal.add_argument("--source-id", default="")
    p_signal.add_argument("--task-type", default="")
    p_signal.add_argument("--severity", type=float, default=0.5)

    sub.add_parser("route", help="Route pending signals")
    sub.add_parser("advance", help="Advance proposals")
    sub.add_parser("stats", help="Signal statistics")

    args = parser.parse_args()

    if args.command == "heartbeat":
        r = heartbeat()
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str))

    elif args.command == "signal":
        r = ingest_signal(args.signal_type, args.source_id, args.task_type, args.severity)
        print(f"Signal: {r}")

    elif args.command == "route":
        r = route_pending_signals()
        print(f"Routed: {r['routed']}, Proposals: {r['proposals_created']}")

    elif args.command == "advance":
        r = advance_proposals()
        print(f"Advanced: {r['advanced']}")
        for d in r["details"]:
            print(f"  {d}")

    elif args.command == "stats":
        s = get_signal_stats()
        print(json.dumps(s, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
