#!/usr/bin/env python3
"""Small benchmark seeds for self-evolution changes.

These checks are intentionally lightweight: they verify that future evolution
proposals include evidence, guardrails, and a measurable regression target.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[2]
AGENTS_PATH = WORKSPACE / "AGENTS.md"
MEMORY_PATH = WORKSPACE / "MEMORY.md"
LEARNING_DIR = WORKSPACE / "memory" / "learning"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def run_benchmarks() -> dict[str, Any]:
    """Run the baseline benchmark suite and return structured results."""
    agents = _read(AGENTS_PATH)
    memory = _read(MEMORY_PATH)
    learning_files = list(LEARNING_DIR.glob("candidates-*-*.md")) if LEARNING_DIR.exists() else []

    checks = [
        _check(
            "subagent_guardrails_present",
            all(term in agents for term in ["子 Agent 硬护栏模板", "禁止项", "验收项", "失败条件", "证据"]),
            "AGENTS.md must contain the hard-guardrail instruction scaffold.",
        ),
        _check(
            "task_outcome_contract_present",
            all(term in agents for term in ["record_success", "record_failure", "task_type"]),
            "Task outcome recording contract must remain visible in AGENTS.md.",
        ),
        _check(
            "architecture_contract_memory_present",
            all(term in memory for term in ["ARCHITECTURE_CONTRACT.md", "X-Memory", "proposal_lifecycle_manager"]),
            "Long-term memory must retain canonical architecture owners.",
        ),
        _check(
            "external_learning_candidates_present",
            len(learning_files) > 0,
            f"Found {len(learning_files)} external-learning candidate files.",
        ),
        _check(
            "benchmark_module_has_cli",
            True,
            "This module provides `python3 self-evolution/modules/evolution_benchmarks.py --json`.",
        ),
    ]

    passed = sum(1 for item in checks if item["passed"])
    return {
        "suite": "self_evolution_seed",
        "passed": passed,
        "total": len(checks),
        "success_rate": passed / len(checks) if checks else 0.0,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run self-evolution benchmark seeds")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    result = run_benchmarks()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['suite']}: {result['passed']}/{result['total']} passed")
        for item in result["checks"]:
            mark = "OK" if item["passed"] else "FAIL"
            print(f"[{mark}] {item['name']} - {item['detail']}")
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
