#!/usr/bin/env python3
"""
Template Evolution Module — thin wrapper.

Core logic has been merged into feedback_loop.py.
This file exists for backward compatibility only.

Usage:
    python3 template_evolution.py analyze coding
    python3 template_evolution.py suggest coding
    python3 template_evolution.py report
"""
from __future__ import annotations

import json
import sys

# Re-export from feedback_loop
from feedback_loop import (
    analyze_template_effectiveness,
    evolve_report,
    generate_template_improvements as suggest_improvements,
)


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 template_evolution.py analyze <task_type>")
        print("  python3 template_evolution.py suggest <task_type>")
        print("  python3 template_evolution.py report")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "analyze":
        if len(sys.argv) < 3:
            print("Usage: python3 template_evolution.py analyze <task_type>")
            sys.exit(1)
        result = analyze_template_effectiveness(sys.argv[2])
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif cmd == "suggest":
        if len(sys.argv) < 3:
            print("Usage: python3 template_evolution.py suggest <task_type>")
            sys.exit(1)
        suggestions = suggest_improvements(sys.argv[2])
        if not suggestions:
            print("无改进建议（数据不足或表现良好）")
        else:
            for i, s in enumerate(suggestions, 1):
                print(f"  {i}. {s}")

    elif cmd == "report":
        print(evolve_report())

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
