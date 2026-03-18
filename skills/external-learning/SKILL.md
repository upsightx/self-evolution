---
name: external-learning
description: |
  外部学习工具。定期从外部信息源学习最新动态，包括 AI 论文、GitHub 热门项目、Hacker News、行业融资等。

  **当以下情况时使用此 Skill**：
  (1) 心跳触发时，轮询外部信息源
  (2) 用户问"最近有什么新东西"、"AI 有什么进展"
  (3) 需要了解某个领域的最新动态
  (4) 用户提到"学习"、"趋势"、"热门"、"前沿"
---

# External Learning

从外部世界主动学习，保持信息敏感度。每次学习要有深度和广度。

## 核心原则

- 每个信息源派独立子 Agent，并行执行，互不阻塞
- 子 Agent 用 MiniMax 模型（省成本），主 Agent 做最终汇总
- 结果写入 `memory/learning/tmp-{源}-{date}.md`，主 Agent 读取汇总
- 子 Agent 指令 = `references/base-template.md`（通用规则）+ `references/{源}.md`（差异配置）

## 信息源优先级

| 优先级 | 信息源 | 源标识 | 频率 | 配置文件 |
|--------|--------|--------|------|----------|
| 1 | GitHub Trending | github | 每次必查 | references/github.md |
| 1 | Hacker News | hn | 每次必查 | references/hackernews.md |
| 2 | 融资动态 | financing | 每天 | references/financing.md |
| 3 | arXiv 论文 | arxiv | 每 2 天 | references/arxiv.md |
| 3 | Product Hunt | products | 每 2 天 | references/products.md |
| 4 | 行业深度 | deep-{topic} | 按需 | references/deep-research.md |

## 子 Agent 配置

- **model**: MiniMax（默认）
- **mode**: run（一次性任务）
- **timeout**: 300 秒
- **每次至少派 3 个子 Agent**，优先级 1 必选，其余按频率轮换
- 指令组装：读取 base-template.md 全文 + 对应源的 references/*.md 全文，拼接为子 Agent 指令

## 执行流程

### Step 1: 检查时间
读取 `memory/heartbeat-state.json` 的 `lastChecks`，判断哪些源需要更新。

### Step 2: 派发子 Agent
根据优先级和频率，并行派发子 Agent。每个子 Agent 的指令：
1. 读取 `references/base-template.md` 获取通用规则
2. 读取对应 `references/{源}.md` 获取数据源和抓取步骤
3. 将两部分拼接为完整指令发给子 Agent

### Step 3: 等待完成
用 `sessions_yield` 等待，子 Agent 完成后自动通知。

### Step 4: 汇总整理
1. 读取所有 `memory/learning/tmp-*-{date}.md`
2. 合并去重（基于标题/URL）
3. 按价值分数排序，标注 TOP 10
4. 写入 `memory/learning/{date}.md`（正式笔记）
5. 删除 tmp 文件
6. 更新 `memory/heartbeat-state.json`

### Step 5: 同步飞书
用 `feishu_create_doc` 创建文档：
- **folder_token**: `<your_folder_token>`
- **标题**: `外部学习笔记 YYYY-MM-DD`

### Step 6: 通知决策

**主动通知**（满足任一且在 08:00-23:00）：
- 价值分数 ≥ 9 的条目
- TOP 3 最有价值发现
- 与用户业务直接相关的重大信息

**静默记录**：常规更新、深夜时段（23:00-08:00）

## 周报汇总

每周从 `memory/learning/` 提炼：
- 本周 TOP 20（按价值分数排序）
- 趋势分析（升温/降温方向）
- 与用户业务的关联点
- 写入审计报告"本周外部动态"章节
