#!/usr/bin/env python3
"""
Evolution Strategy — 进化策略引擎。

从 Evolver 迁移的 3 个核心思想：
1. Strategy Presets — 根据系统状态自动选择进化策略
2. Signal Detection — 从运行数据中提取多维信号
3. Adaptive Reflection — 动态调整反思频率

不做什么：
- 不做 Hub/A2A 网络通信
- 不做 Gene/Capsule 资产管理
- 不做 Git 回滚
- 不做 LLM personality 注入
"""
from __future__ import annotations

import json
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path

from db_common import DB_PATH, get_db


# ============ Strategy Presets ============

STRATEGIES = {
    "balanced": {
        "repair": 0.20,
        "optimize": 0.30,
        "innovate": 0.50,
        "repair_loop_threshold": 0.50,
        "description": "正常运行。稳定增长，兼顾创新。",
    },
    "innovate": {
        "repair": 0.05,
        "optimize": 0.15,
        "innovate": 0.80,
        "repair_loop_threshold": 0.30,
        "description": "系统稳定，最大化创新和新能力。",
    },
    "harden": {
        "repair": 0.40,
        "optimize": 0.40,
        "innovate": 0.20,
        "repair_loop_threshold": 0.70,
        "description": "大改之后，优先稳定和健壮性。",
    },
    "repair_only": {
        "repair": 0.80,
        "optimize": 0.20,
        "innovate": 0.00,
        "repair_loop_threshold": 1.00,
        "description": "紧急修复模式，先修好再说。",
    },
    "steady_state": {
        "repair": 0.60,
        "optimize": 0.30,
        "innovate": 0.10,
        "repair_loop_threshold": 0.90,
        "description": "进化饱和，维持现有能力，最小创新。",
    },
}


def resolve_strategy(override: str | None = None) -> dict:
    """Resolve the current evolution strategy.

    If override is provided and valid, use it.
    Otherwise, auto-detect based on recent task outcomes.

    Returns:
        dict with strategy name, allocations, and reasoning
    """
    if override and override in STRATEGIES:
        s = STRATEGIES[override]
        return {"name": override, **s, "auto": False, "reasoning": f"手动指定策略: {override}"}

    # Auto-detect from recent data
    signals = detect_signals()
    signal_names = [s["signal"] for s in signals]

    # Decision logic
    if "high_failure_rate" in signal_names:
        name = "repair_only"
        reasoning = "检测到高失败率，切换到紧急修复模式"
    elif "repair_loop" in signal_names:
        name = "innovate"
        reasoning = "检测到修复循环（连续修复但没改善），强制切换到创新模式"
    elif "stagnation" in signal_names:
        name = "innovate"
        reasoning = "检测到停滞（成功率稳定但无新进展），尝试创新"
    elif "recent_big_change" in signal_names:
        name = "harden"
        reasoning = "近期有大改动，优先加固稳定性"
    elif "all_healthy" in signal_names:
        name = "balanced"
        reasoning = "系统健康，保持平衡策略"
    else:
        name = "balanced"
        reasoning = "默认平衡策略"

    s = STRATEGIES[name]
    return {"name": name, **s, "auto": True, "reasoning": reasoning, "signals": signal_names}


# ============ Signal Detection ============

def detect_signals(days: int = 7) -> list[dict]:
    """Detect evolution signals from recent task outcomes and experiments.

    Scans:
    - task_outcomes: failure rates, patterns
    - experiments: concluded results
    - observations: recent lessons

    Returns list of signal dicts: {signal, severity, detail}
    """
    signals = []
    db = get_db()

    try:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        # ── Signal 1: High failure rate ──
        rows = db.execute(
            """SELECT task_type, COUNT(*) as total, SUM(success) as wins
               FROM task_outcomes WHERE timestamp >= ?
               GROUP BY task_type HAVING total >= 3""",
            (cutoff,),
        ).fetchall()

        for r in rows:
            total = r["total"]
            wins = r["wins"] or 0
            failure_rate = 1 - (wins / total)
            if failure_rate >= 0.5:
                signals.append({
                    "signal": "high_failure_rate",
                    "severity": "high",
                    "detail": f"{r['task_type']}: {failure_rate:.0%} failure ({total} samples)",
                })
            elif failure_rate >= 0.3:
                signals.append({
                    "signal": "elevated_failure_rate",
                    "severity": "medium",
                    "detail": f"{r['task_type']}: {failure_rate:.0%} failure ({total} samples)",
                })

        # ── Signal 2: Repair loop detection ──
        # If last N task outcomes for a type are all failures, it's a repair loop
        task_types = db.execute(
            "SELECT DISTINCT task_type FROM task_outcomes WHERE timestamp >= ?",
            (cutoff,),
        ).fetchall()

        for tt in task_types:
            recent = db.execute(
                "SELECT success FROM task_outcomes WHERE task_type = ? ORDER BY timestamp DESC LIMIT 5",
                (tt["task_type"],),
            ).fetchall()
            if len(recent) >= 3 and all(not r["success"] for r in recent[:3]):
                signals.append({
                    "signal": "repair_loop",
                    "severity": "high",
                    "detail": f"{tt['task_type']}: 最近3次全部失败",
                })

        # ── Signal 3: Stagnation ──
        # High success rate but no new experiments or observations
        all_recent = db.execute(
            "SELECT COUNT(*) as c, SUM(success) as s FROM task_outcomes WHERE timestamp >= ?",
            (cutoff,),
        ).fetchone()
        if all_recent["c"] >= 5:
            overall_success = (all_recent["s"] or 0) / all_recent["c"]
            if overall_success >= 0.8:
                # Check if there are any new experiments or observations
                new_obs = db.execute(
                    "SELECT COUNT(*) as c FROM observations WHERE created_at >= ?",
                    (cutoff,),
                ).fetchone()["c"]

                # Check experiments table exists
                try:
                    new_exp = db.execute(
                        "SELECT COUNT(*) as c FROM experiments WHERE created_at >= ?",
                        (cutoff,),
                    ).fetchone()["c"]
                except Exception:
                    new_exp = 0

                if new_obs <= 2 and new_exp == 0:
                    signals.append({
                        "signal": "stagnation",
                        "severity": "low",
                        "detail": f"成功率{overall_success:.0%}但近{days}天无新实验/少量新观察",
                    })

        # ── Signal 4: Recent big change ──
        # Many new observations in a short period suggests a big change happened
        recent_3d = (datetime.now() - timedelta(days=3)).isoformat()
        obs_3d = db.execute(
            "SELECT COUNT(*) as c FROM observations WHERE created_at >= ?",
            (recent_3d,),
        ).fetchone()["c"]
        if obs_3d >= 10:
            signals.append({
                "signal": "recent_big_change",
                "severity": "medium",
                "detail": f"近3天新增{obs_3d}条观察记录",
            })

        # ── Signal 5: Capability gap ──
        # Failed tasks with "missing" or "not_found" in gap_analysis
        gap_rows = db.execute(
            """SELECT task_type, gap_analysis FROM task_outcomes
               WHERE timestamp >= ? AND success = 0 AND gap_analysis IS NOT NULL""",
            (cutoff,),
        ).fetchall()
        gap_keywords = {"missing", "not_found", "dependency", "import", "no_result"}
        gap_types = set()
        for gr in gap_rows:
            gap_text = (gr["gap_analysis"] or "").lower()
            if any(kw in gap_text for kw in gap_keywords):
                gap_types.add(gr["task_type"])
        for gt in gap_types:
            signals.append({
                "signal": "capability_gap",
                "severity": "medium",
                "detail": f"{gt}: 失败原因含依赖缺失/能力缺口",
            })

        # ── Signal 6: All healthy ──
        if not signals:
            signals.append({
                "signal": "all_healthy",
                "severity": "info",
                "detail": "无异常信号",
            })

    except Exception as e:
        signals.append({
            "signal": "detection_error",
            "severity": "low",
            "detail": str(e),
        })
    finally:
        db.close()

    return signals


# ============ Adaptive Reflection ============

REFLECTION_STATE_KEY = "lastReflection"

# Base intervals (in days)
REFLECTION_INTERVAL_DEFAULT = 3
REFLECTION_INTERVAL_HEALTHY = 5
REFLECTION_INTERVAL_TROUBLED = 1


def should_reflect(state_path: str | None = None) -> dict:
    """Determine if it's time for a strategic reflection.

    Adapts interval based on recent signals:
    - All healthy + high success → reflect less often (every 5 days)
    - Problems detected → reflect more often (every 1 day)
    - Normal → every 3 days

    Args:
        state_path: path to heartbeat-state.json (auto-detected if None)

    Returns:
        dict with: should_reflect (bool), reason, interval_days, next_reflection
    """
    if state_path is None:
        state_path = str(Path(__file__).parent.parent / "heartbeat-state.json")

    # Read last reflection time
    last_reflection = None
    try:
        with open(state_path) as f:
            state = json.load(f)
        last_str = state.get(REFLECTION_STATE_KEY)
        if last_str:
            last_reflection = datetime.fromisoformat(last_str)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass

    # Detect current signals to determine interval
    signals = detect_signals(days=7)
    signal_names = [s["signal"] for s in signals]

    has_problems = any(s in signal_names for s in [
        "high_failure_rate", "repair_loop", "capability_gap"
    ])
    is_healthy = "all_healthy" in signal_names

    if has_problems:
        interval = REFLECTION_INTERVAL_TROUBLED
        reason = "检测到问题信号，缩短反思间隔"
    elif is_healthy:
        interval = REFLECTION_INTERVAL_HEALTHY
        reason = "系统健康，拉长反思间隔"
    else:
        interval = REFLECTION_INTERVAL_DEFAULT
        reason = "常规反思间隔"

    now = datetime.now()
    if last_reflection is None:
        return {
            "should_reflect": True,
            "reason": "从未反思过",
            "interval_days": interval,
            "next_reflection": now.isoformat(),
        }

    next_time = last_reflection + timedelta(days=interval)
    should = now >= next_time

    return {
        "should_reflect": should,
        "reason": reason if should else f"下次反思: {next_time.strftime('%m-%d %H:%M')}",
        "interval_days": interval,
        "next_reflection": next_time.isoformat(),
        "last_reflection": last_reflection.isoformat(),
    }


def record_reflection(state_path: str | None = None):
    """Record that a reflection just happened."""
    if state_path is None:
        state_path = str(Path(__file__).parent.parent / "heartbeat-state.json")

    try:
        with open(state_path) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}

    state[REFLECTION_STATE_KEY] = datetime.now().isoformat()

    with open(state_path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def build_reflection_context() -> str:
    """Build a context string for strategic reflection.

    Gathers recent signals, experiment results, and failure patterns
    into a concise summary that can be used as input for reflection.
    """
    parts = []

    # Current strategy
    strategy = resolve_strategy()
    parts.append(f"## 当前策略: {strategy['name']}")
    parts.append(f"原因: {strategy['reasoning']}")
    parts.append("")

    # Signals
    signals = detect_signals()
    parts.append("## 信号检测")
    for s in signals:
        parts.append(f"- [{s['severity']}] {s['signal']}: {s['detail']}")
    parts.append("")

    # Recent experiments
    try:
        from evolution_executor import list_experiments
        exps = list_experiments(limit=5)
        if exps:
            parts.append("## 近期实验")
            for e in exps:
                v = f" → {e['verdict']}" if e.get("verdict") else ""
                parts.append(f"- #{e['id']} [{e['status']}] {e['task_type']}: {e['problem'][:50]}{v}")
            parts.append("")
    except Exception:
        pass

    # Failure patterns from feedback_loop
    try:
        from feedback_loop import analyze_patterns
        patterns = analyze_patterns(min_samples=3)
        if patterns:
            parts.append("## 失败模式")
            for p in patterns:
                parts.append(f"- {p['task_type']}/{p['model']}: failure_rate={p['failure_rate']}")
            parts.append("")
    except Exception:
        pass

    # Reflection question
    parts.append("## 反思问题")
    parts.append("1. 当前策略是否合适？需要调整吗？")
    parts.append("2. 有哪些重复出现的问题还没解决？")
    parts.append("3. 下一步最值得投入的改进方向是什么？")
    parts.append("4. 有没有什么该停止做的事？")

    return "\n".join(parts)


# ============ CLI ============

def _cli():
    parser = argparse.ArgumentParser(description="Evolution Strategy — 进化策略引擎")
    sub = parser.add_subparsers(dest="command")

    # strategy
    p_strat = sub.add_parser("strategy", help="Resolve current strategy")
    p_strat.add_argument("--override", default=None, choices=list(STRATEGIES.keys()))

    # signals
    p_sig = sub.add_parser("signals", help="Detect current signals")
    p_sig.add_argument("--days", type=int, default=7)

    # reflect
    sub.add_parser("should-reflect", help="Check if reflection is due")
    sub.add_parser("record-reflection", help="Record that reflection happened")
    sub.add_parser("reflection-context", help="Build reflection context")

    args = parser.parse_args()

    if args.command == "strategy":
        result = resolve_strategy(override=args.override)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "signals":
        signals = detect_signals(days=args.days)
        for s in signals:
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢", "info": "ℹ️"}.get(s["severity"], "•")
            print(f"  {icon} {s['signal']}: {s['detail']}")

    elif args.command == "should-reflect":
        result = should_reflect()
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "record-reflection":
        record_reflection()
        print("✅ Reflection recorded")

    elif args.command == "reflection-context":
        print(build_reflection_context())

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
