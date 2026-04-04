#!/usr/bin/env python3
"""
Agenda Planner — Self-Evolution核心模块之四。

动态议程：根据目标+能力+机会，生成"下一步做什么"。
替代 HEARTBEAT.md 中的固定清单，实现自适应调度。

工作方式：
1. 收集所有信号源（goal gaps, proposals, experiments, routine checks）
2. 按优先级+时效性排序
3. 输出一个有序的 agenda（行动清单）
4. 调度层（心跳/主循环）按 agenda 执行

设计原则：
- 每次调用生成当前最优 agenda，不持久化（实时计算）
- 混合两类任务：目标进度更新 + 例行任务（日历、邮件等）
- 尊重时间窗口：深夜不推送、刚检查过的不重复
- 输出是结构化 list[dict]，每项有 action/priority/source/estimated_minutes

不做什么：
- 不自动执行（只排优先级）
- 不替代 HEARTBEAT.md 的全部功能（例行检查仍由心跳触发）
- 不调用外部 API
"""
from __future__ import annotations

import json
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Routine check intervals (hours)
ROUTINE_INTERVALS = {
    "calendar": 6,
    "email": 8,
    "weather": 12,
    "openclaw_version": 24,
    "config_sync": 24,
    "external_learning": 24,
    "feedback_analysis": 24,
    "experiment_scan": 24,
    "memory_maintenance": 168,  # weekly
    "self_audit": 168,  # weekly
}

# Time-of-day rules (Asia/Shanghai)
QUIET_HOURS = (23, 8)  # 23:00 - 08:00


def generate_agenda(
    max_items: int = 10,
    include_routine: bool = True,
    include_evolution: bool = True,
    now: datetime | None = None,
) -> list[dict]:
    """Generate a prioritized agenda of next actions.

    Args:
        max_items: max items to return
        include_routine: include routine checks (calendar, email, etc.)
        include_evolution: include goal progress tasks
        now: override current time (for testing)

    Returns:
        Sorted list of agenda items, each with:
        - action: what to do (human-readable)
        - category: evolution / routine / maintenance
        - priority: P0-P3
        - source: which module generated this
        - estimated_minutes: rough time estimate
        - details: additional context dict
    """
    if now is None:
        now = datetime.now()

    items = []

    is_quiet = _is_quiet_hours(now)

    # ── Evolution tasks ──
    if include_evolution and not is_quiet:
        evo_items = _evolution_items(now)
        items.extend(evo_items)

    # ── Routine checks ──
    if include_routine:
        routine_items = _routine_items(now, is_quiet)
        items.extend(routine_items)

    # ── Active experiment follow-ups ──
    if include_evolution:
        exp_items = _experiment_items(now)
        items.extend(exp_items)

    # ── Goal progress updates ──
    if include_evolution and not is_quiet:
        goal_items = _goal_update_items(now)
        items.extend(goal_items)

    # Score and sort
    for item in items:
        item["score"] = _compute_agenda_score(item, now, is_quiet)

    items.sort(key=lambda x: -x["score"])
    return items[:max_items]


def _evolution_items(now: datetime) -> list[dict]:
    """Removed: curiosity_engine no longer used."""
    return []

    return items


def _routine_items(now: datetime, is_quiet: bool) -> list[dict]:
    """Generate agenda items for overdue routine checks."""
    items = []
    state = _load_heartbeat_state()
    last_checks = state.get("lastChecks", {})

    for check_name, interval_hours in ROUTINE_INTERVALS.items():
        last_ts = _resolve_last_check(state, check_name)
        if last_ts:
            try:
                last_time = datetime.fromtimestamp(last_ts) if isinstance(last_ts, (int, float)) else datetime.fromisoformat(str(last_ts))
                hours_since = (now - last_time).total_seconds() / 3600
                if hours_since < interval_hours:
                    continue  # Not due yet
                overdue_hours = hours_since - interval_hours
            except (ValueError, TypeError):
                overdue_hours = interval_hours  # Can't parse, assume overdue
        else:
            overdue_hours = interval_hours * 2  # Never checked, high priority

        # Skip non-urgent checks during quiet hours, unless severely overdue
        if is_quiet and check_name not in ("calendar",):
            # Allow execution if overdue by more than 2x interval
            if overdue_hours < interval_hours:
                continue

        # Map check names to human-readable actions
        action_map = {
            "calendar": "检查日历：未来24-48h的日程",
            "email": "检查邮件：有无紧急未读",
            "weather": "检查天气：今明两天天气",
            "openclaw_version": "检查 OpenClaw 版本更新",
            "config_sync": "同步配置文件到飞书",
            "external_learning": "外部学习：扫描信息源",
            "feedback_analysis": "反馈闭环分析",
            "experiment_scan": "进化实验扫描",
            "memory_maintenance": "记忆维护：压缩/归档",
            "self_audit": "自我进化审计",
        }

        priority = "P1" if overdue_hours > interval_hours else "P2"
        if check_name in ("calendar", "email") and overdue_hours > interval_hours:
            priority = "P0"
        # Severe overdue (>2x interval) → upgrade to P0
        if overdue_hours > interval_hours * 2:
            priority = "P0"

        items.append({
            "action": action_map.get(check_name, f"例行检查: {check_name}"),
            "category": "routine",
            "priority": priority,
            "source": "heartbeat",
            "estimated_minutes": _estimate_routine_minutes(check_name),
            "details": {
                "check_name": check_name,
                "overdue_hours": round(overdue_hours, 1),
                "interval_hours": interval_hours,
            },
        })

    return items


def _experiment_items(now: datetime) -> list[dict]:
    """Removed: evolution_executor no longer used."""
    return []


def _goal_update_items(now: datetime) -> list[dict]:
    """Generate agenda items for goals that need progress updates."""
    items = []
    try:
        from goal_tree import get_gaps
        from capability_model import evaluate_all

        gaps = get_gaps()
        # Only suggest updating goals with P0 priority and large gaps
        critical_gaps = [g for g in gaps if g["priority"] == "P0" and g["gap"] > 0.3]

        if critical_gaps:
            items.append({
                "action": f"更新目标进度: {len(critical_gaps)}个P0目标有较大缺口",
                "category": "evolution",
                "priority": "P1",
                "source": "goal_tree",
                "estimated_minutes": 5,
                "details": {
                    "critical_goals": [{"id": g["goal_id"], "title": g["title"], "gap": g["gap"]} for g in critical_gaps[:3]],
                },
            })
    except Exception:
        pass

    return items


def _is_quiet_hours(now: datetime) -> bool:
    """Check if current time is in quiet hours."""
    hour = now.hour
    start, end = QUIET_HOURS
    if start > end:  # Wraps midnight (e.g., 23-8)
        return hour >= start or hour < end
    else:
        return start <= hour < end


def _resolve_last_check(state: dict, check_name: str):
    """Resolve last check timestamp from heartbeat-state.json.

    Handles multiple formats:
    - lastChecks.{name}: unix timestamp (int/float)
    - lastChecks.{name}: ISO string
    - last{Name}: date string like "2026-03-29"
    - last{Name}: ISO datetime string
    - scheduler.{name}: ISO datetime string
    """
    # 1. Check lastChecks dict (unix timestamps or ISO)
    last_checks = state.get("lastChecks", {})
    if check_name in last_checks:
        return last_checks[check_name]

    # 2. Check top-level keys with various naming conventions
    key_map = {
        "config_sync": "lastConfigSync",
        "openclaw_version": "lastVersionCheck",
        "feedback_analysis": "lastFeedbackAnalysis",
        "self_audit": "lastSelfAudit",
        "experiment_scan": "lastExperimentScan",
        "external_learning": None,  # Uses lastChecks sub-keys
        "memory_maintenance": None,  # Uses scheduler
    }

    mapped_key = key_map.get(check_name)
    if mapped_key and mapped_key in state:
        val = state[mapped_key]
        # Date-only string → treat as start of that day
        if isinstance(val, str) and len(val) == 10:
            try:
                return datetime.fromisoformat(val + "T00:00:00")
            except ValueError:
                pass
        return val

    # 3. Check scheduler dict
    scheduler = state.get("scheduler", {})
    # Map check names to scheduler keys
    sched_map = {
        "feedback_analysis": "feedback_analysis",
        "memory_maintenance": "memory_lru",
        "external_learning": "auto_memory",
    }
    sched_key = sched_map.get(check_name)
    if sched_key and sched_key in scheduler:
        return scheduler[sched_key]

    # 4. For external_learning, use the OLDEST (least recently checked) source timestamp
    # This ensures external_learning is flagged as overdue if ANY source hasn't been checked
    if check_name == "external_learning":
        learning_sources = ["github", "hn", "arxiv", "financing", "products", "qbitai", "pwc", "techcrunch"]
        timestamps = []
        for src in learning_sources:
            if src in last_checks:
                ts = last_checks[src]
                if isinstance(ts, (int, float)):
                    timestamps.append(ts)
        if timestamps:
            return min(timestamps)  # Oldest/least recent learning check

    return None


def _load_heartbeat_state() -> dict:
    """Load heartbeat-state.json.

    Search order:
    1. workspace/memory/heartbeat-state.json (current)
    2. workspace/heartbeat-state.json (legacy)
    """
    # modules/ is at workspace root
    workspace_root = Path(__file__).resolve().parent.parent
    candidates = [
        workspace_root / "memory" / "heartbeat-state.json",
        workspace_root / "heartbeat-state.json",
    ]
    for state_path in candidates:
        try:
            with open(state_path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return {}


def _estimate_routine_minutes(check_name: str) -> int:
    """Estimate minutes for a routine check."""
    estimates = {
        "calendar": 2,
        "email": 3,
        "weather": 1,
        "openclaw_version": 1,
        "config_sync": 3,
        "external_learning": 10,
        "feedback_analysis": 5,
        "experiment_scan": 5,
        "memory_maintenance": 10,
        "self_audit": 15,
    }
    return estimates.get(check_name, 5)


def _compute_agenda_score(item: dict, now: datetime, is_quiet: bool) -> float:
    """Compute priority score for an agenda item."""
    priority_weight = {"P0": 10, "P1": 6, "P2": 3, "P3": 1}.get(item.get("priority", "P2"), 3)
    category_weight = {
        "evolution": 1.2,
        "routine": 1.0,
        "maintenance": 0.8,
    }.get(item.get("category", "routine"), 1.0)

    score = priority_weight * category_weight

    # Overdue bonus for routine checks
    overdue = item.get("details", {}).get("overdue_hours", 0)
    if overdue > 24:
        score *= 1.5
    elif overdue > 12:
        score *= 1.2

    # Quiet hours penalty for non-urgent items
    if is_quiet and item.get("priority") not in ("P0",):
        score *= 0.3

    # Prefer quick wins
    est_min = item.get("estimated_minutes", 10)
    if est_min <= 5:
        score *= 1.1

    return round(score, 3)


def format_agenda(items: list[dict]) -> str:
    """Format agenda items for display."""
    if not items:
        return "📋 议程为空 — 系统健康，无待办事项"

    lines = ["📋 当前议程:"]
    total_minutes = 0

    for i, item in enumerate(items, 1):
        icon = {
            "evolution": "🧬",
            "routine": "🔄",
            "maintenance": "🔧",
        }.get(item["category"], "•")

        pri = item["priority"]
        est = item["estimated_minutes"]
        total_minutes += est

        lines.append(f"  {i}. {icon} [{pri}] {item['action']}  (~{est}min)")

    lines.append(f"\n  预计总耗时: ~{total_minutes}min")
    return "\n".join(lines)


# ============ CLI ============

def _cli():
    parser = argparse.ArgumentParser(description="Agenda Planner — Self-Evolution动态议程")
    sub = parser.add_subparsers(dest="command")

    # agenda
    p_agenda = sub.add_parser("agenda", help="Generate current agenda")
    p_agenda.add_argument("--max", type=int, default=10)
    p_agenda.add_argument("--no-routine", action="store_true")
    p_agenda.add_argument("--no-evolution", action="store_true")

    # json
    p_json = sub.add_parser("json", help="Output agenda as JSON")
    p_json.add_argument("--max", type=int, default=10)

    # status
    sub.add_parser("status", help="Quick status")

    args = parser.parse_args()

    if args.command == "agenda":
        items = generate_agenda(
            max_items=args.max,
            include_routine=not args.no_routine,
            include_evolution=not args.no_evolution,
        )
        print(format_agenda(items))

    elif args.command == "json":
        items = generate_agenda(max_items=args.max)
        print(json.dumps(items, indent=2, ensure_ascii=False, default=str))

    elif args.command == "status":
        items = generate_agenda(max_items=20)
        evo = sum(1 for i in items if i["category"] == "evolution")
        routine = sum(1 for i in items if i["category"] == "routine")
        total_min = sum(i["estimated_minutes"] for i in items)
        now = datetime.now()
        quiet = _is_quiet_hours(now)

        print(f"  时间: {now.strftime('%H:%M')} ({'静默时段' if quiet else '活跃时段'})")
        print(f"  待办: {len(items)} 项 (进化={evo}, 例行={routine})")
        print(f"  预计: ~{total_min}min")
        if items:
            print(f"  最高优先: [{items[0]['priority']}] {items[0]['action']}")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
