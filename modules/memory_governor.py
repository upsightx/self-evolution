#!/usr/bin/env python3
"""
Memory Governor — 记忆治理层。

职责：
- 去重：写入前检查相似记录，防止重复
- Lineage：标记每条 observation 的来源链（谁写的、从哪来的）
- 防自激：阻止系统消费自己写回的数据
- 健康度：监控重复率、增长率、冷热分布

设计原则：
- 不替代 memory_store 的 CRUD，而是在其上层做治理
- 所有写入建议通过 governor 而不是直接调 memory_store
- lineage 信息存在独立表，不污染 observations 主表
"""
from __future__ import annotations

import json
import hashlib
import sys
from datetime import datetime, timedelta

from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path, module_dir, module_workspace

_workspace = ensure_workspace_on_path()
_modules = module_dir()
ensure_xmemory_on_path()

from db_common import get_db


# ============ Schema ============

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_lineage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER NOT NULL,
    origin_type TEXT NOT NULL,
    origin_module TEXT NOT NULL,
    origin_ref TEXT DEFAULT '',
    is_bridge_output INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memory_dedup_hashes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT NOT NULL UNIQUE,
    observation_id INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_lineage_obs ON memory_lineage(observation_id);
CREATE INDEX IF NOT EXISTS idx_lineage_origin ON memory_lineage(origin_module);
CREATE INDEX IF NOT EXISTS idx_lineage_bridge ON memory_lineage(is_bridge_output);
CREATE INDEX IF NOT EXISTS idx_dedup_hash ON memory_dedup_hashes(content_hash);
"""

# Modules whose output should NOT be re-ingested by scanners
BRIDGE_MODULES = {
    "proposal_bridge",
    "external_learning_evidence_bridge",
    "evolution_orchestrator",
    "evolution_executor",
    "memory_governor",
    "auto_evolve",  # replaced legacy change_applier
}


def _ensure_schema():
    db = get_db()
    db.executescript(_SCHEMA)
    db.commit()
    db.close()


def _content_hash(title: str, narrative: str = "", source: str = "") -> str:
    """Generate a dedup hash from content."""
    raw = f"{title.strip().lower()}|{(narrative or '').strip()[:200].lower()}|{source}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


# ============ Governed Write ============

def add_observation(
    type: str,
    title: str,
    narrative: str = None,
    facts: list = None,
    concepts: list = None,
    session_id: str = None,
    source: str = None,
    verified: bool = False,
    tags: str | list = None,
    task_type: str = None,
    description: str = "",
    origin_module: str = "",
    origin_ref: str = "",
) -> dict:
    """Governed observation write with dedup and lineage.

    Args:
        origin_module: Which module is writing this (e.g., 'proposal_bridge', 'evolution_orchestrator')
        origin_ref: Reference ID from the origin (e.g., signal_id, proposal_id)

    Returns:
        {"success": bool, "observation_id": int|None, "action": "created"|"duplicate"|"error", "message": str}
    """
    _ensure_schema()

    # Step 1: Dedup check
    ch = _content_hash(title, narrative or "", source or "")
    db = get_db()
    try:
        existing = db.execute(
            "SELECT observation_id FROM memory_dedup_hashes WHERE content_hash = ?",
            (ch,),
        ).fetchone()
        if existing:
            return {
                "success": True,
                "observation_id": existing["observation_id"],
                "action": "duplicate",
                "message": f"Duplicate of observation #{existing['observation_id']}",
            }
    finally:
        db.close()

    # Step 2: Write via memory_store
    try:
        from memory_store import add_observation as _store_add
        obs_id = _store_add(
            type=type, title=title, narrative=narrative, facts=facts,
            concepts=concepts, session_id=session_id, source=source,
            verified=verified, tags=tags, task_type=task_type,
            description=description,
        )
    except Exception as e:
        return {"success": False, "observation_id": None, "action": "error",
                "message": f"Write failed: {e}"}

    # Step 3: Record dedup hash
    db = get_db()
    try:
        db.execute(
            "INSERT OR IGNORE INTO memory_dedup_hashes (content_hash, observation_id) VALUES (?, ?)",
            (ch, obs_id),
        )

        # Step 4: Record lineage
        is_bridge = 1 if origin_module in BRIDGE_MODULES else 0
        db.execute(
            """INSERT INTO memory_lineage
               (observation_id, origin_type, origin_module, origin_ref, is_bridge_output)
               VALUES (?, ?, ?, ?, ?)""",
            (obs_id, type, origin_module or source or "unknown", origin_ref, is_bridge),
        )
        db.commit()
    finally:
        db.close()

    return {
        "success": True,
        "observation_id": obs_id,
        "action": "created",
        "message": f"Observation #{obs_id} created with lineage",
    }


# ============ Lineage Query ============

def get_lineage(observation_id: int) -> dict | None:
    """Get lineage info for an observation."""
    _ensure_schema()
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM memory_lineage WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def is_bridge_output(observation_id: int) -> bool:
    """Check if an observation was written by a bridge module (should not be re-ingested)."""
    _ensure_schema()
    db = get_db()
    try:
        row = db.execute(
            "SELECT is_bridge_output FROM memory_lineage WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()
        return bool(row and row["is_bridge_output"])
    finally:
        db.close()


def get_non_bridge_observations(
    type: str = None,
    source: str = None,
    days: int = 30,
    limit: int = 50,
) -> list[dict]:
    """Get observations that are NOT bridge outputs (safe to re-ingest/scan).

    This is the correct way for scanners to query observations without
    accidentally consuming system-generated records.
    """
    _ensure_schema()
    db = get_db()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        conditions = ["o.created_at >= ?"]
        params = [cutoff]

        if type:
            conditions.append("o.type = ?")
            params.append(type)
        if source:
            conditions.append("o.source = ?")
            params.append(source)

        where = " AND ".join(conditions)
        params.append(limit)

        rows = db.execute(f"""
            SELECT o.* FROM observations o
            LEFT JOIN memory_lineage ml ON o.id = ml.observation_id
            WHERE {where}
              AND (ml.is_bridge_output IS NULL OR ml.is_bridge_output = 0)
            ORDER BY o.created_at DESC
            LIMIT ?
        """, params).fetchall()

        return [dict(r) for r in rows]
    finally:
        db.close()


# ============ Health Metrics ============

def get_health() -> dict:
    """Get memory health metrics."""
    _ensure_schema()
    db = get_db()
    try:
        total_obs = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        total_dec = db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        total_dedup = db.execute("SELECT COUNT(*) FROM memory_dedup_hashes").fetchone()[0]
        total_lineage = db.execute("SELECT COUNT(*) FROM memory_lineage").fetchone()[0]
        bridge_count = db.execute(
            "SELECT COUNT(*) FROM memory_lineage WHERE is_bridge_output = 1"
        ).fetchone()[0]

        # Recent growth (last 7 days)
        cutoff_7d = (datetime.now() - timedelta(days=7)).isoformat()
        recent_obs = db.execute(
            "SELECT COUNT(*) FROM observations WHERE created_at >= ?",
            (cutoff_7d,),
        ).fetchone()[0]

        # Type distribution
        by_type = {}
        for r in db.execute(
            "SELECT type, COUNT(*) as c FROM observations GROUP BY type ORDER BY c DESC"
        ).fetchall():
            by_type[r["type"]] = r["c"]

        # Origin distribution
        by_origin = {}
        for r in db.execute(
            "SELECT origin_module, COUNT(*) as c FROM memory_lineage GROUP BY origin_module ORDER BY c DESC"
        ).fetchall():
            by_origin[r["origin_module"]] = r["c"]

        # Dedup effectiveness
        dedup_rate = round(total_dedup / max(total_obs, 1) * 100, 1)

        return {
            "total_observations": total_obs,
            "total_decisions": total_dec,
            "recent_7d_observations": recent_obs,
            "dedup_hashes": total_dedup,
            "dedup_coverage_pct": dedup_rate,
            "lineage_records": total_lineage,
            "bridge_outputs": bridge_count,
            "by_type": by_type,
            "by_origin": by_origin,
        }
    finally:
        db.close()


# ============ Cleanup ============

def find_duplicates(limit: int = 50) -> list[dict]:
    """Find potential duplicate observations (same title, different IDs)."""
    _ensure_schema()
    db = get_db()
    try:
        rows = db.execute("""
            SELECT title, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
            FROM observations
            GROUP BY LOWER(TRIM(title))
            HAVING cnt > 1
            ORDER BY cnt DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def archive_cold_observations(days: int = 60, min_access: int = 0) -> int:
    """Mark old, unaccessed observations for archival.

    Returns count of observations marked.
    """
    _ensure_schema()
    db = get_db()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        # Only archive if access_count column exists
        cols = {r[1] for r in db.execute("PRAGMA table_info(observations)").fetchall()}
        if "access_count" in cols:
            cursor = db.execute("""
                UPDATE observations SET type = 'archived_' || type
                WHERE created_at < ? AND COALESCE(access_count, 0) <= ?
                  AND type NOT LIKE 'archived_%'
            """, (cutoff, min_access))
        else:
            cursor = db.execute("""
                UPDATE observations SET type = 'archived_' || type
                WHERE created_at < ?
                  AND type NOT LIKE 'archived_%'
            """, (cutoff,))
        count = cursor.rowcount
        db.commit()
        return count
    finally:
        db.close()


# ============ CLI ============

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Memory Governor")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("health", help="Memory health metrics")
    sub.add_parser("duplicates", help="Find duplicate observations")

    p_lineage = sub.add_parser("lineage", help="Get lineage for an observation")
    p_lineage.add_argument("observation_id", type=int)

    p_non_bridge = sub.add_parser("safe-scan", help="List non-bridge observations")
    p_non_bridge.add_argument("--type", default=None)
    p_non_bridge.add_argument("--days", type=int, default=30)
    p_non_bridge.add_argument("--limit", type=int, default=20)

    p_archive = sub.add_parser("archive", help="Archive cold observations")
    p_archive.add_argument("--days", type=int, default=60)

    args = parser.parse_args()

    if args.command == "health":
        h = get_health()
        print(json.dumps(h, indent=2, ensure_ascii=False))

    elif args.command == "duplicates":
        dups = find_duplicates()
        if not dups:
            print("No duplicates found")
        for d in dups:
            print(f"  [{d['cnt']}x] {d['title'][:60]} (ids: {d['ids']})")

    elif args.command == "lineage":
        l = get_lineage(args.observation_id)
        if l:
            print(json.dumps(l, indent=2, ensure_ascii=False, default=str))
        else:
            print("No lineage found")

    elif args.command == "safe-scan":
        obs = get_non_bridge_observations(type=args.type, days=args.days, limit=args.limit)
        for o in obs:
            print(f"  [{o['type']}] #{o['id']}: {o['title'][:50]}")

    elif args.command == "archive":
        count = archive_cold_observations(days=args.days)
        print(f"Archived {count} observations")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
