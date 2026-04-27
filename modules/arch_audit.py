#!/usr/bin/env python3
"""Architecture audit helper — detect legacy writes, dead targets, governor bypasses."""

import sys

from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path, module_dir, module_workspace

_workspace = ensure_workspace_on_path()
_modules = module_dir()
ensure_xmemory_on_path()


def audit() -> dict:
    """Run architecture health checks.

    Returns:
        {"healthy": bool, "issues": list[str], "warnings": list[str]}
    """
    issues = []
    warnings = []

    # 1. Dead target files
    try:
        from auto_evolve import _TASK_TARGET_MAP
        for task_type, target in _TASK_TARGET_MAP.items():
            if not (_workspace / target).exists():
                issues.append(f"Dead target: {target} (task_type={task_type})")
    except Exception as e:
        warnings.append(f"Target audit skipped: {e}")

    # 2. Legacy imports in active modules
    deprecated = ["feedback_loop", "change_applier", "improvement_suggestions", "usage_stats"]
    for py_file in _modules.glob("*.py"):
        if "deprecated" in py_file.name or py_file.name == "arch_audit.py":
            continue
        try:
            lines = py_file.read_text().split("\n")
            for i, line in enumerate(lines, 1):
                s = line.strip()
                if s.startswith("#"):
                    continue
                for dep in deprecated:
                    if f"from {dep} " in s or f"import {dep}" in s:
                        issues.append(f"Legacy import: {py_file.name}:{i} → {dep}")
        except Exception:
            pass

    # 3. Governor bypass rate
    _db_reachable = False
    try:
        from db_common import get_db
        db = get_db()
        total = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        _db_reachable = True
        with_lineage = db.execute("SELECT COUNT(DISTINCT observation_id) FROM memory_lineage").fetchone()[0]
        db.close()
        if total > 10:
            bypass = total - with_lineage
            rate = round(bypass / total * 100, 1)
            if rate > 50:
                warnings.append(f"Governor bypass: {rate}% observations lack lineage ({bypass}/{total})")
    except Exception as e:
        issues.append(f"DB unreachable — audit incomplete: {e}")

    # 4. Legacy evolution_changes writes (should be read-only)
    if _db_reachable:
        try:
            from db_common import get_db
            db = get_db()
            recent = db.execute(
                "SELECT COUNT(*) FROM evolution_changes WHERE applied_at > datetime('now', '-1 day')"
            ).fetchone()[0]
            db.close()
            if recent > 0:
                warnings.append(f"Legacy table: {recent} recent writes to evolution_changes (should be read-only)")
        except Exception:
            pass

    # 5. Schema version
    schema_version = None
    if _db_reachable:
        try:
            from db_common import get_db
            db = get_db()
            row = db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            schema_version = row[0] if row else None
            db.close()
            if schema_version is None:
                warnings.append("No schema_migrations table — run schema versioning")
        except Exception:
            pass

    return {"healthy": len(issues) == 0, "issues": issues, "warnings": warnings, "schema_version": schema_version}


if __name__ == "__main__":
    import json
    result = audit()
    icon = "✅" if result["healthy"] else "❌"
    print(f"{icon} Architecture health: {'healthy' if result['healthy'] else 'issues found'}")
    if result.get("schema_version"):
        print(f"  📋 Schema version: v{result['schema_version']}")
    for i in result["issues"]:
        print(f"  ❌ {i}")
    for w in result["warnings"]:
        print(f"  ⚠️ {w}")
    if not result["issues"] and not result["warnings"]:
        print("  All clear!")
