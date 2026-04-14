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
# Note: External learning already filters these, kept for defense-in-depth
NEWS_KEYWORDS = [
    "funding", "funded", "raises", "raised", "series", "investment",
    "融资", "轮", "估值", "领投", "跟投", "战略投资",
]


def is_pure_news(summary: str) -> bool:
    """Check if proposal is pure news/financing.

    Note: External learning should already filter these.
    This is a defense-in-depth check.
    """
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
    return True, "Dependencies are acceptable"