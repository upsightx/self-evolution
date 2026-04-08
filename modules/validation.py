#!/usr/bin/env python3
"""
Validation — 验证改进效果。

职责：
- 接收已执行的变更列表
- 验证变更是否生效（通过重新评估能力、检查目标进度等）
- 返回验证结果

注意：当前为最小实现，只做前后能力对比。
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime

# 添加路径
_modules_path = Path(__file__).parent
_workspace_path = _modules_path.parent
if str(_modules_path) not in sys.path:
    sys.path.insert(0, str(_modules_path))
try:
    if str(_workspace_path) not in sys.path:
        sys.path.insert(0, str(_workspace_path))
    from runtime_config import XMEMORY_PATH
    if str(XMEMORY_PATH) not in sys.path:
        sys.path.insert(0, str(XMEMORY_PATH))
except ImportError:
    _xmemory_path = _workspace_path / "X记忆"
    if _xmemory_path.exists() and str(_xmemory_path) not in sys.path:
        sys.path.insert(0, str(_xmemory_path))


def validate_changes(applied_changes: list[dict],
                     baseline: list[dict] = None,
                     after: list[dict] = None) -> list[dict]:
    """
    验证改进效果。

    Args:
        applied_changes: 来自 change_applier 的执行结果
        baseline: 改进前的能力基线（可选）
        after: 改进后的能力评估（可选）

    Returns:
        验证结果列表，每个结果包含:
        - title: 验证项标题
        - result: improved|unchanged|degraded|pending
        - description: 验证描述
        - before_score: 改进前分数（如有）
        - after_score: 改进后分数（如有）
    """
    validations = []

    if not applied_changes:
        validations.append({
            "title": "无变更可验证",
            "result": "pending",
            "description": "没有已执行的变更",
        })
        return validations

    # 如果有前后能力数据，做对比
    if baseline and after:
        baseline_map = {b["name"]: b["score"] for b in baseline}
        after_map = {a["name"]: a["score"] for a in after}

        for name in set(list(baseline_map.keys()) + list(after_map.keys())):
            before = baseline_map.get(name, 0)
            after_score = after_map.get(name, 0)
            diff = after_score - before

            if diff > 5:
                result = "improved"
            elif diff < -5:
                result = "degraded"
            else:
                result = "unchanged"

            validations.append({
                "title": f"能力维度: {name}",
                "result": result,
                "description": f"{name}: {before:.1f} → {after_score:.1f} ({diff:+.1f})",
                "before_score": before,
                "after_score": after_score,
            })
    else:
        # 没有前后对比数据，只记录变更状态
        for change in applied_changes:
            status = change.get("status", "unknown")
            validations.append({
                "title": change.get("title", "unknown"),
                "result": "pending" if status == "skipped" else ("improved" if status == "executed" else "degraded"),
                "description": f"变更状态: {status}",
            })

    return validations


def _cli():
    """CLI 入口。"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="验证改进效果")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    # 模拟数据（实际使用时应传入真实数据）
    applied_changes = [
        {"title": "测试变更", "status": "executed"},
    ]

    validations = validate_changes(applied_changes)

    if args.format == "json":
        print(json.dumps(validations, ensure_ascii=False, indent=2))
    else:
        print(f"\n✅ 验证结果 ({len(validations)} 项):\n")
        for v in validations:
            result_icon = {
                "improved": "📈",
                "unchanged": "➡️",
                "degraded": "📉",
                "pending": "⏳",
            }.get(v["result"], "❓")
            print(f"  {result_icon} {v['title']}")
            print(f"     {v['description']}")
            print()


if __name__ == "__main__":
    _cli()
