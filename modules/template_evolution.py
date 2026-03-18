#!/usr/bin/env python3
"""
Template Evolution Module
Analyzes sub-agent success/failure data and generates template improvement suggestions.

Data sources:
- agent-stats.json: aggregated success/failure counts by task_type
- memory.db task_outcomes table: detailed per-task records with gap_analysis/notes

Usage:
    python3 template_evolution.py analyze coding
    python3 template_evolution.py suggest coding
    python3 template_evolution.py report
"""

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

STATS_PATH = Path(__file__).parent.parent / "agent-stats.json"
from db_common import DB_PATH
TEMPLATES_DIR = Path(__file__).parent.parent / "agent-templates" / "templates"


def _load_stats() -> dict:
    """Load agent-stats.json. Returns empty structure on failure."""
    try:
        with open(STATS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _get_db() -> sqlite3.Connection | None:
    """Get DB connection. Returns None if DB doesn't exist."""
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _get_db_outcomes(task_type: str) -> list[dict]:
    """Fetch task_outcomes rows for a given task_type from memory.db."""
    conn = _get_db()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT success, gap_analysis, notes FROM task_outcomes WHERE task_type = ? ORDER BY timestamp DESC",
            (task_type,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _get_all_task_types_from_db() -> list[str]:
    """Get all distinct task_types from task_outcomes table."""
    conn = _get_db()
    if conn is None:
        return []
    try:
        rows = conn.execute("SELECT DISTINCT task_type FROM task_outcomes").fetchall()
        return [r["task_type"] for r in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _extract_failure_reasons(outcomes: list[dict]) -> list[str]:
    """Extract common failure reason keywords from failed outcomes."""
    failure_texts = []
    for o in outcomes:
        if o["success"]:
            continue
        parts = []
        if o.get("gap_analysis"):
            parts.append(o["gap_analysis"])
        if o.get("notes"):
            parts.append(o["notes"])
        if parts:
            failure_texts.append(" ".join(parts))

    if not failure_texts:
        return []

    # Keyword pattern matching for known failure categories
    combined = " ".join(failure_texts).lower()
    reasons = []
    patterns = {
        "超时": ["timeout", "超时", "too_long", "slow"],
        "格式错误": ["format", "格式", "wording_differs", "structure"],
        "依赖缺失": ["missing", "import", "依赖", "dependency", "incomplete"],
        "文件未找到": ["not_found", "file", "文件", "path", "路径"],
        "未执行": ["没执行", "没写代码", "只输出意图", "意图", "no_result", "empty"],
        "输出截断": ["truncat", "cut_off", "partial", "截断"],
        "逻辑错误": ["wrong", "incorrect", "error", "错误", "wrong_logic"],
        "重复冗余": ["repeat", "redundan", "duplicat", "verbose"],
    }

    for reason, keywords in patterns.items():
        if any(kw in combined for kw in keywords):
            reasons.append(reason)

    return reasons


def _count_template_constraints(task_type: str) -> int:
    """Count constraints in the YAML template for a task_type."""
    try:
        import yaml
        yaml_path = TEMPLATES_DIR / f"{task_type}.yaml"
        if not yaml_path.exists():
            return 0
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        constraints = data.get("constraints", [])
        return len(constraints) if isinstance(constraints, list) else 0
    except Exception:
        return 0


def analyze_template_effectiveness(task_type: str) -> dict:
    """Analyze template effectiveness for a given task_type.

    Merges data from agent-stats.json (aggregated counts) and
    memory.db task_outcomes (detailed per-task records).

    Returns:
        dict with keys: task_type, total, success, failure, success_rate,
                        common_failures, suggestions
    """
    # Source 1: agent-stats.json
    stats_data = _load_stats()
    by_type = stats_data.get("stats", {}).get("by_task_type", {})
    type_stats = by_type.get(task_type, {})
    stats_total = type_stats.get("total", 0)
    stats_success = type_stats.get("success", 0)
    stats_fail = type_stats.get("fail", 0)

    # Source 2: memory.db task_outcomes
    db_outcomes = _get_db_outcomes(task_type)
    db_total = len(db_outcomes)
    db_success = sum(1 for o in db_outcomes if o["success"])
    db_fail = db_total - db_success

    # Merge: use the larger total (they may overlap, take max to avoid double-counting)
    total = max(stats_total, db_total)
    success = max(stats_success, db_success)
    failure = max(stats_fail, db_fail)

    # Recalculate to ensure consistency
    if success + failure > total:
        total = success + failure

    success_rate = round(success / total, 4) if total > 0 else 0.0

    # Extract failure reasons from DB outcomes
    common_failures = _extract_failure_reasons(db_outcomes)

    # Generate suggestions
    suggestions = suggest_improvements(task_type, _analysis={
        "success_rate": success_rate,
        "total": total,
        "common_failures": common_failures,
    })

    return {
        "task_type": task_type,
        "total": total,
        "success": success,
        "failure": failure,
        "success_rate": success_rate,
        "common_failures": common_failures,
        "suggestions": suggestions,
    }


def suggest_improvements(task_type: str, _analysis: dict | None = None) -> list[str]:
    """Generate template improvement suggestions based on analysis.

    Args:
        task_type: the task type to analyze
        _analysis: optional pre-computed analysis dict (internal use).
                   If None, runs analyze internally (without recursion).

    Returns:
        list of suggestion strings
    """
    if _analysis is None:
        # Compute analysis data without recursion
        stats_data = _load_stats()
        by_type = stats_data.get("stats", {}).get("by_task_type", {})
        type_stats = by_type.get(task_type, {})
        stats_total = type_stats.get("total", 0)
        stats_success = type_stats.get("success", 0)
        stats_fail = type_stats.get("fail", 0)

        db_outcomes = _get_db_outcomes(task_type)
        db_total = len(db_outcomes)
        db_success = sum(1 for o in db_outcomes if o["success"])
        db_fail = db_total - db_success

        total = max(stats_total, db_total)
        success = max(stats_success, db_success)
        failure = max(stats_fail, db_fail)
        if success + failure > total:
            total = success + failure

        success_rate = round(success / total, 4) if total > 0 else 0.0
        common_failures = _extract_failure_reasons(db_outcomes)

        _analysis = {
            "success_rate": success_rate,
            "total": total,
            "common_failures": common_failures,
        }

    success_rate = _analysis["success_rate"]
    total = _analysis["total"]
    common_failures = _analysis["common_failures"]

    suggestions = []

    if total == 0:
        suggestions.append("无历史数据，建议先积累任务执行记录")
        return suggestions

    # Rule-based suggestions
    if success_rate < 0.7:
        suggestions.append("考虑拆分为更小的子任务")

    if "超时" in common_failures:
        suggestions.append("增加约束：任务必须在5分钟内完成")

    if "格式错误" in common_failures:
        suggestions.append("增加约束：明确输出格式和示例")

    if "依赖缺失" in common_failures:
        suggestions.append("增加约束：列出所有需要的依赖")

    if "文件未找到" in common_failures:
        suggestions.append("增加约束：验证文件路径存在")

    if "未执行" in common_failures:
        suggestions.append("在指令开头添加强制执行提示，如'你必须立即开始写代码'")

    if "输出截断" in common_failures:
        suggestions.append("增加约束：输出必须完整，不要截断")

    if "逻辑错误" in common_failures:
        suggestions.append("增加约束：完成后自行验证逻辑正确性")

    if "重复冗余" in common_failures:
        suggestions.append("增加约束：输出应简洁，避免重复")

    # High success + many constraints → consider simplifying
    constraint_count = _count_template_constraints(task_type)
    if success_rate > 0.95 and constraint_count > 5:
        suggestions.append("考虑精简约束，当前约束可能过多")

    # No failures detected but success rate not great
    if not common_failures and success_rate < 0.9 and total >= 3:
        suggestions.append("失败记录缺少详细原因，建议在记录时补充 notes 字段")

    return suggestions


def evolve_report() -> str:
    """Generate a comprehensive evolution report for all task types.

    Returns:
        Markdown-formatted report string.
    """
    # Collect all known task types from both sources
    stats_data = _load_stats()
    by_type = stats_data.get("stats", {}).get("by_task_type", {})
    all_types = set(by_type.keys())

    db_types = _get_all_task_types_from_db()
    all_types.update(db_types)

    if not all_types:
        return "# 模板进化报告\n\n暂无任务数据。"

    lines = ["# 模板进化报告\n"]

    # Summary table
    lines.append("## 总览\n")
    lines.append("| 任务类型 | 总数 | 成功 | 失败 | 成功率 |")
    lines.append("|----------|------|------|------|--------|")

    analyses = {}
    for task_type in sorted(all_types):
        a = analyze_template_effectiveness(task_type)
        analyses[task_type] = a
        rate_str = f"{a['success_rate']:.0%}" if a["total"] > 0 else "N/A"
        lines.append(f"| {a['task_type']} | {a['total']} | {a['success']} | {a['failure']} | {rate_str} |")

    lines.append("")

    # Per-type details
    lines.append("## 详细分析\n")
    for task_type in sorted(all_types):
        a = analyses[task_type]
        lines.append(f"### {task_type}\n")

        if a["total"] == 0:
            lines.append("暂无执行记录。\n")
            continue

        rate_str = f"{a['success_rate']:.0%}"
        lines.append(f"- 执行次数: {a['total']} (成功 {a['success']}, 失败 {a['failure']})")
        lines.append(f"- 成功率: {rate_str}")

        if a["common_failures"]:
            lines.append(f"- 常见失败原因: {', '.join(a['common_failures'])}")

        if a["suggestions"]:
            lines.append("\n**改进建议:**\n")
            for i, s in enumerate(a["suggestions"], 1):
                lines.append(f"{i}. {s}")

        lines.append("")

    return "\n".join(lines)


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 template_evolution.py analyze <task_type>")
        print("  python3 template_evolution.py suggest <task_type>")
        print("  python3 template_evolution.py report")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "analyze":
        if len(sys.argv) < 3:
            print("Usage: python3 template_evolution.py analyze <task_type>")
            sys.exit(1)
        result = analyze_template_effectiveness(sys.argv[2])
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif cmd == "suggest":
        if len(sys.argv) < 3:
            print("Usage: python3 template_evolution.py suggest <task_type>")
            sys.exit(1)
        suggestions = suggest_improvements(sys.argv[2])
        if not suggestions:
            print("无改进建议（数据不足或表现良好）")
        else:
            for i, s in enumerate(suggestions, 1):
                print(f"  {i}. {s}")

    elif cmd == "report":
        print(evolve_report())

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
