#!/usr/bin/env python3
"""
Learning Conversion Tracker — 学习转化追踪器。

职责：
- 追踪外部学习内容是否转化为实际进化变更
- 对比 observations（学习记录）和 evolution_changes（变更记录）
- 计算学习转化率
"""
from __future__ import annotations

import re
import sys
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

_modules_path = Path(__file__).parent
_xmemory_path = _modules_path.parent / "X记忆"
for p in [_modules_path, _xmemory_path]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from db_common import get_db


def get_learning_items(days: int = 30) -> list[dict]:
    """获取最近 N 天的学习记录。"""
    db = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = db.execute(
        "SELECT id, title, narrative, tags, created_at\n"
        "               FROM observations\n"
        "               WHERE (type = 'discovery' OR tags LIKE '%learning%')\n"
        "                 AND created_at >= ?\n"
        "               ORDER BY created_at DESC",
        (cutoff,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def _get_evolution_changes(days: int = 30) -> list[dict]:
    """获取最近 N 天的进化变更记录。"""
    db = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    try:
        rows = db.execute(
            "SELECT change_id, task_type, suggestion, change_description, verdict, applied_at\n"
            "               FROM evolution_changes\n"
            "               WHERE applied_at >= ?\n"
            "               ORDER BY applied_at DESC",
            (cutoff,)
        ).fetchall()
        db.close()
        return [dict(r) for r in rows]
    except Exception:
        db.close()
        return []


def _match_learning_to_changes(learning_item: dict, changes: list[dict]) -> list[dict]:
    """将学习记录与进化变更进行关键词匹配。"""
    # 提取学习记录关键词
    text = " ".join([
        learning_item.get("title", ""),
        learning_item.get("narrative", ""),
        learning_item.get("tags", ""),
    ])
    learn_keywords = set(re.findall(r'[a-z\u4e00-\u9fff]{3,}', text.lower()))

    matched = []
    for change in changes:
        change_text = " ".join([
            change.get("suggestion", ""),
            change.get("change_description", ""),
            change.get("task_type", ""),
        ])
        change_keywords = set(re.findall(r'[a-z\u4e00-\u9fff]{3,}', change_text.lower()))

        overlap = learn_keywords & change_keywords
        if len(overlap) >= 2:
            matched.append({
                "change_id": change.get("change_id"),
                "task_type": change.get("task_type"),
                "verdict": change.get("verdict", "pending"),
                "overlap_keywords": list(overlap)[:5],
            })

    return matched


def track_conversion(days: int = 30) -> dict:
    """
    追踪学习转化率。

    Returns:
        包含转化统计的字典
    """
    learning_items = get_learning_items(days)
    changes = _get_evolution_changes(days)

    converted_items = 0
    matched_details = []

    for item in learning_items:
        matches = _match_learning_to_changes(item, changes)
        converted = 1 if matches else 0
        converted_items += converted
        matched_details.append({
            "learning_id": item.get("id"),
            "title": item.get("title", ""),
            "created_at": item.get("created_at", ""),
            "matched_changes": matches,
            "converted": converted,
        })

    total = len(learning_items)
    conversion_rate = round(converted_items / total * 100, 1) if total > 0 else 0
    summary = f"Learning conversion: {converted_items}/{total} items converted ({conversion_rate:.1f}%)"

    return {
        "period_days": days,
        "total_learning_items": total,
        "total_evolution_changes": len(changes),
        "converted_items": converted_items,
        "conversion_rate": conversion_rate,
        "matched_details": matched_details,
        "summary": summary,
    }


def _cli():
    parser = argparse.ArgumentParser(description="Learning Conversion Tracker")
    parser.add_argument("--days", type=int, default=30, help="Lookback window")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    result = track_conversion(days=args.days)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n=== Learning Conversion Report ({result['period_days']} days) ===")
        print(f"  Learning items: {result['total_learning_items']}")
        print(f"  Evolution changes: {result['total_evolution_changes']}")
        print(f"  Converted: {result['converted_items']}/{result['total_learning_items']} ({result['conversion_rate']}%)")

        details = result.get("matched_details") or []
        converted_only = [d for d in details if d.get("converted")]
        if converted_only:
            print(f"\nMatched Details:")
            for d in converted_only[:10]:
                print(f"  - {d['title'][:60]}")


if __name__ == "__main__":
    _cli()
