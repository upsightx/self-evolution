#!/usr/bin/env python3
"""
Capability Model — Self-Evolution核心模块之二。

能力自画像：维护"我能做什么"的清单+评分。
从 task_outcomes 自动计算能力评分，识别短板。

设计原则：
- 能力 = task_type 维度的成功率 + 质量分
- 自动从 feedback_loop 的 task_outcomes 表聚合
- 支持手动注册新能力维度
- 输出能力缺口给 goal_tree 消费
- 能力评分 0-100，按最近 N 次任务加权（近期权重更高）

不做什么：
- 不自动执行改进
- 不调用外部 API
- 不做 LLM 推理
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Path setup so db_common and runtime_config can be found
_modules = Path(__file__).parent
_workspace = _modules.parent
for p in [str(_workspace), str(_modules)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from runtime_config import XMEMORY_PATH
    if str(XMEMORY_PATH) not in sys.path:
        sys.path.insert(0, str(XMEMORY_PATH))
except ImportError:
    pass

from db_common import DB_PATH, get_db

SCHEMA = """
CREATE TABLE IF NOT EXISTS capabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'task',
    description TEXT DEFAULT '',
    score REAL DEFAULT 0,
    confidence REAL DEFAULT 0,
    sample_count INTEGER DEFAULT 0,
    last_evaluated TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_capabilities_name ON capabilities(name);
CREATE INDEX IF NOT EXISTS idx_capabilities_category ON capabilities(category);
"""

VALID_CATEGORIES = {"task", "tool", "knowledge", "meta"}


def _ensure_table():
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()
    db.close()


# ============ Core: Auto-evaluate from task_outcomes ============

def evaluate_all(days: int = 30, min_samples: int = 3) -> list[dict]:
    """Auto-evaluate all capabilities from task_outcomes data.

    Scans task_outcomes for distinct task_types, computes weighted
    success rate (recent tasks weighted more), and upserts into
    capabilities table.

    Returns list of evaluated capabilities.
    """
    _ensure_table()
    db = get_db()
    results = []

    try:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        # Get all task types with recent outcomes
        task_types = db.execute(
            """SELECT DISTINCT task_type FROM task_outcomes
               WHERE created_at >= ? AND task_type IS NOT NULL AND task_type != ''""",
            (cutoff,),
        ).fetchall()

        now = datetime.now()

        for tt in task_types:
            task_type = tt["task_type"]

            # Get all outcomes for this task type in the window
            rows = db.execute(
                """SELECT success, created_at, notes
                   FROM task_outcomes
                   WHERE task_type = ? AND created_at >= ?
                   ORDER BY created_at DESC""",
                (task_type, cutoff),
            ).fetchall()

            if len(rows) < min_samples:
                continue

            # Weighted success rate: exponential decay, recent = higher weight
            total_weight = 0.0
            weighted_success = 0.0

            for i, r in enumerate(rows):
                # Parse created_at for age-based weighting
                try:
                    ts = datetime.fromisoformat(r["created_at"])
                    age_days = (now - ts).total_seconds() / 86400
                except (ValueError, TypeError):
                    age_days = days  # fallback: oldest

                # Exponential decay: half-life = 7 days
                weight = math.exp(-0.693 * age_days / 7)
                total_weight += weight
                if r["success"]:
                    weighted_success += weight

            score = (weighted_success / total_weight * 100) if total_weight > 0 else 0

            # Confidence based on sample count
            n = len(rows)
            if n >= 20:
                confidence = 0.95
            elif n >= 10:
                confidence = 0.80
            elif n >= 5:
                confidence = 0.60
            else:
                confidence = 0.40

            # Upsert capability
            existing = db.execute(
                "SELECT id FROM capabilities WHERE name = ?", (task_type,)
            ).fetchone()

            now_str = datetime.now().isoformat()
            if existing:
                db.execute(
                    """UPDATE capabilities SET
                       score = ?, confidence = ?, sample_count = ?,
                       last_evaluated = ?, updated_at = ?
                       WHERE name = ?""",
                    (round(score, 2), round(confidence, 3), n, now_str, now_str, task_type),
                )
            else:
                db.execute(
                    """INSERT INTO capabilities
                       (name, category, description, score, confidence,
                        sample_count, last_evaluated)
                       VALUES (?,?,?,?,?,?,?)""",
                    (task_type, "task", f"Auto-detected from task_outcomes: {task_type}",
                     round(score, 2), round(confidence, 3), n, now_str),
                )

            results.append({
                "name": task_type,
                "score": round(score, 2),
                "confidence": round(confidence, 3),
                "sample_count": n,
            })

        db.commit()
    except sqlite3.Error as e:
        print(f"[capability_model] Error evaluating: {e}")
    finally:
        db.close()

    results.sort(key=lambda x: x["score"])
    return results


# ============ Write ============

def register_capability(
    name: str,
    category: str = "task",
    description: str = "",
    score: float = 0,
) -> int | None:
    """Manually register a new capability dimension."""
    if category not in VALID_CATEGORIES:
        category = "task"

    _ensure_table()
    db = get_db()
    try:
        existing = db.execute("SELECT id FROM capabilities WHERE name = ?", (name,)).fetchone()
        if existing:
            print(f"[capability_model] Capability '{name}' already exists (#{existing['id']})")
            return existing["id"]

        cur = db.execute(
            """INSERT INTO capabilities (name, category, description, score)
               VALUES (?,?,?,?)""",
            (name, category, description, score),
        )
        db.commit()
        return cur.lastrowid
    except sqlite3.Error as e:
        print(f"[capability_model] Error: {e}")
        return None
    finally:
        db.close()


def update_score(name: str, score: float, confidence: float | None = None) -> bool:
    """Manually update a capability's score."""
    _ensure_table()
    db = get_db()
    try:
        row = db.execute("SELECT id FROM capabilities WHERE name = ?", (name,)).fetchone()
        if not row:
            print(f"[capability_model] Capability '{name}' not found")
            return False

        now_str = datetime.now().isoformat()
        if confidence is not None:
            db.execute(
                "UPDATE capabilities SET score = ?, confidence = ?, last_evaluated = ?, updated_at = ? WHERE name = ?",
                (score, confidence, now_str, now_str, name),
            )
        else:
            db.execute(
                "UPDATE capabilities SET score = ?, last_evaluated = ?, updated_at = ? WHERE name = ?",
                (score, now_str, now_str, name),
            )
        db.commit()
        return True
    except sqlite3.Error as e:
        print(f"[capability_model] Error: {e}")
        return False
    finally:
        db.close()


# ============ Query ============

def get_capability(name: str) -> dict | None:
    """Get a single capability by name."""
    _ensure_table()
    db = get_db()
    try:
        row = db.execute("SELECT * FROM capabilities WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def list_capabilities(
    category: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    sort_by: str = "score",
    limit: int = 50,
) -> list[dict]:
    """List capabilities with optional filters."""
    _ensure_table()
    db = get_db()
    try:
        conditions = ["status = 'active'"]
        params = []

        if category:
            conditions.append("category = ?")
            params.append(category)
        if min_score is not None:
            conditions.append("score >= ?")
            params.append(min_score)
        if max_score is not None:
            conditions.append("score <= ?")
            params.append(max_score)

        where = " WHERE " + " AND ".join(conditions)

        order = "score ASC" if sort_by == "score" else "name ASC"
        params.append(limit)

        rows = db.execute(
            f"SELECT * FROM capabilities{where} ORDER BY {order} LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def get_weaknesses(threshold: float = 70.0, min_confidence: float = 0.0) -> list[dict]:
    """Get capabilities below threshold score.

    简化版：只看分数，不等"有把握"再行动。
    """
    _ensure_table()
    db = get_db()
    try:
        rows = db.execute(
            """SELECT * FROM capabilities
               WHERE status = 'active' AND score < ?
               ORDER BY score ASC""",
            (threshold,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def get_strengths(threshold: float = 80.0, min_confidence: float = 0.0) -> list[dict]:
    """Get capabilities above threshold score."""
    _ensure_table()
    db = get_db()
    try:
        rows = db.execute(
            """SELECT * FROM capabilities
               WHERE status = 'active' AND score >= ?
               ORDER BY score DESC""",
            (threshold,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def get_profile() -> dict:
    """Get a complete capability profile: strengths, weaknesses, and overall score."""
    _ensure_table()
    db = get_db()
    try:
        all_caps = db.execute(
            "SELECT * FROM capabilities WHERE status = 'active'"
        ).fetchall()

        if not all_caps:
            return {
                "overall_score": 0,
                "total_capabilities": 0,
                "strengths": [],
                "weaknesses": [],
                "unknown": [],
            }

        caps = [dict(r) for r in all_caps]

        # Weighted overall score (by confidence)
        total_weight = sum(c["confidence"] for c in caps if c["confidence"] > 0)
        if total_weight > 0:
            overall = sum(c["score"] * c["confidence"] for c in caps) / total_weight
        else:
            overall = 0

        strengths = [c for c in caps if c["score"] >= 80]
        weaknesses = [c for c in caps if c["score"] < 70]
        unknown = []

        strengths.sort(key=lambda x: -x["score"])
        weaknesses.sort(key=lambda x: x["score"])

        return {
            "overall_score": round(overall, 2),
            "total_capabilities": len(caps),
            "strengths": [{"name": s["name"], "score": s["score"], "samples": s["sample_count"]} for s in strengths],
            "weaknesses": [{"name": w["name"], "score": w["score"], "samples": w["sample_count"]} for w in weaknesses],
            "unknown": [{"name": u["name"], "score": u["score"], "samples": u["sample_count"]} for u in unknown],
        }
    finally:
        db.close()


def summary() -> dict:
    """Quick summary stats."""
    _ensure_table()
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM capabilities WHERE status='active'").fetchone()[0]
        avg_score = db.execute("SELECT AVG(score) FROM capabilities WHERE status='active'").fetchone()[0] or 0
        by_category = {}
        for r in db.execute(
            "SELECT category, COUNT(*) as c, AVG(score) as avg FROM capabilities WHERE status='active' GROUP BY category"
        ).fetchall():
            by_category[r["category"]] = {"count": r["c"], "avg_score": round(r["avg"] or 0, 2)}

        return {
            "total": total,
            "avg_score": round(avg_score, 2),
            "by_category": by_category,
        }
    finally:
        db.close()


# ============ CLI ============

def _score_bar(score: float) -> str:
    """Visual score bar."""
    bar_len = 10
    filled = int(score / 100 * bar_len)
    return "█" * filled + "░" * (bar_len - filled)


def _cli():
    parser = argparse.ArgumentParser(description="Capability Model — Self-Evolution能力画像")
    sub = parser.add_subparsers(dest="command")

    # evaluate
    p_eval = sub.add_parser("evaluate", help="Auto-evaluate from task_outcomes")
    p_eval.add_argument("--days", type=int, default=30)
    p_eval.add_argument("--min-samples", type=int, default=3)

    # register
    p_reg = sub.add_parser("register", help="Register a new capability")
    p_reg.add_argument("name")
    p_reg.add_argument("--category", default="task", choices=list(VALID_CATEGORIES))
    p_reg.add_argument("--desc", default="")
    p_reg.add_argument("--score", type=float, default=0)

    # update
    p_upd = sub.add_parser("update-score", help="Manually update score")
    p_upd.add_argument("name")
    p_upd.add_argument("score", type=float)
    p_upd.add_argument("--confidence", type=float, default=None)

    # list
    p_list = sub.add_parser("list", help="List capabilities")
    p_list.add_argument("--category", default=None)
    p_list.add_argument("--max-score", type=float, default=None)

    # weaknesses
    p_weak = sub.add_parser("weaknesses", help="Show weaknesses")
    p_weak.add_argument("--threshold", type=float, default=70.0)

    # strengths
    p_str = sub.add_parser("strengths", help="Show strengths")
    p_str.add_argument("--threshold", type=float, default=80.0)

    # profile
    sub.add_parser("profile", help="Full capability profile")

    # summary
    sub.add_parser("summary", help="Quick summary")

    args = parser.parse_args()

    if args.command == "evaluate":
        results = evaluate_all(days=args.days, min_samples=args.min_samples)
        if not results:
            print("No capabilities evaluated (insufficient data)")
        for r in results:
            bar = _score_bar(r["score"])
            print(f"  [{bar}] {r['score']:5.1f}  {r['name']}  (n={r['sample_count']}, conf={r['confidence']:.2f})")

    elif args.command == "register":
        cid = register_capability(args.name, args.category, args.desc, args.score)
        if cid:
            print(f"✅ Registered capability '{args.name}' (#{cid})")

    elif args.command == "update-score":
        ok = update_score(args.name, args.score, args.confidence)
        print(f"{'✅' if ok else '❌'} Update '{args.name}' → {args.score}")

    elif args.command == "list":
        caps = list_capabilities(category=args.category, max_score=args.max_score)
        if not caps:
            print("No capabilities found")
        for c in caps:
            bar = _score_bar(c["score"])
            print(f"  [{bar}] {c['score']:5.1f}  {c['name']}  ({c['category']}, n={c['sample_count']})")

    elif args.command == "weaknesses":
        weak = get_weaknesses(threshold=args.threshold)
        if not weak:
            print(f"No weaknesses below {args.threshold}")
        for w in weak:
            bar = _score_bar(w["score"])
            print(f"  [{bar}] {w['score']:5.1f}  {w['name']}  (n={w['sample_count']})")

    elif args.command == "strengths":
        strong = get_strengths(threshold=args.threshold)
        if not strong:
            print(f"No strengths above {args.threshold}")
        for s in strong:
            bar = _score_bar(s["score"])
            print(f"  [{bar}] {s['score']:5.1f}  {s['name']}  (n={s['sample_count']})")

    elif args.command == "profile":
        p = get_profile()
        print(f"Overall Score: {p['overall_score']:.1f}/100  ({p['total_capabilities']} capabilities)")
        if p["strengths"]:
            print("\nStrengths:")
            for s in p["strengths"]:
                print(f"  ✅ {s['name']}: {s['score']:.1f} (n={s['samples']})")
        if p["weaknesses"]:
            print("\nWeaknesses:")
            for w in p["weaknesses"]:
                print(f"  ⚠️ {w['name']}: {w['score']:.1f} (n={w['samples']})")
        if p["unknown"]:
            print("\nInsufficient data:")
            for u in p["unknown"]:
                print(f"  ❓ {u['name']}: {u['score']:.1f} (n={u['samples']})")

    elif args.command == "summary":
        s = summary()
        print(json.dumps(s, indent=2, ensure_ascii=False))

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
