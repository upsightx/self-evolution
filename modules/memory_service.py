#!/usr/bin/env python3
"""
Memory Service — 自我进化记忆系统的统一入口。

职责：
- remember(): 写入记忆 + 自动提取标签 + 增量更新 embedding
- recall(): 检索记忆 + 构建上下文
- reflect(): 定期分析，生成洞察

所有外部调用方通过这个模块访问记忆系统，不需要知道内部细节。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from db_common import DB_PATH


# ============ Tag Extraction ============

TASK_TYPE_KEYWORDS = {
    "coding": ["python", "javascript", "爬虫", "api", "docker", "git", "代码", "编程", "脚本"],
    "research": ["融资", "投资", "论文", "调研", "market", "报告"],
    "file_ops": ["文件", "上传", "下载", "复制", "移动", "删除"],
    "reasoning": ["决策", "判断", "评估", "比较", "权衡"],
    "general": [],
}

MODEL_KEYWORDS = {
    "kimi": ["kimi", "moonshot", "月之暗面"],
    "minimax": ["minimax", "智谱"],
    "opus": ["opus", "claude"],
    "sonnet": ["sonnet"],
    "gpt": ["gpt", "chatgpt", "openai"],
}

# Word-boundary aware matching: each keyword must be a standalone token
# For CJK: matched as substring (CJK chars are self-delimiting)
# For Latin: matched with word boundaries to avoid "monty python" → python
_LATIN_KEYWORDS = {
    "python", "javascript", "typescript", "rust", "go",
    "sqlite", "fastapi", "docker", "kubernetes",
    "github", "api", "http", "websocket", "grpc",
    "rag", "llm", "bge",
    "trending", "hackernews",
}

_CJK_KEYWORDS = [
    "飞书", "融资", "投资", "爬虫", "代码", "编程",
    "文件", "决策", "论文", "调研", "报告",
]

_MIXED_KEYWORDS = [
    "feishu", "lark", "36kr", "embedding", "vector",
    "subagent", "agent", "workflow", "skill", "tool", "memory",
]


def _word_boundary_match(keyword: str, text_lower: str) -> bool:
    """Check if keyword exists as a standalone word in text.

    For Latin keywords: require word boundary OR CJK char boundary.
    For CJK keywords: substring match (CJK chars are self-delimiting).
    """
    if keyword in _LATIN_KEYWORDS:
        # Word boundary: \b OR CJK char OR start/end of string
        # This handles "使用docker部署" where \b doesn't work between CJK and Latin
        pattern = r'(?:^|[\s\b\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])' + re.escape(keyword) + r'(?:$|[\s\b\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])'
        return bool(re.search(pattern, text_lower))
    else:
        return keyword in text_lower


def extract_tags(content: str, task_type: str | None = None) -> list[str]:
    """从内容中自动提取标签。

    Latin 关键词用词边界匹配（避免 "monty python" → python）。
    CJK 关键词用子串匹配（中文字符自带边界）。

    Returns:
        list of tag strings, deduped, max 10
    """
    tags = []
    content_lower = content.lower()

    if task_type and task_type in TASK_TYPE_KEYWORDS:
        tags.append(task_type)

    # Match task type
    for tt, kws in TASK_TYPE_KEYWORDS.items():
        if tt == "general":
            continue
        if any(kw in content_lower for kw in kws):
            tags.append(tt)

    # Match model
    for model, kws in MODEL_KEYWORDS.items():
        if any(_word_boundary_match(kw, content_lower) for kw in kws):
            tags.append(model)

    # Match tech keywords (all three sets)
    for kw in _LATIN_KEYWORDS | set(_CJK_KEYWORDS) | set(_MIXED_KEYWORDS):
        if _word_boundary_match(kw, content_lower):
            tags.append(kw)

    return list(set(tags))[:10]


# ============ Memory Service ============

def remember(
    content: str,
    type: str = "observation",
    title: str | None = None,
    narrative: str | None = None,
    tags: list | None = None,
    task_type: str | None = None,
    triggered_by_obs_id: int | None = None,
    supersedes_decision_id: int | None = None,
) -> dict:
    """写入记忆 + 自动提取标签 + 增量更新 embedding。

    Returns:
        {"id": int, "tags": list, "title": str}
    """
    from memory_store import add_observation, add_decision

    # Auto-extract tags
    auto_tags = extract_tags(content, task_type)
    if tags:
        merged = list(set(auto_tags + [t for t in tags if t]))
    else:
        merged = auto_tags

    # Generate title
    if not title:
        title = content[:40].strip()
        if len(content) > 40:
            title += "..."

    # Store
    try:
        if type == "decision":
            record_id = add_decision(
                title=title,
                decision=content,
                rejected_alternatives=None,
                rationale=narrative,
                triggered_by_obs_id=triggered_by_obs_id,
                supersedes_decision_id=supersedes_decision_id,
            )
            source_table = "decisions"
        else:
            record_id = add_observation(
                type=type,
                title=title,
                narrative=narrative or content,
                tags=merged,
                task_type=task_type,
            )
            source_table = "observations"

        # Incremental embedding update (non-blocking on failure)
        try:
            from memory_embedding import embed_text, _text_hash, _pack_embedding
            from db_common import get_db
            text_for_embed = f"{title}. {narrative or content}"
            vecs = embed_text([text_for_embed])
            if vecs and vecs[0]:
                db = get_db()
                db.execute(
                    """INSERT OR REPLACE INTO embeddings
                       (source_table, source_id, text_hash, embedding)
                       VALUES (?, ?, ?, ?)""",
                    (source_table, record_id, _text_hash(text_for_embed),
                     _pack_embedding(vecs[0])),
                )
                db.commit()
                db.close()
        except Exception:
            pass  # Embedding failure doesn't block the write

        return {"id": record_id, "tags": merged, "title": title}

    except Exception as e:
        print(f"[memory_service] remember failed: {e}")
        return {"id": None, "error": str(e)}


def recall(
    query: str,
    tags: list | None = None,
    task_type: str | None = None,
    top_k: int = 5,
) -> str:
    """检索记忆 + 构建上下文字符串。

    Returns:
        上下文字符串，可以直接拼到 prompt 末尾。空字符串表示无结果。
    """
    from memory_retrieval import retrieve, build_context, rewrite_query

    queries = rewrite_query(query)
    candidates = retrieve(
        query_or_queries=queries,
        tags=tags,
        task_type=task_type,
        top_k=top_k,
    )

    ctx = build_context(query, candidates)
    if not ctx:
        return ""

    return f"[Relevant Memory]\n{ctx}\n\n"


def reflect() -> dict:
    """定期分析：生成洞察和建议。

    Returns:
        dict with keys: new_insights, tags_frequency, recent_decisions, total_recent
    """
    from memory_store import get_recent

    recent = get_recent(days=7, limit=100)

    # Count tag frequency
    tag_counts = {}
    for r in recent:
        tags_str = r.get("tags", "")
        if tags_str:
            for tag in tags_str.split(","):
                tag = tag.strip()
                if tag:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    insights = [r for r in recent if r.get("type") in ("discovery", "lesson", "bugfix")]
    decisions = [r for r in recent if r.get("kind") == "decision"]

    return {
        "new_insights": insights[:5],
        "tags_frequency": top_tags,
        "recent_decisions": decisions[:5],
        "total_recent": len(recent),
    }


# ============ CLI ============

def cli():
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers()

    remember_p = sub.add_parser("remember", help="Write a memory")
    remember_p.add_argument("type", choices=["observation", "decision", "bugfix", "discovery", "lesson"])
    remember_p.add_argument("content")
    remember_p.add_argument("--title", default=None)
    remember_p.add_argument("--tags", default=None)
    remember_p.add_argument("--task-type", default=None)
    remember_p.set_defaults(cmd="remember")

    recall_p = sub.add_parser("recall", help="Recall memories")
    recall_p.add_argument("query")
    recall_p.add_argument("--top-k", type=int, default=5)
    recall_p.set_defaults(cmd="recall")

    reflect_p = sub.add_parser("reflect", help="Generate insights from recent memories")
    reflect_p.set_defaults(cmd="reflect")

    args = p.parse_args()

    if not hasattr(args, "cmd"):
        p.print_help()
        return

    if args.cmd == "remember":
        tags = args.tags.split(",") if args.tags else None
        result = remember(
            content=args.content,
            type=args.type,
            title=args.title,
            tags=tags,
            task_type=args.task_type,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.cmd == "recall":
        ctx = recall(args.query, top_k=args.top_k)
        print(ctx if ctx else "(no results)")

    elif args.cmd == "reflect":
        result = reflect()
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    cli()
