#!/usr/bin/env python3
"""Tests for model_router.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from model_router import (
    calculate_success_rate, recommend_model, cost_report,
    routing_table, MODELS, classify_task, recommend_for_description,
)


def run_tests():
    passed = 0
    failed = 0

    def assert_eq(actual, expected, msg=""):
        nonlocal passed, failed
        if actual == expected:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL: {msg}\n    expected: {expected}\n    actual:   {actual}")

    def assert_true(cond, msg=""):
        nonlocal passed, failed
        if cond:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL: {msg}")

    def assert_close(actual, expected, tol=0.001, msg=""):
        nonlocal passed, failed
        if actual is not None and abs(actual - expected) < tol:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL: {msg}\n    expected: ~{expected}\n    actual:   {actual}")

    mock_stats = {
        "recent": [
            {"time": "t01", "model": "opus", "task_type": "coding", "success": True, "label": "a"},
            {"time": "t02", "model": "opus", "task_type": "coding", "success": True, "label": "b"},
            {"time": "t03", "model": "opus", "task_type": "coding", "success": True, "label": "c"},
            {"time": "t04", "model": "opus", "task_type": "coding", "success": True, "label": "d"},
            {"time": "t05", "model": "opus", "task_type": "coding", "success": False, "label": "e"},
            {"time": "t06", "model": "minimax", "task_type": "coding", "success": True, "label": "f"},
            {"time": "t07", "model": "minimax", "task_type": "coding", "success": True, "label": "g"},
            {"time": "t08", "model": "minimax", "task_type": "coding", "success": True, "label": "h"},
            {"time": "t09", "model": "minimax", "task_type": "coding", "success": False, "label": "i"},
            {"time": "t10", "model": "sonnet", "task_type": "coding", "success": True, "label": "j"},
            {"time": "t11", "model": "sonnet", "task_type": "coding", "success": True, "label": "k"},
            {"time": "t12", "model": "sonnet", "task_type": "coding", "success": True, "label": "l"},
            {"time": "t13", "model": "glm5", "task_type": "coding", "success": True, "label": "m"},
            {"time": "t14", "model": "glm5", "task_type": "coding", "success": True, "label": "n"},
            {"time": "t15", "model": "opus", "task_type": "research", "success": True, "label": "o"},
            {"time": "t16", "model": "opus", "task_type": "research", "success": True, "label": "p"},
            {"time": "t17", "model": "opus", "task_type": "research", "success": True, "label": "q"},
            {"time": "t18", "model": "opus", "task_type": "research", "success": False, "label": "r"},
            {"time": "t19", "model": "minimax", "task_type": "research", "success": True, "label": "s"},
            {"time": "t20", "model": "minimax", "task_type": "research", "success": True, "label": "t"},
            {"time": "t21", "model": "minimax", "task_type": "research", "success": True, "label": "u"},
            {"time": "t22", "model": "minimax", "task_type": "research", "success": True, "label": "v"},
            {"time": "t23", "model": "sonnet", "task_type": "research", "success": True, "label": "w"},
            {"time": "t24", "model": "sonnet", "task_type": "research", "success": False, "label": "x"},
            {"time": "t25", "model": "sonnet", "task_type": "research", "success": True, "label": "y"},
            {"time": "t26", "model": "sonnet", "task_type": "research", "success": True, "label": "z"},
        ],
    }

    print("Test 1: calculate_success_rate")
    assert_close(calculate_success_rate(mock_stats, model="opus"), 7 / 9, msg="opus overall")
    assert_close(calculate_success_rate(mock_stats, model="minimax"), 7 / 8, msg="minimax overall")
    assert_close(calculate_success_rate(mock_stats, model="opus", task_type="coding"), 0.8, msg="opus coding")
    assert_close(calculate_success_rate(mock_stats, model="minimax", task_type="coding"), 0.75, msg="minimax coding")
    assert_close(calculate_success_rate(mock_stats, model="sonnet", task_type="coding"), 1.0, msg="sonnet coding")
    assert_eq(calculate_success_rate(mock_stats, model="glm5", task_type="coding"), None, msg="glm5 insufficient")
    assert_close(calculate_success_rate(mock_stats, task_type="coding"), 12 / 14, msg="coding overall")
    assert_close(calculate_success_rate(mock_stats), 22 / 26, msg="overall")
    print(f"  {passed} passed")

    print("Test 2: recommend_model priorities")
    rec_quality = recommend_model("coding", priority="quality", stats=mock_stats)
    assert_eq(rec_quality["model"], "sonnet", msg="coding quality → sonnet")
    rec_cost = recommend_model("coding", priority="cost", stats=mock_stats)
    assert_eq(rec_cost["model"], "sonnet", msg="coding cost → sonnet")
    rec_rq = recommend_model("research", priority="quality", stats=mock_stats)
    assert_eq(rec_rq["model"], "minimax", msg="research quality → minimax")
    rec_rc = recommend_model("research", priority="cost", stats=mock_stats)
    assert_eq(rec_rc["model"], "minimax", msg="research cost → minimax")
    rec_rb = recommend_model("research", priority="balanced", stats=mock_stats)
    assert_eq(rec_rb["model"], "minimax", msg="research balanced → minimax")
    rec_cb = recommend_model("coding", priority="balanced", stats=mock_stats)
    assert_eq(rec_cb["model"], "minimax", msg="coding balanced → minimax")
    for key in ("model", "alias", "estimated_success_rate", "estimated_cost", "reason"):
        assert_true(key in rec_quality, msg=f"has '{key}'")
    print(f"  {passed} passed total")

    print("Test 3: cost_report")
    report = cost_report(mock_stats)
    assert_true("by_model" in report, msg="has by_model")
    assert_true("total_tasks" in report, msg="has total_tasks")
    assert_eq(report["cheapest_model_scenario"]["model"], "minimax", msg="cheapest is minimax")
    assert_eq(report["premium_model_scenario"]["model"], "opus", msg="premium is opus")
    for model_name in MODELS:
        assert_true(model_name in report["by_model"], msg=f"has {model_name}")
    assert_true(report["cheapest_model_scenario"]["potential_savings"] >= 0, msg="savings >= 0")
    print(f"  {passed} passed total")

    print("Test 4: routing_table")
    table = routing_table(mock_stats)
    for tt in ("coding", "research", "file_ops", "refactor", "skill_creation"):
        assert_true(tt in table, msg=f"has {tt}")
    for tt, priorities in table.items():
        for prio in ("cost", "quality", "balanced"):
            assert_true(prio in priorities, msg=f"{tt} has {prio}")
            assert_true("model" in priorities[prio], msg=f"{tt}/{prio} has model")
    print(f"  {passed} passed total")

    print("Test 5: fallback behavior")
    rec_unknown = recommend_model("unknown_task", stats=mock_stats)
    assert_eq(rec_unknown["model"], "opus", msg="unknown → opus")
    assert_eq(rec_unknown["estimated_success_rate"], None, msg="unknown rate None")
    rec_fileops = recommend_model("file_ops", stats=mock_stats)
    assert_eq(rec_fileops["model"], "minimax", msg="file_ops → minimax")
    print(f"  {passed} passed total")

    print("Test 6: edge cases")
    empty_stats = {"recent": []}
    assert_eq(calculate_success_rate(empty_stats, model="opus"), None, msg="empty → None")
    rec_empty = recommend_model("coding", stats=empty_stats)
    assert_eq(rec_empty["model"], "opus", msg="empty → opus default")
    report_empty = cost_report(empty_stats)
    assert_eq(report_empty["total_tasks"], 0, msg="empty total = 0")
    table_empty = routing_table(empty_stats)
    assert_true(len(table_empty) > 0, msg="empty table not empty")
    print(f"  {passed} passed total")

    print("Test 7: classify_task")
    assert_eq(classify_task("写代码实现一个函数"), "coding", msg="coding classification")
    assert_eq(classify_task("搜索调研AI趋势"), "research", msg="research classification")
    assert_eq(classify_task("重构优化代码"), "refactor", msg="refactor classification")
    assert_eq(classify_task(""), "general", msg="empty → general")
    print(f"  {passed} passed total")

    print("Test 8: recommend_for_description")
    rec = recommend_for_description("写一个Python爬虫脚本")
    assert_true("task_type" in rec, msg="has task_type")
    assert_true("model" in rec, msg="has model")
    assert_true("confidence" in rec, msg="has confidence")
    print(f"  {passed} passed total")

    print(f"\n{'='*50}")
    if failed == 0:
        print(f"ALL TESTS PASSED ({passed} assertions)")
    else:
        print(f"FAILED: {failed} assertions failed, {passed} passed")
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
