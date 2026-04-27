#!/usr/bin/env python3
"""
Capability Detector — 主动能力探测器。

替代旧的 feedback_loop.py（被动等失败积累）。

核心理念：
- 发现缺口 → 立即行动 → 找工具/写代码 → 测试验证 → 固化能力
- 同时分析成功模式和失败模式
- 不等积累，一次失败就记录，两次就报警，三次就创建实验

职责：
1. 实时记录任务结果（委托 task_outcome_hook）
2. 检测能力缺口（0% 成功的任务类型 = 缺失能力）
3. 检测衰退（曾经好用但最近变差的组合）
4. 识别优势（稳定高成功率的组合，保护不要乱改）
5. 主动触发能力建设（通过 orchestrator 创建实验）
"""
from __future__ import annotations

import sys
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path, module_dir, module_workspace

_workspace = ensure_workspace_on_path()
_modules = module_dir()
ensure_xmemory_on_path()

from db_common import get_db


# ============ Core Detection ============

def detect_all() -> dict:
    """Run all detections and return a complete capability picture.

    Returns:
        {
            "missing": [...],      # 0% success, capability doesn't exist
            "degrading": [...],    # was good, getting worse
            "struggling": [...],   # below 50% success
            "reliable": [...],     # above 80% success
            "strengths": [...],    # above 95% success with 5+ samples
            "recommendations": [...],
            "timestamp": str,
        }
    """
    db = get_db()
    try:
        rows = db.execute("""
            SELECT task_type, model,
                   COUNT(*) as total,
                   SUM(success) as wins,
                   MAX(created_at) as last_seen
            FROM task_outcomes
            GROUP BY task_type, model
            ORDER BY total DESC
        """).fetchall()
    except sqlite3.Error:
        return {"missing": [], "degrading": [], "struggling": [],
                "reliable": [], "strengths": [], "recommendations": [],
                "timestamp": datetime.now().isoformat()}
    finally:
        db.close()

    missing = []
    struggling = []
    reliable = []
    strengths = []
    recommendations = []

    for r in rows:
        total = r["total"]
        wins = r["wins"] or 0
        rate = wins / total if total > 0 else 0
        entry = {
            "task_type": r["task_type"],
            "model": r["model"],
            "success_rate": round(rate, 3),
            "total": total,
            "wins": wins,
            "last_seen": r["last_seen"],
        }

        if wins == 0 and total >= 2:
            missing.append(entry)
            recommendations.append(
                f"🚨 MISSING: {r['task_type']} has 0% success ({total} attempts) — need to build this capability"
            )
        elif rate < 0.5 and total >= 3:
            struggling.append(entry)
            recommendations.append(
                f"⚠️ STRUGGLING: {r['task_type']}/{r['model']} at {rate:.0%} — consider switching model or approach"
            )
        elif rate >= 0.95 and total >= 5:
            strengths.append(entry)
        elif rate >= 0.8 and total >= 3:
            reliable.append(entry)

    # Cross-reference: suggest model switches
    type_models = defaultdict(list)
    for r in rows:
        total = r["total"]
        wins = r["wins"] or 0
        rate = wins / total if total > 0 else 0
        type_models[r["task_type"]].append((r["model"], rate, total))

    for task_type, models in type_models.items():
        if len(models) >= 2:
            models.sort(key=lambda x: x[1], reverse=True)
            best_model, best_rate, _ = models[0]
            worst_model, worst_rate, _ = models[-1]
            if best_rate - worst_rate >= 0.3:
                recommendations.append(
                    f"💡 SWITCH: {task_type} — use {best_model} ({best_rate:.0%}) instead of {worst_model} ({worst_rate:.0%})"
                )

    # Detect degradation
    degrading = _detect_degradation()

    return {
        "missing": missing,
        "degrading": degrading,
        "struggling": struggling,
        "reliable": reliable,
        "strengths": strengths,
        "recommendations": recommendations,
        "timestamp": datetime.now().isoformat(),
    }


def _detect_degradation(window_days: int = 7) -> list[dict]:
    """Detect capabilities that were good but are getting worse.

    Compares recent window vs older history.
    """
    db = get_db()
    cutoff = (datetime.now() - timedelta(days=window_days)).isoformat()

    try:
        # Recent performance
        recent = db.execute("""
            SELECT task_type, model,
                   COUNT(*) as total, SUM(success) as wins
            FROM task_outcomes
            WHERE created_at >= ?
            GROUP BY task_type, model
            HAVING total >= 2
        """, (cutoff,)).fetchall()

        # Historical performance (before recent window)
        historical = db.execute("""
            SELECT task_type, model,
                   COUNT(*) as total, SUM(success) as wins
            FROM task_outcomes
            WHERE created_at < ?
            GROUP BY task_type, model
            HAVING total >= 3
        """, (cutoff,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        db.close()

    hist_map = {}
    for h in historical:
        key = (h["task_type"], h["model"])
        hist_map[key] = (h["wins"] or 0) / h["total"]

    degrading = []
    for r in recent:
        key = (r["task_type"], r["model"])
        recent_rate = (r["wins"] or 0) / r["total"]
        hist_rate = hist_map.get(key)

        if hist_rate is not None and hist_rate - recent_rate >= 0.2:
            degrading.append({
                "task_type": r["task_type"],
                "model": r["model"],
                "historical_rate": round(hist_rate, 3),
                "recent_rate": round(recent_rate, 3),
                "drop": round(hist_rate - recent_rate, 3),
            })

    return degrading


# ============ Quick Checks (for real-time use) ============

def is_capable(task_type: str, min_rate: float = 0.5, min_samples: int = 2) -> bool:
    """Quick check: can the system handle this task type?"""
    db = get_db()
    try:
        row = db.execute("""
            SELECT COUNT(*) as total, SUM(success) as wins
            FROM task_outcomes WHERE task_type = ?
        """, (task_type,)).fetchone()
        if not row or row["total"] < min_samples:
            return True  # Unknown = assume capable, will learn
        return (row["wins"] or 0) / row["total"] >= min_rate
    finally:
        db.close()


def best_model_for(task_type: str) -> str | None:
    """Get the best performing model for a task type."""
    db = get_db()
    try:
        rows = db.execute("""
            SELECT model, COUNT(*) as total, SUM(success) as wins
            FROM task_outcomes
            WHERE task_type = ?
            GROUP BY model
            HAVING total >= 2
            ORDER BY (CAST(wins AS REAL) / total) DESC, total DESC
            LIMIT 1
        """, (task_type,)).fetchall()
        return rows[0]["model"] if rows else None
    finally:
        db.close()


def get_capability_summary() -> dict:
    """Get a quick summary of all capabilities."""
    db = get_db()
    try:
        rows = db.execute("""
            SELECT task_type,
                   COUNT(*) as total,
                   SUM(success) as wins,
                   COUNT(DISTINCT model) as models_tried
            FROM task_outcomes
            GROUP BY task_type
            ORDER BY total DESC
        """).fetchall()

        capabilities = {}
        for r in rows:
            rate = (r["wins"] or 0) / r["total"] if r["total"] > 0 else 0
            status = "missing" if rate == 0 and r["total"] >= 2 else \
                     "struggling" if rate < 0.5 else \
                     "developing" if rate < 0.8 else \
                     "reliable" if rate < 0.95 else "strong"
            capabilities[r["task_type"]] = {
                "status": status,
                "success_rate": round(rate, 3),
                "total": r["total"],
                "models_tried": r["models_tried"],
            }
        return capabilities
    finally:
        db.close()


# ============ Action Triggers ============

def act_on_gaps() -> dict:
    """Detect gaps and immediately create experiments via orchestrator.

    This is the key difference from old feedback_loop:
    - Old: wait for 5+ failures, then suggest
    - New: detect gap, immediately create experiment

    Returns:
        {"experiments_created": int, "signals_sent": int, "details": list}
    """
    detection = detect_all()
    details = []
    experiments = 0
    signals = 0

    # Missing capabilities → immediate P0 experiment
    for m in detection["missing"]:
        try:
            from evolution_orchestrator import create_capability_experiment
            r = create_capability_experiment(
                capability_name=m["task_type"],
                description=f"{m['task_type']} has {m['total']} attempts, 0 successes",
                approach=f"Find tools or methods to handle {m['task_type']} tasks",
                priority="P0",
            )
            if r.get("success"):
                experiments += 1
                details.append(f"🧪 Created experiment for missing: {m['task_type']}")
        except Exception as e:
            details.append(f"⚠️ Failed to create experiment for {m['task_type']}: {e}")

    # Struggling capabilities → P1 signal
    for s in detection["struggling"]:
        try:
            from evolution_orchestrator import ingest_signal
            ingest_signal(
                signal_type="capability_struggling",
                source_id=f"{s['task_type']}_{s['model']}",
                task_type=s["task_type"],
                severity=1.0 - s["success_rate"],
            )
            signals += 1
        except Exception:
            pass

    # Degrading capabilities → P1 signal with high severity
    for d in detection["degrading"]:
        try:
            from evolution_orchestrator import ingest_signal
            ingest_signal(
                signal_type="capability_degrading",
                source_id=f"{d['task_type']}_{d['model']}",
                task_type=d["task_type"],
                severity=d["drop"],
            )
            signals += 1
            details.append(f"📉 Degradation detected: {d['task_type']}/{d['model']} dropped {d['drop']:.0%}")
        except Exception:
            pass

    return {
        "experiments_created": experiments,
        "signals_sent": signals,
        "details": details,
        "detection": detection,
    }


# ============ CLI ============

def _cli():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Capability Detector")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("detect", help="Run full detection")
    sub.add_parser("summary", help="Quick capability summary")
    sub.add_parser("act", help="Detect and act on gaps")

    p_check = sub.add_parser("check", help="Check if capable")
    p_check.add_argument("task_type")

    p_best = sub.add_parser("best-model", help="Best model for task type")
    p_best.add_argument("task_type")

    args = parser.parse_args()

    if args.command == "detect":
        d = detect_all()
        print(f"Missing:    {len(d['missing'])}")
        print(f"Degrading:  {len(d['degrading'])}")
        print(f"Struggling: {len(d['struggling'])}")
        print(f"Reliable:   {len(d['reliable'])}")
        print(f"Strengths:  {len(d['strengths'])}")
        if d["recommendations"]:
            print(f"\nRecommendations:")
            for r in d["recommendations"]:
                print(f"  {r}")

    elif args.command == "summary":
        caps = get_capability_summary()
        if not caps:
            print("No task data yet")
        for task, info in caps.items():
            icon = {"missing": "🚨", "struggling": "⚠️", "developing": "🔨",
                    "reliable": "✅", "strong": "💪"}.get(info["status"], "•")
            print(f"  {icon} {task}: {info['status']} ({info['success_rate']:.0%}, n={info['total']})")

    elif args.command == "act":
        r = act_on_gaps()
        print(f"Experiments: {r['experiments_created']}, Signals: {r['signals_sent']}")
        for d in r["details"]:
            print(f"  {d}")

    elif args.command == "check":
        capable = is_capable(args.task_type)
        print(f"{'✅' if capable else '❌'} {args.task_type}: {'capable' if capable else 'not capable'}")

    elif args.command == "best-model":
        model = best_model_for(args.task_type)
        print(f"Best model for {args.task_type}: {model or 'unknown'}")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
