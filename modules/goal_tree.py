#!/usr/bin/env python3
"""
Goal Tree — Self-Evolution核心模块之一。

目标树管理：定义、分解、追踪长期目标。
每个目标有可衡量的指标和进度，形成树状结构。

设计原则：
- 目标树持久化到 SQLite（复用 memory.db）
- 支持无限层级的父子关系
- 每个目标有 metric（衡量指标）和 current_value / target_value
- 进度自动从子目标聚合（如果有子目标）
- 与 capability_model 联动：目标缺口 → 能力缺口

不做什么：
- 不自动执行任何改动
- 不调用外部 API
- 不做 LLM 推理（纯数据管理）
"""
from __future__ import annotations

import json
import sqlite3
import sys
import argparse
from datetime import datetime

from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path, module_dir, module_workspace

_workspace = ensure_workspace_on_path()
_modules = module_dir()
ensure_xmemory_on_path()

from db_common import DB_PATH, get_db

SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER DEFAULT NULL,
    title TEXT NOT NULL,
    description TEXT,
    metric TEXT,
    target_value REAL,
    current_value REAL DEFAULT 0,
    unit TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    priority TEXT NOT NULL DEFAULT 'P1',
    source TEXT DEFAULT 'manual',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    FOREIGN KEY (parent_id) REFERENCES goals(id)
);

CREATE INDEX IF NOT EXISTS idx_goals_parent ON goals(parent_id);
CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
"""

VALID_STATUSES = {"active", "completed", "paused", "abandoned"}
VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}


def _ensure_table():
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()
    db.close()


# ============ Write ============

def create_goal(
    title: str,
    description: str = "",
    metric: str = "",
    target_value: float = 100.0,
    current_value: float = 0.0,
    unit: str = "%",
    parent_id: int | None = None,
    priority: str = "P1",
    source: str = "manual",
) -> int | None:
    """Create a new goal. Returns goal id."""
    if priority not in VALID_PRIORITIES:
        priority = "P1"

    _ensure_table()
    db = get_db()
    try:
        # Validate parent exists if specified
        if parent_id is not None:
            parent = db.execute("SELECT id FROM goals WHERE id = ?", (parent_id,)).fetchone()
            if not parent:
                print(f"[goal_tree] Parent goal #{parent_id} not found")
                return None

        cur = db.execute(
            """INSERT INTO goals
               (parent_id, title, description, metric, target_value,
                current_value, unit, priority, source)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (parent_id, title, description, metric, target_value,
             current_value, unit, priority, source),
        )
        db.commit()
        gid = cur.lastrowid
        print(f"[goal_tree] Created goal #{gid}: {title}")
        return gid
    except sqlite3.Error as e:
        print(f"[goal_tree] Error: {e}")
        return None
    finally:
        db.close()


def update_goal(
    goal_id: int,
    current_value: float | None = None,
    status: str | None = None,
    title: str | None = None,
    description: str | None = None,
    target_value: float | None = None,
    priority: str | None = None,
) -> bool:
    """Update a goal's fields. Only non-None fields are updated."""
    _ensure_table()
    db = get_db()
    try:
        row = db.execute("SELECT id, status FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if not row:
            print(f"[goal_tree] Goal #{goal_id} not found")
            return False

        updates = []
        params = []

        if current_value is not None:
            updates.append("current_value = ?")
            params.append(current_value)
        if status is not None:
            if status not in VALID_STATUSES:
                print(f"[goal_tree] Invalid status: {status}")
                return False
            updates.append("status = ?")
            params.append(status)
            if status == "completed":
                updates.append("completed_at = ?")
                params.append(datetime.now().isoformat())
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if target_value is not None:
            updates.append("target_value = ?")
            params.append(target_value)
        if priority is not None:
            if priority not in VALID_PRIORITIES:
                print(f"[goal_tree] Invalid priority: {priority}")
                return False
            updates.append("priority = ?")
            params.append(priority)

        if not updates:
            return True

        updates.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(goal_id)

        db.execute(
            f"UPDATE goals SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        db.commit()
        return True
    except sqlite3.Error as e:
        print(f"[goal_tree] Error: {e}")
        return False
    finally:
        db.close()


def delete_goal(goal_id: int, cascade: bool = False) -> bool:
    """Delete a goal. If cascade=True, also delete all children."""
    _ensure_table()
    db = get_db()
    try:
        row = db.execute("SELECT id FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if not row:
            return False

        children = db.execute("SELECT id FROM goals WHERE parent_id = ?", (goal_id,)).fetchall()
        if children and not cascade:
            print(f"[goal_tree] Goal #{goal_id} has {len(children)} children. Use cascade=True to delete all.")
            return False

        if cascade:
            for child in children:
                delete_goal(child["id"], cascade=True)

        db.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        db.commit()
        return True
    except sqlite3.Error as e:
        print(f"[goal_tree] Error: {e}")
        return False
    finally:
        db.close()


# ============ Query ============

def get_goal(goal_id: int) -> dict | None:
    """Get a single goal with computed progress."""
    _ensure_table()
    db = get_db()
    try:
        row = db.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if not row:
            return None
        goal = dict(row)
        goal["progress"] = _compute_progress(db, goal)
        goal["children"] = _get_children_ids(db, goal_id)
        return goal
    finally:
        db.close()


def list_goals(
    status: str | None = None,
    parent_id: int | None = None,
    root_only: bool = False,
    priority: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List goals with optional filters."""
    _ensure_table()
    db = get_db()
    try:
        conditions = []
        params = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if parent_id is not None:
            conditions.append("parent_id = ?")
            params.append(parent_id)
        if root_only:
            conditions.append("parent_id IS NULL")
        if priority:
            conditions.append("priority = ?")
            params.append(priority)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)

        rows = db.execute(
            f"SELECT * FROM goals{where} ORDER BY priority ASC, created_at ASC LIMIT ?",
            params,
        ).fetchall()

        results = []
        for r in rows:
            goal = dict(r)
            goal["progress"] = _compute_progress(db, goal)
            goal["children"] = _get_children_ids(db, goal["id"])
            results.append(goal)
        return results
    finally:
        db.close()


def get_tree(root_id: int | None = None) -> list[dict]:
    """Get the full goal tree (or subtree from root_id), with nested children."""
    _ensure_table()
    db = get_db()
    try:
        if root_id is not None:
            root = db.execute("SELECT * FROM goals WHERE id = ?", (root_id,)).fetchone()
            if not root:
                return []
            return [_build_subtree(db, dict(root))]
        else:
            roots = db.execute(
                "SELECT * FROM goals WHERE parent_id IS NULL ORDER BY priority ASC, created_at ASC"
            ).fetchall()
            return [_build_subtree(db, dict(r)) for r in roots]
    finally:
        db.close()


def get_gaps() -> list[dict]:
    """Find active goals where progress is significantly behind target.

    Returns goals sorted by gap severity (worst first).
    Used by curiosity_engine to identify what to work on.
    """
    _ensure_table()
    db = get_db()
    try:
        rows = db.execute(
            "SELECT * FROM goals WHERE status = 'active' AND target_value > 0"
        ).fetchall()

        gaps = []
        for r in rows:
            goal = dict(r)
            progress = _compute_progress(db, goal)
            gap = 1.0 - progress  # 0 = done, 1 = not started
            if gap > 0.1:  # Only report meaningful gaps
                gaps.append({
                    "goal_id": goal["id"],
                    "title": goal["title"],
                    "metric": goal["metric"],
                    "progress": round(progress, 3),
                    "gap": round(gap, 3),
                    "priority": goal["priority"],
                    "current_value": goal["current_value"],
                    "target_value": goal["target_value"],
                    "unit": goal["unit"],
                })

        # Sort: P0 first, then by gap descending
        priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        gaps.sort(key=lambda g: (priority_order.get(g["priority"], 9), -g["gap"]))
        return gaps
    finally:
        db.close()


def summary() -> dict:
    """Get a summary of the goal tree."""
    _ensure_table()
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM goals").fetchone()[0]
        by_status = {}
        for r in db.execute("SELECT status, COUNT(*) as c FROM goals GROUP BY status").fetchall():
            by_status[r["status"]] = r["c"]
        by_priority = {}
        for r in db.execute("SELECT priority, COUNT(*) as c FROM goals WHERE status='active' GROUP BY priority").fetchall():
            by_priority[r["priority"]] = r["c"]

        # Overall progress of root goals
        roots = db.execute(
            "SELECT * FROM goals WHERE parent_id IS NULL AND status = 'active'"
        ).fetchall()
        root_progress = []
        for r in roots:
            goal = dict(r)
            p = _compute_progress(db, goal)
            root_progress.append({"id": goal["id"], "title": goal["title"], "progress": round(p, 3)})

        return {
            "total": total,
            "by_status": by_status,
            "by_priority": by_priority,
            "root_goals": root_progress,
        }
    finally:
        db.close()


# ============ Internal ============

def _get_children_ids(db, goal_id: int) -> list[int]:
    rows = db.execute("SELECT id FROM goals WHERE parent_id = ?", (goal_id,)).fetchall()
    return [r["id"] for r in rows]


def _compute_progress(db, goal: dict) -> float:
    """Compute progress for a goal.

    If the goal has children, progress = average of children's progress.
    Otherwise, progress = current_value / target_value (clamped to 0-1).
    """
    children = db.execute(
        "SELECT * FROM goals WHERE parent_id = ? AND status != 'abandoned'",
        (goal["id"],),
    ).fetchall()

    if children:
        # Aggregate from children
        if not children:
            return 0.0
        child_progress = []
        for c in children:
            cp = _compute_progress(db, dict(c))
            child_progress.append(cp)
        return sum(child_progress) / len(child_progress)
    else:
        # Leaf goal: use current_value / target_value
        target = goal.get("target_value") or 0
        current = goal.get("current_value") or 0
        if target <= 0:
            return 1.0 if goal.get("status") == "completed" else 0.0
        return max(0.0, min(1.0, current / target))


def _build_subtree(db, goal: dict) -> dict:
    """Recursively build a goal subtree."""
    goal["progress"] = _compute_progress(db, goal)
    children = db.execute(
        "SELECT * FROM goals WHERE parent_id = ? ORDER BY priority ASC, created_at ASC",
        (goal["id"],),
    ).fetchall()
    goal["children"] = [_build_subtree(db, dict(c)) for c in children]
    return goal


# ============ Seed ============

def seed_default_goals() -> bool:
    """Seed the default Self-Evolution goal tree.

    Only runs if no goals exist yet.
    """
    _ensure_table()
    db = get_db()
    try:
        count = db.execute("SELECT COUNT(*) FROM goals").fetchone()[0]
        if count > 0:
            print("[goal_tree] Goals already exist, skipping seed")
            return False
    finally:
        db.close()

    # Root goal
    root = create_goal(
        title="高度自主 (L4)",
        description="实现目标驱动、自主规划、主动探索的AI助手",
        metric="autonomy_level",
        target_value=4.0,
        current_value=2.0,
        unit="level",
        priority="P0",
        source="self-evolution-init",
    )
    if not root:
        return False

    # Branch 1: 任务成功率
    b1 = create_goal(
        title="任务成功率 > 90%",
        description="所有类型任务的综合成功率",
        metric="overall_success_rate",
        target_value=90.0,
        current_value=70.0,
        unit="%",
        parent_id=root,
        priority="P0",
        source="self-evolution-init",
    )
    if b1:
        create_goal(
            title="coding任务成功率 > 80%",
            description="代码开发、调试、部署类任务",
            metric="coding_success_rate",
            target_value=80.0,
            current_value=40.0,
            unit="%",
            parent_id=b1,
            priority="P0",
            source="self-evolution-init",
        )
        create_goal(
            title="信息搜集成功率 > 95%",
            description="搜索、爬取、数据整理类任务",
            metric="research_success_rate",
            target_value=95.0,
            current_value=80.0,
            unit="%",
            parent_id=b1,
            priority="P1",
            source="self-evolution-init",
        )

    # Branch 2: 主动发现并解决问题
    b2 = create_goal(
        title="主动发现并解决问题",
        description="不等失败发生，主动识别和修复潜在问题",
        metric="proactive_improvements",
        target_value=4.0,
        current_value=0.0,
        unit="次/月",
        parent_id=root,
        priority="P1",
        source="self-evolution-init",
    )
    if b2:
        create_goal(
            title="每周至少1个自主改进",
            description="自主发起的改进（非被动修复）",
            metric="weekly_improvements",
            target_value=1.0,
            current_value=0.0,
            unit="次/周",
            parent_id=b2,
            priority="P1",
            source="self-evolution-init",
        )
        create_goal(
            title="能力缺口识别准确率 > 80%",
            description="识别出的缺口确实是真实短板",
            metric="gap_accuracy",
            target_value=80.0,
            current_value=0.0,
            unit="%",
            parent_id=b2,
            priority="P2",
            source="self-evolution-init",
        )

    # Branch 3: 减少对主人的依赖
    b3 = create_goal(
        title="减少对主人的依赖",
        description="更多任务可以自主完成，减少确认环节",
        metric="autonomy_ratio",
        target_value=80.0,
        current_value=40.0,
        unit="%",
        parent_id=root,
        priority="P1",
        source="self-evolution-init",
    )
    if b3:
        create_goal(
            title="中等改动可自主完成",
            description="20-200行的改动不需要主人确认方案",
            metric="medium_task_autonomy",
            target_value=80.0,
            current_value=20.0,
            unit="%",
            parent_id=b3,
            priority="P1",
            source="self-evolution-init",
        )
        create_goal(
            title="异常自愈能力",
            description="session卡死、工具失败等异常可自动恢复",
            metric="self_heal_rate",
            target_value=90.0,
            current_value=50.0,
            unit="%",
            parent_id=b3,
            priority="P2",
            source="self-evolution-init",
        )

    # Branch 4: 知识持续增长
    b4 = create_goal(
        title="知识持续增长",
        description="持续学习新知识并转化为实际能力",
        metric="knowledge_growth",
        target_value=100.0,
        current_value=30.0,
        unit="%",
        parent_id=root,
        priority="P2",
        source="self-evolution-init",
    )
    if b4:
        create_goal(
            title="外部学习落地率 > 30%",
            description="学到的知识中有多少转化为实际改进",
            metric="learning_conversion_rate",
            target_value=30.0,
            current_value=10.0,
            unit="%",
            parent_id=b4,
            priority="P2",
            source="self-evolution-init",
        )
        create_goal(
            title="新Skill创建 ≥ 1/月",
            description="每月至少创建或显著改进一个Skill",
            metric="skill_creation_rate",
            target_value=1.0,
            current_value=0.0,
            unit="个/月",
            parent_id=b4,
            priority="P2",
            source="self-evolution-init",
        )

    print("[goal_tree] Seeded default Self-Evolution goal tree")
    return True


# ============ CLI ============

def _format_tree(node: dict, indent: int = 0) -> str:
    """Format a goal tree node for display."""
    prefix = "  " * indent
    status_icon = {
        "active": "🔵",
        "completed": "✅",
        "paused": "⏸️",
        "abandoned": "❌",
    }.get(node["status"], "•")

    progress = node.get("progress", 0)
    bar_len = 10
    filled = int(progress * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)

    line = f"{prefix}{status_icon} #{node['id']} [{node['priority']}] {node['title']}"
    line += f"  [{bar}] {progress:.0%}"
    if node.get("metric"):
        cv = node.get("current_value", 0)
        tv = node.get("target_value", 0)
        u = node.get("unit", "")
        line += f"  ({cv}/{tv}{u})"

    lines = [line]
    for child in node.get("children", []):
        lines.append(_format_tree(child, indent + 1))
    return "\n".join(lines)


def _cli():
    parser = argparse.ArgumentParser(description="Goal Tree — Self-Evolution目标管理")
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Create a goal")
    p_create.add_argument("title")
    p_create.add_argument("--desc", default="")
    p_create.add_argument("--metric", default="")
    p_create.add_argument("--target", type=float, default=100.0)
    p_create.add_argument("--current", type=float, default=0.0)
    p_create.add_argument("--unit", default="%")
    p_create.add_argument("--parent", type=int, default=None)
    p_create.add_argument("--priority", default="P1", choices=list(VALID_PRIORITIES))

    # update
    p_update = sub.add_parser("update", help="Update a goal")
    p_update.add_argument("id", type=int)
    p_update.add_argument("--value", type=float, default=None)
    p_update.add_argument("--status", default=None, choices=list(VALID_STATUSES))
    p_update.add_argument("--title", default=None)
    p_update.add_argument("--target", type=float, default=None)
    p_update.add_argument("--priority", default=None, choices=list(VALID_PRIORITIES))

    # delete
    p_del = sub.add_parser("delete", help="Delete a goal")
    p_del.add_argument("id", type=int)
    p_del.add_argument("--cascade", action="store_true")

    # get
    p_get = sub.add_parser("get", help="Get goal details")
    p_get.add_argument("id", type=int)

    # list
    p_list = sub.add_parser("list", help="List goals")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--root-only", action="store_true")
    p_list.add_argument("--priority", default=None)

    # tree
    p_tree = sub.add_parser("tree", help="Show goal tree")
    p_tree.add_argument("--root", type=int, default=None)

    # gaps
    sub.add_parser("gaps", help="Show goals with biggest gaps")

    # summary
    sub.add_parser("summary", help="Show goal tree summary")

    # seed
    sub.add_parser("seed", help="Seed default Self-Evolution goals")

    args = parser.parse_args()

    if args.command == "create":
        gid = create_goal(
            title=args.title, description=args.desc, metric=args.metric,
            target_value=args.target, current_value=args.current,
            unit=args.unit, parent_id=args.parent, priority=args.priority,
        )
        if gid:
            print(f"✅ Created goal #{gid}")

    elif args.command == "update":
        ok = update_goal(
            args.id, current_value=args.value, status=args.status,
            title=args.title, target_value=args.target, priority=args.priority,
        )
        print(f"{'✅' if ok else '❌'} Update goal #{args.id}")

    elif args.command == "delete":
        ok = delete_goal(args.id, cascade=args.cascade)
        print(f"{'✅' if ok else '❌'} Delete goal #{args.id}")

    elif args.command == "get":
        goal = get_goal(args.id)
        if goal:
            print(json.dumps(goal, indent=2, ensure_ascii=False, default=str))
        else:
            print("Not found")

    elif args.command == "list":
        goals = list_goals(status=args.status, root_only=args.root_only, priority=args.priority)
        if not goals:
            print("No goals found")
        for g in goals:
            p = g.get("progress", 0)
            print(f"  #{g['id']} [{g['priority']}] [{g['status']}] {g['title']}  {p:.0%}")

    elif args.command == "tree":
        tree = get_tree(root_id=args.root)
        if not tree:
            print("No goals found. Run 'seed' to create default goals.")
        for node in tree:
            print(_format_tree(node))

    elif args.command == "gaps":
        gaps = get_gaps()
        if not gaps:
            print("No significant gaps found")
        for g in gaps:
            print(f"  [{g['priority']}] #{g['goal_id']} {g['title']}: "
                  f"progress={g['progress']:.0%} gap={g['gap']:.0%} "
                  f"({g['current_value']}/{g['target_value']}{g['unit']})")

    elif args.command == "summary":
        s = summary()
        print(json.dumps(s, indent=2, ensure_ascii=False))

    elif args.command == "seed":
        if seed_default_goals():
            print("✅ Default goals seeded")
        else:
            print("⚠️ Goals already exist or seed failed")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()


# ============ Goal Tree Auto（从 goal_tree_auto.py 合并）============

CAPABILITY_GAP_THRESHOLD = 70.0  # 能力缺口阈值，低于此分数视为短板

# ============ 能力缺口驱动 ============
def auto_adjust_priorities() -> list[dict]:
    """
    根据能力缺口自动调整目标优先级。
    
    规则：
    1. capability < 70 分 → 相关目标优先级提升到 P0
    2. capability > 85 分 → 相关目标优先级降到 P2
    3. 新发现能力短板 → 创建新目标
    
    Returns:
        调整记录列表
    """
    db = get_db()
    adjustments = []
    
    try:
        # 获取能力短板
        from capability_model import get_weaknesses
        weaknesses = get_weaknesses(threshold=CAPABILITY_GAP_THRESHOLD)
        
        for weak in weaknesses:
            capability_name = weak["name"]
            capability_score = weak["score"]
            
            # 查找相关目标
            related_goals = find_related_goals(capability_name)
            
            for goal in related_goals:
                old_priority = goal["priority"]
                
                # 能力<70 → P0
                if capability_score < 70:
                    new_priority = "P0"
                # 能力 70-85 → P1
                elif capability_score < 85:
                    new_priority = "P1"
                # 能力>85 → P2
                else:
                    new_priority = "P2"
                
                if old_priority != new_priority:
                    # 更新优先级
                    db.execute(
                        "UPDATE goals SET priority = ?, updated_at = ? WHERE id = ?",
                        (new_priority, datetime.now().isoformat(), goal["id"])
                    )
                    
                    adjustments.append({
                        "goal_id": goal["id"],
                        "goal_title": goal["title"],
                        "capability": capability_name,
                        "capability_score": capability_score,
                        "old_priority": old_priority,
                        "new_priority": new_priority,
                    })
                    
                    print(f"[goal_tree_auto] 📊 调整目标 #{goal['id']} 优先级：{old_priority} → {new_priority} "
                          f"（能力：{capability_name}={capability_score}分）")
        
        db.commit()
    
    except Exception as e:
        print(f"[goal_tree_auto] ❌ 优先级调整失败：{e}")
    
    finally:
        db.close()
    
    return adjustments

def find_related_goals(capability_name: str) -> list[dict]:
    """查找与能力相关的目标。"""
    db = get_db()
    try:
        # 简单关键词匹配
        keywords = capability_name.lower().split()
        
        related = []
        goals = db.execute("SELECT * FROM goals WHERE status = 'active'").fetchall()
        
        for goal in goals:
            title_lower = (goal["title"] or "").lower()
            metric_lower = (goal["metric"] or "").lower()
            
            # 匹配关键词
            if any(kw in title_lower or kw in metric_lower for kw in keywords):
                related.append(dict(goal))
        
        return related
    
    except Exception as e:
        print(f"[goal_tree_auto] ⚠️ 查找相关目标失败：{e}")
        return []
    finally:
        db.close()

# ============ 进度自动聚合 ============
def auto_update_progress() -> list[dict]:
    """
    自动更新目标进度。
    
    规则：
    1. 子目标进度变化 → 自动聚合到父目标
    2. 实验结论 effective → 相关目标进度 +10%
    3. capability 评分提升 → 相关目标进度 +5%
    
    Returns:
        更新记录列表
    """
    db = get_db()
    updates = []
    
    try:
        # 1. 聚合子目标进度
        goals = db.execute("SELECT * FROM goals WHERE status = 'active'").fetchall()
        
        for goal in goals:
            goal_id = goal["id"]
            
            # 查找子目标
            children = db.execute(
                "SELECT * FROM goals WHERE parent_id = ? AND status = 'active'",
                (goal_id,)
            ).fetchall()
            
            if children:
                # 计算平均进度
                progress_sum = sum(c["current_value"] or 0 for c in children)
                new_progress = progress_sum / len(children)
                
                # 更新父目标进度
                old_progress = goal["current_value"] or 0
                if abs(new_progress - old_progress) > 0.01:
                    db.execute(
                        "UPDATE goals SET current_value = ?, updated_at = ? WHERE id = ?",
                        (round(new_progress, 4), datetime.now().isoformat(), goal_id)
                    )
                    
                    updates.append({
                        "goal_id": goal_id,
                        "goal_title": goal["title"],
                        "old_progress": old_progress,
                        "new_progress": new_progress,
                        "reason": "子目标进度聚合",
                    })
        
        # 2. 从能力评分推算目标进度
        try:
            from capability_model import evaluate_all
            all_caps = evaluate_all()
            cap_map = {c["name"]: c["score"] for c in all_caps}
            
            # 进化闭环 → 取 coding + research 平均分作为进度
            coding_score = cap_map.get("coding", 0)
            research_score = cap_map.get("research", 0)
            avg_score = (coding_score + research_score) / 2 if (coding_score or research_score) else 0
            
            for goal in goals:
                goal_lower = (goal["title"] or "").lower()
                new_val = None
                if "进化闭环" in goal_lower or "成功率" in goal_lower:
                    new_val = avg_score
                elif "学习落地" in goal_lower:
                    # 外部学习落地率：从 observations 中统计 evidence 数量
                    evidence_count = db.execute(
                        "SELECT COUNT(*) FROM observations WHERE type = 'external_learning_evidence' AND source = 'external_learning'"
                    ).fetchone()[0]
                    new_val = min(evidence_count * 5, goal["target_value"] or 30)
                elif "系统稳定性" in goal_lower:
                    # 系统稳定性：从 task_outcomes 成功率推算
                    row = db.execute(
                        "SELECT COUNT(*) as total, SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as wins FROM task_outcomes"
                    ).fetchone()
                    if row and row["total"] > 0:
                        new_val = (row["wins"] / row["total"]) * 100
                
                if new_val is not None:
                    old_progress = goal["current_value"] or 0
                    if abs(new_val - old_progress) > 0.1:
                        db.execute(
                            "UPDATE goals SET current_value = ?, updated_at = ? WHERE id = ?",
                            (round(new_val, 2), datetime.now().isoformat(), goal["id"]),
                        )
                        updates.append({
                            "goal_id": goal["id"],
                            "goal_title": goal["title"],
                            "old_progress": old_progress,
                            "new_progress": round(new_val, 2),
                            "reason": "能力/数据驱动推算",
                        })
        except Exception as e:
            print(f"[goal_tree_auto] 能力推算进度失败：{e}")
        
        db.commit()
    
    except Exception as e:
        print(f"[goal_tree_auto] ❌ 进度更新失败：{e}")
    
    finally:
        db.close()
    
    return updates

# ============ 自动创建目标 ============
def auto_create_goals_from_discoveries() -> list[int]:
    """
    从外部探索发现自动创建新目标。
    
    规则：
    1. exploration_engine 发现新领域 → 创建对应目标
    2. 能力画像新增维度 → 创建提升目标
    3. 重复失败模式 → 创建改进目标
    
    Returns:
        新创建的目标 ID 列表
    """
    db = get_db()
    created = []
    
    try:
        # 获取能力画像
        from capability_model import get_profile
        profile = get_profile()
        
        # 检查是否有新能力维度
        for cap in profile.get("unknown", []):
            cap_name = cap["name"]
            
            # 检查是否已有相关目标
            existing = db.execute(
                "SELECT id FROM goals WHERE title LIKE ? AND status = 'active'",
                (f"%{cap_name}%",)
            ).fetchone()
            
            if not existing:
                # 创建新目标
                target_value = 80.0  # 目标达到 80 分
                current_value = cap.get("score", 0)
                
                cursor = db.execute(
                    """INSERT INTO goals
                       (title, description, target_value, current_value, priority,
                        status, parent_id, metric, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (f"提升{cap_name}能力",
                     f"通过实验和练习，将{cap_name}能力提升到{target_value}分以上",
                     target_value,
                     current_value,
                     "P1",
                     "active",
                     None,  # 顶级目标
                     f"{cap_name} 能力评分",
                     datetime.now().isoformat())
                )
                
                created.append(cursor.lastrowid)
                print(f"[goal_tree_auto] ✅ 创建目标 #{cursor.lastrowid}: 提升{cap_name}能力")
        
        db.commit()
    
    except Exception as e:
        print(f"[goal_tree_auto] ❌ 目标创建失败：{e}")
    
    finally:
        db.close()
    
    return created

# ============ 主流程 ============
def run_auto_goal_cycle() -> dict:
    """
    运行完整目标自动更新闭环。
    
    流程：
    1. 根据能力缺口调整优先级
    2. 聚合子目标进度
    3. 从发现创建新目标
    
    Returns:
        执行结果
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 目标自动更新启动")
    
    # Step 1: 调整优先级
    adjustments = auto_adjust_priorities()
    print(f"  优先级调整：{len(adjustments)} 个")
    
    # Step 2: 聚合进度
    progress_updates = auto_update_progress()
    print(f"  进度更新：{len(progress_updates)} 个")
    
    # Step 3: 创建新目标
    new_goals = auto_create_goals_from_discoveries()
    print(f"  新目标创建：{len(new_goals)} 个")
    
    return {
        "adjustments": len(adjustments),
        "progress_updates": len(progress_updates),
        "new_goals": len(new_goals),
    }

# ============ CLI ============
