#!/usr/bin/env python3
"""
Self-Evolution Engine - Structured Memory Database
SQLite + FTS5 full-text search with progressive disclosure retrieval.

Inspired by claude-mem's memory design and Lore's decision recording protocol.
"""

import sqlite3
import json
import os
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.environ.get("SELF_EVOLUTION_DB", Path(__file__).parent / "memory.db"))


def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init_db():
    """Initialize the structured memory database."""
    db = get_db()
    db.executescript("""
        -- Structured observations (core table)
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
            files_related TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Session summaries
        CREATE TABLE IF NOT EXISTS session_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            timestamp TEXT NOT NULL,
            request TEXT,
            investigated TEXT,
            learned TEXT,
            completed TEXT,
            next_steps TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Decision records (Lore protocol inspired)
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            title TEXT NOT NULL,
            decision TEXT NOT NULL,
            rejected_alternatives TEXT,
            rationale TEXT,
            constraints TEXT,
            verification TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- FTS5 full-text search indexes
        CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(
            title, narrative, facts, concepts,
            content=observations,
            content_rowid=id
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
            title, decision, rejected_alternatives, rationale,
            content=decisions,
            content_rowid=id
        );

        -- Triggers: auto-sync FTS indexes
        CREATE TRIGGER IF NOT EXISTS observations_ai AFTER INSERT ON observations BEGIN
            INSERT INTO observations_fts(rowid, title, narrative, facts, concepts)
            VALUES (new.id, new.title, new.narrative, new.facts, new.concepts);
        END;

        CREATE TRIGGER IF NOT EXISTS observations_ad AFTER DELETE ON observations BEGIN
            INSERT INTO observations_fts(observations_fts, rowid, title, narrative, facts, concepts)
            VALUES ('delete', old.id, old.title, old.narrative, old.facts, old.concepts);
        END;

        CREATE TRIGGER IF NOT EXISTS decisions_ai AFTER INSERT ON decisions BEGIN
            INSERT INTO decisions_fts(rowid, title, decision, rejected_alternatives, rationale)
            VALUES (new.id, new.title, new.decision, new.rejected_alternatives, new.rationale);
        END;

        CREATE TRIGGER IF NOT EXISTS decisions_ad AFTER DELETE ON decisions BEGIN
            INSERT INTO decisions_fts(decisions_fts, rowid, title, decision, rejected_alternatives, rationale)
            VALUES ('delete', old.id, old.title, old.decision, old.rejected_alternatives, old.rationale);
        END;
    """)
    db.commit()
    db.close()
    print(f"Database initialized at {DB_PATH}")


# ============ Write Operations ============

def add_observation(type, title, narrative=None, facts=None, concepts=None,
                    source=None, files_related=None, session_id=None):
    """
    Add a structured observation record.
    
    Types: decision, bugfix, feature, refactor, discovery, change
    """
    db = get_db()
    db.execute("""
        INSERT INTO observations (session_id, timestamp, type, title, narrative, 
                                  facts, concepts, source, files_related)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id,
        datetime.now().isoformat(),
        type, title, narrative,
        json.dumps(facts, ensure_ascii=False) if facts else None,
        json.dumps(concepts, ensure_ascii=False) if concepts else None,
        source,
        json.dumps(files_related, ensure_ascii=False) if files_related else None
    ))
    db.commit()
    rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return rid


def add_decision(title, decision, rejected_alternatives=None, rationale=None,
                 constraints=None, verification=None):
    """
    Add a decision record (Lore protocol inspired).
    
    Records not just what was decided, but why, and what was rejected.
    """
    db = get_db()
    db.execute("""
        INSERT INTO decisions (timestamp, title, decision, rejected_alternatives, 
                               rationale, constraints, verification)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        title, decision,
        json.dumps(rejected_alternatives, ensure_ascii=False) if rejected_alternatives else None,
        rationale, constraints, verification
    ))
    db.commit()
    rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return rid


def add_session_summary(request, investigated=None, learned=None,
                        completed=None, next_steps=None, session_id=None):
    """Add a session summary."""
    db = get_db()
    db.execute("""
        INSERT INTO session_summaries (session_id, timestamp, request, investigated, 
                                       learned, completed, next_steps)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (session_id, datetime.now().isoformat(), request, investigated,
          learned, completed, next_steps))
    db.commit()
    db.close()


# ============ Progressive Disclosure Retrieval ============

def search_l1(query=None, type=None, limit=20):
    """
    L1 Index Retrieval: returns id + title + type + timestamp
    Cheapest layer (~50 tokens per result).
    
    Uses dual-path search: FTS5 for English tokens + LIKE for CJK/mixed content.
    """
    db = get_db()
    if query:
        seen = set()
        results = []
        
        # Path 1: FTS5 (good for English words separated by spaces/punctuation)
        try:
            fts_rows = db.execute("""
                SELECT o.id, o.type, o.title, o.timestamp
                FROM observations_fts f
                JOIN observations o ON f.rowid = o.id
                WHERE observations_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, limit)).fetchall()
            for r in fts_rows:
                if r['id'] not in seen:
                    seen.add(r['id'])
                    results.append(dict(r))
        except Exception:
            pass  # FTS5 match syntax error — fall through to LIKE
        
        # Path 2: LIKE (catches CJK, mixed content, partial matches)
        like_pattern = f"%{query}%"
        like_rows = db.execute("""
            SELECT id, type, title, timestamp FROM observations
            WHERE title LIKE ? OR narrative LIKE ? OR facts LIKE ? OR concepts LIKE ?
            ORDER BY timestamp DESC LIMIT ?
        """, (like_pattern, like_pattern, like_pattern, like_pattern, limit)).fetchall()
        for r in like_rows:
            if r['id'] not in seen:
                seen.add(r['id'])
                results.append(dict(r))
        
        rows = results[:limit]
    else:
        where = "WHERE type = ?" if type else ""
        params = [type, limit] if type else [limit]
        rows = [dict(r) for r in db.execute(f"""
            SELECT id, type, title, timestamp FROM observations
            {where}
            ORDER BY timestamp DESC LIMIT ?
        """, params).fetchall()]
    db.close()
    return rows


def search_l2(ids):
    """
    L2 Context Retrieval: returns narrative + facts
    Medium cost (~200 tokens per result).
    """
    db = get_db()
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(f"""
        SELECT id, type, title, narrative, facts, timestamp
        FROM observations WHERE id IN ({placeholders})
        ORDER BY timestamp DESC
    """, ids).fetchall()
    db.close()
    return [dict(r) for r in rows]


def search_l3(id):
    """
    L3 Full Retrieval: returns all fields
    Most expensive (~500 tokens per result).
    """
    db = get_db()
    row = db.execute("SELECT * FROM observations WHERE id = ?", (id,)).fetchone()
    db.close()
    return dict(row) if row else None


def search_decisions(query=None, limit=20):
    """Search decision records. Dual-path: FTS5 + LIKE."""
    db = get_db()
    if query:
        seen = set()
        results = []
        
        # Path 1: FTS5
        try:
            fts_rows = db.execute("""
                SELECT d.id, d.title, d.decision, d.rationale, 
                       d.rejected_alternatives, d.timestamp
                FROM decisions_fts f
                JOIN decisions d ON f.rowid = d.id
                WHERE decisions_fts MATCH ?
                ORDER BY rank LIMIT ?
            """, (query, limit)).fetchall()
            for r in fts_rows:
                if r['id'] not in seen:
                    seen.add(r['id'])
                    results.append(dict(r))
        except Exception:
            pass
        
        # Path 2: LIKE
        like_pattern = f"%{query}%"
        like_rows = db.execute("""
            SELECT id, title, decision, rationale, rejected_alternatives, timestamp
            FROM decisions
            WHERE title LIKE ? OR decision LIKE ? OR rationale LIKE ? OR rejected_alternatives LIKE ?
            ORDER BY timestamp DESC LIMIT ?
        """, (like_pattern, like_pattern, like_pattern, like_pattern, limit)).fetchall()
        for r in like_rows:
            if r['id'] not in seen:
                seen.add(r['id'])
                results.append(dict(r))
        
        rows = results[:limit]
    else:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM decisions ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()]
    db.close()
    return rows


def search_summaries(query=None, limit=10):
    """Search session summaries."""
    db = get_db()
    if query:
        rows = db.execute("""
            SELECT * FROM session_summaries 
            WHERE request LIKE ? OR learned LIKE ? OR completed LIKE ?
            ORDER BY timestamp DESC LIMIT ?
        """, (f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM session_summaries ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def stats():
    """Get database statistics."""
    db = get_db()
    obs_count = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    dec_count = db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    sum_count = db.execute("SELECT COUNT(*) FROM session_summaries").fetchone()[0]
    type_stats = db.execute(
        "SELECT type, COUNT(*) as cnt FROM observations GROUP BY type ORDER BY cnt DESC"
    ).fetchall()
    db.close()
    return {
        "observations": obs_count,
        "decisions": dec_count,
        "summaries": sum_count,
        "by_type": {r["type"]: r["cnt"] for r in type_stats}
    }


# ============ Bulk Import ============

def import_json(data):
    """
    Import structured data from JSON (used by compression agents).
    
    Expected format:
    {
        "observations": [{"type": "...", "title": "...", ...}],
        "decisions": [{"title": "...", "decision": "...", ...}],
        "summary": "..."
    }
    """
    imported = {"observations": 0, "decisions": 0, "summaries": 0}
    
    for obs in data.get("observations", []):
        add_observation(
            type=obs.get("type", "change"),
            title=obs["title"],
            narrative=obs.get("narrative"),
            facts=obs.get("facts"),
            concepts=obs.get("concepts")
        )
        imported["observations"] += 1
    
    for dec in data.get("decisions", []):
        add_decision(
            title=dec["title"],
            decision=dec["decision"],
            rejected_alternatives=dec.get("rejected_alternatives"),
            rationale=dec.get("rationale")
        )
        imported["decisions"] += 1
    
    if data.get("summary"):
        add_session_summary(request=data["summary"])
        imported["summaries"] += 1
    
    return imported


# ============ CLI ============

def main():
    if len(sys.argv) < 2:
        print("""Self-Evolution Memory Database

Usage: memory_db.py <command> [args]

Commands:
  init                          Initialize database
  add <type> <title> [narrative] Add observation
  decision <title> <decision> [rejected] [rationale]  Add decision
  search [query]                L1 search (index only)
  l2 <id1> [id2] ...           L2 search (with context)
  l3 <id>                      L3 search (full details)
  decisions [query]             Search decisions
  summaries [query]             Search session summaries
  stats                         Show statistics
  import <json_file>            Import from JSON file

Environment:
  SELF_EVOLUTION_DB             Database path (default: ./memory.db)
""")
        return

    cmd = sys.argv[1]

    if cmd == "init":
        init_db()

    elif cmd == "add":
        if len(sys.argv) < 4:
            print("Usage: memory_db.py add <type> <title> [narrative]")
            print("Types: decision, bugfix, feature, refactor, discovery, change")
            return
        type_ = sys.argv[2]
        title = sys.argv[3]
        narrative = sys.argv[4] if len(sys.argv) > 4 else None
        rid = add_observation(type_, title, narrative)
        print(f"Added observation #{rid}: [{type_}] {title}")

    elif cmd == "decision":
        if len(sys.argv) < 4:
            print("Usage: memory_db.py decision <title> <decision> [rejected] [rationale]")
            return
        title = sys.argv[2]
        decision = sys.argv[3]
        rejected = sys.argv[4] if len(sys.argv) > 4 else None
        rationale = sys.argv[5] if len(sys.argv) > 5 else None
        rid = add_decision(
            title, decision,
            rejected_alternatives=[rejected] if rejected else None,
            rationale=rationale
        )
        print(f"Added decision #{rid}: {title}")

    elif cmd == "search":
        query = sys.argv[2] if len(sys.argv) > 2 else None
        results = search_l1(query)
        if not results:
            print("No results found.")
            return
        for r in results:
            print(f"  #{r['id']} [{r['type']}] {r['title']} ({r['timestamp'][:10]})")

    elif cmd == "l2":
        ids = [int(x) for x in sys.argv[2:]]
        results = search_l2(ids)
        for r in results:
            print(f"\n--- #{r['id']} [{r['type']}] {r['title']} ---")
            if r['narrative']:
                print(f"  {r['narrative']}")
            if r['facts']:
                print(f"  Facts: {r['facts']}")

    elif cmd == "l3":
        id_ = int(sys.argv[2])
        r = search_l3(id_)
        if r:
            print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
        else:
            print(f"Not found: #{id_}")

    elif cmd == "decisions":
        query = sys.argv[2] if len(sys.argv) > 2 else None
        results = search_decisions(query)
        if not results:
            print("No decisions found.")
            return
        for r in results:
            print(f"\n--- #{r['id']} {r['title']} ({r['timestamp'][:10]}) ---")
            print(f"  Decision: {r['decision']}")
            if r.get('rejected_alternatives'):
                print(f"  Rejected: {r['rejected_alternatives']}")
            if r.get('rationale'):
                print(f"  Rationale: {r['rationale']}")

    elif cmd == "summaries":
        query = sys.argv[2] if len(sys.argv) > 2 else None
        results = search_summaries(query)
        if not results:
            print("No summaries found.")
            return
        for r in results:
            print(f"\n--- Session ({r['timestamp'][:10]}) ---")
            print(f"  Request: {r['request']}")
            if r.get('learned'):
                print(f"  Learned: {r['learned']}")
            if r.get('completed'):
                print(f"  Completed: {r['completed']}")

    elif cmd == "stats":
        s = stats()
        print(json.dumps(s, indent=2, ensure_ascii=False))

    elif cmd == "import":
        if len(sys.argv) < 3:
            print("Usage: memory_db.py import <json_file>")
            return
        with open(sys.argv[2]) as f:
            data = json.load(f)
        result = import_json(data)
        print(f"Imported: {result}")

    else:
        print(f"Unknown command: {cmd}")
        print("Run without arguments for help.")


if __name__ == "__main__":
    main()
