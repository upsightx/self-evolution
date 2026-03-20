#!/usr/bin/env python3
"""
LRU Memory Cache Strategy Module.

Track access frequency for memories, identify hot/cold records,
suggest archival candidates, and generate access heatmaps.

Zero dependencies. Python 3.8+ and SQLite only.
"""

from __future__ import annotations

import sqlite3
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from db_common import DB_PATH, get_db as _get_db_common

SUPPORTED_TABLES = ("observations", "decisions")

# Safe table name mapping — prevents SQL injection via f-string table names
_SAFE_TABLE = {t: t for t in SUPPORTED_TABLES}


def _safe_table(table: str) -> str:
    """Validate and return safe table name. Raises ValueError if invalid."""
    if table not in _SAFE_TABLE:
        raise ValueError(f"Invalid table: {table}. Valid: {SUPPORTED_TABLES}")
    return _SAFE_TABLE[table]


def _get_db(db_path=None):
    if db_path:
        db = sqlite3.connect(str(db_path))
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db
    return _get_db_common()


def ensure_columns(db_path=None):
    """Idempotently add access_count and last_accessed columns to both tables."""
    db = _get_db(db_path)
    for table in SUPPORTED_TABLES:
        tbl = _safe_table(table)
        for col, typedef in [("access_count", "INTEGER DEFAULT 0"), ("last_accessed", "TEXT")]:
            try:
                db.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
    db.commit()
    db.close()


def record_access(record_id, table="observations", db_path=None):
    """Record one access, incrementing access_count and updating last_accessed."""
    tbl = _safe_table(table)
    db = _get_db(db_path)
    ensure_columns(db_path)
    now = datetime.now().isoformat()
    cur = db.execute(
        f"UPDATE {tbl} SET access_count = COALESCE(access_count, 0) + 1, last_accessed = ? WHERE id = ?",
        (now, record_id),
    )
    db.commit()
    updated = cur.rowcount
    db.close()
    return updated > 0


def get_hot_memories(limit=20, db_path=None):
    """Get most frequently accessed memories across observations and decisions."""
    db = _get_db(db_path)
    ensure_columns(db_path)
    results = []
    for table in SUPPORTED_TABLES:
        tbl = _safe_table(table)
        title_col = "title"
        rows = db.execute(
            f"SELECT id, '{tbl}' as tbl, {title_col}, "
            f"COALESCE(access_count, 0) as access_count, last_accessed, created_at "
            f"FROM {tbl} WHERE COALESCE(access_count, 0) > 0 "
            f"ORDER BY access_count DESC LIMIT ?",
            (limit,),
        ).fetchall()
        for r in rows:
            results.append({
                "id": r["id"],
                "table": r["tbl"],
                "title": r[title_col],
                "access_count": r["access_count"],
                "last_accessed": r["last_accessed"],
                "created_at": r["created_at"],
            })
    results.sort(key=lambda x: x["access_count"], reverse=True)
    db.close()
    return results[:limit]


def get_cold_memories(days_unused=30, limit=50, db_path=None):
    """Get memories not accessed in days_unused days, excluding records created in last 7 days."""
    db = _get_db(db_path)
    ensure_columns(db_path)
    cutoff = (datetime.now() - timedelta(days=days_unused)).isoformat()
    recent_cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    results = []
    for table in SUPPORTED_TABLES:
        tbl = _safe_table(table)
        rows = db.execute(
            f"SELECT id, '{tbl}' as tbl, title, "
            f"COALESCE(access_count, 0) as access_count, last_accessed, created_at "
            f"FROM {tbl} "
            f"WHERE (last_accessed IS NULL OR last_accessed < ?) "
            f"AND created_at < ? "
            f"ORDER BY created_at ASC LIMIT ?",
            (cutoff, recent_cutoff, limit),
        ).fetchall()
        for r in rows:
            results.append({
                "id": r["id"],
                "table": r["tbl"],
                "title": r["title"],
                "access_count": r["access_count"],
                "last_accessed": r["last_accessed"],
                "created_at": r["created_at"],
            })
    results.sort(key=lambda x: x["created_at"] or "")
    db.close()
    return results[:limit]


def suggest_archive(days_unused=30, db_path=None):
    """Suggest cold memories for archival."""
    return get_cold_memories(days_unused=days_unused, limit=50, db_path=db_path)


def memory_heatmap(db_path=None):
    """Return access heatmap data grouped by type and by month."""
    db = _get_db(db_path)
    ensure_columns(db_path)

    # by_type: sum access_count per observation type
    by_type = {}
    for r in db.execute(
        "SELECT type, SUM(COALESCE(access_count, 0)) as total "
        "FROM observations GROUP BY type"
    ).fetchall():
        by_type[r["type"]] = r["total"]

    # by_month: sum access_count per month across both tables
    by_month = {}
    for table in SUPPORTED_TABLES:
        tbl = _safe_table(table)
        for r in db.execute(
            f"SELECT SUBSTR(last_accessed, 1, 7) as month, SUM(COALESCE(access_count, 0)) as total "
            f"FROM {tbl} WHERE last_accessed IS NOT NULL GROUP BY month"
        ).fetchall():
            m = r["month"]
            if m:
                by_month[m] = by_month.get(m, 0) + r["total"]

    db.close()
    return {"by_type": by_type, "by_month": by_month}


# ============ CLI ============

def _cli():
    usage = """LRU Memory Cache Strategy

Usage: memory_lru.py <command> [args]

  access <table> <id>              Record an access
  hot [--limit 20]                 Show hot memories
  cold [--days 30] [--limit 50]    Show cold memories
  archive-suggest [--days 30]      Suggest archival candidates
  heatmap                          Show access heatmap
  test                             Run tests
"""
    if len(sys.argv) < 2:
        print(usage)
        return

    cmd = sys.argv[1]

    if cmd == "test":
        print("Tests moved to tests/test_memory_lru.py — run: python3 tests/test_memory_lru.py")
        return

    if cmd == "access":
        if len(sys.argv) < 4:
            print("Usage: access <table> <id>")
            return
        ok = record_access(int(sys.argv[3]), table=sys.argv[2])
        print(f"Access recorded: {ok}")

    elif cmd == "hot":
        limit = 20
        if "--limit" in sys.argv:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        for r in get_hot_memories(limit=limit):
            print(f"  #{r['id']} [{r['table']}] {r['title']}  (count={r['access_count']}, last={r['last_accessed']})")

    elif cmd == "cold":
        days, limit = 30, 50
        if "--days" in sys.argv:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        if "--limit" in sys.argv:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        for r in get_cold_memories(days_unused=days, limit=limit):
            print(f"  #{r['id']} [{r['table']}] {r['title']}  (count={r['access_count']}, created={r['created_at']})")

    elif cmd == "archive-suggest":
        days = 30
        if "--days" in sys.argv:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        candidates = suggest_archive(days_unused=days)
        print(f"Archive candidates: {len(candidates)}")
        for r in candidates:
            print(f"  #{r['id']} [{r['table']}] {r['title']}")

    elif cmd == "heatmap":
        hm = memory_heatmap()
        print(json.dumps(hm, indent=2, ensure_ascii=False))

    else:
        print(f"Unknown command: {cmd}")
        print(usage)


if __name__ == "__main__":
    _cli()
