#!/usr/bin/env python3
"""Tests for skill_discovery.py"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from skill_discovery import (
    parse_failures, analyze_capability_gaps, suggest_skills,
    generate_report, _load_bugfix_observations,
)


def run_tests():
    passed = 0
    failed = 0

    def _assert(cond, msg):
        nonlocal passed, failed
        if cond:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL: {msg}")

    with tempfile.TemporaryDirectory() as tmpdir:
        failures_md = os.path.join(tmpdir, "failures.md")
        Path(failures_md).write_text("""# 失败案例库

## 案例

### [2026-03-10] Docker 部署失败
- **Context:** 在 Docker 容器中部署应用
- **Action:** 运行 docker build
- **Result:** 构建失败，缺少依赖
- **Root Cause:** Dockerfile 配置错误
- **Lesson:** 需要更好的 Docker 技能
- **Prevention:** 使用 deploy-helper skill

### [2026-03-11] API 限流问题
- **Context:** 调用外部 API 时遇到 rate_limit
- **Action:** 连续发送请求
- **Result:** 全部被限流 timeout
- **Root Cause:** 没有限流策略
- **Lesson:** 需要 rate limit 和 timeout 处理
- **Prevention:** 添加重试逻辑

### [2026-03-12] 数据库查询超时
- **Context:** 查询 database 时超时
- **Action:** 执行复杂 SQL
- **Result:** timeout 错误
- **Root Cause:** 缺少索引
- **Lesson:** 需要 database 优化知识
- **Prevention:** 添加索引和监控 monitor
""", encoding="utf-8")

        stats_json = os.path.join(tmpdir, "agent-stats.json")
        stats_data = {
            "stats": {
                "by_task_type": {
                    "coding": {"total": 0, "success": 0, "fail": 0},
                    "testing": {"total": 10, "success": 3, "fail": 7},
                    "deploy": {"total": 5, "success": 1, "fail": 4},
                },
                "by_model": {},
                "recent": [],
            }
        }
        Path(stats_json).write_text(json.dumps(stats_data), encoding="utf-8")

        db_file = os.path.join(tmpdir, "memory.db")
        conn = sqlite3.connect(db_file)
        conn.execute("""CREATE TABLE observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, timestamp TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'change',
            title TEXT NOT NULL, narrative TEXT,
            facts TEXT, concepts TEXT, source TEXT,
            verified INTEGER DEFAULT 0, tags TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.execute("INSERT INTO observations (timestamp, type, title, narrative, facts) VALUES (?, ?, ?, ?, ?)",
            ("2026-03-10T10:00:00", "bugfix", "Docker build fix", "Fixed docker deploy issue with auth config", "docker,auth"))
        conn.execute("INSERT INTO observations (timestamp, type, title, narrative, facts) VALUES (?, ?, ?, ?, ?)",
            ("2026-03-11T10:00:00", "bugfix", "API parse error", "Fixed api response parse failure", "api,parse"))
        conn.execute("INSERT INTO observations (timestamp, type, title, narrative, facts) VALUES (?, ?, ?, ?, ?)",
            ("2026-03-12T10:00:00", "change", "Unrelated change", "Not a bugfix", ""))
        conn.commit()
        conn.close()

        print("Test 1: parse_failures")
        failures = parse_failures(failures_md)
        _assert(len(failures) == 3, f"Expected 3 failures, got {len(failures)}")
        _assert(failures[0]["date"] == "2026-03-10", f"Wrong date")
        _assert("Docker" in failures[0]["title"], f"Wrong title")

        print("Test 2: analyze_capability_gaps")
        stats = json.loads(Path(stats_json).read_text())
        bugfix_obs = _load_bugfix_observations(db_file)
        _assert(len(bugfix_obs) == 2, f"Expected 2 bugfix obs, got {len(bugfix_obs)}")
        gaps = analyze_capability_gaps(failures, stats, bugfix_obs)
        _assert(len(gaps) > 0, "Expected at least one gap")
        gap_areas = [g["gap_area"] for g in gaps]
        _assert("docker" in gap_areas, f"Expected 'docker' in gaps")
        _assert("deploy" in gap_areas, f"Expected 'deploy' in gaps")

        print("Test 3: suggest_skills")
        suggestions = suggest_skills(gaps)
        _assert(len(suggestions) > 0, "Expected at least one suggestion")
        skill_names = [s["suggested_skill"] for s in suggestions]
        _assert("docker-essentials" in skill_names, f"Expected docker-essentials")
        priorities = [s["priority"] for s in suggestions]
        _assert(priorities == sorted(priorities), "Should be sorted by priority")

        print("Test 4: generate_report")
        report = generate_report(failures_md, stats_json, db_file)
        _assert("# Skill Discovery Report" in report, "Missing header")
        _assert("Capability Gaps" in report, "Missing gaps section")
        _assert("docker" in report.lower(), "Should mention docker")

        print("Test 5: edge cases")
        empty_gaps = analyze_capability_gaps([], {}, [])
        _assert(len(empty_gaps) == 0, "No data → no gaps")
        empty_suggestions = suggest_skills([])
        _assert(len(empty_suggestions) == 0, "No gaps → no suggestions")

    print(f"\nResults: {passed} passed, {failed} failed")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
