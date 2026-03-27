#!/usr/bin/env python3
"""
Structured Memory Store — 自我进化记忆系统的存储层。

职责：CRUD + 查询。不做检索排序，不做 embedding，不做上下文拼接。

新增字段：
- observations.tags（逗号分隔字符串）
- observations.task_type（任务类型：coding/research/file_ops/reasoning）
- decisions.triggered_by_obs_id（触发该决策的观察ID）
- decisions.supersedes_decision_id（覆盖的旧决策ID）

向后兼容：原有接口保持不变，新增 search() 支持标签和时间过滤。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from db_common import DB_PATH, get_db


# ============ Schema ============

def init_db():
    """Initialize or migrate the database."""
    db = get_db()

    # Get existing columns
    obs_cols = {r[1] for r in db.execute("PRAGMA table_info(observations)").fetchall()}
    dec_cols = {r[1] for r in db.execute("PRAGMA table_info(decisions)").fetchall()}

    # Migrate observations
    if "task_type" not in obs_cols:
        db.execute("ALTER TABLE observations ADD COLUMN task_type TEXT DEFAULT ''")
    if "tags" in obs_cols:
        # Convert JSON list to comma-separated string
        for row in db.execute("SELECT id, tags FROM observations WHERE tags IS NOT NULL").fetchall():
            row_id, tags = row
            try:
                parsed = json.loads(tags)
                if isinstance(parsed, list):
                    db.execute("UPDATE observations SET tags = ? WHERE id = ?",
                               (",".join(parsed), row_id))
            except Exception:
                pass
    db.execute("CREATE INDEX IF NOT EXISTS idx_obs_task_type ON observations(task_type)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_obs_created ON observations(created_at)")

    # Migrate decisions
    if "triggered_by_obs_id" not in dec_cols:
        db.execute("ALTER TABLE decisions ADD COLUMN triggered_by_obs_id INTEGER DEFAULT NULL")
    if "supersedes_decision_id" not in dec_cols:
        db.execute("ALTER TABLE decisions ADD COLUMN supersedes_decision_id INTEGER DEFAULT NULL")
    db.execute("CREATE INDEX IF NOT EXISTS idx_dec_created ON decisions(created_at)")

    db.commit()
    db.close()
    print(f"[memory_store] Database migrated at {DB_PATH}")


# ============ Write ============

def add_observation(
    type: str = "change",
    title: str = "",
    narrative: str | None = None,
    facts: list | None = None,
    concepts: list | None = None,
    session_id: str | None = None,
    source: str | None = None,
    verified: bool = False,
    tags: list | str | None = None,
    task_type: str | None = None,
) -> int:
    """Add an observation.

    Types: bugfix, discovery, lesson, change, feature, refactor

    Args:
        tags: list of strings OR comma-separated string
        task_type: coding, research, file_ops, reasoning, general
    """
    db = get_db()

    # Normalize tags to comma-separated string
    if tags is None:
        tags_str = ""
    elif isinstance(tags, str):
        tags_str = tags
    else:
        tags_str = ",".join(str(t).strip() for t in tags if t)

    db.execute(
        """INSERT INTO observations
           (session_id, timestamp, type, title, narrative, facts, concepts, source, verified, tags, task_type)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            session_id,
            datetime.now().isoformat(),
            type,
            title,
            narrative,
            json.dumps(facts, ensure_ascii=False) if facts else None,
            json.dumps(concepts, ensure_ascii=False) if concepts else None,
            source,
            1 if verified else 0,
            tags_str,
            task_type or "",
        ),
    )
    db.commit()
    rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return rid


def add_decision(
    title: str,
    decision: str,
    rejected_alternatives: str | list | None = None,
    rationale: str | None = None,
    triggered_by_obs_id: int | None = None,
    supersedes_decision_id: int | None = None,
) -> int:
    """Add a decision record.

    Args:
        triggered_by_obs_id: ID of the observation that triggered this decision
        supersedes_decision_id: ID of the older decision this one supersedes
    """
    db = get_db()
    if isinstance(rejected_alternatives, list):
        rejected_alts_str = json.dumps(rejected_alternatives, ensure_ascii=False)
    else:
        rejected_alts_str = rejected_alternatives

    db.execute(
        """INSERT INTO decisions
           (timestamp, title, decision, rejected_alternatives, rationale,
            triggered_by_obs_id, supersedes_decision_id)
           VALUES (?,?,?,?,?,?,?)""",
        (
            datetime.now().isoformat(),
            title,
            decision,
            rejected_alts_str,
            rationale,
            triggered_by_obs_id,
            supersedes_decision_id,
        ),
    )
    db.commit()
    rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return rid


def add_session_summary(
    request: str,
    learned: str | None = None,
    completed: str | None = None,
    next_steps: str | None = None,
    session_id: str | None = None,
    importance_score: float = 0.5,
) -> None:
    """Add a session summary."""
    db = get_db()
    db.execute(
        """INSERT INTO session_summaries
           (session_id, timestamp, request, learned, completed, next_steps, importance_score)
           VALUES (?,?,?,?,?,?,?)""",
        (
            session_id,
            datetime.now().isoformat(),
            request,
            learned,
            completed,
            next_steps,
            importance_score,
        ),
    )
    db.commit()
    db.close()


# ============ Query ============

def get_recent(days: int = 7, limit: int = 50) -> list[dict]:
    """Get recent observations and decisions."""
    db = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    obs = [
        dict(r)
        for r in db.execute(
            """SELECT id, 'observation' as kind, type, title, narrative, tags, task_type, created_at
               FROM observations WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?""",
            (cutoff, limit),
        ).fetchall()
    ]
    dec = [
        dict(r)
        for r in db.execute(
            """SELECT id, 'decision' as kind, title, decision, rationale,
                      triggered_by_obs_id, supersedes_decision_id, created_at
               FROM decisions WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?""",
            (cutoff, limit),
        ).fetchall()
    ]
    db.close()

    result = obs + dec
    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return result[:limit]


def search(
    query: str | None = None,
    type: str | None = None,
    tags: str | list | None = None,
    task_type: str | None = None,
    time_range: str | None = None,  # "recent"=7d, "month"=30d, "all"=None
    limit: int = 20,
) -> list[dict]:
    """Search observations with optional filters.

    Args:
        query: keyword search (FTS5 + LIKE)
        type: observation type filter
        tags: comma-separated string OR list of tags (AND logic)
        task_type: filter by task type
        time_range: "recent"(7d), "month"(30d), or None(all)
        limit: max results
    """
    db = get_db()
    conditions = []
    params = []

    if type:
        conditions.append("type = ?")
        params.append(type)

    if task_type:
        conditions.append("task_type = ?")
        params.append(task_type)

    if tags:
        if isinstance(tags, str):
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        else:
            tag_list = [str(t).strip() for t in tags if t]
        for tag in tag_list:
            conditions.append("tags LIKE ?")
            params.append(f"%{tag}%")

    if time_range == "recent":
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        conditions.append("created_at >= ?")
        params.append(cutoff)
    elif time_range == "month":
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()
        conditions.append("created_at >= ?")
        params.append(cutoff)

    where = " AND ".join(conditions) if conditions else "1=1"
    params.append(limit)

    # Keyword search via FTS5 + LIKE fallback
    if query:
        seen = set()
        results = []

        # Build query variants for backward compatibility:
        # old callers often pass natural phrases like "主流程 桥接" instead of exact keywords.
        query_variants = []
        q = str(query).strip()
        if q:
            query_variants.append(q)
            if " " in q:
                query_variants.extend([part.strip() for part in q.split() if part.strip()])

        # FTS5
        for qv in query_variants[:5]:
            try:
                for r in db.execute(f"""
                    SELECT t.id, t.type, t.title, t.narrative, t.tags, t.task_type,
                           t.created_at, 'observation' as kind
                    FROM observations_fts f
                    JOIN observations t ON f.rowid = t.id
                    WHERE observations_fts MATCH ? AND {where}
                    ORDER BY rank LIMIT ?
                """, [qv] + params[:-1] + [limit]).fetchall():
                    if r["id"] not in seen:
                        seen.add(r["id"])
                        results.append(dict(r))
            except Exception:
                pass

        # LIKE fallback (full query + split terms)
        for qv in query_variants[:5]:
            like = f"%{qv}%"
            like_where = " OR ".join(f"t.{c} LIKE ?" for c in ["title", "narrative", "tags"])
            for r in db.execute(f"""
                SELECT t.id, t.type, t.title, t.narrative, t.tags, t.task_type,
                       t.created_at, 'observation' as kind
                FROM observations t
                WHERE ({like_where}) AND {where}
                ORDER BY t.created_at DESC LIMIT ?
            """, [like, like, like] + params[:-1] + [limit]).fetchall():
                if r["id"] not in seen:
                    seen.add(r["id"])
                    results.append(dict(r))

        db.close()
        return results[:limit]
    else:
        rows = db.execute(f"""
            SELECT id, type, title, narrative, tags, task_type, created_at,
                   'observation' as kind
            FROM observations
            WHERE {where}
            ORDER BY created_at DESC LIMIT ?
        """, params).fetchall()
        db.close()
        return [dict(r) for r in rows]


def get_by_id(table: str, record_id: int) -> dict | None:
    """Get a single record by ID. table: 'observations' or 'decisions'."""
    db = get_db()
    row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
    db.close()
    return dict(row) if row else None


# ============ Stats ============

def stats() -> dict:
    """Return basic memory counts."""
    db = get_db()
    s = {
        "observations": db.execute(
            "SELECT COUNT(*) FROM observations").fetchone()[0],
        "decisions": db.execute(
            "SELECT COUNT(*) FROM decisions").fetchone()[0],
        "summaries": db.execute(
            "SELECT COUNT(*) FROM session_summaries").fetchone()[0],
    }
    db.close()
    return s


# ============ CLI ============

def cli():
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers()

    init_p = sub.add_parser("init", help="Initialize/migrate database")
    init_p.set_defaults(cmd="init")

    search_p = sub.add_parser("search", help="Search observations")
    search_p.add_argument("query", nargs="?", default=None)
    search_p.add_argument("--type", "-t", default=None)
    search_p.add_argument("--tags", default=None)
    search_p.add_argument("--task-type", default=None)
    search_p.add_argument("--time-range", default=None)
    search_p.add_argument("--limit", "-n", type=int, default=10)
    search_p.set_defaults(cmd="search")

    args = p.parse_args()

    if not hasattr(args, "cmd"):
        p.print_help()
        return

    if args.cmd == "init":
        init_db()
    elif args.cmd == "search":
        results = search(
            query=args.query,
            type=args.type,
            tags=args.tags,
            task_type=args.task_type,
            time_range=args.time_range,
            limit=args.limit,
        )
        for r in results:
            print(f"[{r['type']}] {r['title'][:60]}")
            if r.get("tags"):
                print(f"  tags: {r['tags']}")


if __name__ == "__main__":
    cli()
