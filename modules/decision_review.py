#!/usr/bin/env python3
"""Decision Review System — review past decisions and track outcomes."""

import argparse
import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from db_common import DB_PATH

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
    # Only count reviews that reference existing decisions
    reviewed = conn.execute(
        "SELECT COUNT(DISTINCT dr.decision_id) FROM decision_reviews dr "
        "INNER JOIN decisions d ON dr.decision_id = d.id"
    ).fetchone()[0]
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
        print("Tests moved to tests/test_decision_review.py — run: python3 tests/test_decision_review.py")

    else:
        parser.print_help()


if __name__ == "__main__":
    cli()
