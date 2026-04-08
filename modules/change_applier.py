#!/usr/bin/env python3
"""
Change Applier — 执行改进建议。

职责：
- 接收改进建议列表
- 执行可自动化的改进（如更新配置、创建任务、写入记忆）
- 返回执行结果

注意：当前为最小实现，只支持记录到 memory_db，不涉及实际系统变更。
实际的文件修改、配置调整需要人工确认或更复杂的逻辑。
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


def apply_changes(suggestions: list[dict], auto_execute: bool = False) -> list[dict]:
    """
    执行改进建议。

    Args:
        suggestions: 来自 improvement_suggestions 的建议列表
        auto_execute: 是否真正执行变更（False 时只预览）

    Returns:
        执行结果列表，每个结果包含:
        - title: 建议标题
        - status: executed|skipped|failed
        - description: 执行描述
        - timestamp: 执行时间
    """
    results = []

    if not suggestions:
        return results

    for s in suggestions:
        title = s.get("title", "unknown")
        category = s.get("category", "unknown")
        priority = s.get("priority", "P2")

        # 当前只支持记录到 memory_db，不执行实际变更
        if auto_execute:
            try:
                # 尝试写入 memory_db 作为 observation
                from memory_db import MemoryDB
                db = MemoryDB()
                db.add_observation(
                    type="improvement",
                    title=title[:100],
                    narrative=s.get("description", "")[:200],
                    source="change_applier",
                    tags=[f"improvement:{category}", f"priority:{priority}"],
                )
                results.append({
                    "title": title,
                    "status": "executed",
                    "description": f"已记录到 memory_db: {title[:50]}",
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception as e:
                results.append({
                    "title": title,
                    "status": "failed",
                    "description": f"执行失败: {str(e)[:50]}",
                    "timestamp": datetime.now().isoformat(),
                })
        else:
            results.append({
                "title": title,
                "status": "skipped",
                "description": f"预览模式，未执行: {title[:50]}",
                "timestamp": datetime.now().isoformat(),
            })

    return results


def _cli():
    """CLI 入口。"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="执行改进建议")
    parser.add_argument("--auto-execute", action="store_true", help="真正执行变更")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    # 先生成建议
    from improvement_suggestions import generate_suggestions
    suggestions = generate_suggestions()

    # 再执行
    results = apply_changes(suggestions, auto_execute=args.auto_execute)

    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"\n🔧 执行结果 ({len(results)} 项):\n")
        for r in results:
            status_icon = {"executed": "✅", "skipped": "⏭️", "failed": "❌"}.get(r["status"], "❓")
            print(f"  {status_icon} {r['title']}")
            print(f"     {r['description']}")
            print()


if __name__ == "__main__":
    _cli()
