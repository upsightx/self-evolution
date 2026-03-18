#!/usr/bin/env python3
"""Skill Discovery Module — identify capability gaps from failure records and suggest skills."""

import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # project root  # memory/
FAILURES_PATH = BASE_DIR / "failures.md"
STATS_PATH = BASE_DIR / "agent-stats.json"
DB_PATH = Path(__file__).parent / "memory.db"

# keyword → skill suggestion mapping
SKILL_MAP = {
    "docker": {"skill": "docker-essentials", "method": "clawhub"},
    "deploy": {"skill": "deploy-helper", "method": "existing"},
    "git": {"skill": "github", "method": "existing"},
    "test": {"skill": "testing-framework", "method": "create"},
    "monitor": {"skill": "monitoring", "method": "create"},
    "database": {"skill": "db-tools", "method": "clawhub"},
    "api": {"skill": "api-client", "method": "create"},
    "scrape": {"skill": "web-scraper", "method": "create"},
    "schedule": {"skill": "cron-manager", "method": "create"},
    "auth": {"skill": "auth-helper", "method": "create"},
    "rate_limit": {"skill": "rate-limiter", "method": "create"},
    "timeout": {"skill": "timeout-handler", "method": "create"},
    "memory": {"skill": "memory-compress", "method": "existing"},
    "format": {"skill": "formatter", "method": "create"},
    "parse": {"skill": "parser-toolkit", "method": "create"},
}

# Regex pattern to match any SKILL_MAP keyword (word boundaries, case-insensitive)
_KW_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in SKILL_MAP) + r")\b",
    re.IGNORECASE,
)


def parse_failures(failures_md_path: str) -> list[dict]:
    """Parse failures.md into structured records."""
    text = Path(failures_md_path).read_text(encoding="utf-8")
    entries: list[dict] = []
    # Split on ### headers
    blocks = re.split(r"^### ", text, flags=re.MULTILINE)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # Header line: [date] title
        header_m = re.match(r"\[(\d{4}-\d{2}-\d{2})\]\s*(.+)", block)
        if not header_m:
            continue
        date_str, title = header_m.group(1), header_m.group(2).strip()
        # Extract fields
        def _field(name: str) -> str:
            m = re.search(
                rf"\*\*{re.escape(name)}:\*\*\s*(.+?)(?=\n- \*\*|\Z)",
                block,
                re.DOTALL,
            )
            return m.group(1).strip() if m else ""

        entries.append({
            "date": date_str,
            "title": title,
            "context": _field("Context"),
            "action": _field("Action"),
            "result": _field("Result"),
            "root_cause": _field("Root Cause"),
            "lesson": _field("Lesson"),
            "prevention": _field("Prevention"),
        })
    return entries


def _extract_keywords(text: str) -> list[str]:
    """Extract SKILL_MAP keywords from text."""
    found = _KW_PATTERN.findall(text.lower())
    return list(set(found))


def _load_bugfix_observations(db_path: str) -> list[dict]:
    """Load bugfix observations from memory.db."""
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT title, narrative, facts FROM observations WHERE type='bugfix'"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def analyze_capability_gaps(
    failures: list[dict],
    stats: dict,
    bugfix_obs: list[dict] | None = None,
) -> list[dict]:
    """Analyze capability gaps from failures, stats, and bugfix observations."""
    # Count keyword evidence from failures
    kw_evidence: dict[str, dict] = {}  # keyword -> {count, sources set}

    for f in failures:
        blob = " ".join(
            f.get(k, "") for k in ("title", "context", "action", "result", "root_cause", "lesson")
        )
        for kw in _extract_keywords(blob):
            entry = kw_evidence.setdefault(kw, {"count": 0, "sources": set()})
            entry["count"] += 1
            entry["sources"].add("failures")

    # Count from bugfix observations
    for obs in bugfix_obs or []:
        blob = " ".join(str(obs.get(k, "") or "") for k in ("title", "narrative", "facts"))
        for kw in _extract_keywords(blob):
            entry = kw_evidence.setdefault(kw, {"count": 0, "sources": set()})
            entry["count"] += 1
            entry["sources"].add("bugfix_db")

    # Find low success-rate task types from stats
    by_task = stats.get("stats", stats).get("by_task_type", {})
    for task_type, data in by_task.items():
        total = data.get("total", 0)
        success = data.get("success", 0)
        if total == 0:
            # Zero attempts = potential gap
            for kw in _extract_keywords(task_type):
                entry = kw_evidence.setdefault(kw, {"count": 0, "sources": set()})
                entry["count"] += 1
                entry["sources"].add("stats_zero")
        elif total > 0 and (success / total) < 0.5:
            for kw in _extract_keywords(task_type):
                entry = kw_evidence.setdefault(kw, {"count": 0, "sources": set()})
                entry["count"] += 2  # weight low success higher
                entry["sources"].add("stats_low_rate")

    # Build gap list
    gaps: list[dict] = []
    for kw, info in sorted(kw_evidence.items(), key=lambda x: -x[1]["count"]):
        count = info["count"]
        severity = "high" if count >= 3 else ("medium" if count >= 2 else "low")
        gaps.append({
            "gap_area": kw,
            "evidence_count": count,
            "sources": sorted(info["sources"]),
            "severity": severity,
        })
    return gaps


def suggest_skills(gaps: list[dict]) -> list[dict]:
    """Suggest skills to acquire based on capability gaps."""
    suggestions: list[dict] = []
    severity_priority = {"high": 1, "medium": 2, "low": 3}
    for gap in gaps:
        area = gap["gap_area"].lower()
        mapping = SKILL_MAP.get(area)
        if not mapping:
            continue
        suggestions.append({
            "gap_area": area,
            "suggested_skill": mapping["skill"],
            "acquisition_method": mapping["method"],
            "priority": severity_priority.get(gap.get("severity", "low"), 3),
        })
    suggestions.sort(key=lambda x: x["priority"])
    return suggestions


def generate_report(
    failures_path: str | None = None,
    stats_path: str | None = None,
    db_path: str | None = None,
) -> str:
    """Generate a full capability gap report in markdown."""
    fp = failures_path or str(FAILURES_PATH)
    sp = stats_path or str(STATS_PATH)
    dp = db_path or str(DB_PATH)

    # Load data
    failures = parse_failures(fp) if os.path.exists(fp) else []
    stats = json.loads(Path(sp).read_text(encoding="utf-8")) if os.path.exists(sp) else {}
    bugfix_obs = _load_bugfix_observations(dp)

    gaps = analyze_capability_gaps(failures, stats, bugfix_obs)
    suggestions = suggest_skills(gaps)

    # Build report
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Skill Discovery Report",
        f"",
        f"Generated: {now}",
        f"",
        f"## Data Sources",
        f"",
        f"- Failure cases: {len(failures)}",
        f"- Bugfix observations: {len(bugfix_obs)}",
        f"- Task types tracked: {len(stats.get('stats', stats).get('by_task_type', {}))}",
        f"",
        f"## Capability Gaps",
        f"",
    ]
    if gaps:
        lines.append("| Area | Evidence | Sources | Severity |")
        lines.append("|------|----------|---------|----------|")
        for g in gaps:
            lines.append(
                f"| {g['gap_area']} | {g['evidence_count']} | {', '.join(g['sources'])} | {g['severity']} |"
            )
    else:
        lines.append("No capability gaps detected.")
    lines += [
        "",
        "## Suggested Skills",
        "",
    ]
    if suggestions:
        lines.append("| Gap | Skill | Method | Priority |")
        lines.append("|-----|-------|--------|----------|")
        prio_label = {1: "🔴 High", 2: "🟡 Medium", 3: "🟢 Low"}
        for s in suggestions:
            lines.append(
                f"| {s['gap_area']} | {s['suggested_skill']} | {s['acquisition_method']} | {prio_label.get(s['priority'], str(s['priority']))} |"
            )
    else:
        lines.append("No skill suggestions at this time.")
    lines.append("")
    return "\n".join(lines)


# ── Tests ──────────────────────────────────────────────────────────────

def _run_tests():
    """Run all tests with temp data. Prints ALL TESTS PASSED on success."""
    import traceback

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
        # ── Create temp failures.md ──
        failures_md = os.path.join(tmpdir, "failures.md")
        Path(failures_md).write_text(
            """# 失败案例库

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
""",
            encoding="utf-8",
        )

        # ── Create temp agent-stats.json ──
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

        # ── Create temp memory.db ──
        db_file = os.path.join(tmpdir, "memory.db")
        conn = sqlite3.connect(db_file)
        conn.execute(
            """CREATE TABLE observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT, timestamp TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'change',
                title TEXT NOT NULL, narrative TEXT,
                facts TEXT, concepts TEXT, source TEXT,
                verified INTEGER DEFAULT 0, tags TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        conn.execute(
            "INSERT INTO observations (timestamp, type, title, narrative, facts) VALUES (?, ?, ?, ?, ?)",
            ("2026-03-10T10:00:00", "bugfix", "Docker build fix", "Fixed docker deploy issue with auth config", "docker,auth"),
        )
        conn.execute(
            "INSERT INTO observations (timestamp, type, title, narrative, facts) VALUES (?, ?, ?, ?, ?)",
            ("2026-03-11T10:00:00", "bugfix", "API parse error", "Fixed api response parse failure", "api,parse"),
        )
        conn.execute(
            "INSERT INTO observations (timestamp, type, title, narrative, facts) VALUES (?, ?, ?, ?, ?)",
            ("2026-03-12T10:00:00", "change", "Unrelated change", "Not a bugfix", ""),
        )
        conn.commit()
        conn.close()

        # ── Test 1: parse_failures ──
        print("Test 1: parse_failures")
        failures = parse_failures(failures_md)
        _assert(len(failures) == 3, f"Expected 3 failures, got {len(failures)}")
        _assert(failures[0]["date"] == "2026-03-10", f"Wrong date: {failures[0].get('date')}")
        _assert("Docker" in failures[0]["title"], f"Wrong title: {failures[0].get('title')}")
        _assert("Docker" in failures[0]["context"], f"Missing context")
        _assert(failures[1]["root_cause"] == "没有限流策略", f"Wrong root_cause: {failures[1].get('root_cause')}")

        # ── Test 2: analyze_capability_gaps ──
        print("Test 2: analyze_capability_gaps")
        stats = json.loads(Path(stats_json).read_text())
        bugfix_obs = _load_bugfix_observations(db_file)
        _assert(len(bugfix_obs) == 2, f"Expected 2 bugfix obs, got {len(bugfix_obs)}")

        gaps = analyze_capability_gaps(failures, stats, bugfix_obs)
        _assert(len(gaps) > 0, "Expected at least one gap")
        gap_areas = [g["gap_area"] for g in gaps]
        _assert("docker" in gap_areas, f"Expected 'docker' in gaps, got {gap_areas}")
        _assert("deploy" in gap_areas, f"Expected 'deploy' in gaps, got {gap_areas}")
        _assert("rate_limit" in gap_areas or "timeout" in gap_areas, f"Expected rate_limit or timeout in gaps")
        # Check severity
        for g in gaps:
            _assert(g["severity"] in ("high", "medium", "low"), f"Invalid severity: {g['severity']}")
            _assert(g["evidence_count"] > 0, f"Evidence count should be > 0")

        # ── Test 3: suggest_skills ──
        print("Test 3: suggest_skills")
        suggestions = suggest_skills(gaps)
        _assert(len(suggestions) > 0, "Expected at least one suggestion")
        skill_names = [s["suggested_skill"] for s in suggestions]
        _assert("docker-essentials" in skill_names, f"Expected docker-essentials, got {skill_names}")
        for s in suggestions:
            _assert(s["acquisition_method"] in ("clawhub", "existing", "create"), f"Invalid method: {s['acquisition_method']}")
            _assert(s["priority"] in (1, 2, 3), f"Invalid priority: {s['priority']}")
        # Check sorted by priority
        priorities = [s["priority"] for s in suggestions]
        _assert(priorities == sorted(priorities), "Suggestions should be sorted by priority")

        # ── Test 4: generate_report ──
        print("Test 4: generate_report")
        report = generate_report(failures_md, stats_json, db_file)
        _assert("# Skill Discovery Report" in report, "Report missing header")
        _assert("Capability Gaps" in report, "Report missing gaps section")
        _assert("Suggested Skills" in report, "Report missing suggestions section")
        _assert("docker" in report.lower(), "Report should mention docker")
        _assert("Failure cases: 3" in report, "Report should show 3 failures")
        _assert("Bugfix observations: 2" in report, "Report should show 2 bugfix obs")

        # ── Test 5: edge cases ──
        print("Test 5: edge cases")
        # Empty failures
        empty_failures = parse_failures(os.path.join(tmpdir, "nonexistent.md")) if os.path.exists(os.path.join(tmpdir, "nonexistent.md")) else []
        _assert(len(empty_failures) == 0, "Empty path should return empty list")
        # Empty gaps
        empty_gaps = analyze_capability_gaps([], {}, [])
        _assert(len(empty_gaps) == 0, "No data should produce no gaps")
        # Empty suggestions
        empty_suggestions = suggest_skills([])
        _assert(len(empty_suggestions) == 0, "No gaps should produce no suggestions")

    print(f"\nResults: {passed} passed, {failed} failed")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        sys.exit(1)


# ── CLI ────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 skill_discovery.py <report|gaps|suggest|test>")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "test":
        _run_tests()
    elif cmd == "report":
        print(generate_report())
    elif cmd == "gaps":
        failures = parse_failures(str(FAILURES_PATH)) if FAILURES_PATH.exists() else []
        stats = json.loads(STATS_PATH.read_text(encoding="utf-8")) if STATS_PATH.exists() else {}
        bugfix_obs = _load_bugfix_observations(str(DB_PATH))
        gaps = analyze_capability_gaps(failures, stats, bugfix_obs)
        for g in gaps:
            print(f"[{g['severity'].upper():6s}] {g['gap_area']} (evidence: {g['evidence_count']}, sources: {', '.join(g['sources'])})")
    elif cmd == "suggest":
        failures = parse_failures(str(FAILURES_PATH)) if FAILURES_PATH.exists() else []
        stats = json.loads(STATS_PATH.read_text(encoding="utf-8")) if STATS_PATH.exists() else {}
        bugfix_obs = _load_bugfix_observations(str(DB_PATH))
        gaps = analyze_capability_gaps(failures, stats, bugfix_obs)
        suggestions = suggest_skills(gaps)
        for s in suggestions:
            print(f"[P{s['priority']}] {s['gap_area']} → {s['suggested_skill']} ({s['acquisition_method']})")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
