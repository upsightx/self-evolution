# 🧬 Self-Evolution Engine — AI Agent 自我进化引擎

结构化记忆、智能调度、质量控制、自我审计工具集，让 AI Agent 越用越强。

## 核心：memory_db.py

SQLite + FTS5 结构化记忆数据库。零依赖。记住**为什么**，而不只是记住什么。

```bash
# 搜索（双路径：FTS5 + LIKE，中英文都能搜）
python3 memory_db.py search "部署"
python3 memory_db.py decisions "模型选择"

# 写入
python3 memory_db.py add discovery "标题" "描述"
python3 memory_db.py decision "标题" "决策" "被拒绝的方案" "原因"

# 统计
python3 memory_db.py stats
```

三张核心表：
- **observations** — 发生了什么（分类：discovery/bugfix/feature/refactor/decision/change）
- **decisions** — 选了什么、拒绝了什么、为什么这么选
- **session_summaries** — 做了什么、学到了什么

## 工具集

| 文件 | 用途 |
|------|------|
| `memory_db.py` | 核心结构化记忆数据库 |
| `import_legacy.py` | 将已有的 Markdown 记忆文件导入数据库 |
| `record_agent_stat.py` | 按模型和任务类型追踪子 Agent 成功率 |
| `self-evolution-checklist.md` | 自我进化审计检查清单 |

## 子 Agent 指令模板

`agent-templates/` 包含可复用的子 Agent 指令模板：
- SAGE 四角色机制（Solver / Critic / Planner / Challenger）
- Critic 审查模板（三维度评分：相关性、完整性、可执行性）
- 6 种任务类型模板（代码开发、信息搜索、Skill 创建、文档操作、记忆压缩、Critic 审查）
- 决策记录格式（含 rejected_alternatives）

## Skills

`skills/` 包含 OpenClaw 兼容的 Agent 技能：

- **external-learning** — 自动化外部学习系统。并行派发子 Agent 从 GitHub Trending、Hacker News、arXiv、融资动态、Product Hunt 搜集信息。关键词过滤、价值评分、自动去重。
- **deploy-helper** — 安全部署 SOP。Docker 优先测试、常见坑点速查表、生产环境迁移清单。

## 设计原则

1. **记住为什么** — 每个决策都记录被拒绝的方案和理由
2. **关键词过滤** — 不用"相关性 > 0.7"这种模糊指标，用具体的关键词匹配
3. **双路径搜索** — FTS5 处理英文分词 + LIKE 兜底中文内容
4. **按复杂度选模型** — 复杂任务（重构/审计）→ 强模型；简单任务（信息搜集）→ 便宜模型
5. **一个 Agent 一件事** — 绝不让两个 Agent 改同一个文件

## 许可证

MIT
