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
    "coding": ["写代码", "实现", "开发", "bug", "fix", "feature", "函数", "类", "API", "接口", "测试", "test", "代码", "脚本", "script", "python", "程序", "编程", "编写", "写一个"],
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


DEFAULT_STATS_PATH = str(Path(__file__).parent.parent / "agent-stats.json")
DEFAULT_DB_PATH = str(Path(__file__).parent / "memory.db")

# ── Data Loading ─────────────────────────────────────────────────────────────

def load_stats(stats_path=None):
    """Load agent-stats.json and optionally merge task_outcomes from memory.db."""
    path = stats_path or DEFAULT_STATS_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    stats = data.get("stats", data)
    # Ensure 'recent' list exists
    if "recent" not in stats:
        stats["recent"] = []

    # Try to enrich from memory.db task_outcomes table
    db_path = DEFAULT_DB_PATH
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            # Check if task_outcomes table exists
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_outcomes'")
            if cur.fetchone():
                cur.execute("SELECT model, task_type, success, timestamp FROM task_outcomes ORDER BY timestamp DESC")
                existing_times = {r.get("time") for r in stats["recent"] if r.get("time")}
                for row in cur.fetchall():
                    model, task_type, success, ts = row
                    if ts not in existing_times:
                        stats["recent"].append({
                            "time": ts,
                            "model": model or "unknown",
                            "task_type": task_type or "unknown",
                            "success": bool(success),
                            "label": "from_db",
                        })
            conn.close()
        except Exception:
            pass  # DB read is best-effort

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
        run_tests()
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


# ── Tests ────────────────────────────────────────────────────────────────────

def run_tests():
    """Run all tests with mock data."""
    passed = 0
    failed = 0

    def assert_eq(actual, expected, msg=""):
        nonlocal passed, failed
        if actual == expected:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL: {msg}\n    expected: {expected}\n    actual:   {actual}")

    def assert_true(cond, msg=""):
        nonlocal passed, failed
        if cond:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL: {msg}")

    def assert_close(actual, expected, tol=0.001, msg=""):
        nonlocal passed, failed
        if actual is not None and abs(actual - expected) < tol:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL: {msg}\n    expected: ~{expected}\n    actual:   {actual}")

    # ── Mock data ────────────────────────────────────────────────────────
    mock_stats = {
        "by_model": {
            "opus":    {"total": 10, "success": 9, "fail": 1},
            "minimax": {"total": 8,  "success": 5, "fail": 3},
            "sonnet":  {"total": 6,  "success": 5, "fail": 1},
            "glm5":    {"total": 4,  "success": 3, "fail": 1},
        },
        "by_task_type": {
            "coding":   {"total": 10, "success": 8, "fail": 2},
            "research": {"total": 8,  "success": 6, "fail": 2},
            "file_ops": {"total": 5,  "success": 5, "fail": 0},
            "refactor": {"total": 5,  "success": 4, "fail": 1},
        },
        "recent": [
            # opus coding: 4 success, 1 fail → 80%
            {"time": "t01", "model": "opus",    "task_type": "coding",   "success": True,  "label": "a"},
            {"time": "t02", "model": "opus",    "task_type": "coding",   "success": True,  "label": "b"},
            {"time": "t03", "model": "opus",    "task_type": "coding",   "success": True,  "label": "c"},
            {"time": "t04", "model": "opus",    "task_type": "coding",   "success": True,  "label": "d"},
            {"time": "t05", "model": "opus",    "task_type": "coding",   "success": False, "label": "e"},
            # minimax coding: 3 success, 1 fail → 75%
            {"time": "t06", "model": "minimax", "task_type": "coding",   "success": True,  "label": "f"},
            {"time": "t07", "model": "minimax", "task_type": "coding",   "success": True,  "label": "g"},
            {"time": "t08", "model": "minimax", "task_type": "coding",   "success": True,  "label": "h"},
            {"time": "t09", "model": "minimax", "task_type": "coding",   "success": False, "label": "i"},
            # sonnet coding: 3 success, 0 fail → 100%
            {"time": "t10", "model": "sonnet",  "task_type": "coding",   "success": True,  "label": "j"},
            {"time": "t11", "model": "sonnet",  "task_type": "coding",   "success": True,  "label": "k"},
            {"time": "t12", "model": "sonnet",  "task_type": "coding",   "success": True,  "label": "l"},
            # glm5 coding: only 2 samples → insufficient
            {"time": "t13", "model": "glm5",    "task_type": "coding",   "success": True,  "label": "m"},
            {"time": "t14", "model": "glm5",    "task_type": "coding",   "success": True,  "label": "n"},
            # opus research: 3 success, 1 fail → 75%
            {"time": "t15", "model": "opus",    "task_type": "research", "success": True,  "label": "o"},
            {"time": "t16", "model": "opus",    "task_type": "research", "success": True,  "label": "p"},
            {"time": "t17", "model": "opus",    "task_type": "research", "success": True,  "label": "q"},
            {"time": "t18", "model": "opus",    "task_type": "research", "success": False, "label": "r"},
            # minimax research: 4 success, 0 fail → 100%
            {"time": "t19", "model": "minimax", "task_type": "research", "success": True,  "label": "s"},
            {"time": "t20", "model": "minimax", "task_type": "research", "success": True,  "label": "t"},
            {"time": "t21", "model": "minimax", "task_type": "research", "success": True,  "label": "u"},
            {"time": "t22", "model": "minimax", "task_type": "research", "success": True,  "label": "v"},
            # sonnet research: 3 success, 1 fail → 75%
            {"time": "t23", "model": "sonnet",  "task_type": "research", "success": True,  "label": "w"},
            {"time": "t24", "model": "sonnet",  "task_type": "research", "success": False, "label": "x"},
            {"time": "t25", "model": "sonnet",  "task_type": "research", "success": True,  "label": "y"},
            {"time": "t26", "model": "sonnet",  "task_type": "research", "success": True,  "label": "z"},
        ],
    }

    # ── Test 1: calculate_success_rate ────────────────────────────────────
    print("Test 1: calculate_success_rate")

    # opus overall: 9 entries (5 coding + 4 research), 7 success → 7/9
    rate_opus = calculate_success_rate(mock_stats, model="opus")
    assert_close(rate_opus, 7 / 9, msg="opus overall rate")

    # minimax overall: 8 entries (4 coding + 4 research), 7 success → 7/8
    rate_minimax = calculate_success_rate(mock_stats, model="minimax")
    assert_close(rate_minimax, 7 / 8, msg="minimax overall rate")

    # opus + coding: 5 entries, 4 success → 0.8
    rate_opus_coding = calculate_success_rate(mock_stats, model="opus", task_type="coding")
    assert_close(rate_opus_coding, 0.8, msg="opus coding rate")

    # minimax + coding: 4 entries, 3 success → 0.75
    rate_mm_coding = calculate_success_rate(mock_stats, model="minimax", task_type="coding")
    assert_close(rate_mm_coding, 0.75, msg="minimax coding rate")

    # sonnet + coding: 3 entries, 3 success → 1.0
    rate_sonnet_coding = calculate_success_rate(mock_stats, model="sonnet", task_type="coding")
    assert_close(rate_sonnet_coding, 1.0, msg="sonnet coding rate")

    # glm5 + coding: only 2 samples → None
    rate_glm5_coding = calculate_success_rate(mock_stats, model="glm5", task_type="coding")
    assert_eq(rate_glm5_coding, None, msg="glm5 coding insufficient data")

    # task_type only: coding = 14 entries, 12 success → 12/14
    rate_coding = calculate_success_rate(mock_stats, task_type="coding")
    assert_close(rate_coding, 12 / 14, msg="coding overall rate")

    # no filter: all 26 entries, 22 success → 22/26
    rate_all = calculate_success_rate(mock_stats)
    assert_close(rate_all, 22 / 26, msg="overall rate")

    print(f"  {passed} passed")

    # ── Test 2: recommend_model different priorities ──────────────────────
    print("Test 2: recommend_model priorities")

    # coding + quality → sonnet (100% success)
    rec_quality = recommend_model("coding", priority="quality", stats=mock_stats)
    assert_eq(rec_quality["model"], "sonnet", msg="coding quality → sonnet")

    # coding + cost → minimax should NOT qualify (75% < 80%), opus qualifies (80%)
    # opus is cheapest among qualified (opus=0.15, sonnet=0.05... wait sonnet=100%)
    # Actually: qualified (>=80%) are opus(80%) and sonnet(100%). Cheapest = sonnet($0.05)
    rec_cost = recommend_model("coding", priority="cost", stats=mock_stats)
    assert_eq(rec_cost["model"], "sonnet", msg="coding cost → sonnet (cheapest ≥80%)")

    # research + quality → minimax (100%)
    rec_rq = recommend_model("research", priority="quality", stats=mock_stats)
    assert_eq(rec_rq["model"], "minimax", msg="research quality → minimax")

    # research + cost → minimax (100% ≥ 80%, cheapest at $0.01)
    rec_rc = recommend_model("research", priority="cost", stats=mock_stats)
    assert_eq(rec_rc["model"], "minimax", msg="research cost → minimax")

    # research + balanced → minimax (100%/0.01 = 100 ratio, best)
    rec_rb = recommend_model("research", priority="balanced", stats=mock_stats)
    assert_eq(rec_rb["model"], "minimax", msg="research balanced → minimax")

    # coding + balanced → sonnet (1.0/0.05=20) vs minimax (0.75/0.01=75) vs opus (0.8/0.15=5.3)
    # minimax has best ratio but only 75%. The function picks best ratio regardless.
    rec_cb = recommend_model("coding", priority="balanced", stats=mock_stats)
    assert_eq(rec_cb["model"], "minimax", msg="coding balanced → minimax (best ratio)")

    # Verify return structure
    for key in ("model", "alias", "estimated_success_rate", "estimated_cost", "reason"):
        assert_true(key in rec_quality, msg=f"recommend result has '{key}'")

    print(f"  {passed} passed total")

    # ── Test 3: cost_report structure ─────────────────────────────────────
    print("Test 3: cost_report")

    report = cost_report(mock_stats)
    assert_true("by_model" in report, msg="cost_report has by_model")
    assert_true("total_tasks" in report, msg="cost_report has total_tasks")
    assert_true("total_estimated_cost" in report, msg="cost_report has total_estimated_cost")
    assert_true("cheapest_model_scenario" in report, msg="cost_report has cheapest_model_scenario")
    assert_true("premium_model_scenario" in report, msg="cost_report has premium_model_scenario")

    # Verify cheapest is minimax
    assert_eq(report["cheapest_model_scenario"]["model"], "minimax", msg="cheapest is minimax")
    # Verify premium is opus
    assert_eq(report["premium_model_scenario"]["model"], "opus", msg="premium is opus")

    # Verify per-model data
    for model_name in MODELS:
        assert_true(model_name in report["by_model"], msg=f"cost_report has {model_name}")
        assert_true("total_tasks" in report["by_model"][model_name], msg=f"{model_name} has total_tasks")
        assert_true("estimated_cost" in report["by_model"][model_name], msg=f"{model_name} has estimated_cost")

    # Savings should be positive (current mix is more expensive than all-minimax)
    assert_true(report["cheapest_model_scenario"]["potential_savings"] >= 0, msg="savings >= 0")

    print(f"  {passed} passed total")

    # ── Test 4: routing_table coverage ────────────────────────────────────
    print("Test 4: routing_table")

    table = routing_table(mock_stats)

    # Should cover all task types from mock data + defaults
    expected_types = {"coding", "research", "file_ops", "refactor", "skill_creation"}
    for tt in expected_types:
        assert_true(tt in table, msg=f"routing_table has {tt}")

    # Each task_type should have all 3 priorities
    for tt, priorities in table.items():
        for prio in ("cost", "quality", "balanced"):
            assert_true(prio in priorities, msg=f"{tt} has {prio}")
            rec = priorities[prio]
            assert_true("model" in rec, msg=f"{tt}/{prio} has model")
            assert_true("reason" in rec, msg=f"{tt}/{prio} has reason")

    print(f"  {passed} passed total")

    # ── Test 5: fallback for unknown task_type ────────────────────────────
    print("Test 5: fallback behavior")

    # Task type with zero data → default
    rec_unknown = recommend_model("unknown_task", stats=mock_stats)
    assert_eq(rec_unknown["model"], "opus", msg="unknown task → opus default")
    assert_eq(rec_unknown["estimated_success_rate"], None, msg="unknown task rate is None")
    assert_true("No history" in rec_unknown["reason"], msg="unknown task reason mentions no history")

    # file_ops has no data in mock_stats recent → default
    rec_fileops = recommend_model("file_ops", stats=mock_stats)
    assert_eq(rec_fileops["model"], "minimax", msg="file_ops no data → minimax default")

    print(f"  {passed} passed total")

    # ── Test 6: edge cases ────────────────────────────────────────────────
    print("Test 6: edge cases")

    # Empty stats
    empty_stats = {"recent": [], "by_model": {}, "by_task_type": {}}
    rate_empty = calculate_success_rate(empty_stats, model="opus")
    assert_eq(rate_empty, None, msg="empty stats → None")

    rec_empty = recommend_model("coding", stats=empty_stats)
    assert_eq(rec_empty["model"], "opus", msg="empty stats coding → opus default")

    report_empty = cost_report(empty_stats)
    assert_eq(report_empty["total_tasks"], 0, msg="empty stats total_tasks = 0")

    table_empty = routing_table(empty_stats)
    assert_true(len(table_empty) > 0, msg="empty stats routing_table not empty (has defaults)")

    print(f"  {passed} passed total")

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'='*50}")
    if failed == 0:
        print(f"ALL TESTS PASSED ({passed} assertions)")
    else:
        print(f"FAILED: {failed} assertions failed, {passed} passed")
        sys.exit(1)


if __name__ == "__main__":
    cli()