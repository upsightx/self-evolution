#!/usr/bin/env python3
"""
Feedback Loop Automation Module
Records task outcomes, analyzes failure patterns, and generates improvement suggestions.
"""

from __future__ import annotations

import sqlite3
import os
import sys
import re
import argparse
import tempfile
from collections import Counter
from pathlib import Path

from db_common import DB_PATH

DEFAULT_DB = str(DB_PATH)

SCHEMA = """
CREATE TABLE IF NOT EXISTS task_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    task_type TEXT NOT NULL,
    model TEXT,
    expected TEXT,
    actual TEXT,
    success INTEGER NOT NULL,
    gap_analysis TEXT,
    notes TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);
"""


def _get_conn(db_path: str | None = None) -> sqlite3.Connection | None:
    """Get database connection. Returns None on failure."""
    conn = None
    try:
        conn = sqlite3.connect(db_path or DEFAULT_DB)
        conn.row_factory = sqlite3.Row
        conn.execute(SCHEMA)
        conn.commit()
        return conn
    except sqlite3.Error as e:
        print(f"[ERROR] Database connection failed: {e}", file=sys.stderr)
        if conn:
            conn.close()
        return None


def _compute_gap(expected: str | None, actual: str | None) -> str | None:
    """Compute a simple gap analysis between expected and actual."""
    if not expected and not actual:
        return None
    if not expected:
        return f"no_expectation; actual={actual}"
    if not actual:
        return f"no_result; expected={expected}"
    if expected.strip() == actual.strip():
        return "match"
    # Extract key differences
    exp_words = set(expected.lower().split())
    act_words = set(actual.lower().split())
    missing = exp_words - act_words
    extra = act_words - exp_words
    parts = []
    if missing:
        parts.append(f"missing: {' '.join(sorted(missing)[:10])}")
    if extra:
        parts.append(f"unexpected: {' '.join(sorted(extra)[:10])}")
    if not parts:
        parts.append("wording_differs")
    return "; ".join(parts)


def record_task_outcome(
    task_id: str | None,
    task_type: str,
    model: str | None,
    expected: str | None,
    actual: str | None,
    success: bool,
    notes: str | None = None,
    db_path: str | None = None,
) -> int | None:
    """Record a task outcome. Returns the row id or None on failure."""
    conn = _get_conn(db_path)
    if conn is None:
        return None
    
    try:
        gap = _compute_gap(expected, actual)
        cur = conn.execute(
            "INSERT INTO task_outcomes (task_id, task_type, model, expected, actual, success, gap_analysis, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, task_type, model, expected, actual, int(success), gap, notes),
        )
        conn.commit()
        row_id = cur.lastrowid
        return row_id
    except sqlite3.Error as e:
        print(f"[ERROR] Failed to record task outcome: {e}", file=sys.stderr)
        return None
    finally:
        conn.close()


def analyze_patterns(min_samples: int = 5, db_path: str | None = None) -> list[dict]:
    """Analyze failure patterns. Returns groups with success rate < 70%."""
    conn = _get_conn(db_path)
    if conn is None:
        return []
    
    try:
        rows = conn.execute(
            "SELECT task_type, model, "
            "COUNT(*) as total, SUM(success) as wins, "
            "GROUP_CONCAT(gap_analysis, '|||') as gaps "
            "FROM task_outcomes "
            "GROUP BY task_type, model "
            "HAVING total >= ?",
            (min_samples,),
        ).fetchall()
    except sqlite3.Error as e:
        print(f"[ERROR] Failed to analyze patterns: {e}", file=sys.stderr)
        return []
    finally:
        conn.close()

    results = []
    for r in rows:
        total = r["total"]
        wins = r["wins"] or 0
        success_rate = wins / total
        if success_rate >= 0.7:
            continue

        # Extract keyword patterns from gap_analysis
        gaps_raw = r["gaps"] or ""
        gap_list = [g.strip() for g in gaps_raw.split("|||") if g.strip() and g.strip() != "match"]
        # Count words across all gaps (skip stopwords)
        stopwords = {"the", "a", "an", "is", "was", "to", "of", "in", "for", "and", "or", "no", "not"}
        word_counter: Counter = Counter()
        for gap in gap_list:
            tokens = re.findall(r"[a-z_\u4e00-\u9fff]+", gap.lower())
            for t in tokens:
                if t not in stopwords and len(t) > 1:
                    word_counter[t] += 1

        # Top patterns: words appearing in >= 30% of gaps
        threshold = max(2, len(gap_list) * 0.3)
        patterns = [w for w, c in word_counter.most_common(10) if c >= threshold]
        pattern_str = ", ".join(patterns) if patterns else "mixed_failures"

        # Recent gaps (last 5)
        recent = gap_list[-5:] if gap_list else []

        results.append({
            "pattern": pattern_str,
            "task_type": r["task_type"],
            "model": r["model"],
            "failure_rate": round(1 - success_rate, 3),
            "sample_count": total,
            "recent_gaps": recent,
        })

    results.sort(key=lambda x: x["failure_rate"], reverse=True)
    return results


def generate_template_improvements(task_type: str, db_path: str | None = None) -> list[str]:
    """Generate improvement suggestions based on historical failures for a task type."""
    conn = _get_conn(db_path)
    if conn is None:
        return []
    
    try:
        rows = conn.execute(
            "SELECT gap_analysis, notes FROM task_outcomes "
            "WHERE task_type = ? AND success = 0 ORDER BY timestamp DESC LIMIT 100",
            (task_type,),
        ).fetchall()
    except sqlite3.Error as e:
        print(f"[ERROR] Failed to generate improvements for task type '{task_type}': {e}", file=sys.stderr)
        return []
    finally:
        conn.close()

    if not rows:
        return []

    # Collect all text from gaps and notes
    all_text = []
    for r in rows:
        if r["gap_analysis"]:
            all_text.append(r["gap_analysis"])
        if r["notes"]:
            all_text.append(r["notes"])

    combined = " ".join(all_text).lower()

    # Rule-based pattern detection → suggestions
    suggestions = []
    keyword_rules = [
        (["missing", "incomplete", "not_found"], "Add explicit checklist of required output elements in the prompt"),
        (["format", "formatting", "structure", "wording_differs"], "Specify exact output format with examples in the template"),
        (["timeout", "slow", "too_long"], "Add time/length constraints and break into smaller subtasks"),
        (["wrong", "incorrect", "error"], "Add validation step: ask the model to verify its answer before finalizing"),
        (["hallucin", "fabricat", "invent", "made_up"], "Add grounding instruction: only use provided context, cite sources"),
        (["truncat", "cut_off", "partial"], "Request complete output explicitly; add 'do not truncate' instruction"),
        (["repeat", "redundan", "duplicat"], "Add deduplication instruction and ask for concise output"),
        (["no_result", "empty", "blank"], "Provide fallback instructions for when no data is available"),
        (["unexpected", "extra", "irrelevant"], "Add negative constraints: specify what NOT to include"),
        (["no_expectation"], "Define clear success criteria before dispatching the task"),
    ]

    for keywords, suggestion in keyword_rules:
        if any(kw in combined for kw in keywords):
            suggestions.append(suggestion)

    # Count failures to add general suggestions
    failure_count = len(rows)
    if failure_count >= 10:
        suggestions.append(f"High failure count ({failure_count}): consider decomposing '{task_type}' into simpler subtasks")
    if failure_count >= 5:
        suggestions.append(f"Consider using a more capable model for '{task_type}' tasks")

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    return unique


def get_task_history(
    task_type: str | None = None,
    model: str | None = None,
    limit: int = 50,
    db_path: str | None = None,
) -> list[dict]:
    """Query task outcome history with optional filters."""
    conn = _get_conn(db_path)
    if conn is None:
        return []
    
    try:
        clauses = []
        params: list = []
        if task_type:
            clauses.append("task_type = ?")
            params.append(task_type)
        if model:
            clauses.append("model = ?")
            params.append(model)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM task_outcomes{where} ORDER BY timestamp DESC LIMIT ?", params
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as e:
        print(f"[ERROR] Failed to get task history: {e}", file=sys.stderr)
        return []
    finally:
        conn.close()


# ─── Template Evolution (merged from template_evolution.py) ────────────────────

def _extract_failure_reasons(outcomes: list[dict]) -> list[str]:
    """Extract common failure reason keywords from failed outcomes."""
    failure_texts = []
    for o in outcomes:
        if o.get("success"):
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

    combined = " ".join(failure_texts).lower()
    reasons = []
    reason_patterns = {
        "超时": ["timeout", "超时", "too_long", "slow"],
        "格式错误": ["format", "格式", "wording_differs", "structure"],
        "依赖缺失": ["missing", "import", "依赖", "dependency", "incomplete"],
        "文件未找到": ["not_found", "file", "文件", "path", "路径"],
        "未执行": ["没执行", "没写代码", "只输出意图", "意图", "no_result", "empty"],
        "输出截断": ["truncat", "cut_off", "partial", "截断"],
        "逻辑错误": ["wrong", "incorrect", "error", "错误", "wrong_logic"],
        "重复冗余": ["repeat", "redundan", "duplicat", "verbose"],
    }
    for reason, keywords in reason_patterns.items():
        if any(kw in combined for kw in keywords):
            reasons.append(reason)
    return reasons


def analyze_template_effectiveness(task_type: str, db_path: str | None = None) -> dict:
    """Analyze template effectiveness for a given task_type.

    Merges data from task_outcomes table.

    Returns:
        dict with keys: task_type, total, success, failure, success_rate,
                        common_failures, suggestions
    """
    conn = _get_conn(db_path)
    if conn is None:
        return {"task_type": task_type, "total": 0, "success": 0, "failure": 0,
                "success_rate": 0.0, "common_failures": [], "suggestions": []}

    try:
        rows = conn.execute(
            "SELECT success, gap_analysis, notes FROM task_outcomes WHERE task_type = ? ORDER BY timestamp DESC",
            (task_type,),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()

    outcomes = [dict(r) for r in rows]
    total = len(outcomes)
    success = sum(1 for o in outcomes if o["success"])
    failure = total - success
    success_rate = round(success / total, 4) if total > 0 else 0.0
    common_failures = _extract_failure_reasons(outcomes)

    suggestions = []
    if total == 0:
        suggestions.append("无历史数据，建议先积累任务执行记录")
    else:
        if success_rate < 0.7:
            suggestions.append("考虑拆分为更小的子任务")
        if "超时" in common_failures:
            suggestions.append("增加约束：任务必须在5分钟内完成")
        if "格式错误" in common_failures:
            suggestions.append("增加约束：明确输出格式和示例")
        if "依赖缺失" in common_failures:
            suggestions.append("增加约束：列出所有需要的依赖")
        if "未执行" in common_failures:
            suggestions.append("在指令开头添加强制执行提示")
        if "输出截断" in common_failures:
            suggestions.append("增加约束：输出必须完整，不要截断")
        if "逻辑错误" in common_failures:
            suggestions.append("增加约束：完成后自行验证逻辑正确性")
        if not common_failures and success_rate < 0.9 and total >= 3:
            suggestions.append("失败记录缺少详细原因，建议补充 notes 字段")

    return {
        "task_type": task_type,
        "total": total,
        "success": success,
        "failure": failure,
        "success_rate": success_rate,
        "common_failures": common_failures,
        "suggestions": suggestions,
    }


def evolve_report(db_path: str | None = None) -> str:
    """Generate a comprehensive evolution report for all task types."""
    conn = _get_conn(db_path)
    if conn is None:
        return "# 模板进化报告\n\n暂无任务数据。"

    try:
        rows = conn.execute("SELECT DISTINCT task_type FROM task_outcomes").fetchall()
        all_types = [r["task_type"] for r in rows]
    except sqlite3.Error:
        all_types = []
    finally:
        conn.close()

    if not all_types:
        return "# 模板进化报告\n\n暂无任务数据。"

    lines = ["# 模板进化报告\n"]
    lines.append("## 总览\n")
    lines.append("| 任务类型 | 总数 | 成功 | 失败 | 成功率 |")
    lines.append("|----------|------|------|------|--------|")

    analyses = {}
    for task_type in sorted(all_types):
        a = analyze_template_effectiveness(task_type, db_path=db_path)
        analyses[task_type] = a
        rate_str = f"{a['success_rate']:.0%}" if a["total"] > 0 else "N/A"
        lines.append(f"| {a['task_type']} | {a['total']} | {a['success']} | {a['failure']} | {rate_str} |")

    lines.append("")
    lines.append("## 详细分析\n")
    for task_type in sorted(all_types):
        a = analyses[task_type]
        lines.append(f"### {task_type}\n")
        if a["total"] == 0:
            lines.append("暂无执行记录。\n")
            continue
        lines.append(f"- 执行次数: {a['total']} (成功 {a['success']}, 失败 {a['failure']})")
        lines.append(f"- 成功率: {a['success_rate']:.0%}")
        if a["common_failures"]:
            lines.append(f"- 常见失败原因: {', '.join(a['common_failures'])}")
        if a["suggestions"]:
            lines.append("\n**改进建议:**\n")
            for i, s in enumerate(a["suggestions"], 1):
                lines.append(f"{i}. {s}")
        lines.append("")

    return "\n".join(lines)


# ─── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    parser = argparse.ArgumentParser(description="Feedback Loop CLI")
    sub = parser.add_subparsers(dest="command")

    # record
    p_rec = sub.add_parser("record")
    p_rec.add_argument("task_type")
    p_rec.add_argument("model")
    p_rec.add_argument("success", type=int, choices=[0, 1])
    p_rec.add_argument("--task-id", default=None)
    p_rec.add_argument("--expected", default=None)
    p_rec.add_argument("--actual", default=None)
    p_rec.add_argument("--notes", default=None)

    # analyze
    sub.add_parser("analyze")

    # improvements
    p_imp = sub.add_parser("improvements")
    p_imp.add_argument("task_type")

    # history
    p_hist = sub.add_parser("history")
    p_hist.add_argument("--type", default=None)
    p_hist.add_argument("--model", default=None)
    p_hist.add_argument("--limit", type=int, default=20)

    # evolve (merged from template_evolution)
    p_evolve_analyze = sub.add_parser("evolve-analyze")
    p_evolve_analyze.add_argument("task_type")

    sub.add_parser("evolve-report")

    args = parser.parse_args()

    if args.command == "record":
        rid = record_task_outcome(
            task_id=args.task_id,
            task_type=args.task_type,
            model=args.model,
            expected=args.expected,
            actual=args.actual,
            success=bool(args.success),
            notes=args.notes,
        )
        if rid is None:
            print("[FAIL] Failed to record outcome", file=sys.stderr)
            sys.exit(1)
        print(f"Recorded outcome #{rid}")

    elif args.command == "analyze":
        patterns = analyze_patterns()
        if not patterns:
            print("No problematic patterns found (all groups >= 70% success or < 5 samples)")
        for p in patterns:
            print(f"\n[{p['task_type']} / {p['model']}] failure_rate={p['failure_rate']} samples={p['sample_count']}")
            print(f"  pattern: {p['pattern']}")
            for g in p["recent_gaps"]:
                print(f"  - {g}")

    elif args.command == "improvements":
        imps = generate_template_improvements(args.task_type)
        if not imps:
            print(f"No improvements found for '{args.task_type}' (no failure records)")
        for i, s in enumerate(imps, 1):
            print(f"  {i}. {s}")

    elif args.command == "history":
        rows = get_task_history(task_type=args.type, model=args.model, limit=args.limit)
        if not rows:
            print("No records found")
        for r in rows:
            status = "✓" if r["success"] else "✗"
            print(f"  {status} [{r['timestamp']}] {r['task_type']}/{r['model']} gap={r['gap_analysis'] or '-'}")

    elif args.command == "evolve-analyze":
        result = analyze_template_effectiveness(args.task_type)
        import json
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "evolve-report":
        print(evolve_report())

    else:
        parser.print_help()


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        print("Tests moved to tests/test_feedback_loop.py — run: python3 tests/test_feedback_loop.py")
    else:
        _cli()
