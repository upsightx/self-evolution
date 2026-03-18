# Hacker News — 差异配置

**源标识**: `hn`
**源名称**: Hacker News Top
**特有指标**: 🔥 HN分数 | 💬 评论数

## 数据源与抓取

1. 用 `exec` 调用 HN API 获取 Top 30：
   ```bash
   curl -s "https://hacker-news.firebaseio.com/v0/topstories.json" | python3 -c "import json,sys; ids=json.loads(sys.stdin.read())[:30]; print('\n'.join(str(i) for i in ids))"
   ```

2. 对每个 ID 批量获取详情（每次 5 个）：
   ```bash
   curl -s "https://hacker-news.firebaseio.com/v0/item/{id}.json"
   ```

3. 用 `web_search` 搜索 `site:news.ycombinator.com` 补充最近 24h 热门讨论

4. 对 HN 分数 > 300 的帖子，用 `web_fetch` 读取原文写摘要

## 提取字段

标题、URL、HN 分数、评论数、发布时间

## 输出格式示例

```
### 1. [标题](url) | 分数: 8.2 | 🔥 523 | 💬 234
- **摘要**: 核心内容摘要
- **标签**: [AI] [编程]
- **为什么值得记**: 价值说明
```
