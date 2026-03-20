#!/usr/bin/env python3
"""
Context Builder for memory_db.

Handles: search_with_context, search_with_metadata.
Builds formatted context strings from search results for LLM consumption.
Separated from memory_db.py for single-responsibility.
"""
from __future__ import annotations

import re

from db_common import get_db


def _extract_date(timestamp_str: str | None) -> str:
    """Extract YYYY-MM-DD from an ISO timestamp string."""
    if not timestamp_str:
        return "未知日期"
    match = re.search(r'\d{4}-\d{2}-\d{2}', str(timestamp_str))
    return match.group(0) if match else "未知日期"


def _format_entry(entry_type: str, title: str, content: str | None) -> str:
    """Format a single entry line. Truncate content to 200 chars."""
    if content and len(content) > 200:
        content = content[:197] + "..."
    suffix = f": {content}" if content else ""
    return f"[{entry_type}] {title}{suffix}"


def _build_context_from_entries(entries: list[dict], max_chars: int, top_per_group: int) -> str:
    """Shared logic: take a list of dicts with 'type'/'title'/'content'/'timestamp',
    group by date, truncate, return formatted string."""
    merged: dict[str, list[str]] = {}
    for e in entries:
        date = _extract_date(e.get("timestamp"))
        merged.setdefault(date, [])
        merged[date].append(_format_entry(
            e.get("type", "unknown"), e.get("title", ""), e.get("content", "")))

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


def _search_with_context_semantic(query: str, max_chars: int, top_per_group: int) -> str:
    """Semantic-only search_with_context."""
    from memory_embedding import semantic_search
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


def _search_with_context_hybrid(query: str, max_chars: int, top_per_group: int) -> str:
    """Hybrid: merge keyword + semantic results, deduplicate, weighted score."""
    from memory_db import search, search_decisions
    from memory_embedding import semantic_search

    obs_kw = search(query=query, limit=30)
    decs_kw = search_decisions(query=query, limit=30)

    try:
        sem_results = semantic_search(query, limit=30)
    except Exception:
        sem_results = []

    scored: dict[tuple, dict] = {}

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

    db = get_db()
    for r in sem_results:
        key = (r["source_table"], r["source_id"])
        sem_score = r["score"]
        if key in scored:
            scored[key]["sem_score"] = sem_score
        else:
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

    combined = []
    for key, val in scored.items():
        final_score = 0.4 * val["kw_score"] + 0.6 * val["sem_score"]
        combined.append((final_score, val["entry"]))

    combined.sort(key=lambda x: x[0], reverse=True)
    entries = [c[1] for c in combined[:50]]

    return _build_context_from_entries(entries, max_chars, top_per_group)


def search_with_context(query: str, max_chars: int = 6000, top_per_group: int = 3,
                        mode: str = "keyword") -> str:
    """Search and build context string.

    Args:
        mode: "keyword" (default, FTS5+LIKE), "semantic" (embedding cosine),
              "hybrid" (merge both, weighted score)
    """
    if mode == "semantic":
        return _search_with_context_semantic(query, max_chars, top_per_group)
    elif mode == "hybrid":
        return _search_with_context_hybrid(query, max_chars, top_per_group)

    # Default: keyword mode
    from memory_db import search, search_decisions

    obs = search(query=query, limit=50)
    decs = search_decisions(query=query, limit=50)

    merged: dict[str, list[str]] = {}
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

    sorted_dates = sorted(merged.keys(), reverse=True)
    date_parts = []
    for date in sorted_dates:
        entries = merged[date][:top_per_group]
        block = f"--- {date} ---\n" + "\n".join(entries)
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


def search_with_metadata(query: str, max_chars: int = 6000, top_per_group: int = 3) -> dict:
    """Search and return context + metadata.

    Returns: {
        "context": "formatted context string",
        "total_results": 10,
        "context_chars": 5800,
        "truncated": False,
        "date_range": {"earliest": "2026-03-15", "latest": "2026-03-18"}
    }
    """
    from memory_db import search, search_decisions

    obs = search(query=query, limit=50)
    decs = search_decisions(query=query, limit=50)
    total_results = len(obs) + len(decs)

    all_dates = []
    for r in obs + decs:
        d = _extract_date(r.get("timestamp"))
        if d != "未知日期":
            all_dates.append(d)

    context = search_with_context(query, max_chars=max_chars, top_per_group=top_per_group)
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
