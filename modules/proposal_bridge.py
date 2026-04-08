#!/usr/bin/env python3
"""
Proposal Bridge — external-learning → self-evolution 桥接模块。

职责：
- 读取结构化学习项（来自 gather_v3 或 memory_db observations）
- 按优先级筛选：P0 直接创建 evolution proposal，P1 写入候选队列，其余 skip
- 调用 evolution_executor.register_external_learning_proposal() 完成注册
- P0 级提案自动触发 auto_evolve

这是三插件联动的关键桥接层，将文档中的承诺变为可执行代码。
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from datetime import datetime

# Setup paths
_workspace = Path(__file__).resolve().parent.parent
_modules = _workspace / "modules"
for p in [str(_workspace), str(_modules)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from runtime_config import XMEMORY_PATH
    if str(XMEMORY_PATH) not in sys.path:
        sys.path.insert(0, str(XMEMORY_PATH))
except ImportError:
    _xm = _workspace / "X\u8bb0\u5fc6"
    if _xm.exists() and str(_xm) not in sys.path:
        sys.path.insert(0, str(_xm))


def process_learning_items(items: list[dict]) -> dict:
    """Process structured learning items into evolution proposals.

    Args:
        items: List of learning items, each with at least:
            - id or proposal_id: unique identifier
            - priority: "P0", "P1", or "P2"/"skip"
            - summary: short description
            - target_module (optional): which module to improve
            - change_description (optional): what to change

    Returns:
        {
            "processed": int,
            "p0_proposals": int,
            "p1_candidates": int,
            "skipped": int,
            "results": list[dict],
            "auto_evolve_triggered": bool,
        }
    """
    results = []
    p0_count = 0
    p1_count = 0
    skipped = 0

    for item in items:
        priority = item.get("priority", "P2").upper()
        item_id = item.get("id") or item.get("proposal_id") or f"learn_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        summary = item.get("summary", "")[:200]

        if priority == "P0":
            result = _register_proposal(item_id, summary, item)
            results.append(result)
            if result.get("success"):
                p0_count += 1
            else:
                print(f"  ⚠️ P0 registration failed: {result.get('message')}")

        elif priority == "P1":
            result = _record_candidate(item_id, summary, item)
            results.append(result)
            p1_count += 1

        else:
            skipped += 1
            results.append({
                "id": item_id,
                "action": "skipped",
                "priority": priority,
                "success": True,
                "message": f"Priority {priority} — skipped",
            })

    # Auto-trigger evolve for P0 proposals
    auto_triggered = False
    if p0_count > 0:
        auto_triggered = _trigger_auto_evolve()

    summary = {
        "processed": len(items),
        "p0_proposals": p0_count,
        "p1_candidates": p1_count,
        "skipped": skipped,
        "results": results,
        "auto_evolve_triggered": auto_triggered,
    }

    print(f"[proposal_bridge] Processed {len(items)} items: "
          f"P0={p0_count}, P1={p1_count}, skip={skipped}, "
          f"auto_evolve={'yes' if auto_triggered else 'no'}")

    return summary


def process_learning_note(note: dict) -> dict:
    """Process a single learning note. Convenience wrapper.

    Args:
        note: Single learning item dict

    Returns:
        Processing result dict
    """
    result = process_learning_items([note])
    return result["results"][0] if result["results"] else {"success": False, "message": "No items"}


def _register_proposal(item_id: str, summary: str, item: dict) -> dict:
    """Register a P0 item as an evolution proposal via proposal_lifecycle_manager."""
    try:
        from proposal_lifecycle_manager import create_proposal

        proposal_id = f"ext_{item_id}_{datetime.now().strftime('%Y%m%d')}"
        result = create_proposal(
            proposal_id=proposal_id,
            title=summary[:100],
            summary=summary,
            category=item.get("type", "external_learning"),
            source_type="external_learning",
            source_ref=item_id,
            priority=item.get("priority", "P0"),
            target_module=item.get("target_module", ""),
            change_description=item.get("change_description", summary),
            initial_status="draft",
            evidence=[{
                "type": "learning_item",
                "ref": item_id,
                "description": summary[:200],
            }],
        )
        result["action"] = "registered_proposal"
        result["priority"] = item.get("priority", "P0")
        result["id"] = item_id
        result["proposal_id"] = proposal_id
        return result

    except Exception as e:
        return {
            "id": item_id,
            "action": "register_failed",
            "priority": "P0",
            "success": False,
            "message": str(e),
        }


def _record_candidate(item_id: str, summary: str, item: dict) -> dict:
    """Record a P1 item as a landing candidate via memory_governor."""
    try:
        from memory_governor import add_observation as gov_add

        result = gov_add(
            type="discovery",
            title=f"[P1 Candidate] {summary[:80]}",
            narrative=json.dumps(item, ensure_ascii=False, default=str),
            source="external_learning",
            tags="learning,P1,candidate",
            task_type="external_learning",
            origin_module="proposal_bridge",
            origin_ref=item_id,
        )
        return {
            "id": item_id,
            "action": "recorded_candidate",
            "priority": "P1",
            "success": result.get("success", False),
            "observation_id": result.get("observation_id"),
            "message": result.get("message", ""),
        }

    except Exception as e:
        return {
            "id": item_id,
            "action": "record_failed",
            "priority": "P1",
            "success": False,
            "message": str(e),
        }


def _trigger_auto_evolve() -> bool:
    """Trigger evolution via orchestrator for P0 proposals.
    
    Prefers orchestrator.advance_proposals() for unified flow.
    Falls back to auto_evolve if orchestrator unavailable.
    """
    try:
        # Prefer orchestrator (unified entry point)
        from evolution_orchestrator import advance_proposals
        print("[proposal_bridge] ⚡ P0 detected — advancing via orchestrator...")
        result = advance_proposals()
        if result["advanced"] > 0:
            print(f"[proposal_bridge] Orchestrator advanced {result['advanced']} proposals")
        return True
    except ImportError:
        pass
    except Exception as e:
        print(f"[proposal_bridge] ⚠️ orchestrator failed: {e}, falling back to auto_evolve")

    # Fallback: direct auto_evolve
    try:
        from auto_evolve import evolve
        try:
            from llm_provider import is_available
            can_execute = is_available()
        except ImportError:
            can_execute = False

        mode = "execute" if can_execute else "diagnose-only"
        print(f"[proposal_bridge] Fallback: auto_evolve ({mode})...")
        evolve(min_pattern_count=1, auto_execute=can_execute, max_rounds=1)
        return True
    except Exception as e:
        print(f"[proposal_bridge] ⚠️ auto_evolve also failed: {e}")
        return False


def scan_pending_observations() -> dict:
    """Scan memory_db for unprocessed high-score learning observations.

    Finds observations with type='discovery' and source='external_learning'
    that haven't been converted to proposals yet.

    Returns:
        process_learning_items result
    """
    try:
        from db_common import get_db
        db = get_db()

        rows = db.execute("""
            SELECT id, title, narrative, tags, created_at
            FROM observations
            WHERE type = 'discovery'
              AND source = 'external_learning'
              AND source != 'proposal_bridge'
              AND title NOT LIKE '[P1 Candidate]%'
              AND title NOT LIKE '[P0%'
            ORDER BY created_at DESC
            LIMIT 20
        """).fetchall()
        db.close()

        items = []
        for r in rows:
            # Try to parse narrative as JSON for structured data
            meta = {}
            try:
                meta = json.loads(r["narrative"]) if r["narrative"] else {}
            except (json.JSONDecodeError, TypeError):
                pass

            priority = "P2"  # Default
            tags = r["tags"] or ""
            if "P0" in tags:
                priority = "P0"
            elif "P1" in tags:
                priority = "P1"
            elif meta.get("priority"):
                priority = meta["priority"]

            items.append({
                "id": f"obs_{r['id']}",
                "priority": priority,
                "summary": r["title"][:200],
                "target_module": meta.get("target_module", ""),
                "change_description": meta.get("change_description", ""),
            })

        if items:
            return process_learning_items(items)
        else:
            print("[proposal_bridge] No pending learning observations found")
            return {"processed": 0, "p0_proposals": 0, "p1_candidates": 0, "skipped": 0, "results": [], "auto_evolve_triggered": False}

    except Exception as e:
        print(f"[proposal_bridge] Scan failed: {e}")
        return {"processed": 0, "p0_proposals": 0, "p1_candidates": 0, "skipped": 0, "results": [], "auto_evolve_triggered": False}


# ============ CLI ============

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Proposal Bridge: external-learning → self-evolution")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("scan", help="Scan pending observations and create proposals")

    p_process = sub.add_parser("process", help="Process a JSON file of learning items")
    p_process.add_argument("file", help="JSON file with learning items array")

    args = parser.parse_args()

    if args.command == "scan":
        result = scan_pending_observations()
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    elif args.command == "process":
        with open(args.file, "r", encoding="utf-8") as f:
            items = json.load(f)
        result = process_learning_items(items)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
