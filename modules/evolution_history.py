#!/usr/bin/env python3
"""
Evolution History Visualizer — 进化历史报告生成器。

职责：
- 生成进化历史 Markdown 报告
- 包含趋势图（ASCII）、统计表、变更详情

用法：
    python3 evolution_history.py report
    python3 evolution_history.py report --format markdown
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from db_common import get_db
from causal_validator import get_verification_report


def get_event_stats() -> dict:
    """Get event statistics from evolution_runtime.
    
    Delegates to evolution_runtime for unified event tracking.
    Falls back to evolution_changes table if runtime unavailable.
    """
    try:
        from evolution_runtime import get_event_summary
        summary = get_event_summary(days=30)
        return {
            "total_events": summary["total"],
            "unprocessed": 0,  # runtime tracks all as processed
            "by_type": summary["by_type"],
        }
    except ImportError:
        pass

    # Fallback: derive from evolution_changes
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM evolution_changes").fetchone()[0]
        unprocessed = db.execute(
            "SELECT COUNT(*) FROM evolution_changes WHERE status = 'pending'"
        ).fetchone()[0]
        by_type = {}
        for r in db.execute(
            "SELECT task_type, COUNT(*) as c FROM evolution_changes GROUP BY task_type ORDER BY c DESC"
        ).fetchall():
            by_type[r["task_type"]] = r["c"]
        return {
            "total_events": total,
            "unprocessed": unprocessed,
            "by_type": by_type,
        }
    except Exception:
        return {"total_events": 0, "unprocessed": 0, "by_type": {}}
    finally:
        db.close()

WORKSPACE = Path(__file__).parent.parent


def _get_task_outcome_trend(days: int = 30) -> list[dict]:
    """Get daily success rate trend."""
    db = get_db()
    try:
        rows = db.execute(
            """SELECT DATE(created_at) as day,
                      COUNT(*) as total,
                      SUM(success) as wins
               FROM task_outcomes
               WHERE created_at >= datetime('now', ?)
               GROUP BY DATE(created_at)
               ORDER BY day ASC""",
            (f"-{days} days",),
        ).fetchall()

        trend = []
        for r in rows:
            rate = (r["wins"] / r["total"] * 100) if r["total"] > 0 else 0
            trend.append({
                "day": r["day"],
                "total": r["total"],
                "wins": r["wins"],
                "success_rate": round(rate, 1),
            })
        return trend
    finally:
        db.close()


def _ascii_bar_chart(values: list[float], labels: list[str], width: int = 40) -> str:
    """Generate a simple ASCII bar chart."""
    if not values:
        return "  (no data)"

    max_val = max(values) if values else 1
    lines = []

    for val, label in zip(values, labels):
        bar_len = int(val / max_val * width) if max_val > 0 else 0
        bar = "█" * bar_len + "░" * (width - bar_len)
        lines.append(f"  {label:>10s} |{bar}| {val:.0%}")

    return "\n".join(lines)


def generate_report(days: int = 30, output_path: str | None = None) -> str:
    """Generate evolution history report.

    Args:
        days: Lookback window
        output_path: If provided, save report to this file

    Returns:
        Report content as string
    """
    lines = [
        "# 进化历史报告",
        f"",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"统计周期: 最近 {days} 天",
        f"",
    ]

    # Section 1: Task Outcome Trend
    lines.append("## 📈 任务成功率趋势")
    lines.append("")
    trend = _get_task_outcome_trend(days)
    if trend:
        # Show last 7 days
        recent = trend[-7:]
        values = [t["success_rate"] / 100 for t in recent]
        labels = [t["day"][5:] for t in recent]  # MM-DD
        lines.append("```")
        lines.append(_ascii_bar_chart(values, labels))
        lines.append("```")
        lines.append("")
        lines.append(f"最近一天成功率: {trend[-1]['success_rate']:.1f}% (n={trend[-1]['total']})")
    else:
        lines.append("暂无任务执行数据")
    lines.append("")

    # Section 2: Evolution Changes
    lines.append("## 🔬 进化变更统计")
    lines.append("")
    vr = get_verification_report()
    lines.append(f"| 状态 | 数量 |")
    lines.append(f"|------|------|")
    lines.append(f"| ✅ 有效 | {vr['effective']} |")
    lines.append(f"| ❌ 无效 | {vr['ineffective']} |")
    lines.append(f"| ❓ 不确定 | {vr['uncertain']} |")
    lines.append(f"| ⏳ 等待样本 | {vr.get('pending', 0)} |")
    lines.append(f"| 🟡 待验证 | {vr['total_changes'] - vr['effective'] - vr['ineffective'] - vr['uncertain'] - vr.get('pending', 0)} |")
    lines.append("")

    # Section 3: Event Stats
    lines.append("## 📨 事件统计")
    lines.append("")
    es = get_event_stats()
    lines.append(f"总事件数: {es['total_events']}")
    lines.append(f"未处理: {es['unprocessed']}")
    lines.append("")
    if es["by_type"]:
        lines.append("| 事件类型 | 数量 |")
        lines.append("|----------|------|")
        for t, c in list(es["by_type"].items())[:10]:
            lines.append(f"| {t} | {c} |")
    lines.append("")

    # Section 4: Capability Profile
    lines.append("## 📉 能力画像")
    lines.append("")
    try:
        from capability_model import get_profile
        profile = get_profile()
        lines.append(f"整体评分: {profile['overall_score']}/100")
        lines.append(f"能力维度: {profile['total_capabilities']}")
        lines.append("")
        if profile["strengths"]:
            lines.append("优势:")
            for s in profile["strengths"]:
                lines.append(f"- ✅ {s['name']}: {s['score']} (n={s['samples']})")
        if profile["weaknesses"]:
            lines.append("")
            lines.append("短板:")
            for w in profile["weaknesses"]:
                lines.append(f"- ⚠️ {w['name']}: {w['score']} (n={w['samples']})")
    except Exception as e:
        lines.append(f"能力画像获取失败: {e}")
    lines.append("")

    # Section 5: Recent Changes Detail
    lines.append("## 📋 最近变更详情")
    lines.append("")
    if vr["changes"]:
        for c in vr["changes"][:10]:
            verdict = c.get("verdict", "pending")
            icon = {"effective": "✅", "ineffective": "❌", "uncertain": "❓", "pending": "⏳"}.get(verdict, "🟡")
            lines.append(f"### {icon} #{c['change_id']}")
            lines.append(f"- 任务类型: {c['task_type']}")
            lines.append(f"- 建议: {c['suggestion'][:80]}")
            lines.append(f"- 状态: {verdict}")
            lines.append(f"- 应用时间: {c['applied_at']}")
            if c.get('verified_at'):
                lines.append(f"- 验证时间: {c['verified_at']}")
            lines.append("")
    else:
        lines.append("暂无变更记录")
    lines.append("")

    report = "\n".join(lines)

    if output_path:
        Path(output_path).write_text(report, encoding="utf-8")
        print(f"Report saved to: {output_path}")

    return report


# ============ CLI ============

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Evolution History Report")
    parser.add_argument("--days", type=int, default=30, help="Lookback window")
    parser.add_argument("--output", default=None, help="Output file path")
    args = parser.parse_args()

    report = generate_report(days=args.days, output_path=args.output)

    if not args.output:
        print(report)


if __name__ == "__main__":
    _cli()
