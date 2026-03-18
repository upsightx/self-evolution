"""
Todo extractor - 从对话文本中用纯规则提取待办事项。
采用"宽松提取+置信度分级"思路，零LLM成本。
可选 LLM 兜底层：规则提取不到时，用 MiniMax 做一次提取。

依赖：纯 stdlib (re, os, difflib, urllib, json)
"""

import re
import os
import json as _json
import urllib.request
import urllib.error
from difflib import SequenceMatcher

# ============================================================
# 规则定义
# ============================================================

# 明确承诺 (confidence 0.8-0.9)
COMMIT_PATTERNS = [
    # "帮我..." / "帮我们..."
    (r'帮我(?:们)?(.+)', 0.85),
    # "记得..."
    (r'记得(.+)', 0.85),
    # "我会..." / "我来..." / "我去..."
    (r'我(?:会|来|去)(.+)', 0.85),
    # "好的我..." / "好我..." / "行我..."
    (r'(?:好的?|行|OK|ok)[\s,，]*我(?:来|去|会)?(.+)', 0.85),
    # "麻烦..." (请求类)
    (r'麻烦(?:你)?(.+)', 0.80),
    # "请..." (请求类)
    (r'请(?:你)?(?:帮我)?(.+)', 0.80),
    # "一定要..."
    (r'一定(?:要|得)(.+)', 0.85),
    # "别忘了..."
    (r'别忘了(.+)', 0.85),
    # "不要忘记..."
    (r'不要忘记(.+)', 0.85),
]

# 计划讨论 (confidence 0.6-0.7)
PLAN_PATTERNS = [
    (r'需要(.+)', 0.65),
    (r'应该(.+)', 0.60),
    (r'打算(.+)', 0.65),
    (r'准备(.+)', 0.65),
    (r'考虑(?:一下)?(.+)', 0.60),
    (r'想(?:要|办法)?(.+)', 0.60),
    (r'得(?:去|想办法)?(.+)', 0.60),
]

# 时间约定 (confidence 0.7-0.8) — 时间词开头
TIME_PATTERNS = [
    (r'(明天.+)', 0.75),
    (r'(后天.+)', 0.75),
    (r'(下周.+)', 0.75),
    (r'(下个?月.+)', 0.75),
    (r'(等(?:会儿?|一下|下).+)', 0.70),
    (r'(今晚.+)', 0.75),
    (r'(周[一二三四五六日天].+)', 0.75),
    (r'(这周.+)', 0.70),
]

# 时间词提取（用于 time_hint）
TIME_HINT_RE = re.compile(
    r'(今天|明天|后天|今晚|明晚|'
    r'下周[一二三四五六日天]?|这周[一二三四五六日天]?|'
    r'周[一二三四五六日天]|'
    r'下个?月|月底|年底|'
    r'等(?:会儿?|一下|下)|'
    r'待会儿?|稍后|晚点|'
    r'\d+[点时](?:半|钟)?(?:\d+分?)?|'
    r'\d+月\d+[日号])'
)

# 排除模式 — 匹配到这些说明不是待办
EXCLUDE_RE = re.compile(
    r'^(今天天气|天气不错|天气真|你好|谢谢|哈哈|嗯|好的$|'
    r'是的|对的|没错|不是|不用|不需要|算了|没事|'
    r'早上好|晚上好|中午好|下午好|你觉得|我觉得.{0,4}$|'
    r'好吧$|行吧$|可以$|没问题$|知道了$|了解$|收到$|'
    r'不好意思|抱歉|对不起)',
    re.IGNORECASE
)

# 太短的内容不算待办
MIN_TITLE_LEN = 3
MAX_TITLE_LEN = 30

# ============================================================
# 核心函数
# ============================================================


def _clean_title(raw: str) -> str:
    """清理提取到的标题文本"""
    # 去掉首尾标点和空白
    title = raw.strip()
    title = re.sub(r'^[,，。.、;；:：!！?？\s]+', '', title)
    title = re.sub(r'[,，。.;；!！?？\s]+$', '', title)
    # 截断到 MAX_TITLE_LEN
    if len(title) > MAX_TITLE_LEN:
        title = title[:MAX_TITLE_LEN]
    return title


def _extract_time_hint(text: str) -> str:
    """从文本中提取时间提示词"""
    m = TIME_HINT_RE.search(text)
    return m.group(1) if m else ""


def _is_excluded(text: str) -> bool:
    """判断文本是否应被排除（寒暄、确认等非待办内容）"""
    return bool(EXCLUDE_RE.search(text.strip()))


def _similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度 (0-1)"""
    return SequenceMatcher(None, a, b).ratio()


def _load_existing_titles(pending_tasks_path: str) -> list[str]:
    """从 pending-tasks.md 加载已有的待办标题"""
    titles = []
    if not os.path.exists(pending_tasks_path):
        return titles
    with open(pending_tasks_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # 匹配 "- [ ] xxx" 或 "- [x] xxx" 或 "- xxx" 格式
            m = re.match(r'^-\s*(?:\[[ x]\]\s*)?(.+)', line)
            if m:
                titles.append(m.group(1).strip())
    return titles


def _is_duplicate(title: str, existing_titles: list[str], threshold: float = 0.7) -> bool:
    """检查标题是否与已有待办重复"""
    for existing in existing_titles:
        if _similarity(title, existing) > threshold:
            return True
    return False


def extract_todos_with_llm(text: str) -> list[dict]:
    """用 MiniMax LLM 从文本中提取待办事项（兜底层）。

    Returns:
        [{"title": "...", "confidence": 0.5-0.9, "time_hint": "..."}]
        解析失败返回空列表。
    """
    api_key = os.environ.get("MINIMAX_API_KEY", "")
    if not api_key:
        return []
    url = "https://api.minimaxi.com/v1/chat/completions"
    payload = _json.dumps({
        "model": "MiniMax-M2.5",
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是待办提取助手。从文本中识别待办事项。\n"
                    "返回JSON数组，每项包含 title(≤20字)、confidence(0.5-0.9)、time_hint(时间词或空)。\n"
                    "没有待办返回空数组。只返回JSON，不要解释。"
                ),
            },
            {"role": "user", "content": text},
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = _json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        # Strip <think>...</think> reasoning tags if present
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
        content = content.strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
        items = _json.loads(content)
        if not isinstance(items, list):
            return []
        # Validate and normalise each item
        result = []
        for item in items:
            if not isinstance(item, dict) or "title" not in item:
                continue
            result.append({
                "title": str(item["title"])[:20],
                "confidence": float(item.get("confidence", 0.6)),
                "time_hint": str(item.get("time_hint", "")),
            })
        return result
    except Exception:
        return []


def extract_todos_from_text(
    text: str,
    pending_tasks_path: str = "",
    use_llm: bool = False,
) -> list[dict]:
    """从文本中提取待办（规则引擎 + 可选 LLM 兜底）

    Args:
        text: 对话文本（可以是多行）
        pending_tasks_path: pending-tasks.md 的路径，用于去重。
                           为空则使用默认路径。
        use_llm: 为 True 时，规则提取为空则调用 LLM 兜底。

    Returns:
        [{"title": "...", "confidence": 0.8, "source_text": "...", "time_hint": "..."}]
    """
    if not pending_tasks_path:
        pending_tasks_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'pending-tasks.md'
        )

    existing_titles = _load_existing_titles(pending_tasks_path)
    results = []
    seen_titles = set()  # 本次提取内去重

    # 按行处理
    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 排除寒暄/确认类
        if _is_excluded(line):
            continue

        best_match = None
        best_confidence = 0.0

        # 依次尝试三类模式，取最高置信度
        all_patterns = (
            list(COMMIT_PATTERNS) +
            list(TIME_PATTERNS) +
            list(PLAN_PATTERNS)
        )

        for pattern, confidence in all_patterns:
            m = re.search(pattern, line)
            if m:
                raw_title = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
                title = _clean_title(raw_title)

                if len(title) < MIN_TITLE_LEN:
                    continue

                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = title

        if best_match and best_confidence > 0:
            # 本次提取内去重
            if best_match in seen_titles:
                continue

            # 跟已有待办去重
            if _is_duplicate(best_match, existing_titles):
                continue

            time_hint = _extract_time_hint(line)

            results.append({
                "title": best_match,
                "confidence": best_confidence,
                "source_text": line[:80],  # 保留来源，截断
                "time_hint": time_hint,
            })
            seen_titles.add(best_match)
            existing_titles.append(best_match)  # 后续行也不重复

    # LLM 兜底：规则提取为空且启用 LLM 时
    if use_llm and not results:
        llm_items = extract_todos_with_llm(text)
        for item in llm_items:
            title = _clean_title(item["title"])
            if len(title) < MIN_TITLE_LEN:
                continue
            if title in seen_titles:
                continue
            if _is_duplicate(title, existing_titles):
                continue
            # LLM 结果 confidence 统一降 0.1
            confidence = max(0.0, item["confidence"] - 0.1)
            time_hint = item.get("time_hint", "")
            results.append({
                "title": title,
                "confidence": confidence,
                "source_text": text[:80],
                "time_hint": time_hint,
            })
            seen_titles.add(title)
            existing_titles.append(title)

    return results


# ============================================================
# CLI 入口（调试用）
# ============================================================

if __name__ == '__main__':
    import sys
    import json

    use_llm = False
    args = sys.argv[1:]

    if '--llm' in args:
        use_llm = True
        args.remove('--llm')

    if args:
        text = ' '.join(args)
    else:
        text = sys.stdin.read()

    todos = extract_todos_from_text(text, use_llm=use_llm)
    print(json.dumps(todos, ensure_ascii=False, indent=2))
