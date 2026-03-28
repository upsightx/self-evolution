# Product Hunt & AI 工具 — 差异配置

**源标识**: `products`
**源名称**: 新产品 & AI 工具
**特有指标**: 🗳️ votes | 免费/付费/开源

## 数据源与抓取

1. 用 `web_fetch` 抓取 Product Hunt 首页：`https://www.producthunt.com`

2. 用 `web_search` 搜索：
   - "new AI tool 2026" 最近一周
   - "AI agent platform launch 2026" 最近一周
   - "developer tool launch 2026" 最近一周

3. 用 `web_fetch` 补充：
   - `https://theresanaiforthat.com/most-saved/`
   - `https://news.ycombinator.com/show`

## 提取字段

产品名、URL、一句话描述、分类、是否免费/开源、投票数

## 输出格式示例

```
### 1. [产品名](url) | 分数: 8.0 | 🗳️ 1.2k votes
- **摘要**: 产品核心功能
- **标签**: [AI工具] [效率工具]
- **免费/付费/开源**: 开源
- **为什么值得记**: 价值说明
```
