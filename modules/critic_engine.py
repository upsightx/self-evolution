#!/usr/bin/env python3
"""
Critic Engine — External Learning Proposal Reviewer.

职责：
- 审查外部学习生成的进化提案
- 检查重复造轮子（memory_db 检索）
- 检查硬件适配性（是否重型依赖）
- 价值质疑（是否值得投入）

工作流程：
1. 接收外部学习提案（来自 external-learning）
2. 检查 X-Memory 是否有类似记录
3. 检查是否需要重型依赖（torch/cuda 等）
4. 输出审查结果：APPROVE / REJECT / APPROVE_WITH_CAUTION
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add parent dir to path
_modules_path = Path(__file__).parent
if str(_modules_path) not in sys.path:
    sys.path.insert(0, str(_modules_path))

# Heavy dependencies that may not fit resource-constrained environments
HEAVY_DEPS = {"torch", "tensorflow", "cuda", "transformers", "pytorch"}

# Keywords that indicate pure news/financing (not actionable tech proposals)
NEWS_KEYWORDS = [
    "funding", "funded", "raises", "raised", "series", "investment",
    "融资", "轮", "估值", "领投", "跟投", "战略投资",
    "acquisition", "acquired", "并购",
    "ipo", "listing", "上市",
]


def is_pure_news(summary: str) -> bool:
    """Check if the proposal is pure news/financing (not actionable).

    Args:
        summary: Proposal summary

    Returns:
        True if this is pure news (should be filtered out)
    """
    summary_lower = summary.lower()
    for keyword in NEWS_KEYWORDS:
        if keyword.lower() in summary_lower:
            return True
    return False


def check_memory_overlap(topic: str, summary: str) -> bool:
    """Check if similar work already exists in X-Memory.

    Args:
        topic: Proposal topic/summary
        summary: Detailed summary

    Returns:
        True if overlap detected (should reject)
    """
    try:
        from memory_retrieval import search
        # Search for similar topics
        results = search(topic, limit=5)
        for r in results:
            # Simple keyword overlap check
            topic_lower = topic.lower()
            content_lower = r.get("content", "").lower()
            if topic_lower in content_lower or any(
                kw in content_lower for kw in topic_lower.split()[:3]
            ):
                return True
        return False
    except Exception:
        # If memory retrieval fails, assume no overlap (safe default)
        return False


def check_hardware_fit(dependencies: list[str] | None = None) -> tuple[bool, str]:
    """Check if dependencies fit resource-constrained environment.

    Args:
        dependencies: List of required dependencies

    Returns:
        (fits: bool, reason: str)
    """
    if not dependencies:
        return True, "No dependencies specified"

    heavy_found = [dep for dep in dependencies if dep.lower() in HEAVY_DEPS]
    if heavy_found:
        return False, f"Requires heavy dependencies: {', '.join(heavy_found)}"
    return True, "Dependencies are lightweight"


def critical_review(proposal: dict) -> dict:
    """Review an external learning proposal.

    Args:
        proposal: {
            "id": str,
            "summary": str,
            "dependencies": list[str] (optional),
            "source_url": str (optional),
            "priority": str (optional, P0/P1/P2),
        }

    Returns:
        {
            "verdict": "APPROVE" | "REJECT" | "APPROVE_WITH_CAUTION",
            "critique_points": list[str],
            "questions_for_builder": list[str],
        }
    """
    print(f"👨\u200d⚖️ Critic Engine: Reviewing proposal '{proposal.get('id', 'unknown')}'...")

    summary = proposal.get("summary", "")
    critique_points = []
    verdict = "APPROVE"
    questions = []

    # Rule 0: Filter pure news/financing (not actionable tech proposals)
    if is_pure_news(summary):
        critique_points.append(
            "❌ REJECT: Pure news/financing. Not an actionable technical proposal."
        )
        verdict = "REJECT"
        result = {
            "verdict": verdict,
            "critique_points": critique_points,
            "questions_for_builder": questions,
        }
        print(f"  📝 Critique Result: {result['verdict']}")
        for point in result["critique_points"]:
            print(f"     {point}")
        return result

    # Rule 1: Check for redundancy (don't reinvent the wheel)
    summary = proposal.get("summary", "")
    if check_memory_overlap(proposal.get("id", ""), summary):
        critique_points.append(
            "❌ REJECT: Redundant! Similar work already exists in memory."
        )
        verdict = "REJECT"

    # Rule 2: Hardware/resource fit
    deps = proposal.get("dependencies", [])
    fits, reason = check_hardware_fit(deps)
    if not fits:
        critique_points.append(f"⚠️ WARNING: {reason}")
        if verdict == "APPROVE":
            verdict = "APPROVE_WITH_CAUTION"

    # Rule 3: Value质疑 (summary too vague)
    if len(summary) < 20:
        critique_points.append(
            "❓ QUERY: Summary too vague. What is the core innovation?"
        )
        questions.append("Can you clarify the specific problem this solves?")

    # Rule 4: Priority check (P0 needs extra scrutiny)
    priority = proposal.get("priority", "")
    if priority == "P0" and not critique_points:
        questions.append(
            "This is marked P0. What is the expected impact if NOT implemented?"
        )

    result = {
        "verdict": verdict,
        "critique_points": critique_points if critique_points else ["✅ Passed all checks."],
        "questions_for_builder": questions,
    }

    print(f"  📝 Critique Result: {result['verdict']}")
    for point in result["critique_points"]:
        print(f"     {point}")
    if questions:
        print(f"  ❓ Questions: {questions}")

    return result


def review_external_learning(learning_note: dict) -> dict:
    """Review an external learning note and decide if it should trigger evolution.

    Args:
        learning_note: {
            "title": str,
            "summary": str,
            "dependencies": list[str],
            "landing_priority": str (P0/P1/P2),
            "related_modules": list[str],
        }

    Returns:
        Critic review result
    """
    proposal = {
        "id": learning_note.get("title", ""),
        "summary": learning_note.get("summary", ""),
        "dependencies": learning_note.get("dependencies", []),
        "priority": learning_note.get("landing_priority", ""),
    }
    return critical_review(proposal)


if __name__ == "__main__":
    # Test run
    test_prop = {
        "id": "test_heavy_torch",
        "summary": "Use MiroThinker with full torch backend",
        "dependencies": ["torch", "cuda"],
        "priority": "P0",
    }
    result = critical_review(test_prop)
    print(f"\nFinal verdict: {result['verdict']}")
