"""自然语言查询解析器

从用户输入中提取结构化查询条件：时间范围、关键词、查询类型。
规则优先 + LLM 兜底。零外部依赖。

用法：
    parser = QueryParser()
    result = parser.parse("最近3天的会议记录")
    # QueryConditions(start_time=..., end_time=..., keywords=["会议记录"])
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class QueryConditions:
    start_time: datetime | None = None
    end_time: datetime | None = None
    keywords: list[str] = field(default_factory=list)
    query_type: str = "general"  # general/stats/search/todo

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "keywords": self.keywords,
            "query_type": self.query_type,
        }


class QueryParser:
    """规则优先的查询解析器"""

    # 中文时间模式 → (start_time, end_time) 生成函数
    TIME_PATTERNS: list[tuple[str, Any]] = []

    def __init__(self):
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=0)

        self.TIME_PATTERNS = [
            (r"今天", lambda m: (today_start, today_end)),
            (r"昨天", lambda m: (today_start - timedelta(days=1),
                                today_end - timedelta(days=1))),
            (r"前天", lambda m: (today_start - timedelta(days=2),
                                today_end - timedelta(days=2))),
            (r"最近(\d+)天", lambda m: (now - timedelta(days=int(m.group(1))), now)),
            (r"最近(\d+)小时", lambda m: (now - timedelta(hours=int(m.group(1))), now)),
            (r"这周|本周", lambda m: (today_start - timedelta(days=now.weekday()), today_end)),
            (r"上周", lambda m: (
                today_start - timedelta(days=now.weekday() + 7),
                today_end - timedelta(days=now.weekday() + 1)
            )),
            (r"这个月|本月", lambda m: (today_start.replace(day=1), today_end)),
        ]

        # 查询类型关键词
        self.TYPE_KEYWORDS = {
            "stats": ["统计", "多少", "频率", "排行", "占比", "分布"],
            "search": ["搜索", "查找", "找", "有没有"],
            "todo": ["待办", "任务", "提醒", "todo"],
        }

        # 停用词（提取关键词时过滤）
        self.STOP_WORDS = {
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都",
            "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你",
            "会", "着", "没有", "看", "好", "自己", "这", "他", "她", "它",
            "什么", "怎么", "哪些", "多少", "请", "帮", "查", "看看",
        }

    def parse(self, query: str) -> QueryConditions:
        """解析查询，返回结构化条件"""
        conditions = QueryConditions()

        # 1. 提取时间范围
        conditions.start_time, conditions.end_time = self._extract_time(query)

        # 2. 判断查询类型
        conditions.query_type = self._classify_type(query)

        # 3. 提取关键词
        conditions.keywords = self._extract_keywords(query)

        return conditions

    def _extract_time(self, query: str) -> tuple[datetime | None, datetime | None]:
        """从查询中提取时间范围"""
        for pattern, fn in self.TIME_PATTERNS:
            match = re.search(pattern, query)
            if match:
                return fn(match)
        return None, None

    def _classify_type(self, query: str) -> str:
        """关键词匹配查询类型"""
        for qtype, keywords in self.TYPE_KEYWORDS.items():
            if any(kw in query for kw in keywords):
                return qtype
        return "general"

    def _extract_keywords(self, query: str) -> list[str]:
        """提取有意义的关键词（去停用词 + 去时间词）"""
        # 移除时间表达式
        cleaned = query
        for pattern, _ in self.TIME_PATTERNS:
            cleaned = re.sub(pattern, "", cleaned)

        # 简单分词（按非中文字符和标点分割）
        tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', cleaned)

        # 过滤停用词和短词
        keywords = [t for t in tokens if t not in self.STOP_WORDS and len(t) >= 2]
        return keywords
