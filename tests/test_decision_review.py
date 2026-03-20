#!/usr/bin/env python3
"""Tests for decision_review.py"""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from decision_review import (
    get_unreviewed_decisions, record_review, get_review_history,
    review_stats, generate_review_prompt, generate_review_report,
)


def run_tests():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    try:
        conn = sqlite3.connect(str(tmp_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                title TEXT NOT NULL,
                decision TEXT NOT NULL,
                rejected_alternatives TEXT,
                rationale TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decision_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id INTEGER NOT NULL,
                review_date TEXT NOT NULL,
                outcome TEXT NOT NULL,
                evidence TEXT,
                would_change INTEGER DEFAULT 0,
                lessons TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (decision_id) REFERENCES decisions(id)
            )
        """)

        now = datetime.now()
        decisions_data = [
            (now - timedelta(days=30), "Use SQLite for memory", "Store structured memory in SQLite",
             json.dumps(["JSON files", "PostgreSQL"]), "Simple, zero-dep, portable"),
            (now - timedelta(days=20), "Python over Node", "Use Python for agent scripts",
             json.dumps(["Node.js", "Go"]), "Better ML ecosystem"),
            (now - timedelta(days=10), "Skill-based architecture", "Organize capabilities as skills",
             json.dumps(["Monolithic", "Plugin system"]), "Modular and composable"),
            (now - timedelta(days=3), "Too recent decision", "This should not appear with min_age_days=7",
             json.dumps(["Alt A"]), "Testing age filter"),
            (now - timedelta(days=15), "Use markdown for docs", "Write docs in markdown format",
             json.dumps(["RST", "AsciiDoc"]), "Universal support"),
        ]
        for ts, title, decision, alts, rationale in decisions_data:
            conn.execute(
                "INSERT INTO decisions (timestamp, title, decision, rejected_alternatives, rationale) VALUES (?,?,?,?,?)",
                (ts.isoformat(), title, decision, alts, rationale)
            )
        conn.commit()
        conn.close()

        # Test 1
        unreviewed = get_unreviewed_decisions(min_age_days=7, limit=10, db_path=tmp_path)
        assert len(unreviewed) == 4, f"Expected 4 unreviewed (age>=7), got {len(unreviewed)}"
        titles = [d["title"] for d in unreviewed]
        assert "Too recent decision" not in titles
        assert unreviewed[0]["title"] == "Use SQLite for memory"
        assert all("age_days" in d for d in unreviewed)
        print("✓ Test 1: get_unreviewed_decisions filters correctly")

        # Test 2
        rid = record_review(1, "validated", evidence="Works great", would_change=False,
                            lessons="SQLite is solid", db_path=tmp_path)
        assert rid is not None and rid > 0
        unreviewed2 = get_unreviewed_decisions(min_age_days=7, limit=10, db_path=tmp_path)
        assert len(unreviewed2) == 3
        print("✓ Test 2: record_review reduces unreviewed count")

        # Test 3
        try:
            record_review(2, "bad_outcome", db_path=tmp_path)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        print("✓ Test 3: invalid outcome raises ValueError")

        # Test 4
        record_review(2, "partially_validated", would_change=True, lessons="Node might be faster", db_path=tmp_path)
        record_review(3, "validated", evidence="Skills work well", db_path=tmp_path)
        history = get_review_history(db_path=tmp_path)
        assert len(history) == 3
        history_filtered = get_review_history(decision_id=1, db_path=tmp_path)
        assert len(history_filtered) == 1
        print("✓ Test 4: get_review_history works correctly")

        # Test 5
        s = review_stats(db_path=tmp_path)
        assert s["total_decisions"] == 5
        assert s["reviewed"] == 3
        assert s["unreviewed"] == 2
        assert s["outcome_distribution"].get("validated") == 2
        assert s["would_change_count"] == 1
        assert s["regret_rate"] > 0
        print("✓ Test 5: review_stats correct")

        # Test 6
        prompt = generate_review_prompt(unreviewed[0])
        assert "Decision Review" in prompt
        assert unreviewed[0]["title"] in prompt
        print("✓ Test 6: generate_review_prompt contains necessary info")

        # Test 7
        report = generate_review_report(db_path=tmp_path)
        assert "Decision Review Report" in report
        assert "Summary" in report
        print("✓ Test 7: generate_review_report returns valid markdown")

        print("\nALL TESTS PASSED")

    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    run_tests()
