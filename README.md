# 🧬 AI Agent 自我进化引擎

帮助 AI Agent 从经验中学习、持续改进的轻量级自我进化系统。砍掉了所有没用的，只留实际在跑的。

## 模块

| 模块 | 功能 |
|------|------|
| `memory_db` | 结构化记忆（观察/决策/会话摘要），FTS5 中英文双路径搜索 |
| `memory_service` | 记忆的统一接口层，对外提供 remember/recall 等原子能力 |
| `memory_store` | 记忆的持久化层，封装写入逻辑 |
| `memory_retrieval` | 记忆的检索层，支持 FTS5/语义/冷热多维查询 |
| `memory_embedding` | 记忆的向量化 Embedding 支持 |
| `feedback_loop` | 任务结果记录、失败模式分析、改进建议生成 |
| `memory_lru` | 记忆冷热追踪，归档建议 |
| `file_registry` | 文件/文档记忆台账，自动关联飞书文档等外部资源 |
| `db_common` | 共享 SQLite 连接（WAL 模式） |

## 子功能：外部学习

定期从外部信息源学习最新动态，产出可操作的知识而非浅层摘要。

- 信息源：GitHub Trending、Hacker News、arXiv、融资动态、Product Hunt、OpenClaw 生态等
- 两阶段：先广筛（子Agent并行扫描）→ 后深读（Top 10 精选）
- 产出写入 `memory/learning/YYYY-MM-DD.md`，关键发现入库 `memory_db`

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                     对话层（主 Agent）                   │
├─────────────────────────────────────────────────────────┤
│                  memory_service（接口层）                │
│              remember / recall / forget / stats          │
├──────────────────┬──────────────────────────────────────┤
│   存储层          │              检索层                  │
│ memory_store     │ memory_retrieval / memory_embedding   │
├──────────────────┼──────────────────────────────────────┤
│   结构化记忆      │           文件记忆                   │
│   memory_db      │         file_registry                 │
├──────────────────┴──────────────────────────────────────┤
│   反馈闭环          │           LRU 管理                 │
│   feedback_loop    │         memory_lru                  │
├─────────────────────────────────────────────────────────┤
│               db_common（SQLite + FTS5）                │
└─────────────────────────────────────────────────────────┘
```

## 快速开始

```bash
cd modules

# 初始化数据库
python3 memory_db.py init

# 搜索记忆
python3 memory_db.py search "模型选择"

# 记录一次观察
python3 memory_service.py remember --content "Kimi在融资任务上表现更好" --type observation --tags 模型,任务

# 分析失败模式
python3 feedback_loop.py analyze

# 查看记忆冷热分布
python3 memory_lru.py heatmap

# 归档冷记忆（30天未访问）
python3 memory_lru.py archive-suggest --days 30
```

## 文件记忆（file_registry）

自动追踪外部文件/文档，让 AI 记住"今天下午那个文档叫什么"。

```bash
python3 file_registry.py \
  --title "光因科技商业计划书" \
  --doc-title "光因科技BP" \
  --url "https://..." \
  --folder-token "Zxw7fE4z..." \
  --tags 商业计划书,投资人
```

## 设计原则

- **零外部依赖** — 只需 Python 3.8+ 和 SQLite
- **中英文双路径搜索** — FTS5 处理英文分词，LIKE 兜底中文
- **决策记录被否方案** — 记住"为什么选 X 而不选 Y"
- **查询永不崩溃** — 失败返回空；写入可以抛异常
- **只留在用的** — 从 18 个模块精简到核心在跑的
- **脱敏发布** — 不含任何 token、secret、真实用户数据

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `SELF_EVOLUTION_DB` | 否 | 覆盖默认数据库路径（默认：`./memory.db`） |

## License

MIT
