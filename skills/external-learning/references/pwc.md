# Papers With Code — 差异配置

**源标识**: `pwc`
**源名称**: Papers With Code
**特有指标**: ⭐ GitHub星数 | 📊 SOTA基准

## 数据源与抓取

1. 用 `web_fetch` 抓取 Trending 页面：
   - `https://paperswithcode.com/latest`
   - `https://paperswithcode.com/greatest`

2. 用 `web_search` 补充：
   - "papers with code trending 2026" 最近一周
   - "state of the art AI benchmark 2026" 最近一周

3. 对高价值论文（分数≥8），用 `web_fetch` 读取论文页面获取详细摘要和代码链接

## 提取字段

论文标题、URL、GitHub代码链接、星数、SOTA任务名、基准分数、摘要

## 输出格式示例

```
### 1. [论文标题](url) | 分数: 8.5 | ⭐ 2.3k | 📊 SOTA on ImageNet
- **摘要**: 核心方法和贡献（中文）
- **标签**: [AI] [LLM] ...
- **代码**: https://github.com/xxx
- **为什么值得记**: 价值说明
```
