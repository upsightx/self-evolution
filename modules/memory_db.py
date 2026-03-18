#!/usr/bin/env python3
"""
Structured Memory Database for AI Agents.

Core value: remember WHY, not just WHAT.
- Decisions with rejected alternatives and rationale
- Observations with type classification
- Session summaries for continuity
- Dual-path search (FTS5 + LIKE) for CJK/mixed content

Zero dependencies. Python 3.8+ and SQLite only.
"""

import sqlite3
import json
import os
import sys
import struct
import hashlib
import urllib.request
import math
from datetime import datetime, timedelta
from pathlib import Path

from db_common import DB_PATH, get_db


def init_db():
    """Initialize the database. Safe to call multiple times."""
    db = get_db()
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

        CREATE TABLE IF NOT EXISTS session_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            timestamp TEXT NOT NULL,
            request TEXT,
            learned TEXT,
            completed TEXT,
            next_steps TEXT,
            importance_score REAL DEFAULT 0.5,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(
            title, narrative, facts, concepts,
            content=observations, content_rowid=id
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
            title, decision, rejected_alternatives, rationale,
            content=decisions, content_rowid=id
        );

        CREATE TRIGGER IF NOT EXISTS obs_fts_insert AFTER INSERT ON observations BEGIN
            INSERT INTO observations_fts(rowid, title, narrative, facts, concepts)
            VALUES (new.id, new.title, new.narrative, new.facts, new.concepts);
        END;

        CREATE TRIGGER IF NOT EXISTS obs_fts_delete AFTER DELETE ON observations BEGIN
            INSERT INTO observations_fts(observations_fts, rowid, title, narrative, facts, concepts)
            VALUES ('delete', old.id, old.title, old.narrative, old.facts, old.concepts);
        END;

        CREATE TRIGGER IF NOT EXISTS dec_fts_insert AFTER INSERT ON decisions BEGIN
            INSERT INTO decisions_fts(rowid, title, decision, rejected_alternatives, rationale)
            VALUES (new.id, new.title, new.decision, new.rejected_alternatives, new.rationale);
        END;

        CREATE TRIGGER IF NOT EXISTS dec_fts_delete AFTER DELETE ON decisions BEGIN
            INSERT INTO decisions_fts(decisions_fts, rowid, title, decision, rejected_alternatives, rationale)
            VALUES ('delete', old.id, old.title, old.decision, old.rejected_alternatives, old.rationale);
        END;

        CREATE TRIGGER IF NOT EXISTS obs_fts_update AFTER UPDATE ON observations BEGIN
            INSERT INTO observations_fts(observations_fts, rowid, title, narrative, facts, concepts)
            VALUES ('delete', old.id, old.title, old.narrative, old.facts, old.concepts);
            INSERT INTO observations_fts(rowid, title, narrative, facts, concepts)
            VALUES (new.id, new.title, new.narrative, new.facts, new.concepts);
        END;

        CREATE TRIGGER IF NOT EXISTS dec_fts_update AFTER UPDATE ON decisions BEGIN
            INSERT INTO decisions_fts(decisions_fts, rowid, title, decision, rejected_alternatives, rationale)
            VALUES ('delete', old.id, old.title, old.decision, old.rejected_alternatives, old.rationale);
            INSERT INTO decisions_fts(rowid, title, decision, rejected_alternatives, rationale)
            VALUES (new.id, new.title, new.decision, new.rejected_alternatives, new.rationale);
        END;

        CREATE TABLE IF NOT EXISTS embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_table TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            text_hash TEXT NOT NULL,
            embedding BLOB NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(source_table, source_id)
        );
    """)
    db.commit()
    db.close()
    print(f"Database initialized at {DB_PATH}")


# ============ Write ============

def add_observation(type, title, narrative=None, facts=None, concepts=None, session_id=None, source=None, verified=False, tags=None):
    """Add an observation. Types: decision, bugfix, feature, refactor, discovery, change
    
    Args:
        source: 信息来源 (如 'chat', 'file', 'web', 'task' 等)
        verified: 是否已验证 (bool)
        tags: 标签列表 (list)
    """
    db = get_db()
    db.execute(
        "INSERT INTO observations (session_id, timestamp, type, title, narrative, facts, concepts, source, verified, tags) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (session_id, datetime.now().isoformat(), type, title, narrative,
         json.dumps(facts, ensure_ascii=False) if facts else None,
         json.dumps(concepts, ensure_ascii=False) if concepts else None,
         source, 1 if verified else 0, json.dumps(tags, ensure_ascii=False) if tags else None)
    )
    db.commit()
    rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return rid


def add_decision(title, decision, rejected_alternatives=None, rationale=None):
    """Add a decision record. The key: record what you rejected and why."""
    db = get_db()
    db.execute(
        "INSERT INTO decisions (timestamp, title, decision, rejected_alternatives, rationale) VALUES (?,?,?,?,?)",
        (datetime.now().isoformat(), title, decision,
         json.dumps(rejected_alternatives, ensure_ascii=False) if rejected_alternatives else None,
         rationale)
    )
    db.commit()
    rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return rid


def add_session_summary(request, learned=None, completed=None, next_steps=None, session_id=None, importance_score=0.5):
    """Add a session summary for continuity across sessions.
    
    Args:
        importance_score: 重要性评分 (0.0-1.0)
    """
    db = get_db()
    db.execute(
        "INSERT INTO session_summaries (session_id, timestamp, request, learned, completed, next_steps, importance_score) VALUES (?,?,?,?,?,?,?)",
        (session_id, datetime.now().isoformat(), request, learned, completed, next_steps, importance_score)
    )
    db.commit()
    db.close()


# ============ Search (dual-path: FTS5 + LIKE) ============

def _dual_search(db, fts_table, join_table, select_cols, fts_cols, like_cols, query, limit):
    """FTS5 for English tokens, LIKE fallback for CJK/mixed content. Merged, deduped."""
    seen = set()
    results = []

    # Path 1: FTS5
    try:
        for r in db.execute(f"""
            SELECT {select_cols} FROM {fts_table} f
            JOIN {join_table} t ON f.rowid = t.id
            WHERE {fts_table} MATCH ? ORDER BY rank LIMIT ?
        """, (query, limit)).fetchall():
            if r['id'] not in seen:
                seen.add(r['id'])
                results.append(dict(r))
    except Exception:
        pass

    # Path 2: LIKE
    like = f"%{query}%"
    where = " OR ".join(f"{c} LIKE ?" for c in like_cols)
    params = [like] * len(like_cols) + [limit]
    for r in db.execute(f"""
        SELECT {select_cols} FROM {join_table} t
        WHERE {where} ORDER BY timestamp DESC LIMIT ?
    """, params).fetchall():
        if r['id'] not in seen:
            seen.add(r['id'])
            results.append(dict(r))

    return results[:limit]


def search(query=None, type=None, limit=20):
    """Search observations. Returns id, type, title, narrative, facts, timestamp."""
    db = get_db()
    if query:
        results = _dual_search(db,
            fts_table="observations_fts", join_table="observations",
            select_cols="t.id, t.type, t.title, t.narrative, t.facts, t.timestamp",
            fts_cols=["title", "narrative", "facts", "concepts"],
            like_cols=["title", "narrative", "facts", "concepts"],
            query=query, limit=limit)
    else:
        where = "WHERE type = ?" if type else ""
        params = [type, limit] if type else [limit]
        results = [dict(r) for r in db.execute(f"""
            SELECT id, type, title, narrative, facts, timestamp FROM observations
            {where} ORDER BY timestamp DESC LIMIT ?
        """, params).fetchall()]
    db.close()
    return results


def search_decisions(query=None, limit=20):
    """Search decisions."""
    db = get_db()
    if query:
        results = _dual_search(db,
            fts_table="decisions_fts", join_table="decisions",
            select_cols="t.id, t.title, t.decision, t.rationale, t.rejected_alternatives, t.timestamp",
            fts_cols=["title", "decision", "rejected_alternatives", "rationale"],
            like_cols=["title", "decision", "rejected_alternatives", "rationale"],
            query=query, limit=limit)
    else:
        results = [dict(r) for r in db.execute(
            "SELECT * FROM decisions ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()]
    db.close()
    return results


def get(id):
    """Get full observation by id."""
    db = get_db()
    row = db.execute("SELECT * FROM observations WHERE id = ?", (id,)).fetchone()
    db.close()
    return dict(row) if row else None


def stats():
    """Database statistics."""
    db = get_db()
    r = {
        "observations": db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
        "decisions": db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0],
        "summaries": db.execute("SELECT COUNT(*) FROM session_summaries").fetchone()[0],
        "by_type": {r["type"]: r["cnt"] for r in db.execute(
            "SELECT type, COUNT(*) as cnt FROM observations GROUP BY type ORDER BY cnt DESC"
        ).fetchall()}
    }
    db.close()
    return r


def count_by_type(table="observations"):
    """统计指定表的记录数量（按类型分组）。
    
    Args:
        table: 表名，可选 'observations', 'decisions', 'session_summaries'
    
    Returns:
        dict: {type: count}
    """
    valid_tables = {"observations", "decisions", "session_summaries"}
    if table not in valid_tables:
        raise ValueError(f"Invalid table: {table}. Valid: {valid_tables}")
    
    db = get_db()
    if table == "observations":
        results = {r["type"]: r["cnt"] for r in db.execute(
            "SELECT type, COUNT(*) as cnt FROM observations GROUP BY type ORDER BY cnt DESC"
        ).fetchall()}
    elif table == "decisions":
        # decisions 表没有 type 字段，返回总数
        results = {"total": db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]}
    else:
        # session_summaries 没有 type，返回总数
        results = {"total": db.execute("SELECT COUNT(*) FROM session_summaries").fetchone()[0]}
    db.close()
    return results


def recent_by_days(days=7, table="observations"):
    """获取最近 N 天的记录。
    
    Args:
        days: 天数
        table: 表名，可选 'observations', 'decisions', 'session_summaries'
    
    Returns:
        list: 记录列表，每条记录包含 id, timestamp 等字段
    """
    valid_tables = {"observations", "decisions", "session_summaries"}
    if table not in valid_tables:
        raise ValueError(f"Invalid table: {table}. Valid: {valid_tables}")
    
    db = get_db()
    cutoff = datetime.now() - timedelta(days=days)
    
    if table == "observations":
        results = [dict(r) for r in db.execute("""
            SELECT id, session_id, timestamp, type, title, narrative, source, verified, tags
            FROM observations 
            WHERE timestamp >= ? ORDER BY timestamp DESC
        """, (cutoff.isoformat(),)).fetchall()]
    elif table == "decisions":
        results = [dict(r) for r in db.execute("""
            SELECT id, timestamp, title, decision, rejected_alternatives, rationale
            FROM decisions 
            WHERE timestamp >= ? ORDER BY timestamp DESC
        """, (cutoff.isoformat(),)).fetchall()]
    else:
        results = [dict(r) for r in db.execute("""
            SELECT id, session_id, timestamp, request, learned, completed, next_steps, importance_score
            FROM session_summaries 
            WHERE timestamp >= ? ORDER BY timestamp DESC
        """, (cutoff.isoformat(),)).fetchall()]
    db.close()
    return results


# ============ Context Builder ============

def _extract_date(timestamp_str):
    """Extract YYYY-MM-DD from an ISO timestamp string."""
    if not timestamp_str:
        return "未知日期"
    import re
    match = re.search(r'\d{4}-\d{2}-\d{2}', str(timestamp_str))
    return match.group(0) if match else "未知日期"


def _format_entry(entry_type, title, content):
    """Format a single entry line. Truncate content to 200 chars."""
    if content and len(content) > 200:
        content = content[:197] + "..."
    suffix = f": {content}" if content else ""
    return f"[{entry_type}] {title}{suffix}"


def _group_by_date(results, entry_type):
    """Group search results by date, returning list of (date, entries)."""
    groups = {}
    for r in results:
        date = _extract_date(r.get("timestamp"))
        groups.setdefault(date, [])
        content = r.get("narrative") or r.get("decision") or ""
        groups[date].append(_format_entry(
            entry_type if entry_type else r.get("type", "unknown"),
            r.get("title", ""),
            content
        ))
    return groups


def _build_context_from_entries(entries, max_chars, top_per_group):
    """Shared logic: take a list of dicts with 'type'/'title'/'content'/'timestamp',
    group by date, truncate, return formatted string."""
    merged = {}
    for e in entries:
        date = _extract_date(e.get("timestamp"))
        merged.setdefault(date, [])
        merged[date].append(_format_entry(e.get("type", "unknown"), e.get("title", ""), e.get("content", "")))

    if not merged:
        return ""

    sorted_dates = sorted(merged.keys(), reverse=True)
    date_parts = []
    for date in sorted_dates:
        block_entries = merged[date][:top_per_group]
        block = f"--- {date} ---\n" + "\n".join(block_entries)
        date_parts.append((date, block))

    while len(date_parts) > 1:
        total = sum(len(dp[1]) for dp in date_parts) + len(date_parts) - 1
        if total <= max_chars:
            break
        date_parts.pop()

    result = "\n\n".join(dp[1] for dp in date_parts)
    if len(result) > max_chars:
        result = result[:max_chars - 3] + "..."
    return result


def _search_with_context_semantic(query, max_chars, top_per_group):
    """Semantic-only search_with_context."""
    sem_results = semantic_search(query, limit=50)
    db = get_db()
    entries = []
    for r in sem_results:
        if r["source_table"] == "observations":
            row = db.execute("SELECT type, title, narrative, timestamp FROM observations WHERE id = ?",
                             (r["source_id"],)).fetchone()
            if row:
                entries.append({
                    "type": row["type"], "title": row["title"],
                    "content": row["narrative"] or "", "timestamp": row["timestamp"]
                })
        else:
            row = db.execute("SELECT title, decision, timestamp FROM decisions WHERE id = ?",
                             (r["source_id"],)).fetchone()
            if row:
                entries.append({
                    "type": "decision", "title": row["title"],
                    "content": row["decision"] or "", "timestamp": row["timestamp"]
                })
    db.close()
    return _build_context_from_entries(entries, max_chars, top_per_group)


def _search_with_context_hybrid(query, max_chars, top_per_group):
    """Hybrid: merge keyword + semantic results, deduplicate, weighted score."""
    # Keyword results
    obs_kw = search(query=query, limit=30)
    decs_kw = search_decisions(query=query, limit=30)

    # Semantic results
    try:
        sem_results = semantic_search(query, limit=30)
    except Exception:
        sem_results = []

    # Build unified scored dict: key=(source_table, source_id) -> {score, entry_data}
    scored = {}  # (table, id) -> {"kw_score": float, "sem_score": float, "entry": dict}

    # Keyword results get rank-based score (1.0 for first, decreasing)
    for rank, r in enumerate(obs_kw):
        key = ("observations", r["id"])
        kw_score = 1.0 / (rank + 1)
        scored[key] = {
            "kw_score": kw_score, "sem_score": 0.0,
            "entry": {"type": r.get("type", "observation"), "title": r.get("title", ""),
                       "content": r.get("narrative") or "", "timestamp": r.get("timestamp")}
        }
    for rank, r in enumerate(decs_kw):
        key = ("decisions", r["id"])
        kw_score = 1.0 / (rank + 1)
        scored[key] = {
            "kw_score": kw_score, "sem_score": 0.0,
            "entry": {"type": "decision", "title": r.get("title", ""),
                       "content": r.get("decision") or "", "timestamp": r.get("timestamp")}
        }

    # Semantic results
    db = get_db()
    for r in sem_results:
        key = (r["source_table"], r["source_id"])
        sem_score = r["score"]
        if key in scored:
            scored[key]["sem_score"] = sem_score
        else:
            # Fetch entry data
            if r["source_table"] == "observations":
                row = db.execute("SELECT type, title, narrative, timestamp FROM observations WHERE id = ?",
                                 (r["source_id"],)).fetchone()
                if row:
                    scored[key] = {
                        "kw_score": 0.0, "sem_score": sem_score,
                        "entry": {"type": row["type"], "title": row["title"],
                                   "content": row["narrative"] or "", "timestamp": row["timestamp"]}
                    }
            else:
                row = db.execute("SELECT title, decision, timestamp FROM decisions WHERE id = ?",
                                 (r["source_id"],)).fetchone()
                if row:
                    scored[key] = {
                        "kw_score": 0.0, "sem_score": sem_score,
                        "entry": {"type": "decision", "title": row["title"],
                                   "content": row["decision"] or "", "timestamp": row["timestamp"]}
                    }
    db.close()

    # Weighted combined score: 0.4 * keyword + 0.6 * semantic
    combined = []
    for key, val in scored.items():
        final_score = 0.4 * val["kw_score"] + 0.6 * val["sem_score"]
        combined.append((final_score, val["entry"]))

    combined.sort(key=lambda x: x[0], reverse=True)
    entries = [c[1] for c in combined[:50]]

    return _build_context_from_entries(entries, max_chars, top_per_group)


def search_with_context(query, max_chars=6000, top_per_group=3, mode="keyword"):
    """搜索并构建上下文字符串

    流程：
    1. 用现有 search() + search_decisions() 获取结果
    2. 按日期分组
    3. 每组取 top_per_group 条
    4. 拼接并截断到 max_chars（从最旧的组开始删，保留最新的）
    5. 返回格式化的上下文字符串

    Args:
        mode: "keyword" (default, FTS5+LIKE), "semantic" (embedding cosine),
              "hybrid" (merge both, weighted score)
    """
    if mode == "semantic":
        return _search_with_context_semantic(query, max_chars, top_per_group)
    elif mode == "hybrid":
        return _search_with_context_hybrid(query, max_chars, top_per_group)

    # Default: keyword mode (original behavior)
    obs = search(query=query, limit=50)
    decs = search_decisions(query=query, limit=50)

    # Group by date
    merged = {}  # date -> [lines]
    for r in obs:
        date = _extract_date(r.get("timestamp"))
        merged.setdefault(date, [])
        content = r.get("narrative") or ""
        merged[date].append(_format_entry(r.get("type", "observation"), r.get("title", ""), content))
    for r in decs:
        date = _extract_date(r.get("timestamp"))
        merged.setdefault(date, [])
        content = r.get("decision") or ""
        merged[date].append(_format_entry("decision", r.get("title", ""), content))

    if not merged:
        return ""

    # Sort dates descending (newest first), each group top_per_group
    sorted_dates = sorted(merged.keys(), reverse=True)

    # Build parts per date group
    date_parts = []  # [(date, text_block)]
    for date in sorted_dates:
        entries = merged[date][:top_per_group]
        block = f"--- {date} ---\n" + "\n".join(entries)
        date_parts.append((date, block))

    # Truncation: remove oldest groups first until within budget
    # date_parts[0] is newest, date_parts[-1] is oldest
    while len(date_parts) > 1:
        total = sum(len(dp[1]) for dp in date_parts) + len(date_parts) - 1  # newlines between blocks
        if total <= max_chars:
            break
        date_parts.pop()  # remove oldest

    result = "\n\n".join(dp[1] for dp in date_parts)

    # Hard truncate if single group still exceeds
    if len(result) > max_chars:
        result = result[:max_chars - 3] + "..."

    return result


def search_with_metadata(query, max_chars=6000, top_per_group=3):
    """搜索并返回上下文+元数据

    返回: {
        "context": "格式化的上下文字符串",
        "total_results": 10,
        "context_chars": 5800,
        "truncated": False,
        "date_range": {"earliest": "2026-03-15", "latest": "2026-03-18"}
    }
    """
    obs = search(query=query, limit=50)
    decs = search_decisions(query=query, limit=50)
    total_results = len(obs) + len(decs)

    # Collect all dates for range
    all_dates = []
    for r in obs + decs:
        d = _extract_date(r.get("timestamp"))
        if d != "未知日期":
            all_dates.append(d)

    # Build context using search_with_context
    context = search_with_context(query, max_chars=max_chars, top_per_group=top_per_group)

    # Determine if truncated: rebuild without limit to compare
    full_context = search_with_context(query, max_chars=999999, top_per_group=top_per_group)
    truncated = len(full_context) > len(context)

    return {
        "context": context,
        "total_results": total_results,
        "context_chars": len(context),
        "truncated": truncated,
        "date_range": {
            "earliest": min(all_dates) if all_dates else None,
            "latest": max(all_dates) if all_dates else None,
        }
    }


def import_json(data):
    """Import from JSON. Format: {observations: [...], decisions: [...], summary: "..."}"""
    imported = {"observations": 0, "decisions": 0, "summaries": 0}
    for obs in data.get("observations", []):
        add_observation(obs.get("type", "change"), obs["title"],
                        obs.get("narrative"), obs.get("facts"), obs.get("concepts"))
        imported["observations"] += 1
    for dec in data.get("decisions", []):
        add_decision(dec["title"], dec["decision"],
                     dec.get("rejected_alternatives"), dec.get("rationale"))
        imported["decisions"] += 1
    if data.get("summary"):
        add_session_summary(request=data["summary"])
        imported["summaries"] += 1
    return imported


# ============ Embedding / Semantic Search ============

SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
SILICONFLOW_ENDPOINT = "https://api.siliconflow.cn/v1/embeddings"
EMBED_MODEL = "BAAI/bge-m3"
EMBED_DIM = 1024
EMBED_BATCH_SIZE = 20


def _text_hash(text):
    """SHA256 hash of text for change detection."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pack_embedding(vec):
    """Pack a list of floats into a BLOB using struct (float32)."""
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_embedding(blob):
    """Unpack a BLOB back into a list of floats."""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def embed_text(texts):
    """Call SiliconFlow BGE-M3 API to get embeddings.

    Args:
        texts: list[str] — texts to embed

    Returns:
        list[list[float]] — one embedding per input text
    """
    if not texts:
        return []

    if not SILICONFLOW_API_KEY:
        print("Warning: SILICONFLOW_API_KEY not set, skipping embedding")
        return []

    all_embeddings = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        payload = json.dumps({
            "model": EMBED_MODEL,
            "input": batch,
        }).encode("utf-8")

        req = urllib.request.Request(
            SILICONFLOW_ENDPOINT,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        # Sort by index to preserve order
        sorted_data = sorted(body["data"], key=lambda x: x["index"])
        all_embeddings.extend([item["embedding"] for item in sorted_data])

    return all_embeddings


def _cosine_similarity(a, b):
    """Cosine similarity between two vectors. Pure Python, no numpy."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_embeddings():
    """Build/update embeddings for all observations and decisions."""
    init_db()
    db = get_db()

    # Gather records to embed
    tasks = []  # (source_table, source_id, text, text_hash)

    # Observations: title + narrative + facts
    for row in db.execute("SELECT id, title, narrative, facts FROM observations").fetchall():
        parts = [row["title"] or ""]
        if row["narrative"]:
            parts.append(row["narrative"])
        if row["facts"]:
            parts.append(row["facts"])
        text = "\n".join(parts)
        tasks.append(("observations", row["id"], text, _text_hash(text)))

    # Decisions: title + decision + rationale
    for row in db.execute("SELECT id, title, decision, rationale FROM decisions").fetchall():
        parts = [row["title"] or ""]
        if row["decision"]:
            parts.append(row["decision"])
        if row["rationale"]:
            parts.append(row["rationale"])
        text = "\n".join(parts)
        tasks.append(("decisions", row["id"], text, _text_hash(text)))

    if not tasks:
        print("No records to embed.")
        db.close()
        return

    # Check existing embeddings to skip unchanged
    existing = {}
    for row in db.execute("SELECT source_table, source_id, text_hash FROM embeddings").fetchall():
        existing[(row["source_table"], row["source_id"])] = row["text_hash"]

    to_embed = []
    for source_table, source_id, text, th in tasks:
        key = (source_table, source_id)
        if key in existing and existing[key] == th:
            continue  # unchanged, skip
        to_embed.append((source_table, source_id, text, th))

    if not to_embed:
        print("All embeddings up to date.")
        db.close()
        return

    print(f"Embedding {len(to_embed)} records...")
    texts_to_embed = [t[2] for t in to_embed]
    vectors = embed_text(texts_to_embed)

    for (source_table, source_id, text, th), vec in zip(to_embed, vectors):
        blob = _pack_embedding(vec)
        db.execute("""
            INSERT INTO embeddings (source_table, source_id, text_hash, embedding)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_table, source_id) DO UPDATE SET
                text_hash = excluded.text_hash,
                embedding = excluded.embedding,
                created_at = datetime('now')
        """, (source_table, source_id, th, blob))

    db.commit()
    db.close()
    print(f"Done. Embedded {len(to_embed)} records.")


def semantic_search(query, limit=10):
    """Semantic search using cosine similarity against stored embeddings.

    Args:
        query: search query string
        limit: max results to return

    Returns:
        list[dict] with keys: source_table, source_id, title, score
    """
    init_db()
    query_vec = embed_text([query])[0]

    db = get_db()
    rows = db.execute("SELECT source_table, source_id, embedding FROM embeddings").fetchall()

    scored = []
    for row in rows:
        vec = _unpack_embedding(row["embedding"])
        score = _cosine_similarity(query_vec, vec)
        scored.append((score, row["source_table"], row["source_id"]))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    results = []
    for score, source_table, source_id in top:
        if source_table == "observations":
            r = db.execute("SELECT title, timestamp FROM observations WHERE id = ?", (source_id,)).fetchone()
        else:
            r = db.execute("SELECT title, timestamp FROM decisions WHERE id = ?", (source_id,)).fetchone()
        if r:
            results.append({
                "source_table": source_table,
                "source_id": source_id,
                "title": r["title"],
                "timestamp": r["timestamp"],
                "score": round(score, 4),
            })

    db.close()
    return results


# ============ CLI ============

def main():
    if len(sys.argv) < 2:
        print("""Self-Evolution Memory Database

Usage: memory_db.py <command> [args]

  init                                    Initialize database
  add <type> <title> [narrative]          Add observation
  decision <title> <decision> [rejected] [rationale]  Add decision
  search [query]                          Search observations
  decisions [query]                       Search decisions
  get <id>                                Get full observation
  stats                                   Statistics
  import <json_file>                      Import from JSON
  embed                                   Build/update all embeddings
  semantic <query>                        Semantic search
""")
        return

    cmd = sys.argv[1]

    if cmd == "init":
        init_db()
    elif cmd == "add":
        if len(sys.argv) < 4:
            print("Usage: add <type> <title> [narrative]")
            return
        rid = add_observation(sys.argv[2], sys.argv[3],
                              sys.argv[4] if len(sys.argv) > 4 else None)
        print(f"#{rid} [{sys.argv[2]}] {sys.argv[3]}")
    elif cmd == "decision":
        if len(sys.argv) < 4:
            print("Usage: decision <title> <decision> [rejected] [rationale]")
            return
        rid = add_decision(sys.argv[2], sys.argv[3],
                           [sys.argv[4]] if len(sys.argv) > 4 else None,
                           sys.argv[5] if len(sys.argv) > 5 else None)
        print(f"Decision #{rid}: {sys.argv[2]}")
    elif cmd == "search":
        for r in search(sys.argv[2] if len(sys.argv) > 2 else None):
            print(f"  #{r['id']} [{r['type']}] {r['title']}")
            if r.get('narrative'):
                print(f"    {r['narrative']}")
    elif cmd == "decisions":
        for r in search_decisions(sys.argv[2] if len(sys.argv) > 2 else None):
            print(f"  #{r['id']} {r['title']}: {r['decision']}")
            if r.get('rejected_alternatives'):
                print(f"    rejected: {r['rejected_alternatives']}")
            if r.get('rationale'):
                print(f"    why: {r['rationale']}")
    elif cmd == "get":
        r = get(int(sys.argv[2]))
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str) if r else "Not found")
    elif cmd == "stats":
        print(json.dumps(stats(), indent=2))
    elif cmd == "import":
        with open(sys.argv[2]) as f:
            print(f"Imported: {import_json(json.load(f))}")
    elif cmd == "embed":
        build_embeddings()
    elif cmd == "semantic":
        if len(sys.argv) < 3:
            print("Usage: semantic <query>")
            return
        results = semantic_search(sys.argv[2])
        if not results:
            print("No results. Run 'embed' first to build embeddings.")
            return
        for r in results:
            print(f"  [{r['source_table']}#{r['source_id']}] (score={r['score']}) {r['title']}")
    else:
        print(f"Unknown: {cmd}")


if __name__ == "__main__":
    main()
