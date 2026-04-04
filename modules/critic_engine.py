#!/usr/bin/env python3
"""
Critic Engine — Feasibility Reviewer for External Learning Proposals.

职责：
审核外部学习内容是否值得落地成真实软件。

审核维度：
1. 资源适配性：本机 4GB 内存，需要 16GB 的→拒绝
2. 架构复杂度：高并发分布式架构→拒绝（个人用户）
3. 依赖重量：需要 torch/cuda 等重型依赖→警告或拒绝
4. 重复造轮子：X-Memory 已有类似功能→拒绝
5. 价值质疑：摘要太模糊/无明确收益→要求澄清

输出 verdict：
- APPROVE: 可行，值得落地
- APPROVE_WITH_CAUTION: 可行但有风险（如重型依赖）
- REJECT: 不可行，拒绝落地
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add parent dir to path
_modules_path = Path(__file__).parent
if str(_modules_path) not in sys.path:
    sys.path.insert(0, str(_modules_path))

# Resource constraints (current machine)
MAX_RAM_GB = 4
MAX_CPU_CORES = 2

# Heavy dependencies (may not fit 4GB RAM)
HEAVY_DEPS = {
    "torch", "tensorflow", "pytorch", "cuda", "cudnn",
    "transformers", "diffusers", "accelerate",
    "spark", "hadoop", "kafka", "celery",
}

# Architecture patterns unsuitable for personal use
UNSUITABLE_ARCHS = [
    "distributed", "microservice", "high concurrency", "cluster",
    "kubernetes", "docker swarm", "service mesh",
    "分布式", "微服务", "高并发", "集群",
]

# Keywords indicating pure news/financing (not actionable)
NEWS_KEYWORDS = [
    "funding", "funded", "raises", "raised", "series", "investment",
    "融资", "轮", "估值", "领投", "跟投", "战略投资",
    "acquisition", "acquired", "并购", "ipo", "listing", "上市",
]


def is_pure_news(summary: str) -> bool:
    """Check if proposal is pure news/financing (not actionable)."""
    summary_lower = summary.lower()
    return any(kw.lower() in summary_lower for kw in NEWS_KEYWORDS)


def check_resource_fit(requirements: dict | None = None) -> tuple[bool, str]:
    """Check if resource requirements fit current machine (4GB RAM, 2 cores).

    Args:
        requirements: {
            "ram_gb": int,
            "cpu_cores": int,
            "gpu": bool,
        }

    Returns:
        (fits: bool, reason: str)
    """
    if not requirements:
        return True, "No specific requirements"

    ram = requirements.get("ram_gb", 0)
    if ram > MAX_RAM_GB:
        return False, f"Requires {ram}GB RAM, but machine has only {MAX_RAM_GB}GB"

    cores = requirements.get("cpu_cores", 0)
    if cores > MAX_CPU_CORES:
        return False, f"Requires {cores} CPU cores, but machine has only {MAX_CPU_CORES}"

    if requirements.get("gpu", False):
        return False, "Requires GPU, but machine has none"

    return True, "Resource requirements fit"


def check_dependency_weight(dependencies: list[str] | None = None) -> tuple[bool, str]:
    """Check if dependencies are too heavy for current environment.

    Args:
        dependencies: List of required packages

    Returns:
        (acceptable: bool, reason: str)
    """
    if not dependencies:
        return True, "No dependencies"

    heavy_found = [dep for dep in dependencies if dep.lower() in HEAVY_DEPS]
    if heavy_found:
        return False, f"Requires heavy dependencies: {', '.join(heavy_found)}"
    return True, "Dependencies are lightweight"


def check_architecture_suitability(description: str) -> tuple[bool, str]:
    """Check if architecture is suitable for personal use.

    Args:
        description: Project description

    Returns:
        (suitable: bool, reason: str)
    """
    desc_lower = description.lower()
    for arch in UNSUITABLE_ARCHS:
        if arch.lower() in desc_lower:
            return False, f"Architecture '{arch}' is overkill for personal use"
    return True, "Architecture is suitable"


def check_memory_overlap(topic: str, summary: str) -> bool:
    """Check if similar work already exists in X-Memory.

    Args:
        topic: Proposal topic
        summary: Detailed summary

    Returns:
        True if overlap detected
    """
    try:
        from memory_retrieval import search
        results = search(topic, limit=5)
        for r in results:
            topic_lower = topic.lower()
            content_lower = r.get("content", "").lower()
            if topic_lower in content_lower or any(
                kw in content_lower for kw in topic_lower.split()[:3]
            ):
                return True
        return False
    except Exception:
        return False


def critical_review(proposal: dict) -> dict:
    """Review an external learning proposal for feasibility.

    Args:
        proposal: {
            "id": str,
            "summary": str,
            "description": str (optional, detailed),
            "dependencies": list[str] (optional),
            "resource_requirements": dict (optional, {ram_gb, cpu_cores, gpu}),
            "architecture": str (optional),
            "priority": str (optional, P0/P1/P2),
        }

    Returns:
        {
            "verdict": "APPROVE" | "REJECT" | "APPROVE_WITH_CAUTION",
            "critique_points": list[str],
            "questions_for_builder": list[str],
        }
    """
    print(f"👨\u200d⚖️ Critic Engine: Reviewing '{proposal.get('id', 'unknown')}'...")

    summary = proposal.get("summary", "")
    description = proposal.get("description", summary)
    deps = proposal.get("dependencies", [])
    resources = proposal.get("resource_requirements")
    architecture = proposal.get("architecture", "")

    critique_points = []
    verdict = "APPROVE"
    questions = []

    # Rule 0: Filter pure news/financing
    if is_pure_news(summary):
        return {
            "verdict": "REJECT",
            "critique_points": ["❌ REJECT: Pure news/financing, not actionable."],
            "questions_for_builder": [],
        }

    # Rule 1: Resource fit (4GB RAM, 2 cores, no GPU)
    fits, reason = check_resource_fit(resources)
    if not fits:
        critique_points.append(f"❌ REJECT: {reason}")
        verdict = "REJECT"

    # Rule 2: Dependency weight
    dep_ok, dep_reason = check_dependency_weight(deps)
    if not dep_ok:
        critique_points.append(f"⚠️ WARNING: {dep_reason}")
        if verdict == "APPROVE":
            verdict = "APPROVE_WITH_CAUTION"

    # Rule 3: Architecture suitability
    arch_ok, arch_reason = check_architecture_suitability(architecture or description)
    if not arch_ok:
        critique_points.append(f"❌ REJECT: {arch_reason}")
        verdict = "REJECT"

    # Rule 4: Redundancy check
    if check_memory_overlap(proposal.get("id", ""), summary):
        critique_points.append("❌ REJECT: Similar work already exists in memory.")
        verdict = "REJECT"

    # Rule 5: Value clarity
    if len(summary) < 20:
        critique_points.append("❓ QUERY: Summary too vague. What problem does this solve?")
        questions.append("Can you clarify the specific problem and expected benefit?")

    result = {
        "verdict": verdict,
        "critique_points": critique_points if critique_points else ["✅ Passed all feasibility checks."],
        "questions_for_builder": questions,
    }

    print(f"  📝 Verdict: {result['verdict']}")
    for point in result["critique_points"]:
        print(f"     {point}")
    if questions:
        print(f"  ❓ Questions: {questions}")

    return result


def review_external_learning(learning_note: dict) -> dict:
    """Review an external learning note for software feasibility.

    Args:
        learning_note: {
            "title": str,
            "summary": str,
            "description": str,
            "dependencies": list[str],
            "resource_requirements": dict,
            "architecture": str,
            "landing_priority": str,
        }

    Returns:
        Critic review result
    """
    proposal = {
        "id": learning_note.get("title", ""),
        "summary": learning_note.get("summary", ""),
        "description": learning_note.get("description", ""),
        "dependencies": learning_note.get("dependencies", []),
        "resource_requirements": learning_note.get("resource_requirements"),
        "architecture": learning_note.get("architecture", ""),
        "priority": learning_note.get("landing_priority", ""),
    }
    return critical_review(proposal)


if __name__ == "__main__":
    # Test cases
    print("="*60)
    print("Test 1: Heavy dependency (torch)")
    print("="*60)
    r = critical_review({
        "id": "test_torch",
        "summary": "Use MiroThinker with full torch backend",
        "dependencies": ["torch", "cuda"],
    })
    print(f"Result: {r['verdict']}\n")

    print("="*60)
    print("Test 2: Pure financing news")
    print("="*60)
    r = critical_review({
        "id": "test_funding",
        "summary": "Skild AI raises $1.4B Series C led by Softbank",
    })
    print(f"Result: {r['verdict']}\n")

    print("="*60)
    print("Test 3: Feasible lightweight project")
    print("="*60)
    r = critical_review({
        "id": "test_lightweight",
        "summary": "Interactive scaling for agent performance using RL feedback",
        "dependencies": ["numpy"],
        "architecture": "single-process Python script",
    })
    print(f"Result: {r['verdict']}\n")
