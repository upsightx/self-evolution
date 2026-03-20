#!/usr/bin/env python3
"""Tests for classify_task and recommend_for_description in model_router."""

import sys
import os

# Ensure the module is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_router import classify_task, recommend_for_description, TASK_KEYWORDS


def run_tests():
    passed = 0
    failed = 0

    def assert_eq(actual, expected, msg=""):
        nonlocal passed, failed
        if actual == expected:
            passed += 1
            print(f"  ✓ {msg}")
        else:
            failed += 1
            print(f"  ✗ FAIL: {msg}\n    expected: {expected}\n    actual:   {actual}")

    def assert_true(cond, msg=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  ✓ {msg}")
        else:
            failed += 1
            print(f"  ✗ FAIL: {msg}")

    # ── Test 1: Required classification cases ────────────────────────────
    print("Test 1: classify_task — required cases")

    assert_eq(classify_task("帮我写一个Python脚本处理CSV"), "coding",
              '"帮我写一个Python脚本处理CSV" → coding')

    assert_eq(classify_task("搜索最近的AI论文"), "research",
              '"搜索最近的AI论文" → research')

    assert_eq(classify_task("把这个文件备份一下"), "file_ops",
              '"把这个文件备份一下" → file_ops')

    assert_eq(classify_task("重构memory_db模块"), "refactor",
              '"重构memory_db模块" → refactor')

    assert_eq(classify_task("创建一个新的skill"), "skill_creation",
              '"创建一个新的skill" → skill_creation')

    assert_eq(classify_task("今天天气怎么样"), "general",
              '"今天天气怎么样" → general')

    # ── Test 2: Edge cases ───────────────────────────────────────────────
    print("\nTest 2: classify_task — edge cases")

    assert_eq(classify_task(""), "general", "empty string → general")
    assert_eq(classify_task("   "), "general", "whitespace → general")
    assert_eq(classify_task("hello world"), "general", "unrelated English → general")

    # Case insensitivity
    assert_eq(classify_task("Fix a BUG in the API"), "coding",
              '"Fix a BUG in the API" → coding (case insensitive)')

    assert_eq(classify_task("创建SKILL.md文件"), "skill_creation",
              '"创建SKILL.md文件" → skill_creation')

    # ── Test 3: Multi-keyword disambiguation ─────────────────────────────
    print("\nTest 3: classify_task — multi-keyword disambiguation")

    # "写代码实现一个函数" hits coding 3 times (写代码, 实现, 函数)
    result = classify_task("写代码实现一个函数")
    assert_eq(result, "coding", '"写代码实现一个函数" → coding (3 keyword hits)')

    # "搜索并整理收集资料" hits research 3 times
    result = classify_task("搜索并整理收集资料")
    assert_eq(result, "research", '"搜索并整理收集资料" → research (3 keyword hits)')

    # ── Test 4: recommend_for_description ────────────────────────────────
    print("\nTest 4: recommend_for_description")

    rec = recommend_for_description("帮我写一个Python脚本处理CSV")
    assert_eq(rec["task_type"], "coding", "recommend: task_type is coding")
    assert_true("model" in rec, "recommend: has model")
    assert_true("alias" in rec, "recommend: has alias")
    assert_true("confidence" in rec, "recommend: has confidence")
    assert_eq(rec["confidence"], 0.9, "recommend: keyword hit → confidence 0.9")

    rec_general = recommend_for_description("今天天气怎么样")
    assert_eq(rec_general["task_type"], "general", "recommend: general task_type")
    assert_eq(rec_general["confidence"], 0.3, "recommend: general → confidence 0.3")

    # ── Test 5: All strategies work ──────────────────────────────────────
    print("\nTest 5: recommend_for_description — strategies")

    for strategy in ("cost", "quality", "balanced"):
        rec = recommend_for_description("写代码", strategy=strategy)
        assert_eq(rec["task_type"], "coding",
                  f"strategy={strategy}: task_type is coding")
        assert_true(rec["model"] in ("opus", "minimax", "sonnet", "glm5"),
                    f"strategy={strategy}: model is valid")

    # ── Test 6: TASK_KEYWORDS coverage ───────────────────────────────────
    print("\nTest 6: TASK_KEYWORDS — every category has at least one keyword that works")

    for task_type, keywords in TASK_KEYWORDS.items():
        # Use the first keyword as a test input
        result = classify_task(keywords[0])
        assert_eq(result, task_type,
                  f'keyword "{keywords[0]}" → {task_type}')

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"\n{'='*50}")
    if failed == 0:
        print(f"ALL TESTS PASSED ({passed} assertions)")
    else:
        print(f"FAILED: {failed} assertions failed, {passed} passed")
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
