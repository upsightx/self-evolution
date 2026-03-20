#!/usr/bin/env python3
"""Multi-model dynamic routing module.

Recommends the optimal model for a task based on historical success rates and cost.
Zero external dependencies — stdlib only.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

# ── Model Configuration ──────────────────────────────────────────────────────

MODELS = {
    "opus":    {"cost_per_task": 0.15, "alias": "LtCraft",        "tier": "premium"},
    "minimax": {"cost_per_task": 0.01, "alias": "Minimax",        "tier": "budget"},
    "glm5":   {"cost_per_task": 0.02, "alias": "GPT5",            "tier": "mid"},
    "sonnet":  {"cost_per_task": 0.05, "alias": "LtCraft-Sonnet", "tier": "mid"},
}

DEFAULT_RECOMMENDATIONS = {
    "coding":         "opus",
    "research":       "minimax",
    "file_ops":       "minimax",
    "refactor":       "opus",
    "skill_creation": "sonnet",
}

# ── Task Classification (rule-first + fuzzy fallback) ────────────────────────

TASK_KEYWORDS = {
    "coding": ["写代码", "实现", "开发", "bug", "fix", "feature", "函数", "类", "API", "接口", "测试", "test", "代码", "脚本", "script", "python", "程序", "编程", "编写", "写一个", "爬虫", "crawler", "解析", "parser", "处理"],
    "research": ["搜索", "调研", "查找", "整理", "收集", "分析", "对比", "学习", "了解", "搜一下", "查一下", "找一下", "看看", "融资", "论文", "新闻", "趋势", "报告"],
    "file_ops": ["文件", "复制", "移动", "删除", "创建目录", "上传", "下载", "备份", "归档", "archive", "同步", "清理文件"],
    "refactor": ["重构", "优化", "重写", "清理", "整合", "迁移", "升级", "精简"],
    "skill_creation": ["skill", "技能", "SKILL.md", "创建skill", "新skill"],
}

FUZZY_THRESHOLD = 0.3


def classify_task(description: str) -> str:
    """从任务描述中分类任务类型

    分层策略：
    1. 关键词规则匹配（零成本）
    2. 如果规则匹配不到，用模糊匹配打分
    3. 都不行返回 "general"

    返回: task_type 字符串（coding/research/file_ops/refactor/skill_creation/general）
    """
    if not description or not description.strip():
        return "general"

    desc_lower = description.lower()

    # Layer 1: exact keyword match — count hits per category
    hit_counts = {}
    for task_type, keywords in TASK_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw.lower() in desc_lower)
        if count > 0:
            hit_counts[task_type] = count

    if hit_counts:
        # Return the category with the most keyword hits
        return max(hit_counts, key=hit_counts.get)

    # Layer 2: fuzzy character-overlap scoring
    scores = {}
    desc_chars = set(desc_lower)
    for task_type, keywords in TASK_KEYWORDS.items():
        kw_chars = set()
        for kw in keywords:
            kw_chars.update(kw.lower())
        if not kw_chars:
            continue
        overlap = len(desc_chars & kw_chars)
        union = len(desc_chars | kw_chars)
        score = overlap / union if union > 0 else 0.0
        scores[task_type] = score

    if scores:
        best_type = max(scores, key=scores.get)
        if scores[best_type] >= FUZZY_THRESHOLD:
            return best_type

    # Layer 3: fallback
    return "general"


def recommend_for_description(description: str, strategy: str = "balanced") -> dict:
    """Classify a task description and recommend a model.

    Args:
        description: Natural language task description.
        strategy: "cost" | "quality" | "balanced"

    Returns:
        {"task_type": "...", "model": "...", "alias": "...", "confidence": float}
    """
    task_type = classify_task(description)

    try:
        stats = load_stats()
    except Exception:
        stats = {"recent": []}

    rec = recommend_model(task_type, priority=strategy, stats=stats)

    # Determine confidence
    if task_type == "general":
        confidence = 0.3
    else:
        # Check if it was a keyword hit (re-run layer 1 quickly)
        desc_lower = description.lower()
        keyword_hit = any(
            any(kw.lower() in desc_lower for kw in TASK_KEYWORDS.get(task_type, []))
            for _ in [1]
        )
        confidence = 0.9 if keyword_hit else 0.6

    return {
        "task_type": task_type,
        "model": rec["model"],
        "alias": rec["alias"],
        "confidence": confidence,
    }


from db_common import DB_PATH as _DB_PATH

DEFAULT_DB_PATH = str(_DB_PATH)
# Legacy path kept for backcompat; load_stats() now prefers memory.db
DEFAULT_STATS_PATH = str(Path(__file__).parent.parent / "agent-stats.json")

# ── Data Loading ─────────────────────────────────────────────────────────────

def load_stats(stats_path=None, db_path=None):
    """Load task outcome data. Primary source: memory.db task_outcomes.
    Falls back to agent-stats.json if DB is unavailable.
    
    Returns dict with 'recent' list of {time, model, task_type, success, label}.
    """
    stats = {"recent": []}
    seen_keys = set()  # (time, model, task_type) for dedup

    # Primary source: memory.db task_outcomes
    dp = db_path or DEFAULT_DB_PATH
    if os.path.exists(dp):
        try:
            conn = sqlite3.connect(dp)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_outcomes'")
            if cur.fetchone():
                cur.execute("SELECT model, task_type, success, timestamp FROM task_outcomes ORDER BY timestamp DESC LIMIT 200")
                for row in cur.fetchall():
                    model, task_type, success, ts = row
                    model = model or "unknown"
                    task_type = task_type or "unknown"
                    key = (ts, model, task_type)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        stats["recent"].append({
                            "time": ts,
                            "model": model,
                            "task_type": task_type,
                            "success": bool(success),
                            "label": "from_db",
                        })
            conn.close()
        except Exception:
            pass

    # Fallback: agent-stats.json (for legacy data not yet in DB)
    sp = stats_path or DEFAULT_STATS_PATH
    if os.path.exists(sp):
        try:
            with open(sp, "r", encoding="utf-8") as f:
                data = json.load(f)
            for r in data.get("stats", data).get("recent", []):
                ts = r.get("time", "")
                model = r.get("model", "unknown")
                task_type = r.get("task_type", "unknown")
                key = (ts, model, task_type)
                if key not in seen_keys:
                    seen_keys.add(key)
                    stats["recent"].append({
                        "time": ts,
                        "model": model,
                        "task_type": task_type,
                        "success": bool(r.get("success")),
                        "label": r.get("label", "from_json"),
                    })
        except Exception:
            pass

    return stats


def calculate_success_rate(stats, model=None, task_type=None):
    """Calculate success rate from the recent list.

    Returns float 0.0-1.0, or None if fewer than 3 matching samples.
    """
    recent = stats.get("recent", [])
    filtered = recent
    if model:
        filtered = [r for r in filtered if r.get("model") == model]
    if task_type:
        filtered = [r for r in filtered if r.get("task_type") == task_type]

    if len(filtered) < 3:
        return None

    successes = sum(1 for r in filtered if r.get("success"))
    return successes / len(filtered)


def recommend_model(task_type, priority="balanced", stats=None):
    """Recommend the best model for a task type.

    priority: "cost" | "quality" | "balanced"
    Returns dict with model, alias, estimated_success_rate, estimated_cost, reason.
    """
    if stats is None:
        try:
            stats = load_stats()
        except Exception:
            stats = {"recent": []}

    candidates = []
    for model_name, config in MODELS.items():
        rate = calculate_success_rate(stats, model=model_name, task_type=task_type)
        candidates.append({
            "model": model_name,
            "alias": config["alias"],
            "cost": config["cost_per_task"],
            "tier": config["tier"],
            "rate": rate,  # None if insufficient data
        })

    # Check if we have ANY data for this task_type
    has_data = any(c["rate"] is not None for c in candidates)

    if not has_data:
        # Fallback to defaults
        default_model = DEFAULT_RECOMMENDATIONS.get(task_type, "opus")
        cfg = MODELS[default_model]
        return {
            "model": default_model,
            "alias": cfg["alias"],
            "estimated_success_rate": None,
            "estimated_cost": cfg["cost_per_task"],
            "reason": f"No history for '{task_type}', using default recommendation",
        }

    if priority == "cost":
        # Cheapest model with success_rate >= 0.8 (or best available if none qualifies)
        qualified = [c for c in candidates if c["rate"] is not None and c["rate"] >= 0.8]
        if qualified:
            best = min(qualified, key=lambda c: c["cost"])
            reason = f"Cheapest with ≥80% success rate ({best['rate']:.0%})"
        else:
            # No model hits 80%, pick cheapest with data
            with_data = [c for c in candidates if c["rate"] is not None]
            best = min(with_data, key=lambda c: c["cost"])
            reason = f"No model ≥80% success; cheapest with data ({best['rate']:.0%})"

    elif priority == "quality":
        # Highest success rate; tie-break by cost (cheaper wins)
        with_data = [c for c in candidates if c["rate"] is not None]
        best = max(with_data, key=lambda c: (c["rate"], -c["cost"]))
        reason = f"Highest success rate ({best['rate']:.0%})"

    else:  # balanced
        # Best success_rate / cost_per_task ratio
        with_data = [c for c in candidates if c["rate"] is not None]
        best = max(with_data, key=lambda c: c["rate"] / c["cost"])
        ratio = best["rate"] / best["cost"]
        reason = f"Best value ratio ({best['rate']:.0%} success, ${best['cost']:.2f}/task, ratio={ratio:.1f})"

    return {
        "model": best["model"],
        "alias": best["alias"],
        "estimated_success_rate": best["rate"],
        "estimated_cost": best["cost"],
        "reason": reason,
    }


def cost_report(stats):
    """Generate a cost analysis report."""
    recent = stats.get("recent", [])
    by_model = stats.get("by_model", {})

    # Per-model stats
    model_stats = {}
    for model_name in MODELS:
        agg = by_model.get(model_name, {})
        total = agg.get("total", 0)
        # Also count from recent if aggregates are stale
        recent_count = sum(1 for r in recent if r.get("model") == model_name)
        count = max(total, recent_count)
        cost = count * MODELS[model_name]["cost_per_task"]
        model_stats[model_name] = {"total_tasks": count, "estimated_cost": round(cost, 4)}

    total_tasks = sum(v["total_tasks"] for v in model_stats.values())
    total_cost = sum(v["estimated_cost"] for v in model_stats.values())

    # Cheapest model scenario
    cheapest = min(MODELS.values(), key=lambda m: m["cost_per_task"])
    cheapest_name = [k for k, v in MODELS.items() if v is cheapest][0]
    cheapest_cost = total_tasks * cheapest["cost_per_task"]
    savings = total_cost - cheapest_cost

    # Most expensive (highest quality) scenario
    priciest = max(MODELS.values(), key=lambda m: m["cost_per_task"])
    priciest_name = [k for k, v in MODELS.items() if v is priciest][0]
    priciest_cost = total_tasks * priciest["cost_per_task"]

    # Quality uplift estimate
    current_successes = sum(1 for r in recent if r.get("success"))
    current_rate = current_successes / len(recent) if recent else 0
    priciest_rate = calculate_success_rate(stats, model=priciest_name)

    return {
        "by_model": model_stats,
        "total_tasks": total_tasks,
        "total_estimated_cost": round(total_cost, 4),
        "cheapest_model_scenario": {
            "model": cheapest_name,
            "cost_per_task": cheapest["cost_per_task"],
            "total_cost": round(cheapest_cost, 4),
            "potential_savings": round(savings, 4),
        },
        "premium_model_scenario": {
            "model": priciest_name,
            "cost_per_task": priciest["cost_per_task"],
            "total_cost": round(priciest_cost, 4),
            "current_overall_success_rate": round(current_rate, 4),
            "premium_model_success_rate": priciest_rate,
        },
    }


def routing_table(stats):
    """Generate a full routing table: task_type → {priority → recommendation}."""
    # Collect all known task types
    task_types = set()
    by_task = stats.get("by_task_type", {})
    task_types.update(by_task.keys())
    for r in stats.get("recent", []):
        tt = r.get("task_type")
        if tt:
            task_types.add(tt)
    task_types.update(DEFAULT_RECOMMENDATIONS.keys())

    table = {}
    for tt in sorted(task_types):
        table[tt] = {}
        for prio in ("cost", "quality", "balanced"):
            table[tt][prio] = recommend_model(tt, priority=prio, stats=stats)
    return table


# ── CLI ──────────────────────────────────────────────────────────────────────

def cli():
    args = sys.argv[1:]
    if not args:
        print("Usage: model_router.py <command> [options]")
        print("Commands: recommend, table, cost, rate, test")
        sys.exit(1)

    cmd = args[0]

    if cmd == "test":
        print("Tests moved to tests/test_model_router.py — run: python3 tests/test_model_router.py")
        return

    if cmd == "classify":
        if len(args) < 2:
            print("Usage: model_router.py classify <description> [--strategy balanced]")
            sys.exit(1)
        desc = args[1]
        strategy = "balanced"
        if "--strategy" in args:
            idx = args.index("--strategy")
            if idx + 1 < len(args):
                strategy = args[idx + 1]
        result = recommend_for_description(desc, strategy=strategy)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    stats = load_stats()

    if cmd == "recommend":
        if len(args) < 2:
            print("Usage: model_router.py recommend <task_type> [--priority balanced]")
            sys.exit(1)
        task_type = args[1]
        priority = "balanced"
        if "--priority" in args:
            idx = args.index("--priority")
            if idx + 1 < len(args):
                priority = args[idx + 1]
        result = recommend_model(task_type, priority=priority, stats=stats)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif cmd == "table":
        result = routing_table(stats)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif cmd == "cost":
        result = cost_report(stats)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif cmd == "rate":
        model = None
        task_type = None
        if "--model" in args:
            idx = args.index("--model")
            if idx + 1 < len(args):
                model = args[idx + 1]
        if "--task" in args:
            idx = args.index("--task")
            if idx + 1 < len(args):
                task_type = args[idx + 1]
        rate = calculate_success_rate(stats, model=model, task_type=task_type)
        if rate is None:
            print("Insufficient data (< 3 samples)")
        else:
            print(f"{rate:.2%}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    cli()