#!/usr/bin/env python3
"""
LRU Memory Cache Strategy Module.

Track access frequency for memories, identify hot/cold records,
suggest archival candidates, and generate access heatmaps.

Zero dependencies. Python 3.8+ and SQLite only.
"""

import sqlite3
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "memory.db"

SUPPORTED_TABLES = ("observations", "decisions")


def _get_db(db_path=None):
    db = sqlite3.connect(str(db_path or DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def ensure_columns(db_path=None):
    """Idempotently add access_count and last_accessed columns to both tables."""
    db = _get_db(db_path)
    for table in SUPPORTED_TABLES:
        for col, typedef in [("access_count", "INTEGER DEFAULT 0"), ("last_accessed", "TEXT")]:
            try:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
    db.commit()
    db.close()


def record_access(record_id, table="observations", db_path=None):
    """Record one access, incrementing access_count and updating last_accessed."""
    if table not in SUPPORTED_TABLES:
        raise ValueError(f"Invalid table: {table}. Valid: {SUPPORTED_TABLES}")
    db = _get_db(db_path)
    ensure_columns(db_path)
    now = datetime.now().isoformat()
    cur = db.execute(
        f"UPDATE {table} SET access_count = COALESCE(access_count, 0) + 1, last_accessed = ? WHERE id = ?",
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
        title_col = "title"
        rows = db.execute(
            f"SELECT id, '{table}' as tbl, {title_col}, "
            f"COALESCE(access_count, 0) as access_count, last_accessed, created_at "
            f"FROM {table} WHERE COALESCE(access_count, 0) > 0 "
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
        rows = db.execute(
            f"SELECT id, '{table}' as tbl, title, "
            f"COALESCE(access_count, 0) as access_count, last_accessed, created_at "
            f"FROM {table} "
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
        for r in db.execute(
            f"SELECT SUBSTR(last_accessed, 1, 7) as month, SUM(COALESCE(access_count, 0)) as total "
            f"FROM {table} WHERE last_accessed IS NOT NULL GROUP BY month"
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
        _run_tests()
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


# ============ Tests ============

def _run_tests():
    import tempfile
    import os

    tmp = tempfile.mkdtemp()
    test_db = Path(tmp) / "test_memory.db"

    try:
        # 1. Init schema (replicate from memory_db.py)
        db = sqlite3.connect(str(test_db))
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'change',
                title TEXT NOT NULL,
                narrative TEXT,
                facts TEXT,
                concepts TEXT,
                source TEXT,
                verified INTEGER DEFAULT 0,
                tags TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                title TEXT NOT NULL,
                decision TEXT NOT NULL,
                rejected_alternatives TEXT,
                rationale TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        db.commit()

        # 2. Insert test data — old records (created 60 days ago)
        old_ts = (datetime.now() - timedelta(days=60)).isoformat()
        old_created = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute(
            "INSERT INTO observations (id, timestamp, type, title, created_at) VALUES (1, ?, 'discovery', 'Old finding', ?)",
            (old_ts, old_created),
        )
        db.execute(
            "INSERT INTO observations (id, timestamp, type, title, created_at) VALUES (2, ?, 'bugfix', 'Old bugfix', ?)",
            (old_ts, old_created),
        )
        # Recent record (created 2 days ago — should be excluded from cold)
        recent_ts = (datetime.now() - timedelta(days=2)).isoformat()
        recent_created = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute(
            "INSERT INTO observations (id, timestamp, type, title, created_at) VALUES (3, ?, 'change', 'Recent change', ?)",
            (recent_ts, recent_created),
        )
        # Decision records
        db.execute(
            "INSERT INTO decisions (id, timestamp, title, decision, created_at) VALUES (1, ?, 'Use SQLite', 'Chose SQLite over Postgres', ?)",
            (old_ts, old_created),
        )
        db.commit()
        db.close()

        print("Test 1: ensure_columns idempotency...")
        ensure_columns(test_db)
        ensure_columns(test_db)  # second call should not raise
        # Verify columns exist
        db = sqlite3.connect(str(test_db))
        db.row_factory = sqlite3.Row
        cols_obs = {r[1] for r in db.execute("PRAGMA table_info(observations)").fetchall()}
        cols_dec = {r[1] for r in db.execute("PRAGMA table_info(decisions)").fetchall()}
        assert "access_count" in cols_obs, "access_count missing in observations"
        assert "last_accessed" in cols_obs, "last_accessed missing in observations"
        assert "access_count" in cols_dec, "access_count missing in decisions"
        assert "last_accessed" in cols_dec, "last_accessed missing in decisions"
        db.close()
        print("  PASSED")

        print("Test 2: record_access increments count...")
        assert record_access(1, "observations", db_path=test_db) is True
        assert record_access(1, "observations", db_path=test_db) is True
        assert record_access(1, "observations", db_path=test_db) is True
        db = sqlite3.connect(str(test_db))
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT access_count, last_accessed FROM observations WHERE id=1").fetchone()
        assert row["access_count"] == 3, f"Expected 3, got {row['access_count']}"
        assert row["last_accessed"] is not None
        db.close()
        # Access decision too
        record_access(1, "decisions", db_path=test_db)
        print("  PASSED")

        print("Test 3: record_access returns False for missing id...")
        assert record_access(9999, "observations", db_path=test_db) is False
        print("  PASSED")

        print("Test 4: get_hot_memories...")
        hot = get_hot_memories(limit=10, db_path=test_db)
        assert len(hot) > 0, "Expected hot memories"
        assert hot[0]["access_count"] == 3, f"Top hot should have count=3, got {hot[0]['access_count']}"
        assert hot[0]["table"] == "observations"
        # Check decision is also in hot list
        tables_in_hot = {r["table"] for r in hot}
        assert "decisions" in tables_in_hot, "Decisions should appear in hot memories"
        print(f"  PASSED ({len(hot)} hot memories)")

        print("Test 5: get_cold_memories...")
        cold = get_cold_memories(days_unused=30, limit=50, db_path=test_db)
        cold_ids = [(r["table"], r["id"]) for r in cold]
        # id=1 obs was accessed (hot), should NOT be cold
        assert ("observations", 1) not in cold_ids, "Accessed record should not be cold"
        # id=2 obs was never accessed and is old, should be cold
        assert ("observations", 2) in cold_ids, "Old unaccessed record should be cold"
        # id=3 obs is recent (2 days), should be excluded
        assert ("observations", 3) not in cold_ids, "Recent record should be excluded from cold"
        print(f"  PASSED ({len(cold)} cold memories)")

        print("Test 6: suggest_archive...")
        archive = suggest_archive(days_unused=30, db_path=test_db)
        assert isinstance(archive, list)
        assert len(archive) > 0
        print(f"  PASSED ({len(archive)} archive candidates)")

        print("Test 7: memory_heatmap...")
        hm = memory_heatmap(db_path=test_db)
        assert "by_type" in hm
        assert "by_month" in hm
        assert isinstance(hm["by_type"], dict)
        assert isinstance(hm["by_month"], dict)
        # discovery type should have access_count=3
        assert hm["by_type"].get("discovery", 0) == 3, f"Expected discovery=3, got {hm['by_type']}"
        assert len(hm["by_month"]) > 0, "by_month should have entries"
        print(f"  PASSED (types={list(hm['by_type'].keys())}, months={list(hm['by_month'].keys())})")

        print("Test 8: invalid table raises ValueError...")
        try:
            record_access(1, "nonexistent", db_path=test_db)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        print("  PASSED")

        print("\nALL TESTS PASSED")

    finally:
        # Cleanup
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    _cli()
