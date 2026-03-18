# 意图分类 Prompt

零成本规则优先 + LLM 兜底的意图分类方案。

## 规则引擎（优先）

```python
INTENT_KEYWORDS = {
    "greeting": ["你好", "hi", "hello", "嗨", "早上好", "晚上好"],
    "thanks": ["谢谢", "感谢", "thank"],
    "help": ["怎么用", "功能", "帮助", "教程", "help"],
    "stats": ["统计", "多少", "频率", "排行", "占比", "分布", "趋势"],
    "todo": ["待办", "任务", "提醒", "todo", "记得"],
    "search": ["搜索", "查找", "找一下", "有没有"],
    "calendar": ["日程", "会议", "日历", "安排"],
}

def classify_by_rules(query: str) -> str | None:
    """关键词匹配，命中返回意图，否则 None"""
    query_lower = query.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            return intent
    return None
```

## LLM 兜底

```
判断以下用户输入的意图类型：

"{query}"

可选意图：
- greeting: 打招呼
- thanks: 感谢
- help: 求助/教程
- stats: 数据统计
- todo: 待办管理
- search: 信息搜索
- calendar: 日程相关
- chat: 闲聊
- unknown: 无法判断

只返回意图名称，不要解释。
```

## 设计要点

1. 规则优先：零延迟、零成本、可预测
2. LLM 兜底：处理规则覆盖不到的长尾
3. 意图列表可扩展：加关键词即可，不需要重新训练
4. 多意图场景：可以返回 top-2 意图，让下游决策
