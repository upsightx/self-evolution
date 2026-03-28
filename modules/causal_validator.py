#!/usr/bin/env python3
"""
Causal Validator — 判断实验改动是否真的有效。

职责：
- 接收实验的 baseline 和 experiment 结果
- 用工程规则（不是统计模型）判断：有效 / 存疑 / 无效
- 输出置信度和原因说明
- 防止系统因单次巧合误以为自己进化了

不做什么：
- 不做复杂因果推断（没有 DAG、没有 IV）
- 不自动执行任何改动
- 不访问外部 API

Phase 1 规则：
1. 样本量门槛：< 3 次直接 uncertain
2. 同类任务前后对比：成功率 + critic 分 + 返工率
3. 综合指标加权打分
4. 允许输出 "uncertain"
"""
from __future__ import annotations

import json
import sys
import argparse
from dataclasses import dataclass

# 不依赖 db_common，只接收数据做判断


@dataclass
class ValidationResult:
    verdict: str          # effective / uncertain / ineffective
    confidence: float     # 0.0 ~ 1.0
    reason: str           # human-readable explanation
    details: dict         # breakdown of metrics

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "details": self.details,
        }


def _calc_metrics(results: list[dict]) -> dict:
    """Calculate aggregate metrics from a list of trial results."""
    if not results:
        return {
            "count": 0,
            "success_rate": 0.0,
            "avg_critic": None,
            "rework_rate": 0.0,
            "avg_duration": None,
        }

    count = len(results)
    successes = sum(1 for r in results if r.get("success"))
    success_rate = successes / count

    critic_scores = [r["critic_score"] for r in results if r.get("critic_score") is not None]
    avg_critic = sum(critic_scores) / len(critic_scores) if critic_scores else None

    reworks = sum(1 for r in results if r.get("rework"))
    rework_rate = reworks / count

    durations = [r["duration_s"] for r in results if r.get("duration_s") is not None]
    avg_duration = sum(durations) / len(durations) if durations else None

    return {
        "count": count,
        "success_rate": round(success_rate, 4),
        "avg_critic": round(avg_critic, 2) if avg_critic is not None else None,
        "rework_rate": round(rework_rate, 4),
        "avg_duration": round(avg_duration, 2) if avg_duration is not None else None,
    }


def validate(
    baseline_results: list[dict],
    experiment_results: list[dict],
    min_samples: int = 3,
) -> ValidationResult:
    """Validate whether an experiment's change is genuinely effective.

    Args:
        baseline_results: list of trial dicts from before the change
        experiment_results: list of trial dicts from after the change
        min_samples: minimum trials per phase to make a judgment

    Returns:
        ValidationResult with verdict, confidence, reason, and metric details
    """
    b = _calc_metrics(baseline_results)
    e = _calc_metrics(experiment_results)

    details = {"baseline": b, "experiment": e, "deltas": {}}
    reasons = []

    # ── Rule 1: Sample size gate ──
    if e["count"] < min_samples:
        return ValidationResult(
            verdict="uncertain",
            confidence=0.2,
            reason=f"实验样本不足：{e['count']}/{min_samples}，无法判断",
            details=details,
        )

    if b["count"] < min_samples:
        # No baseline to compare against — can only look at absolute performance
        if e["success_rate"] >= 0.8:
            return ValidationResult(
                verdict="uncertain",
                confidence=0.4,
                reason=f"无足够基线数据对比（基线{b['count']}条），实验成功率{e['success_rate']:.0%}看起来不错但无法确认是改动带来的",
                details=details,
            )
        else:
            return ValidationResult(
                verdict="uncertain",
                confidence=0.25,
                reason=f"无足够基线数据对比（基线{b['count']}条），实验成功率{e['success_rate']:.0%}",
                details=details,
            )

    # ── Rule 2: Calculate deltas ──
    delta_success = e["success_rate"] - b["success_rate"]
    delta_rework = e["rework_rate"] - b["rework_rate"]  # negative is better
    details["deltas"]["success_rate"] = round(delta_success, 4)
    details["deltas"]["rework_rate"] = round(delta_rework, 4)

    if b["avg_critic"] is not None and e["avg_critic"] is not None:
        delta_critic = e["avg_critic"] - b["avg_critic"]
        details["deltas"]["avg_critic"] = round(delta_critic, 2)
    else:
        delta_critic = None

    if b["avg_duration"] is not None and e["avg_duration"] is not None:
        delta_duration = e["avg_duration"] - b["avg_duration"]  # negative is better
        details["deltas"]["avg_duration"] = round(delta_duration, 2)
    else:
        delta_duration = None

    # ── Rule 3: Weighted scoring ──
    # Each dimension contributes a score from -1 to +1
    # Positive = improvement, negative = regression
    score = 0.0
    weight_total = 0.0

    # Success rate (weight: 0.4)
    w_success = 0.4
    if delta_success > 0.15:
        score += w_success * 1.0
        reasons.append(f"成功率提升 {delta_success:+.0%}")
    elif delta_success > 0.05:
        score += w_success * 0.5
        reasons.append(f"成功率小幅提升 {delta_success:+.0%}")
    elif delta_success > -0.05:
        score += 0
        reasons.append(f"成功率基本持平 {delta_success:+.0%}")
    elif delta_success > -0.15:
        score += w_success * -0.5
        reasons.append(f"成功率小幅下降 {delta_success:+.0%}")
    else:
        score += w_success * -1.0
        reasons.append(f"成功率明显下降 {delta_success:+.0%}")
    weight_total += w_success

    # Rework rate (weight: 0.25, inverted — lower is better)
    w_rework = 0.25
    if delta_rework < -0.1:
        score += w_rework * 1.0
        reasons.append(f"返工率下降 {delta_rework:+.0%}")
    elif delta_rework < -0.03:
        score += w_rework * 0.5
        reasons.append(f"返工率小幅下降 {delta_rework:+.0%}")
    elif delta_rework < 0.03:
        score += 0
    elif delta_rework < 0.1:
        score += w_rework * -0.5
        reasons.append(f"返工率小幅上升 {delta_rework:+.0%}")
    else:
        score += w_rework * -1.0
        reasons.append(f"返工率明显上升 {delta_rework:+.0%}")
    weight_total += w_rework

    # Critic score (weight: 0.25, only if available)
    if delta_critic is not None:
        w_critic = 0.25
        if delta_critic > 5:
            score += w_critic * 1.0
            reasons.append(f"Critic 分提升 {delta_critic:+.1f}")
        elif delta_critic > 2:
            score += w_critic * 0.5
            reasons.append(f"Critic 分小幅提升 {delta_critic:+.1f}")
        elif delta_critic > -2:
            score += 0
        elif delta_critic > -5:
            score += w_critic * -0.5
            reasons.append(f"Critic 分小幅下降 {delta_critic:+.1f}")
        else:
            score += w_critic * -1.0
            reasons.append(f"Critic 分明显下降 {delta_critic:+.1f}")
        weight_total += w_critic

    # Duration (weight: 0.1, only if available, inverted)
    if delta_duration is not None:
        w_dur = 0.1
        pct = delta_duration / max(b["avg_duration"], 1)
        if pct < -0.2:
            score += w_dur * 1.0
            reasons.append(f"耗时减少 {abs(pct):.0%}")
        elif pct < -0.05:
            score += w_dur * 0.5
        elif pct < 0.05:
            score += 0
        elif pct < 0.2:
            score += w_dur * -0.5
        else:
            score += w_dur * -1.0
            reasons.append(f"耗时增加 {pct:.0%}")
        weight_total += w_dur

    # Normalize score to 0~1 range
    if weight_total > 0:
        normalized = (score / weight_total + 1) / 2  # map [-1,1] → [0,1]
    else:
        normalized = 0.5

    # ── Rule 4: Sample size confidence adjustment ──
    # More samples → higher confidence in the verdict
    total_samples = b["count"] + e["count"]
    if total_samples >= 20:
        sample_factor = 1.0
    elif total_samples >= 10:
        sample_factor = 0.85
    elif total_samples >= 6:
        sample_factor = 0.7
    else:
        sample_factor = 0.55

    confidence = normalized * sample_factor

    # ── Rule 5: Final verdict ──
    if normalized >= 0.65 and confidence >= 0.5:
        verdict = "effective"
    elif normalized <= 0.35 or confidence < 0.3:
        verdict = "ineffective"
    else:
        verdict = "uncertain"

    reason_str = "；".join(reasons) if reasons else "各指标无明显变化"

    return ValidationResult(
        verdict=verdict,
        confidence=round(confidence, 3),
        reason=reason_str,
        details=details,
    )


def validate_experiment(experiment: dict) -> ValidationResult:
    """Convenience: validate directly from an experiment dict (as returned by evolution_executor.get_experiment).

    Handles parsing of baseline_results and experiment_results fields.
    """
    baseline = experiment.get("baseline_results") or []
    exp_results = experiment.get("experiment_results") or []
    min_samples = experiment.get("min_samples", 3)

    # Parse if still JSON strings
    if isinstance(baseline, str):
        baseline = json.loads(baseline)
    if isinstance(exp_results, str):
        exp_results = json.loads(exp_results)

    return validate(baseline, exp_results, min_samples=min_samples)


# ============ CLI ============

def _cli():
    parser = argparse.ArgumentParser(description="Causal Validator — 实验归因验证")
    sub = parser.add_subparsers(dest="command")

    # validate from experiment id
    p_val = sub.add_parser("validate", help="Validate an experiment by ID")
    p_val.add_argument("id", type=int)

    # validate from inline JSON (for testing)
    p_test = sub.add_parser("test-validate", help="Validate from inline JSON data")
    p_test.add_argument("--baseline", required=True, help="JSON array of baseline results")
    p_test.add_argument("--experiment", required=True, help="JSON array of experiment results")
    p_test.add_argument("--min-samples", type=int, default=3)

    args = parser.parse_args()

    if args.command == "validate":
        # Import here to avoid circular dependency at module level
        from evolution_executor import get_experiment
        exp = get_experiment(args.id)
        if not exp:
            print(f"Experiment #{args.id} not found")
            sys.exit(1)
        result = validate_experiment(exp)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

    elif args.command == "test-validate":
        baseline = json.loads(args.baseline)
        experiment = json.loads(args.experiment)
        result = validate(baseline, experiment, min_samples=args.min_samples)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
