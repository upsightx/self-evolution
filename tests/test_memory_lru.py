#!/usr/bin/env python3
"""Tests for memory_lru.py"""
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from memory_lru import (
    ensure_columns, record_access, get_hot_memories,
    get_cold_memories, suggest_archive, memory_heatmap,
)


def run_tests():
    tmp = tempfile.mkdtemp()
    test_db = Path(tmp) / "test_memory.db"

    try:
        db = sqlite3.connect(str(test_db))
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT, timestamp TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'change', title TEXT NOT NULL,
                narrative TEXT, facts TEXT, concepts TEXT, source TEXT,
                verified INTEGER DEFAULT 0, tags TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL, title TEXT NOT NULL,
                decision TEXT NOT NULL, rejected_alternatives TEXT,
                rationale TEXT, created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        db.commit()

        old_ts = (datetime.now() - timedelta(days=60)).isoformat()
        old_created = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute("INSERT INTO observations (id, timestamp, type, title, created_at) VALUES (1, ?, 'discovery', 'Old finding', ?)", (old_ts, old_created))
        db.execute("INSERT INTO observations (id, timestamp, type, title, created_at) VALUES (2, ?, 'bugfix', 'Old bugfix', ?)", (old_ts, old_created))
        recent_ts = (datetime.now() - timedelta(days=2)).isoformat()
        recent_created = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute("INSERT INTO observations (id, timestamp, type, title, created_at) VALUES (3, ?, 'change', 'Recent change', ?)", (recent_ts, recent_created))
        db.execute("INSERT INTO decisions (id, timestamp, title, decision, created_at) VALUES (1, ?, 'Use SQLite', 'Chose SQLite over Postgres', ?)", (old_ts, old_created))
        db.commit()
        db.close()

        print("Test 1: ensure_columns idempotency...")
        ensure_columns(test_db)
        ensure_columns(test_db)
        db = sqlite3.connect(str(test_db))
        cols_obs = {r[1] for r in db.execute("PRAGMA table_info(observations)").fetchall()}
        assert "access_count" in cols_obs and "last_accessed" in cols_obs
        db.close()
        print("  PASSED")

        print("Test 2: record_access increments count...")
        assert record_access(1, "observations", db_path=test_db) is True
        assert record_access(1, "observations", db_path=test_db) is True
        assert record_access(1, "observations", db_path=test_db) is True
        db = sqlite3.connect(str(test_db))
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT access_count FROM observations WHERE id=1").fetchone()
        assert row["access_count"] == 3
        db.close()
        record_access(1, "decisions", db_path=test_db)
        print("  PASSED")

        print("Test 3: record_access returns False for missing id...")
        assert record_access(9999, "observations", db_path=test_db) is False
        print("  PASSED")

        print("Test 4: get_hot_memories...")
        hot = get_hot_memories(limit=10, db_path=test_db)
        assert len(hot) > 0 and hot[0]["access_count"] == 3
        print(f"  PASSED ({len(hot)} hot memories)")

        print("Test 5: get_cold_memories...")
        cold = get_cold_memories(days_unused=30, limit=50, db_path=test_db)
        cold_ids = [(r["table"], r["id"]) for r in cold]
        assert ("observations", 1) not in cold_ids
        assert ("observations", 2) in cold_ids
        assert ("observations", 3) not in cold_ids
        print(f"  PASSED ({len(cold)} cold memories)")

        print("Test 6: suggest_archive...")
        archive = suggest_archive(days_unused=30, db_path=test_db)
        assert isinstance(archive, list) and len(archive) > 0
        print(f"  PASSED ({len(archive)} archive candidates)")

        print("Test 7: memory_heatmap...")
        hm = memory_heatmap(db_path=test_db)
        assert "by_type" in hm and "by_month" in hm
        assert hm["by_type"].get("discovery", 0) == 3
        print(f"  PASSED")

        print("Test 8: invalid table raises ValueError...")
        try:
            record_access(1, "nonexistent", db_path=test_db)
            assert False
        except ValueError:
            pass
        print("  PASSED")

        print("\nALL TESTS PASSED")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    run_tests()
