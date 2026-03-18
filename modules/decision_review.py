#!/usr/bin/env python3
"""Decision Review System — review past decisions and track outcomes."""

import argparse
import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "memory.db"

VALID_OUTCOMES = ("validated", "partially_validated", "invalidated", "inconclusive")


def _get_conn(db_path=None):
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_table(conn):
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
    conn.commit()


def get_unreviewed_decisions(min_age_days=7, limit=10, db_path=None):
    conn = _get_conn(db_path)
    _ensure_table(conn)
    cutoff = (datetime.now() - timedelta(days=min_age_days)).isoformat()
    rows = conn.execute("""
        SELECT d.id, d.title, d.decision, d.rejected_alternatives,
               d.rationale, d.timestamp,
               CAST(julianday('now') - julianday(d.timestamp) AS INTEGER) AS age_days
        FROM decisions d
        LEFT JOIN decision_reviews dr ON d.id = dr.decision_id
        WHERE dr.id IS NULL AND d.timestamp <= ?
        ORDER BY d.timestamp ASC
        LIMIT ?
    """, (cutoff, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_review(decision_id, outcome, evidence=None, would_change=False, lessons=None, db_path=None):
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"outcome must be one of {VALID_OUTCOMES}, got '{outcome}'")
    conn = _get_conn(db_path)
    _ensure_table(conn)
    cur = conn.execute("""
        INSERT INTO decision_reviews (decision_id, review_date, outcome, evidence, would_change, lessons)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (decision_id, datetime.now().strftime("%Y-%m-%d"), outcome, evidence, int(would_change), lessons))
    conn.commit()
    review_id = cur.lastrowid
    conn.close()
    return review_id


def get_review_history(decision_id=None, limit=20, db_path=None):
    conn = _get_conn(db_path)
    _ensure_table(conn)
    query = """
        SELECT dr.id AS review_id, dr.decision_id, d.title, d.decision,
               dr.review_date, dr.outcome, dr.evidence, dr.would_change, dr.lessons, dr.created_at
        FROM decision_reviews dr
        JOIN decisions d ON dr.decision_id = d.id
    """
    params = []
    if decision_id is not None:
        query += " WHERE dr.decision_id = ?"
        params.append(decision_id)
    query += " ORDER BY dr.created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def review_stats(db_path=None):
    conn = _get_conn(db_path)
    _ensure_table(conn)
    total = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    reviewed = conn.execute("SELECT COUNT(DISTINCT decision_id) FROM decision_reviews").fetchone()[0]
    unreviewed = total - reviewed

    outcome_rows = conn.execute("""
        SELECT outcome, COUNT(*) AS cnt FROM decision_reviews GROUP BY outcome
    """).fetchall()
    outcome_distribution = {r["outcome"]: r["cnt"] for r in outcome_rows}

    would_change_count = conn.execute(
        "SELECT COUNT(*) FROM decision_reviews WHERE would_change = 1"
    ).fetchone()[0]
    total_reviews = conn.execute("SELECT COUNT(*) FROM decision_reviews").fetchone()[0]
    regret_rate = (would_change_count / total_reviews * 100) if total_reviews > 0 else 0.0

    conn.close()
    return {
        "total_decisions": total,
        "reviewed": reviewed,
        "unreviewed": unreviewed,
        "outcome_distribution": outcome_distribution,
        "regret_rate": round(regret_rate, 1),
        "total_reviews": total_reviews,
        "would_change_count": would_change_count,
    }


def generate_review_prompt(decision):
    alts = decision.get("rejected_alternatives") or "N/A"
    if isinstance(alts, str):
        try:
            parsed = json.loads(alts)
            if isinstance(parsed, list):
                alts = "\n".join(f"  - {a}" for a in parsed)
        except (json.JSONDecodeError, TypeError):
            pass

    return f"""## 🔍 Decision Review: {decision['title']}

**Made on:** {decision['timestamp']}  |  **Age:** {decision.get('age_days', '?')} days

**Decision:** {decision['decision']}

**Rationale:** {decision.get('rationale') or 'N/A'}

**Rejected alternatives:**
{alts}

---

### Questions to consider:
1. Was this the right call? What actually happened?
2. Did the rationale hold up?
3. Would you make the same decision today?
4. What evidence supports or contradicts the decision?
5. Any lessons learned?

### Record your review:
```
python3 decision_review.py review {decision['id']} <validated|partially_validated|invalidated|inconclusive> \\
    --evidence "what happened" --lessons "what I learned"
```
"""


def generate_review_report(db_path=None):
    stats = review_stats(db_path)
    history = get_review_history(limit=50, db_path=db_path)
    pending = get_unreviewed_decisions(min_age_days=0, limit=100, db_path=db_path)

    lines = [
        "# 📊 Decision Review Report",
        f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "\n## Summary",
        f"- Total decisions: {stats['total_decisions']}",
        f"- Reviewed: {stats['reviewed']}",
        f"- Unreviewed: {stats['unreviewed']}",
        f"- Total reviews: {stats['total_reviews']}",
        f"- Regret rate: {stats['regret_rate']}%",
    ]

    if stats["outcome_distribution"]:
        lines.append("\n## Outcome Distribution")
        for outcome, cnt in sorted(stats["outcome_distribution"].items()):
            lines.append(f"- {outcome}: {cnt}")

    if history:
        lines.append("\n## Recent Reviews")
        for r in history[:10]:
            change = " ⚠️ would change" if r["would_change"] else ""
            lines.append(f"- **{r['title']}** → {r['outcome']}{change} ({r['review_date']})")
            if r.get("lessons"):
                lines.append(f"  - Lesson: {r['lessons']}")

    if pending:
        lines.append(f"\n## Pending Reviews ({len(pending)})")
        for d in pending[:10]:
            lines.append(f"- [{d['id']}] {d['title']} ({d.get('age_days', '?')} days old)")

    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────

def cli():
    parser = argparse.ArgumentParser(description="Decision Review System")
    sub = parser.add_subparsers(dest="command")

    p_pending = sub.add_parser("pending", help="List unreviewed decisions")
    p_pending.add_argument("--days", type=int, default=7)
    p_pending.add_argument("--limit", type=int, default=10)

    p_review = sub.add_parser("review", help="Record a review")
    p_review.add_argument("decision_id", type=int)
    p_review.add_argument("outcome", choices=VALID_OUTCOMES)
    p_review.add_argument("--evidence", default=None)
    p_review.add_argument("--would-change", action="store_true")
    p_review.add_argument("--lessons", default=None)

    p_history = sub.add_parser("history", help="View review history")
    p_history.add_argument("--decision-id", type=int, default=None)
    p_history.add_argument("--limit", type=int, default=20)

    sub.add_parser("stats", help="Show review statistics")

    p_prompt = sub.add_parser("prompt", help="Generate review prompt")
    p_prompt.add_argument("decision_id", type=int)

    sub.add_parser("report", help="Generate full report")
    sub.add_parser("test", help="Run tests")

    args = parser.parse_args()

    if args.command == "pending":
        results = get_unreviewed_decisions(min_age_days=args.days, limit=args.limit)
        if not results:
            print("No unreviewed decisions found.")
        for d in results:
            print(f"[{d['id']}] {d['title']} ({d.get('age_days', '?')} days old)")
            print(f"     Decision: {d['decision'][:80]}")

    elif args.command == "review":
        rid = record_review(args.decision_id, args.outcome,
                            evidence=args.evidence, would_change=args.would_change, lessons=args.lessons)
        print(f"Review recorded (id={rid})")

    elif args.command == "history":
        results = get_review_history(decision_id=args.decision_id, limit=args.limit)
        if not results:
            print("No reviews found.")
        for r in results:
            print(f"[{r['review_id']}] {r['title']} → {r['outcome']} ({r['review_date']})")

    elif args.command == "stats":
        s = review_stats()
        print(json.dumps(s, indent=2, ensure_ascii=False))

    elif args.command == "prompt":
        conn = _get_conn()
        _ensure_table(conn)
        row = conn.execute("SELECT *, CAST(julianday('now') - julianday(timestamp) AS INTEGER) AS age_days FROM decisions WHERE id = ?", (args.decision_id,)).fetchone()
        conn.close()
        if not row:
            print(f"Decision {args.decision_id} not found.")
            return
        print(generate_review_prompt(dict(row)))

    elif args.command == "report":
        print(generate_review_report())

    elif args.command == "test":
        run_tests()

    else:
        parser.print_help()


# ── Tests ────────────────────────────────────────────────────────────

def run_tests():
    import os
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

        # Insert 5 decisions at different times
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

        # Test 1: get_unreviewed_decisions filters correctly
        unreviewed = get_unreviewed_decisions(min_age_days=7, limit=10, db_path=tmp_path)
        assert len(unreviewed) == 4, f"Expected 4 unreviewed (age>=7), got {len(unreviewed)}"
        # "Too recent" (3 days) should be excluded
        titles = [d["title"] for d in unreviewed]
        assert "Too recent decision" not in titles, "Recent decision should be filtered out"
        # Should be sorted by timestamp ASC (oldest first)
        assert unreviewed[0]["title"] == "Use SQLite for memory", f"Oldest first, got {unreviewed[0]['title']}"
        assert all("age_days" in d for d in unreviewed), "age_days missing"
        print("✓ Test 1: get_unreviewed_decisions filters correctly")

        # Test 2: record_review reduces unreviewed count
        rid = record_review(1, "validated", evidence="Works great", would_change=False,
                            lessons="SQLite is solid", db_path=tmp_path)
        assert rid is not None and rid > 0, f"Expected valid review_id, got {rid}"
        unreviewed2 = get_unreviewed_decisions(min_age_days=7, limit=10, db_path=tmp_path)
        assert len(unreviewed2) == 3, f"Expected 3 after review, got {len(unreviewed2)}"
        print("✓ Test 2: record_review reduces unreviewed count")

        # Test 3: invalid outcome raises
        try:
            record_review(2, "bad_outcome", db_path=tmp_path)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        print("✓ Test 3: invalid outcome raises ValueError")

        # Test 4: record more reviews and check history
        record_review(2, "partially_validated", would_change=True, lessons="Node might be faster", db_path=tmp_path)
        record_review(3, "validated", evidence="Skills work well", db_path=tmp_path)

        history = get_review_history(db_path=tmp_path)
        assert len(history) == 3, f"Expected 3 reviews, got {len(history)}"
        assert all("title" in h for h in history), "title missing from history"

        history_filtered = get_review_history(decision_id=1, db_path=tmp_path)
        assert len(history_filtered) == 1, f"Expected 1 review for decision 1, got {len(history_filtered)}"
        print("✓ Test 4: get_review_history works correctly")

        # Test 5: review_stats
        stats = review_stats(db_path=tmp_path)
        assert stats["total_decisions"] == 5, f"Expected 5 total, got {stats['total_decisions']}"
        assert stats["reviewed"] == 3, f"Expected 3 reviewed, got {stats['reviewed']}"
        assert stats["unreviewed"] == 2, f"Expected 2 unreviewed, got {stats['unreviewed']}"
        assert stats["outcome_distribution"].get("validated") == 2
        assert stats["outcome_distribution"].get("partially_validated") == 1
        assert stats["would_change_count"] == 1
        assert stats["regret_rate"] > 0
        print("✓ Test 5: review_stats correct")

        # Test 6: generate_review_prompt
        prompt = generate_review_prompt(unreviewed[0])
        assert "Decision Review" in prompt, "Missing header"
        assert unreviewed[0]["title"] in prompt, "Missing title"
        assert "Questions to consider" in prompt, "Missing questions"
        print("✓ Test 6: generate_review_prompt contains necessary info")

        # Test 7: generate_review_report
        report = generate_review_report(db_path=tmp_path)
        assert "Decision Review Report" in report, "Missing report header"
        assert "Summary" in report, "Missing summary section"
        assert "Outcome Distribution" in report, "Missing outcome distribution"
        assert "validated" in report
        print("✓ Test 7: generate_review_report returns valid markdown")

        print("\nALL TESTS PASSED")

    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    cli()
