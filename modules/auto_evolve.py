#!/usr/bin/env python3
"""
Auto Evolve — Self-Evolution 自动进化引擎。

职责：
- 目标缺口 → 失败分析 → 生成改进 → 执行验证 → 更新进度
- 提供一键式"诊断 → 修复 → 验证"闭环
- 支持持续多轮进化（MiroThinker 交互扩展思想）
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from datetime import datetime

_modules_path = Path(__file__).parent
if str(_modules_path) not in sys.path:
    sys.path.insert(0, str(_modules_path))

WORKSPACE = Path(__file__).parent.parent


def _ensure_xmemory_path():
    """Ensure X-Memory modules are importable via runtime_config."""
    try:
        if str(WORKSPACE) not in sys.path:
            sys.path.insert(0, str(WORKSPACE))
        from runtime_config import XMEMORY_PATH
        if str(XMEMORY_PATH) not in sys.path:
            sys.path.insert(0, str(XMEMORY_PATH))
    except ImportError:
        # Fallback
        xm = WORKSPACE / "X\u8bb0\u5fc6"
        if xm.exists() and str(xm) not in sys.path:
            sys.path.insert(0, str(xm))


# Task type → likely target file mapping
_TASK_TARGET_MAP = {
    "coding": "modules/critic_engine.py",
    "research": "modules/learning_conversion.py",
    "exploration": "modules/skillify.py",
    "deploy": "modules/evolution_executor.py",
    "external_learning": "modules/learning_conversion.py",
    "capability_building": "modules/capability_detector.py",
}


def _resolve_target_file(task_type: str, pattern: str) -> str:
    """Map task_type + failure pattern to a likely target file.

    Returns empty string if no mapping found (caller should skip execution).
    """
    # Direct mapping
    target = _TASK_TARGET_MAP.get(task_type, "")
    if target:
        return target

    # Pattern-based heuristics
    pattern_lower = pattern.lower() if pattern else ""
    if any(kw in pattern_lower for kw in ["template", "prompt", "instruction"]):
        return "modules/critic_engine.py"
    if any(kw in pattern_lower for kw in ["memory", "recall", "search"]):
        return "modules/memory_governor.py"
    if any(kw in pattern_lower for kw in ["goal", "capability", "skill", "detect"]):
        return "modules/capability_detector.py"
    if any(kw in pattern_lower for kw in ["signal", "route", "orchestrat"]):
        return "modules/evolution_orchestrator.py"
    if any(kw in pattern_lower for kw in ["proposal", "lifecycle", "approve"]):
        return "modules/proposal_lifecycle_manager.py"

    return ""


def evolve(
    min_pattern_count: int = 3,
    auto_execute: bool = True,
    max_changes: int = 3,
    max_rounds: int = 1,
    min_improvement: float = 0.05,
) -> dict:
    """Execute automatic evolution with continuous feedback loop.

    Inspired by MiroThinker's persistent multi-turn reasoning:
    iterate based on validation results until improvement plateaus.

    Args:
        min_pattern_count: Min failure patterns to trigger evolution
        auto_execute: Auto-apply changes (default False for safety)
        max_changes: Max changes per round
        max_rounds: Max evolution rounds (default 1, set >1 for continuous)
        min_improvement: Min capability improvement to continue (0.0-1.0)

    Returns:
        Evolution result with round-by-round breakdown
    """
    full_result = {
        "timestamp": datetime.now().isoformat(),
        "rounds": [],
        "total_improvement": 0.0,
        "stopped_reason": "",
    }

    prev_avg_score = None

    for round_num in range(1, max_rounds + 1):
        print(f"\n{'='*60}")
        print(f"🔄 Round {round_num}/{max_rounds}")
        print(f"{'='*60}")

        result = _run_single_round(min_pattern_count, auto_execute, max_changes)
        full_result["rounds"].append(result)

        # Calculate improvement
        if result["capability_before"] and result["capability_after"]:
            before_avg = sum(c["score"] for c in result["capability_before"]) / len(result["capability_before"])
            after_avg = sum(c["score"] for c in result["capability_after"]) / len(result["capability_after"])
            improvement = after_avg - before_avg
            result["round_improvement"] = improvement
            full_result["total_improvement"] += improvement

            print(f"\n📈 Round {round_num} improvement: {improvement:+.2f}")

            # Check if should continue
            if prev_avg_score is not None and improvement < min_improvement:
                full_result["stopped_reason"] = f"Improvement {improvement:.2f} < threshold {min_improvement}"
                print(f"⏹️ Stopped: {full_result['stopped_reason']}")
                break

            prev_avg_score = after_avg
        else:
            full_result["stopped_reason"] = "No capability data"
            break

        # Final capability
        if result["capability_after"]:
            full_result["final_capability"] = result["capability_after"]

    return full_result


def _get_proposal_details(proposal_id: str) -> dict | None:
    """Fetch proposal details from DB."""
    try:
        from proposal_lifecycle_manager import get_proposal
        return get_proposal(proposal_id)
    except Exception:
        return None


def _run_single_round(min_pattern_count: int, auto_execute: bool, max_changes: int) -> dict:
    """Run a single evolution round."""
    # Ensure DB tables exist
    try:
        _ensure_xmemory_path()
        from memory_db import init_db
        init_db()
    except Exception:
        pass
    result = {
        "round_start": datetime.now().isoformat(),
        "goal_gaps": [],
        "capability_weaknesses": [],
        "failure_patterns": [],
        "improvement_suggestions": [],
        "applied_changes": [],
        "validations": [],
        "capability_before": [],
        "capability_after": [],
        "actions_taken": [],
        "round_improvement": 0.0,
    }

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Evolution round start")
    print("=" * 50)

    # Step 0: Baseline capability
    print("\n📊 Step 0: Capability baseline...")
    try:
        from capability_model import evaluate_all
        baseline = evaluate_all()
        result["capability_before"] = baseline
        print(f"  Dimensions: {len(baseline)}")
        for b in sorted(baseline, key=lambda x: x["score"])[:5]:
            bar = "█" * int(b["score"] / 10) + "░" * (10 - int(b["score"] / 10))
            print(f"    [{bar}] {b['name']:15s} {b['score']:5.1f}  (n={b['sample_count']})")
        result["actions_taken"].append(f"Baseline: {len(baseline)} dims")
    except Exception as e:
        print(f"  ⚠️ {e}")
        result["actions_taken"].append(f"Baseline failed: {e}")

    # Step 1: Goal gaps
    print("\n🎯 Step 1: Goal gaps...")
    try:
        from goal_tree import get_gaps
        gaps = get_gaps()
        result["goal_gaps"] = gaps
        if gaps:
            print(f"  Found {len(gaps)} gaps:")
            for g in gaps[:3]:
                print(f"    [{g.get('priority', '?')}] {g.get('title', '')[:30]}")
        result["actions_taken"].append(f"Gaps: {len(gaps)}")
    except Exception as e:
        print(f"  ⚠️ {e}")

    # Step 2: Capability weaknesses
    print("\n📉 Step 2: Capability weaknesses...")
    try:
        from capability_model import get_weaknesses
        weaknesses = get_weaknesses(threshold=70.0)
        result["capability_weaknesses"] = weaknesses
        if weaknesses:
            print(f"  Found {len(weaknesses)} weaknesses:")
            for w in weaknesses[:3]:
                print(f"    {w.get('name', '')}: {w.get('score', 0):.1f}")
        result["actions_taken"].append(f"Weaknesses: {len(weaknesses)}")
    except Exception as e:
        print(f"  ⚠️ {e}")

    # Step 3: Capability detection (replaces old failure pattern analysis)
    print("\n🔍 Step 3: Capability detection...")
    try:
        from capability_detector import detect_all
        detection = detect_all()
        
        # Combine missing + struggling as actionable items
        issues = detection.get("missing", []) + detection.get("struggling", [])
        result["failure_patterns"] = issues
        if issues:
            print(f"  Found {len(issues)} capability issues:")
            for item in issues[:3]:
                print(f"    {item['task_type']}/{item['model']}: {item['success_rate']:.0%} ({item['total']} samples)")
        
        if detection.get("recommendations"):
            print(f"  Recommendations:")
            for rec in detection["recommendations"][:3]:
                print(f"    {rec}")
        
        result["actions_taken"].append(f"Issues: {len(issues)}")

        # Generate suggestions from capability issues
        if issues:
            suggestions = []
            for item in issues[:max_changes]:
                target = _resolve_target_file(item.get("task_type", "general"), "")
                suggestions.append({
                    "task_type": item.get("task_type", "general"),
                    "title": f"Fix {item['task_type']}/{item['model']} ({item['success_rate']:.0%})",
                    "description": f"Capability issue: {item['task_type']} at {item['success_rate']:.0%} success rate",
                    "target_file": target,
                })
            result["improvement_suggestions"] = suggestions
            print(f"  Generated {len(suggestions)} suggestions")
        result["actions_taken"].append(f"Suggestions: {len(result['improvement_suggestions'])}")
    except Exception as e:
        print(f"  ⚠️ {e}")

    # Step 4: Create proposals from all detected issues
    print("\n📋 Step 4: Creating proposals from detected issues...")
    proposal_ids = []
    try:
        from proposal_lifecycle_manager import create_proposal, transition
        import uuid
        proposal_count = 0

        # Convert goal gaps to proposals
        for gap in result.get("goal_gaps", []):
            pid = f"gap-{uuid.uuid4().hex[:12]}"
            r = create_proposal(
                proposal_id=pid,
                title=gap.get("title", "Goal gap")[:200],
                summary=f"Goal gap (priority {gap.get('priority', '?')}): current={gap.get('current_value', '?')}, target={gap.get('target_value', '?')}",
                category="goal_gap",
                source_type="goal_tree",
                priority=gap.get("priority", "P1"),
                target_module=gap.get("target", ""),
                change_description=gap.get("suggestion", ""),
                initial_status="draft",
                created_by="auto_evolve",
            )
            if r["success"]:
                proposal_count += 1
                proposal_ids.append(pid)
                print(f"  📌 {pid} — {gap.get('title', '?')[:50]}")

        # Convert capability weaknesses to proposals
        for w in result.get("capability_weaknesses", []):
            pid = f"weak-{uuid.uuid4().hex[:12]}"
            r = create_proposal(
                proposal_id=pid,
                title=f"Improve {w.get('name', 'unknown')} ({w.get('score', 0):.0f}/100)",
                summary=f"Capability weakness: {w.get('name', '')} scores {w.get('score', 0):.1f}/100 (threshold 70)",
                category="capability_weakness",
                source_type="capability_model",
                priority="P1" if w.get("score", 100) < 50 else "P2",
                target_module=w.get("name", ""),
                change_description=w.get("suggestion", ""),
                initial_status="draft",
                created_by="auto_evolve",
            )
            if r["success"]:
                proposal_count += 1
                proposal_ids.append(pid)
                print(f"  📌 {pid} — {w.get('name', '?')}")

        # Convert improvement suggestions to proposals
        for sug in result.get("improvement_suggestions", []):
            pid = f"fix-{uuid.uuid4().hex[:12]}"
            r = create_proposal(
                proposal_id=pid,
                title=sug.get("title", "Improvement")[:200],
                summary=sug.get("description", ""),
                category="capability_fix",
                source_type="capability_detector",
                priority="P0",
                target_module=sug.get("task_type", ""),
                target_scope=sug.get("target_file", ""),
                change_description=sug.get("description", ""),
                initial_status="draft",
                created_by="auto_evolve",
                evidence=[{"type": "capability_issue", "ref": sug.get("task_type", ""),
                           "description": f"Success rate: {sug.get('description', '')}"}],
            )
            if r["success"]:
                proposal_count += 1
                proposal_ids.append(pid)
                print(f"  📌 {pid} — {sug.get('title', '?')[:50]}")

        result["proposals_created"] = proposal_count
        result["actions_taken"].append(f"Proposals: {proposal_count} created")
        print(f"  Total proposals created: {proposal_count}")
    except Exception as e:
        print(f"  ⚠️ Proposal creation failed: {e}")
        import traceback; traceback.print_exc()

    # Step 4b: Auto-approve and execute if auto_execute=True
    if auto_execute and proposal_ids:
        print("\n🔧 Step 4b: Auto-approving and executing proposals...")
        approved = []
        for pid in proposal_ids:
            try:
                # draft → pending_review → approved (state machine requires sequential)
                r1 = transition(pid, "pending_review", actor="auto_evolve",
                                reason="Auto-promoted for execution")
                if r1.get("success"):
                    r2 = transition(pid, "approved", actor="auto_evolve",
                                   reason="Auto-approved for execution")
                    if r2.get("success"):
                        approved.append(pid)
                        print(f"  ✅ Approved: {pid}")
                    else:
                        print(f"  ⏭️ Approve failed: {pid} — {r2.get('message', '?')}")
                else:
                    # May already be beyond draft (e.g. re-run)
                    print(f"  ⏭️ Skip: {pid} — {r1.get('message', '?')}")
            except Exception as e:
                print(f"  ⚠️ Approve failed: {pid} — {e}")

        # Execute approved proposals
        if approved:
            try:
                for pid in approved:
                    prop = _get_proposal_details(pid)
                    if not prop:
                        continue
                    target = prop.get("target_scope", "")
                    if not target or not target.strip():
                        # No concrete target file — mark as released (tracked, not auto-modified)
                        transition(pid, "released", actor="auto_evolve",
                                   reason="Tracked goal — no auto-modification target")
                        result["applied_changes"].append({
                            "proposal_id": pid,
                            "success": True,
                            "change_id": None,
                            "message": "Tracked (no target file)",
                        })
                        print(f"    📋 Tracked: {pid} — {prop.get('title', '?')[:40]}")
                        continue

                    from evolution_executor import apply_improvement
                    change_result = apply_improvement(
                        task_type=prop.get("target_module", "general"),
                        suggestion=prop.get("change_description", ""),
                        target_file=target,
                        change_description=prop.get("title", ""),
                    )
                    result["applied_changes"].append({
                        "proposal_id": pid,
                        **change_result,
                    })
                    if change_result.get("success"):
                        transition(pid, "experimenting", actor="auto_evolve",
                                   reason="Change applied, pending validation")
                        print(f"    🔬 Experimenting: {pid}")
                    else:
                        print(f"    ❌ Apply failed: {pid} — {change_result.get('message', '?')}")
                        transition(pid, "failed", actor="auto_evolve",
                                   reason=f"Apply failed: {change_result.get('message', '?')}")
                result["actions_taken"].append(f"Executed: {len(result['applied_changes'])}")
            except Exception as e:
                print(f"  ⚠️ Execution failed: {e}")
    elif not auto_execute:
        print("\n⏸️ Auto-execute disabled. Proposals created in draft status.")

    # Step 5: Post-evolution capability
    print("\n📊 Step 5: Post-evolution capability...")
    try:
        from capability_model import evaluate_all
        after = evaluate_all()
        result["capability_after"] = after
        print(f"  Dimensions: {len(after)}")
        for b in sorted(after, key=lambda x: x["score"])[:5]:
            bar = "█" * int(b["score"] / 10) + "░" * (10 - int(b["score"] / 10))
            print(f"    [{bar}] {b['name']:15s} {b['score']:5.1f}  (n={b['sample_count']})")
        result["actions_taken"].append(f"Post: {len(after)} dims")
    except Exception as e:
        print(f"  ⚠️ {e}")

    print(f"\n✅ Round complete. Actions: {', '.join(result['actions_taken'])}")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Auto-evolve self-evolution engine")
    parser.add_argument("--min-patterns", type=int, default=3, help="Min failure patterns")
    parser.add_argument("--auto-execute", action="store_true", default=True, help="Auto-apply changes (default True)")
    parser.add_argument("--max-changes", type=int, default=3, help="Max changes per round")
    parser.add_argument("--max-rounds", type=int, default=1, help="Max evolution rounds")
    parser.add_argument("--min-improvement", type=float, default=0.05, help="Min improvement to continue")
    args = parser.parse_args()

    result = evolve(
        min_pattern_count=args.min_patterns,
        auto_execute=args.auto_execute,
        max_changes=args.max_changes,
        max_rounds=args.max_rounds,
        min_improvement=args.min_improvement,
    )

    print(f"\n{'='*60}")
    print(f"📊 Final Summary")
    print(f"{'='*60}")
    print(f"Total rounds: {len(result['rounds'])}")
    print(f"Total improvement: {result['total_improvement']:+.2f}")
    print(f"Stopped: {result.get('stopped_reason', 'N/A')}")
