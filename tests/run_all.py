#!/usr/bin/env python3
"""Run all self-evolution module tests."""
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
FAILURES = []


def run_test(name):
    path = TESTS_DIR / name
    print(f"\n{'='*60}")
    print(f"Running {name}...")
    print('='*60)
    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(TESTS_DIR.parent),
        capture_output=False,
    )
    if result.returncode != 0:
        FAILURES.append(name)
    return result.returncode == 0


def main():
    test_files = sorted(TESTS_DIR.glob("test_*.py"))
    total = len(test_files)
    passed = 0

    for tf in test_files:
        if run_test(tf.name):
            passed += 1

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed}/{total} test files passed")
    if FAILURES:
        print(f"FAILED: {', '.join(FAILURES)}")
        sys.exit(1)
    else:
        print("ALL TEST FILES PASSED ✅")


if __name__ == "__main__":
    main()
