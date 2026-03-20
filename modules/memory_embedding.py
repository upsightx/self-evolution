#!/usr/bin/env python3
"""
Embedding & Semantic Search for memory_db.

Handles: embed_text (SiliconFlow BGE-M3), build_embeddings, semantic_search.
Separated from memory_db.py for single-responsibility.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import urllib.request

from db_common import get_db

SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
SILICONFLOW_ENDPOINT = "https://api.siliconflow.cn/v1/embeddings"
EMBED_MODEL = "BAAI/bge-m3"
EMBED_DIM = 1024
EMBED_BATCH_SIZE = 20


def _text_hash(text: str) -> str:
    """SHA256 hash of text for change detection."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pack_embedding(vec: list[float]) -> bytes:
    """Pack a list of floats into a BLOB using struct (float32)."""
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_embedding(blob: bytes) -> list[float]:
    """Unpack a BLOB back into a list of floats."""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def embed_text(texts: list[str]) -> list[list[float]]:
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

        sorted_data = sorted(body["data"], key=lambda x: x["index"])
        all_embeddings.extend([item["embedding"] for item in sorted_data])

    return all_embeddings


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Pure Python, no numpy."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_embeddings():
    """Build/update embeddings for all observations and decisions."""
    from memory_db import init_db
    init_db()
    db = get_db()

    tasks = []  # (source_table, source_id, text, text_hash)

    for row in db.execute("SELECT id, title, narrative, facts FROM observations").fetchall():
        parts = [row["title"] or ""]
        if row["narrative"]:
            parts.append(row["narrative"])
        if row["facts"]:
            parts.append(row["facts"])
        text = "\n".join(parts)
        tasks.append(("observations", row["id"], text, _text_hash(text)))

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

    existing = {}
    for row in db.execute("SELECT source_table, source_id, text_hash FROM embeddings").fetchall():
        existing[(row["source_table"], row["source_id"])] = row["text_hash"]

    to_embed = []
    for source_table, source_id, text, th in tasks:
        key = (source_table, source_id)
        if key in existing and existing[key] == th:
            continue
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


def semantic_search(query: str, limit: int = 10) -> list[dict]:
    """Semantic search using cosine similarity against stored embeddings.

    Returns:
        list[dict] with keys: source_table, source_id, title, timestamp, score
    """
    from memory_db import init_db
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
