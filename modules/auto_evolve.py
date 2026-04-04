#!/usr/bin/env python3
"""
Auto Evolve — Self-Evolution 自动进化引擎。

职责：
- 目标缺口 → 失败分析 → 生成改进 → 执行验证 → 更新进度
- 提供一键式"诊断 → 修复 → 验证"闭环
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


def evolve(min_pattern_count: int = 3, auto_save_skills: bool = False, auto_execute: bool = False, max_changes: int = 3) -> dict:
    """执行自动进化流程。"""
    result = {
        "timestamp": datetime.now().isoformat(),
        "goal_gaps": [],
        "capability_weaknesses": [],
        "actionable_learnings": [],
        "failure_patterns": [],
        "improvement_suggestions": {},
        "applied_changes": [],
        "validations": [],
        "skills_from_patterns": [],
        "capability_before": [],
        "capability_after": [],
        "actions_taken": [],
    }

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 自动进化启动")
    print("=" * 50)

    # Step 0: Baseline
    print("\n📊 Step 0: 记录能力基线...")
    try:
        from capability_model import evaluate_all
        baseline = evaluate_all()
        result["capability_before"] = baseline
        print(f"  当前能力维度: {len(baseline)}")
        for b in sorted(baseline, key=lambda x: x["score"]):
            bar = "█" * int(b["score"] / 10) + "░" * (10 - int(b["score"] / 10))
            print(f"    [{bar}] {b['name']:15s} {b['score']:5.1f}  (n={b['sample_count']})")
        result["actions_taken"].append(f"基线: {len(baseline)} 维度")
    except Exception as e:
        print(f"  ⚠️ {e}")
        result["actions_taken"].append(f"基线失败: {e}")

    # Step 1: Goal gaps
    print("\n🎯 Step 1: 识别目标缺口...")
    try:
        from goal_tree import get_gaps
        gaps = get_gaps()
        result["goal_gaps"] = gaps
        if gaps:
            print(f"  发现 {len(gaps)} 个缺口:")
            for g in gaps[:5]:
                print(f"    [{g['priority']}] {g['title'][:30]}: 缺口={g['gap']:.0%}")
        result["actions_taken"].append(f"缺口: {len(gaps)}")
    except Exception as e:
        print(f"  ⚠️ {e}")
        result["actions_taken"].append(f"缺口失败: {e}")

    # Step 2: Capability weaknesses
    print("\n📉 Step 2: 识别能力短板...")
    try:
        from capability_model import get_weaknesses
        weaknesses = get_weaknesses(threshold=70.0)
        result["capability_weaknesses"] = weaknesses
        if weaknesses:
            print(f"  发现 {len(weaknesses)} 个短板:")
            for w in weaknesses:
                print(f"    ⚠️ {w['name']:15s} {w['score']:5.1f}")
        result["actions_taken"].append(f"短板: {len(weaknesses)}")
    except Exception as e:
        print(f"  ⚠️ {e}")
        result["actions_taken"].append(f"短板失败: {e}")

    # Step 2.5: Actionable learnings
    print("\n📚 Step 2.5: 检查外部学习 actionable 项...")
    actionable_items = []
    applied_changes = []
    try:
        from learning_conversion import convert_learning
        actionable_items = convert_learning()
        if actionable_items:
            print(f"  发现 {len(actionable_items)} 个 actionable 项:")
            for item in actionable_items[:5]:
                print(f"    {item['title'][:30]}: {item['description'][:50]}")
        result["actionable_learnings"] = actionable_items
        result["actions_taken"].append(f"actionable 项: {len(actionable_items)}")
    except Exception as e:
        print(f"  ⚠️ {e}")
        result["actions_taken"].append(f"actionable 项失败: {e}")

    # Step 3: Improvement suggestions
    print("\n💡 Step 3: 生成改进建议...")
    try:
        from improvement_suggestions import generate_suggestions
        suggestions = generate_suggestions(actionable_items)
        result["improvement_suggestions"] = suggestions
        if suggestions:
            print(f"  生成 {len(suggestions)} 个改进建议:")
            for suggestion in suggestions[:5]:
                print(f"    {suggestion['title'][:30]}: {suggestion['description'][:50]}")
        result["actions_taken"].append(f"改进建议: {len(suggestions)}")
    except Exception as e:
        print(f"  ⚠️ {e}")
        result["actions_taken"].append(f"改进建议失败: {e}")

    # Step 4: Apply changes
    if auto_execute:
        print("\n🔧 Step 4: 执行改进...")
        try:
            from change_applier import apply_changes
            applied_changes = apply_changes(suggestions)
            result["applied_changes"] = applied_changes
            if applied_changes:
                print(f"  执行 {len(applied_changes)} 个改进:")
                for change in applied_changes[:5]:
                    print(f"    {change['title'][:30]}: {change['description'][:50]}")
            result["actions_taken"].append(f"改进执行: {len(applied_changes)}")
        except Exception as e:
            print(f"  ⚠️ {e}")
            result["actions_taken"].append(f"改进执行失败: {e}")

    # Step 5: Validate changes
    if auto_execute:
        print("\n✅ Step 5: 验证改进...")
        try:
            from validation import validate_changes
            validations = validate_changes(applied_changes)
            result["validations"] = validations
            if validations:
                print(f"  验证 {len(validations)} 个改进:")
                for validation in validations[:5]:
                    print(f"    {validation['title'][:30]}: {validation['result']}")
            result["actions_taken"].append(f"改进验证: {len(validations)}")
        except Exception as e:
            print(f"  ⚠️ {e}")
            result["actions_taken"].append(f"改进验证失败: {e}")

    # Step 6: Evaluate capability after changes
    if auto_execute:
        print("\n📊 Step 6: 评估改进后的能力...")
        try:
            from capability_model import evaluate_all
            after_changes = evaluate_all()
            result["capability_after"] = after_changes
            print(f"  改进后的能力维度: {len(after_changes)}")
            for b in sorted(after_changes, key=lambda x: x["score"]):
                bar = "█" * int(b["score"] / 10) + "░" * (10 - int(b["score"] / 10))
                print(f"    [{bar}] {b['name']:15s} {b['score']:5.1f}  (n={b['sample_count']})")
            result["actions_taken"].append(f"改进后能力评估: {len(after_changes)}")
        except Exception as e:
            print(f"  ⚠️ {e}")
            result["actions_taken"].append(f"改进后能力评估失败: {e}")

    return result