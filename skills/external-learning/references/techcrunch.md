# TechCrunch — 差异配置

**源标识**: `techcrunch`
**源名称**: TechCrunch
**特有指标**: 💰 融资金额 | 🏢 公司

## 数据源与抓取

1. 用 `web_search` 搜索 TechCrunch 最新文章：
   - "site:techcrunch.com AI startup funding" 最近 3 天
   - "site:techcrunch.com AI agent" 最近 3 天
   - "site:techcrunch.com robotics" 最近 3 天

2. 用 `web_fetch` 抓取 TechCrunch AI 频道：
   - `https://techcrunch.com/category/artificial-intelligence/`

3. 用 `web_search` 补充 VentureBeat：
   - "site:venturebeat.com AI" 最近 3 天

4. 对高价值文章（分数≥7），用 `web_fetch` 读取全文提取融资细节

## 提取字段

标题、URL、公司名、融资金额、轮次、投资方、产品描述

## 特有标注
- 🔥 融资金额 > $50M
- 🦄 估值 > $1B
- 🚀 新产品发布

## 输出格式示例

```
### 1. [标题](url) | 分数: 8.5 | 💰 Series B $80M
- **摘要**: 公司/产品核心介绍
- **标签**: [AI] [融资] ...
- **投资方**: Sequoia, a16z
- **为什么值得记**: 价值说明
```
