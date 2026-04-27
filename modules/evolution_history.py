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
import sys
from datetime import datetime
from pathlib import Path

from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path, module_dir, module_workspace

_workspace = ensure_workspace_on_path()
_modules = module_dir()
ensure_xmemory_on_path()

from db_common import get_db
from causal_validator import get_verification_report
from controlled_loop_router import ACTIVE_STATUSES, build_action_panel
from evidence_validator import evaluate_many
from proposal_lifecycle_manager import get_governance_actions, list_proposals


def get_event_stats() -> dict:
    """Get event statistics from evolution_runtime.
    
    Delegates to evolution_runtime for unified event tracking.
    """
    try:
        from evolution_runtime import get_event_summary
        summary = get_event_summary(days=30)
        return {
            "total_events": summary["total"],
            "unprocessed": 0,
            "by_type": summary["by_type"],
        }
    except ImportError:
        return {"total_events": 0, "unprocessed": 0, "by_type": {}}

WORKSPACE = module_workspace()


def get_validation_action_summary(limit: int = 50) -> dict:
    """Summarize proposal validation + triage actions across evidence/causal/human tracks."""
    proposals = []
    for status in sorted(ACTIVE_STATUSES):
        proposals.extend(list_proposals(status=status, limit=limit))
    proposals = proposals[:limit]
    panel = build_action_panel(proposals, limit=limit)
    verdicts = evaluate_many(proposals, collect=True, run_tests=False)
    governance = get_governance_actions(limit=limit)
    by_verdict: dict[str, int] = {}
    by_track: dict[str, int] = {}
    for verdict in verdicts:
        by_verdict[verdict["verdict"]] = by_verdict.get(verdict["verdict"], 0) + 1
        by_track[verdict["validation_track"]] = by_track.get(verdict["validation_track"], 0) + 1

    return {
        "total": len(proposals),
        "validation_total": len(proposals),
        "governance_total": governance.get("active_total", 0),
        "by_action": panel.get("by_action", {}),
        "by_risk": panel.get("by_risk", {}),
        "human_required": len(panel.get("human_required", [])),
        "by_verdict": by_verdict,
        "by_track": by_track,
        "triage_delete": governance.get("delete", []),
        "triage_keep": governance.get("keep", []),
        "triage_fuse": governance.get("fuse", []),
        "next_items": panel.get("next_items", [])[:10],
    }


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
    lines.append(f"| ✅ 有效 | {vr.get('effective', 0)} |")
    lines.append(f"| ❌ 无效 | {vr.get('ineffective', 0)} |")
    lines.append(f"| ❓ 不确定 | {vr.get('uncertain', 0)} |")
    lines.append(f"| ⏳ 因果样本等待 | {vr.get('pending', 0)} |")
    lines.append(f"| 🟡 待验证 | {vr.get('total_changes', 0) - vr.get('effective', 0) - vr.get('ineffective', 0) - vr.get('uncertain', 0) - vr.get('pending', 0)} |")
    lines.append("")

    vas = get_validation_action_summary()
    lines.append("### 验证行动面板")
    lines.append("")
    if vas.get("error"):
        lines.append(f"行动面板生成失败: {vas['error']}")
    else:
        lines.append(f"- 验证活跃提案: {vas['validation_total']}")
        lines.append(f"- 治理活跃提案: {vas['governance_total']}")
        lines.append(f"- 需要人工确认: {vas['human_required']}")
        lines.append(f"- 验证轨道: {vas['by_track']}")
        lines.append(f"- 证据结论: {vas['by_verdict']}")
        lines.append(f"- 下一步动作: {vas['by_action']}")
        lines.append(f"- 风险分布: {vas['by_risk']}")
        lines.append(f"- Triage 删除: {vas.get('triage_delete', [])}")
        lines.append(f"- Triage 保留: {vas.get('triage_keep', [])}")
        lines.append(f"- Triage 融合: {len(vas.get('triage_fuse', []))}")
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
    if vr.get("changes"):
        for c in vr.get("changes", [])[:10]:
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
