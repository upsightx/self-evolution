#!/usr/bin/env python3
"""
Skillify — 自动技能化模块。

职责：
- 检测重复执行的任务模式
- 自动生成 Skill 草稿（SKILL.md）
- 用 LLM 提炼执行步骤

设计原则：
- 从 task_outcomes 中挖掘高频成功模式
- 生成标准化的 SKILL.md 草稿
- 不自动部署，只生成草稿供人工审核
"""
from __future__ import annotations

import os
import re
import sys
import json
import urllib.request
from collections import Counter
from pathlib import Path
from datetime import datetime

_modules_path = Path(__file__).parent
_workspace_path = _modules_path.parent
if str(_modules_path) not in sys.path:
    sys.path.insert(0, str(_modules_path))
try:
    if str(_workspace_path) not in sys.path:
        sys.path.insert(0, str(_workspace_path))
    from runtime_config import XMEMORY_PATH
    if str(XMEMORY_PATH) not in sys.path:
        sys.path.insert(0, str(XMEMORY_PATH))
except ImportError:
    _xmemory_path = _workspace_path / "X记忆"
    if _xmemory_path.exists() and str(_xmemory_path) not in sys.path:
        sys.path.insert(0, str(_xmemory_path))

from db_common import get_db


def detect_repeated_patterns(min_count: int = 3) -> list[dict]:
    """
    检测重复执行的任务模式。

    Returns:
        重复模式列表，每项包含 pattern, count, descriptions, suggested_skill_name
    """
    db = get_db()
    rows = db.execute(
        """
        SELECT description, notes, tags
        FROM task_outcomes
        WHERE success = 1
        ORDER BY created_at DESC
        """
    ).fetchall()
    db.close()

    # 提取关键词
    word_counter: Counter = Counter()
    desc_by_word: dict = {}

    for row in rows:
        text = " ".join([
            row.get("description", "") or "",
            row.get("notes", "") or "",
            row.get("tags", "") or "",
        ])
        words = [w for w in re.findall(r'[a-z\u4e00-\u9fff]{3,}', text.lower()) if len(w) > 2]
        for w in words:
            word_counter[w] += 1
            if w not in desc_by_word:
                desc_by_word[w] = []
            if len(desc_by_word[w]) < 20:
                desc_by_word[w].append(text[:100])

    # 过滤高频词（停用词）
    stopwords = {"the", "and", "for", "not", "with", "this", "that", "from", "are", "was"}

    patterns = []
    seen = set()
    for word, count in word_counter.most_common(30):
        if count < min_count:
            break
        if word in stopwords or word in seen:
            continue
        seen.add(word)

        descriptions = list(dict.fromkeys(desc_by_word.get(word, [])))[:5]
        suggested_skill_name = word.replace(" ", "_")

        patterns.append({
            "pattern": word,
            "count": count,
            "descriptions": descriptions,
            "suggested_skill_name": suggested_skill_name,
        })

    patterns.sort(key=lambda x: -x["count"])
    return patterns


def _generate_steps_with_llm(pattern: str, descriptions: list[str]) -> str | None:
    """用 LLM 生成执行步骤。"""
    api_key = os.environ.get("SILICONFLOW_API_KEY")
    if not api_key:
        return None

    sample = descriptions[:10]
    prompt = (
        "You are an expert AI Agent Skill Creator.\n"
        "Analyze the following repeated task executions and extract a standardized, step-by-step execution procedure.\n"
        "Focus on **actions**, **tools used**, and **key parameters**.\n\n"
        "Task Descriptions:\n"
        + "\n".join(f"- {d}" for d in sample)
        + "\n\nOutput ONLY the numbered steps. Do not include headers or explanations.\n"
        "Example format:\n"
        "1. Use `tool_name` to fetch data from `url`.\n"
        "2. Parse the result to extract `field_x`.\n"
        "3. Save the output to `path`.\n"
    )

    data = json.dumps({
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }).encode()

    req = urllib.request.Request(
        "https://api.siliconflow.cn/v1/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[skillify] LLM generation failed: {e}")
        return None


def generate_skill_draft(pattern: dict) -> str:
    """
    生成 Skill 草稿（SKILL.md 格式）。

    Args:
        pattern: 来自 detect_repeated_patterns 的模式字典

    Returns:
        SKILL.md 内容字符串
    """
    name = pattern.get("suggested_skill_name", "auto_skill")
    count = pattern.get("count", 0)
    descriptions = pattern.get("descriptions", [])
    first_desc = descriptions[0] if descriptions else name

    # 尝试用 LLM 生成步骤
    steps_text = _generate_steps_with_llm(name, descriptions)
    if not steps_text:
        steps_text = "1. 执行任务\n2. 验证结果\n3. 记录输出"

    title = name.replace("_", " ").title()

    return (
        f"---\n"
        f"name: {name}\n"
        f"description: |\n"
        f"  Auto-generated skill for: {first_desc}\n"
        f"  Detected from {count} repeated task executions.\n\n"
        f"  **Use when**:\n"
        f"  (1) {first_desc}\n"
        f"  (2) Similar tasks requiring automation\n"
        f"---\n\n"
        f"# {title}\n\n"
        f"Auto-generated skill based on repeated task patterns.\n\n"
        f"## Trigger Conditions\n\n"
        f"- When the user asks to {name.replace('_', ' ')}\n"
        f"- When similar tasks are detected in conversation\n\n"
        f"## Execution Steps\n\n"
        f"{steps_text}\n"
    )


def run_skillify(min_count: int = 3, output_dir: str | None = None) -> list[dict]:
    """
    检测模式并生成 Skill 草稿。

    Returns:
        生成的 Skill 草稿列表
    """
    patterns = detect_repeated_patterns(min_count=min_count)
    results = []

    for p in patterns[:5]:  # 最多生成 5 个
        draft = generate_skill_draft(p)
        skill_name = p["suggested_skill_name"]

        if output_dir:
            out_path = Path(output_dir) / f"{skill_name}.md"
            out_path.write_text(draft, encoding="utf-8")
            print(f"[skillify] Generated: {out_path}")

        results.append({
            "skill_name": skill_name,
            "pattern_count": p["count"],
            "draft": draft,
        })

    return results


def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="Skillify — 自动技能化")
    parser.add_argument("--min-count", type=int, default=3, help="最小重复次数")
    parser.add_argument("--output-dir", type=str, default=None, help="输出目录")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    results = run_skillify(min_count=args.min_count, output_dir=args.output_dir)

    if args.json:
        print(json.dumps([{"skill_name": r["skill_name"], "pattern_count": r["pattern_count"]} for r in results], ensure_ascii=False, indent=2))
    else:
        print(f"\n🔧 Skillify 结果 ({len(results)} 个草稿):\n")
        for r in results:
            print(f"  ✅ {r['skill_name']} (检测到 {r['pattern_count']} 次重复)")


if __name__ == "__main__":
    _cli()
