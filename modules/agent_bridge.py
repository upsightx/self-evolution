#!/usr/bin/env python3
"""
Agent Bridge — 子Agent调度与进化系统的桥接层。

职责：
- 子Agent完成后一行调用录入 task_outcome
- 自动检查是否有活跃实验，有则同时录入实验结果
- 自动提取标签（从任务描述中抽关键词）

用法：
    from agent_bridge import record_agent_result
    record_agent_result(
        task_type="coding",
        model="minimax",
        success=True,
        description="重构 feedback_loop.py",
        notes="一次通过，无返工",
        critic_score=85,
    )

不做什么：
- 不派子Agent（那是主Agent的事）
- 不做复杂分析（交给 feedback_loop / evolution_executor）
"""
from __future__ import annotations

import re
from datetime import datetime


# ============ 自动标签提取 ============

_TAG_RULES = {
    # 技术关键词
    "python": ["python"],
    "javascript": ["javascript", "js", "node"],
    "docker": ["docker", "容器"],
    "git": ["git", "github", "仓库"],
    "sqlite": ["sqlite", "数据库", "db"],
    "api": ["api", "接口", "endpoint"],
    # 任务类型
    "重构": ["重构", "refactor"],
    "修复": ["修复", "fix", "bug"],
    "新功能": ["新功能", "feature", "新增"],
    "测试": ["测试", "test", "验证"],
    "文档": ["文档", "readme", "doc"],
    "部署": ["部署", "deploy", "上线"],
    "搜索": ["搜索", "search", "爬虫", "抓取"],
    "飞书": ["飞书", "feishu", "lark"],
    # 模块
    "记忆": ["记忆", "memory", "recall"],
    "进化": ["进化", "evolution", "evolver"],
    "反馈": ["反馈", "feedback", "闭环"],
}


def extract_tags(text: str) -> list[str]:
    """从文本中自动提取标签。规则匹配，不调LLM。"""
    if not text:
        return []
    text_lower = text.lower()
    tags = []
    for tag, keywords in _TAG_RULES.items():
        if any(kw in text_lower for kw in keywords):
            tags.append(tag)
    return tags[:8]  # 最多8个标签


# ============ 时间表达解析 ============

_TIME_PATTERNS = {
    r"今天|today": 0,
    r"昨天|yesterday": 1,
    r"前天": 2,
    r"上午": 0,
    r"下午": 0,
    r"最近|近期": 7,
    r"上周|last\s*week": 7,
    r"这周|this\s*week": 7,
    r"上个月|last\s*month": 30,
    r"这个月|this\s*month": 30,
}


def parse_time_hint(query: str) -> dict | None:
    """从查询中提取时间暗示。

    Returns:
        {"days_ago": int, "matched": str} or None
    """
    if not query:
        return None
    for pattern, days in _TIME_PATTERNS.items():
        if re.search(pattern, query, re.IGNORECASE):
            return {"days_ago": days, "matched": pattern}
    return None


# ============ 核心：录入子Agent结果 ============

def record_agent_result(
    task_type: str,
    model: str,
    success: bool,
    description: str = "",
    expected: str | None = None,
    actual: str | None = None,
    notes: str | None = None,
    critic_score: float | None = None,
    rework: bool = False,
    duration_s: float | None = None,
    task_id: str | None = None,
) -> dict:
    """录入一次子Agent执行结果。一行调用，自动完成：

    1. 录入 task_outcome（feedback_loop）
    2. 自动提取标签，录入 observation（如果失败）
    3. 检查是否有活跃实验，有则录入实验结果并可能自动结论

    Args:
        task_type: 任务类型（coding/research/file_ops/reasoning）
        model: 使用的模型（minimax/opus/kimi/gpt5）
        success: 是否成功
        description: 任务描述（用于提取标签和记录）
        expected: 预期结果
        actual: 实际结果
        notes: 备注
        critic_score: Critic评分（0-100）
        rework: 是否需要返工
        duration_s: 耗时（秒）
        task_id: 任务ID（可选）

    Returns:
        dict with keys: outcome_id, observation_id, experiment_verdict
    """
    result = {
        "outcome_id": None,
        "observation_id": None,
        "experiment_verdict": None,
    }

    # 1. 录入 task_outcome
    try:
        from feedback_loop import record_task_outcome
        outcome_id = record_task_outcome(
            task_id=task_id,
            task_type=task_type,
            model=model,
            expected=expected,
            actual=actual,
            success=success,
            notes=notes,
        )
        result["outcome_id"] = outcome_id
    except Exception as e:
        print(f"[agent_bridge] Warning: failed to record task_outcome: {e}")

    # 2. 如果失败，自动录入一条 observation（教训）
    if not success and (description or notes):
        try:
            from memory_store import add_observation
            tags = extract_tags(f"{description} {notes or ''} {task_type} {model}")
            obs_id = add_observation(
                type="lesson",
                title=f"[{task_type}/{model}] {description[:80]}",
                narrative=f"预期: {expected or '未指定'}\n实际: {actual or '未指定'}\n备注: {notes or '无'}",
                tags=tags,
                task_type=task_type,
            )
            result["observation_id"] = obs_id
        except Exception as e:
            print(f"[agent_bridge] Warning: failed to record observation: {e}")

    # 3. 检查活跃实验
    try:
        from evolution_executor import get_active_experiment_for_task, record_and_maybe_conclude
        exp = get_active_experiment_for_task(task_type)
        if exp:
            # 判断 phase：如果实验有 baseline_snapshot 且当前用的是旧方案，记为 baseline
            # 简化处理：如果 baseline 样本不够，先填 baseline；否则填 experiment
            baseline = exp.get("baseline_results") or []
            min_samples = exp.get("min_samples", 5)

            phase = "baseline" if len(baseline) < min_samples else "experiment"

            verdict_result = record_and_maybe_conclude(
                exp["id"],
                phase=phase,
                success=success,
                critic_score=critic_score,
                rework=rework,
                duration_s=duration_s,
                notes=f"[auto] {description[:60]}",
            )
            if verdict_result:
                result["experiment_verdict"] = verdict_result
                print(f"[agent_bridge] Experiment #{exp['id']} auto-concluded: {verdict_result['verdict']}")
    except Exception as e:
        print(f"[agent_bridge] Warning: experiment recording failed: {e}")

    status = "✓" if success else "✗"
    print(f"[agent_bridge] {status} {task_type}/{model}: {description[:60]}")
    return result


# ============ CLI ============

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="Agent Bridge — 子Agent结果录入")
    sub = parser.add_subparsers(dest="command")

    p_rec = sub.add_parser("record", help="Record agent result")
    p_rec.add_argument("task_type")
    p_rec.add_argument("model")
    p_rec.add_argument("success", type=int, choices=[0, 1])
    p_rec.add_argument("--desc", default="")
    p_rec.add_argument("--expected", default=None)
    p_rec.add_argument("--actual", default=None)
    p_rec.add_argument("--notes", default=None)
    p_rec.add_argument("--critic-score", type=float, default=None)
    p_rec.add_argument("--rework", action="store_true")
    p_rec.add_argument("--duration", type=float, default=None)

    p_tags = sub.add_parser("extract-tags", help="Test tag extraction")
    p_tags.add_argument("text")

    p_time = sub.add_parser("parse-time", help="Test time hint parsing")
    p_time.add_argument("query")

    args = parser.parse_args()

    if args.command == "record":
        result = record_agent_result(
            task_type=args.task_type,
            model=args.model,
            success=bool(args.success),
            description=args.desc,
            expected=args.expected,
            actual=args.actual,
            notes=args.notes,
            critic_score=args.critic_score,
            rework=args.rework,
            duration_s=args.duration,
        )
        import json
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    elif args.command == "extract-tags":
        tags = extract_tags(args.text)
        print(f"Tags: {tags}")

    elif args.command == "parse-time":
        hint = parse_time_hint(args.query)
        print(f"Time hint: {hint}")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
