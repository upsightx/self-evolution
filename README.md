# 🧬 AI Agent 自我进化引擎

帮助 AI Agent 从经验中学习、持续改进的轻量级自我进化系统。砍掉了所有没用的，只留实际在跑的。

## 模块

| 模块 | 功能 |
|------|------|
| `memory_db` | 结构化记忆（观察/决策/会话摘要），FTS5 中英文双路径搜索 |
| `feedback_loop` | 任务结果记录、失败模式分析、改进建议生成 |
| `memory_lru` | 记忆冷热追踪，归档建议 |
| `model_router` | 多模型路由，按 任务类型 × 成功率 × 成本 推荐最优模型 |
| `db_common` | 共享 SQLite 连接（WAL 模式） |

## 子功能：外部学习

定期从外部信息源学习最新动态，产出可操作的知识而非浅层摘要。

- 信息源：GitHub Trending、Hacker News、arXiv、融资动态、TechCrunch、量子位等
- 两阶段：先广筛（子Agent并行扫描）→ 后深读（Top 10 精选）
- 产出写入 `memory/learning/YYYY-MM-DD.md`，关键发现入库 `memory_db`

## 架构

```
┌──────────────┬───────────────┐
│   记忆层     │   策略层      │
├──────────────┼───────────────┤
│ memory_db    │ model_router  │
│ memory_lru   │ feedback_loop │
└──────┬───────┴───────┬───────┘
       │               │
       └───────┬───────┘
               │
        ┌──────┴──────┐
        │  memory.db  │
        │(SQLite+FTS5)│
        └──────┬──────┘
               │
        ┌──────┴──────┐
        │  外部学习    │
        │(子Agent并行) │
        └─────────────┘
```

## 快速开始

```bash
cd modules

# 初始化数据库
python3 memory_db.py init

# 搜索记忆
python3 memory_db.py search "模型选择"

# 分析失败模式
python3 feedback_loop.py analyze

# 查看模型路由推荐
python3 model_router.py table

# 查看记忆冷热分布
python3 memory_lru.py heatmap
```

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `SELF_EVOLUTION_DB` | 否 | 覆盖默认数据库路径（默认：`./memory.db`） |

## 设计原则

- **零外部依赖** — 只需 Python 3.8+ 和 SQLite
- **中英文双路径搜索** — FTS5 处理英文分词，LIKE 兜底中文
- **决策记录被否方案** — 记住"为什么选 X 而不选 Y"
- **查询永不崩溃** — 失败返回空；写入可以抛异常
- **只留在用的** — 从 18 个模块精简到 5 个

## 演进历史

- v1：18 个模块，4500 行代码，过度工程化
- v2（当前）：5 个核心模块 + 外部学习子功能，够用就好

## License

MIT
