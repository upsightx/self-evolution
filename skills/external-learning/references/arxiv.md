# arXiv 论文 — 差异配置

**源标识**: `arxiv`
**源名称**: arXiv 论文
**特有指标**: 作者 | 代码链接

## 数据源与抓取

1. 用 `web_fetch` 抓取 arXiv API（每分类 10 篇）：
   - `https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=10`
   - `https://export.arxiv.org/api/query?search_query=cat:cs.CL&sortBy=submittedDate&sortOrder=descending&max_results=10`
   - `https://export.arxiv.org/api/query?search_query=cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=10`
   - `https://export.arxiv.org/api/query?search_query=cat:cs.MA&sortBy=submittedDate&sortOrder=descending&max_results=10`

2. 用 `web_search` 补充热门论文：
   - "arxiv 2026 agent framework"
   - "arxiv 2026 LLM reasoning"
   - "arxiv 2026 RAG retrieval"

3. 用 `web_fetch` 抓取 `https://paperswithcode.com/latest` 获取有代码的论文

## 提取字段

标题、URL、作者（前 3）、摘要（中文翻译 2-3 句）、分类、代码链接（有/无）

## 输出格式示例

```
### 1. [论文标题](url) | 分数: 8.8 | 作者: xxx et al.
- **摘要**: 中文核心贡献
- **标签**: [Agent] [LLM推理]
- **代码**: [有] https://github.com/xxx
- **为什么值得记**: 价值说明
```
