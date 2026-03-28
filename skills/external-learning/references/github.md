# GitHub Trending — 差异配置

**源标识**: `github`
**源名称**: GitHub Trending
**特有指标**: ⭐ star数 | +日增star

## 数据源与抓取

用 `web_fetch` 抓取以下 6 个页面：
- https://github.com/trending?since=daily
- https://github.com/trending?since=weekly
- https://github.com/trending/python?since=daily
- https://github.com/trending/typescript?since=daily
- https://github.com/trending/rust?since=daily
- https://github.com/trending/go?since=daily

## 提取字段

每个项目提取：项目名、URL、star 数、今日新增 star、语言、一句话描述

## 输出格式示例

```
### 1. [项目名](url) | 分数: 8.5 | ⭐ 12.3k | +1.2k/天
- **摘要**: 核心功能描述
- **标签**: [AI工具] [开源]
- **为什么值得记**: 具体价值说明
```
