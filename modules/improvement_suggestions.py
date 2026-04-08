#!/usr/bin/env python3
"""
Improvement Suggestions — 基于目标缺口和能力短板生成改进建议。

职责：
- 分析 actionable learnings、goal gaps、capability weaknesses
- 生成可执行的改进建议（含优先级、预期影响、实施难度）
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime

# 添加路径
_modules_path = Path(__file__).parent
_xmemory_path = _modules_path.parent / "X记忆"
for p in [_modules_path, _xmemory_path]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def generate_suggestions(actionable_items: list[dict] = None,
                         gaps: list[dict] = None,
                         weaknesses: list[dict] = None) -> list[dict]:
    """
    生成改进建议。

    Args:
        actionable_items: 来自 learning_conversion 的可执行学习项
        gaps: 来自 goal_tree 的目标缺口
        weaknesses: 来自 capability_model 的能力短板

    Returns:
        建议列表，每个建议包含:
        - title: 建议标题
        - description: 详细描述
        - priority: P0/P1/P2
        - category: capability|goal|learning
        - effort: low/medium/high
        - expected_impact: 预期影响描述
    """
    suggestions = []

    # 基于能力短板生成建议
    if weaknesses:
        for w in weaknesses:
            name = w.get("name", "unknown")
            score = w.get("score", 0)
            suggestions.append({
                "title": f"提升 {name} 能力",
                "description": f"当前 {name} 得分 {score:.1f}/100，需要通过实际任务填充数据并针对性改进",
                "priority": "P0" if score < 50 else "P1",
                "category": "capability",
                "effort": "medium",
                "expected_impact": f"将 {name} 提升到 70+ 分",
                "source": f"capability_model:{name}",
            })

    # 基于目标缺口生成建议
    if gaps:
        for g in gaps[:5]:  # 只取前5个最高优先级的
            title = g.get("title", "unknown")
            gap = g.get("gap", 0)
            priority = g.get("priority", "P2")
            suggestions.append({
                "title": f"缩小目标缺口: {title[:30]}",
                "description": f"目标 '{title}' 当前缺口 {gap:.0%}，需要制定具体行动计划",
                "priority": priority,
                "category": "goal",
                "effort": "high",
                "expected_impact": f"将缺口从 {gap:.0%} 降低到 <20%",
                "source": f"goal_tree:{title}",
            })

    # 基于外部学习 actionable 项生成建议
    if actionable_items:
        for item in actionable_items[:3]:  # 只取前3个
            title = item.get("title", "unknown")
            suggestions.append({
                "title": f"落地外部学习: {title[:30]}",
                "description": f"外部学习发现的可执行项: {title}",
                "priority": "P1",
                "category": "learning",
                "effort": "medium",
                "expected_impact": "将外部知识转化为内部能力",
                "source": f"learning_conversion:{title}",
            })

    # 去重（按 title）
    seen = set()
    unique_suggestions = []
    for s in suggestions:
        if s["title"] not in seen:
            seen.add(s["title"])
            unique_suggestions.append(s)

    # 按优先级排序
    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    unique_suggestions.sort(key=lambda x: priority_order.get(x["priority"], 3))

    return unique_suggestions


def _cli():
    """CLI 入口。"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="生成改进建议")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    suggestions = generate_suggestions()

    if args.format == "json":
        print(json.dumps(suggestions, ensure_ascii=False, indent=2))
    else:
        print(f"\n💡 生成 {len(suggestions)} 个改进建议:\n")
        for i, s in enumerate(suggestions, 1):
            print(f"  {i}. [{s['priority']}] {s['title']}")
            print(f"     {s['description'][:60]}")
            print(f"     努力程度: {s['effort']} | 类别: {s['category']}")
            print()


if __name__ == "__main__":
    _cli()
