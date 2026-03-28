# 🧬 Self-Evolution Engine for AI Agents

让 AI Agent 从经验中学习、持续自我改进的轻量级框架。

Python 3.8+ · SQLite · 零外部依赖 · 全状态持久化

## 它解决什么问题

大多数 AI Agent 每次启动都从零开始——不记得上次犯了什么错，不知道哪个模型更适合哪类任务，也不会从失败中总结教训。

Self-Evolution 让 Agent 具备七种能力：

1. **结构化记忆** — 持久化存储经验、决策和教训，重启不丢失
2. **失败模式分析** — 自动识别重复出现的失败，生成改进建议
3. **A/B 实验验证** — 把改进建议变成可回滚的实验，用数据判断是否有效
4. **归因验证** — 防止被单次巧合误导，样本不足时敢说"不确定"
5. **策略自适应** — 根据系统状态自动切换进化策略（激进/保守/修复）
6. **外部学习** — 定期从 9 个信息源主动学习，产出结构化知识笔记
7. **冷热记忆管理** — 追踪记忆访问频率，自动建议归档冷数据

## 架构

三层架构，每层职责独立：

```
┌─────────────────────────────────────────────────┐
│  进化层                                          │
│  evolution_strategy · evolution_executor          │
│  策略选择 · 信号检测 · 实验管理 · 自适应反思       │
├─────────────────────────────────────────────────┤
│  分析层                                          │
│  feedback_loop · causal_validator                │
│  失败模式分析 · 改进建议 · 归因验证               │
├─────────────────────────────────────────────────┤
│  记忆层                                          │
│  memory_db · memory_store · memory_retrieval     │
│  memory_service · memory_embedding · memory_lru  │
│  结构化存储 · FTS5搜索 · 语义检索 · 冷热管理      │
└─────────────────────────────────────────────────┘
```

## 核心闭环

```
feedback_loop 发现失败模式
        ↓
evolution_executor 生成候选实验
        ↓
    创建实验 → 激活
        ↓
  任务执行时自动录入结果
        ↓
  causal_validator 样本够了自动验证
        ↓
  effective → 固化    uncertain → 继续观察    ineffective → 回滚
```

`evolution_strategy` 持续监控系统信号，自动切换策略。

## 模块一览

### 记忆层

| 模块 | 功能 |
|------|------|
| `memory_db.py` | 结构化记忆数据库，FTS5 中英文双路径搜索 |
| `memory_store.py` | 持久化写入，标签/时间/任务类型过滤 |
| `memory_retrieval.py` | 智能检索：查询改写、时间感知、动态阈值、时间衰减 |
| `memory_service.py` | 统一接口：remember / recall / reflect |
| `memory_embedding.py` | 可选语义搜索（SiliconFlow BGE-M3，免费） |
| `memory_lru.py` | 冷热追踪，归档建议 |
| `file_registry.py` | 文件/文档元信息台账 |
| `db_common.py` | SQLite 连接管理（WAL 模式） |

### 分析层

| 模块 | 功能 |
|------|------|
| `feedback_loop.py` | 任务结果记录、失败模式分析、改进建议生成 |
| `causal_validator.py` | 纯函数归因验证，4维度加权，三档判定 |

### 进化层

| 模块 | 功能 |
|------|------|
| `evolution_executor.py` | 实验生命周期：draft → active → concluded/cancelled |
| `evolution_strategy.py` | 5种策略预设、6种信号检测、自适应反思频率 |
| `agent_bridge.py` | 子Agent结果一键录入（task_outcome + observation + 实验） |

### 配套 Skill

| 目录 | 功能 |
|------|------|
| `skills/external-learning/` | 两阶段外部学习（广筛→深读），9个信息源，含落地评估 |

## 快速开始

```bash
# 初始化
python3 modules/memory_db.py init

# 录入任务结果
python3 modules/feedback_loop.py record coding gpt-4 1 --notes "重构成功"
python3 modules/feedback_loop.py record coding gpt-4 0 --notes "只输出意图没写代码"

# 分析失败模式
python3 modules/feedback_loop.py analyze

# 检测系统信号 & 策略
python3 modules/evolution_strategy.py signals
python3 modules/evolution_strategy.py strategy

# 创建实验
python3 modules/evolution_executor.py create \
  --source feedback_loop --task-type coding \
  --problem "子Agent只描述计划不执行" \
  --proposal "指令首段加强制执行提示"

# 验证实验
python3 modules/causal_validator.py validate 1
```

Python 集成：

```python
from agent_bridge import record_agent_result

# 每次子Agent完成后调一行
record_agent_result(
    task_type="coding",
    model="gpt-4",
    success=True,
    description="重构用户模块",
    critic_score=85,
)
```

数据库路径通过环境变量配置：
```bash
export SELF_EVOLUTION_DB=/path/to/your/memory.db  # 默认在模块目录下
```

## 进化策略

系统根据运行信号自动选择策略：

| 策略 | 修复 | 优化 | 创新 | 触发条件 |
|------|------|------|------|----------|
| `balanced` | 20% | 30% | 50% | 系统健康 |
| `innovate` | 5% | 15% | 80% | 停滞或修复循环 |
| `harden` | 40% | 40% | 20% | 近期大改动 |
| `repair_only` | 80% | 20% | 0% | 高失败率 |
| `steady_state` | 60% | 30% | 10% | 进化饱和 |

信号类型：`high_failure_rate` · `repair_loop` · `elevated_failure_rate` · `recent_big_change` · `capability_gap` · `stagnation` · `all_healthy`

## 归因验证

实验结论不靠感觉，靠工程规则：

- **样本门槛**：< 3 次 → `uncertain`
- **4维度加权**：成功率(0.4) + 返工率(0.25) + Critic分(0.25) + 耗时(0.1)
- **三档判定**：`effective` / `uncertain` / `ineffective`
- **核心原则**：敢说"不确定"比乱自信强

## 外部学习

两阶段流程，从 9 个信息源主动学习：

**广筛**（子Agent并行）→ **深读**（主Agent逐条读原文）→ **落地评估**（自动过滤噪声）

信息源：GitHub Trending · Hacker News · arXiv · 融资动态 · TechCrunch · 量子位 · Product Hunt · Papers With Code · 行业深度

每条深读笔记包含：来源等级标签（摘要级/原文级/多源验证级）、二次验证、落地评估（相关模块/改动规模/优先级）。P0 条目自动进入实验队列。

## 数据库

单文件 SQLite，WAL 模式。

| 表 | 用途 |
|----|------|
| `observations` | 观察、发现、教训 |
| `decisions` | 决策记录（含被拒方案和理由） |
| `session_summaries` | 会话摘要 |
| `task_outcomes` | 任务执行结果 |
| `experiments` | 进化实验 |
| `embeddings` | 向量索引（可选） |

## 设计原则

- **零依赖** — Python 3.8+ 和 SQLite，不依赖 LangChain / LlamaIndex
- **全持久化** — 所有状态存 SQLite，重启不丢失
- **可回滚** — 所有实验可取消/回滚
- **敢说不知道** — 样本不足输出 `uncertain`
- **查询不 crash** — 查询失败返回空值，写入失败返回 None

## 适用场景

适合任何需要从经验中学习的 Agent 系统。不绑定特定框架。

已在 [OpenClaw](https://github.com/openclaw/openclaw) 生产环境验证。

不适合：单轮对话机器人、纯 RAG 系统、需要分布式多节点共享记忆的场景。

## FAQ

**Q: 和 LangChain Memory / Mem0 的区别？**
它们解决对话上下文记忆，本项目解决经验积累和自我改进。不冲突，可同时使用。

**Q: 语义搜索怎么配？**
可选功能，基于 SiliconFlow BGE-M3（免费）。设置 `SILICONFLOW_API_KEY` 环境变量后运行 `python3 modules/memory_db.py embed`。不配置自动降级为关键词搜索。

**Q: 数据量大了会慢吗？**
SQLite + FTS5 + WAL，10万条级别无压力。`memory_lru` 自动识别冷数据建议归档。

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1~v5 | 2026-03-17 | 记忆系统 + 反馈闭环 + LRU + Critic审查 |
| v6 | 2026-03-20 | 检索层重构（查询改写 + 时间衰减 + 动态阈值） |
| v7 | 2026-03-28 | 进化执行器 + 归因验证器 + 策略引擎 |
| v7.1 | 2026-03-28 | agent_bridge + 时间感知检索 |
| v7.2 | 2026-03-28 | 外部学习模块 + 落地评估机制 |

## 致谢

部分设计思想借鉴自以下项目（仅思想参考，未复制代码）：

- [Capability-Evolver](https://github.com/EvoMap/evolver)（MIT）— 策略预设、信号检测、自适应反思
- [FreeTodo](https://github.com/FreeU-group/FreeTodo)（FreeU Community License）— 结构化任务上下文管理

## License

MIT
