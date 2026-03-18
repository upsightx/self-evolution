"""RAG 上下文构建器

控制送入 LLM 的上下文大小和质量。
按相关性排序 → 时间分组 → 截断到 token 预算。

用法：
    builder = ContextBuilder(max_chars=8000)
    context = builder.build(query="最近的会议", records=[...])
"""

from datetime import datetime
from typing import Any


class ContextBuilder:
    def __init__(self, max_chars: int = 8000):
        self.max_chars = max_chars

    def build(self, query: str, records: list[dict[str, Any]]) -> str:
        """构建上下文字符串

        Args:
            query: 用户查询
            records: 检索到的记录列表，每条需有 text/content, score, timestamp 字段

        Returns:
            拼接并截断后的上下文字符串
        """
        if not records:
            return ""

        # 1. 按相关性排序
        ranked = sorted(records, key=lambda r: r.get("score", 0), reverse=True)

        # 2. 按日期分组
        grouped = self._group_by_date(ranked)

        # 3. 每组取 top-N，拼接
        parts = []
        for date_str, group in grouped.items():
            parts.append(f"\n--- {date_str} ---")
            for record in group[:5]:  # 每组最多5条
                text = record.get("text") or record.get("content", "")
                source = record.get("source", "")
                score = record.get("score", 0)
                formatted = self._format_record(text, source, score)
                parts.append(formatted)

        # 4. 截断到 max_chars
        return self._truncate(parts)

    def build_with_metadata(self, query: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        """构建上下文并返回元数据"""
        context = self.build(query, records)
        return {
            "context": context,
            "total_records": len(records),
            "context_chars": len(context),
            "truncated": len(context) >= self.max_chars - 100,
            "date_range": self._get_date_range(records),
        }

    def _format_record(self, text: str, source: str, score: float) -> str:
        """格式化单条记录"""
        header = f"[{source}]" if source else ""
        # 单条记录最多 500 字符
        if len(text) > 500:
            text = text[:497] + "..."
        return f"{header} {text}".strip()

    def _group_by_date(self, records: list[dict[str, Any]]) -> dict[str, list]:
        """按日期分组，保持组内排序"""
        groups: dict[str, list] = {}
        for record in records:
            ts = record.get("timestamp") or record.get("created_at", "")
            date_str = self._extract_date(ts) or "未知日期"
            groups.setdefault(date_str, []).append(record)
        return groups

    def _extract_date(self, timestamp: Any) -> str | None:
        """从各种时间格式中提取日期字符串"""
        if not timestamp:
            return None
        if isinstance(timestamp, datetime):
            return timestamp.strftime("%Y-%m-%d")
        if isinstance(timestamp, (int, float)):
            # Unix timestamp (秒或毫秒)
            if timestamp > 1e12:
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
        if isinstance(timestamp, str):
            # 尝试提取 YYYY-MM-DD
            import re
            match = re.search(r'\d{4}-\d{2}-\d{2}', timestamp)
            return match.group(0) if match else None
        return None

    def _get_date_range(self, records: list[dict[str, Any]]) -> dict[str, str | None]:
        """获取记录的时间范围"""
        dates = [self._extract_date(r.get("timestamp")) for r in records]
        dates = [d for d in dates if d]
        return {
            "earliest": min(dates) if dates else None,
            "latest": max(dates) if dates else None,
        }

    def _truncate(self, parts: list[str]) -> str:
        """从后往前删，保留最相关的（排在前面的）"""
        text = "\n".join(parts)
        while len(text) > self.max_chars and len(parts) > 1:
            parts.pop()
            text = "\n".join(parts)
        if len(text) > self.max_chars:
            text = text[:self.max_chars - 3] + "..."
        return text
