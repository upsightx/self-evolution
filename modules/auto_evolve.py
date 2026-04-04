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


def evolve(
    min_pattern_count: int = 3,
    auto_execute: bool = False,
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

            prev_avg_score = after_avg_score if 'after_avg_score' in dir() else after_avg
        else:
            full_result["stopped_reason"] = "No capability data"
            break

        # Final capability
        if result["capability_after"]:
            full_result["final_capability"] = result["capability_after"]

    return full_result


def _run_single_round(min_pattern_count: int, auto_execute: bool, max_changes: int) -> dict:
    """Run a single evolution round."""
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

    # Step 3: Failure patterns
    print("\n🔍 Step 3: Failure patterns...")
    try:
        from feedback_loop import analyze_patterns
        patterns = analyze_patterns(min_samples=min_pattern_count)
        result["failure_patterns"] = patterns
        if patterns:
            print(f"  Found {len(patterns)} patterns:")
            for p in patterns[:3]:
                print(f"    {p.get('pattern', '')[:40]}: success={p.get('success_rate', 0):.0%}")
        result["actions_taken"].append(f"Patterns: {len(patterns)}")

        # Generate suggestions from patterns
        if patterns:
            suggestions = []
            for p in patterns[:max_changes]:
                suggestions.append({
                    "task_type": p.get("task_type", "general"),
                    "title": f"Fix {p.get('pattern', 'unknown')}",
                    "description": p.get("suggestion", ""),
                    "target_file": "",  # Would need LLM to determine
                })
            result["improvement_suggestions"] = suggestions
            print(f"  Generated {len(suggestions)} suggestions")
        result["actions_taken"].append(f"Suggestions: {len(result['improvement_suggestions'])}")
    except Exception as e:
        print(f"  ⚠️ {e}")

    # Step 4: Apply changes (if auto_execute)
    if auto_execute and result["improvement_suggestions"]:
        print("\n🔧 Step 4: Applying changes...")
        try:
            from evolution_executor import apply_improvement
            for sug in result["improvement_suggestions"][:max_changes]:
                change_result = apply_improvement(
                    task_type=sug.get("task_type", "general"),
                    suggestion=sug.get("description", ""),
                    target_file=sug.get("target_file", ""),
                    change_description=sug.get("title", ""),
                )
                result["applied_changes"].append(change_result)
                status = "✅" if change_result["success"] else "❌"
                print(f"    {status} {change_result.get('change_id', '?')}")
            result["actions_taken"].append(f"Applied: {len(result['applied_changes'])}")
        except Exception as e:
            print(f"  ⚠️ {e}")
    elif not auto_execute:
        print("\n⏸️ Step 4: Skipped (auto_execute=False)")

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
    parser.add_argument("--auto-execute", action="store_true", help="Auto-apply changes")
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
