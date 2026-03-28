<p align="center">
  <h1 align="center">🧬 Self-Evolution Engine</h1>
  <p align="center">
    让 AI Agent 从经验中学习、持续自我改进的轻量级框架。
  </p>
  <p align="center">
    <a href="https://github.com/upsightx/self-evolution/blob/main/LICENSE"><img src="https://img.shields.io/github/license/upsightx/self-evolution" alt="License"></a>
    <img src="https://img.shields.io/badge/python-3.8%2B-blue" alt="Python 3.8+">
    <img src="https://img.shields.io/badge/依赖-零-green" alt="零依赖">
    <img src="https://img.shields.io/badge/存储-SQLite-lightgrey" alt="SQLite">
    <img src="https://img.shields.io/github/last-commit/upsightx/self-evolution" alt="Last Commit">
  </p>
  <p align="center">
    <a href="README.md">English</a> | <b>中文</b>
  </p>
</p>

---

## 它解决什么问题

大多数 AI Agent 每次启动都从零开始——不记得上次犯了什么错，不知道哪个模型更适合哪类任务，也不会从失败中总结教训。

Self-Evolution 让 Agent 具备七种能力：

| # | 能力 | 说明 |
|---|------|------|
| 1 | **结构化记忆** | 持久化存储经验、决策（含被拒方案及理由）和教训，重启不丢失 |
| 2 | **失败模式分析** | 自动识别重复出现的失败模式，生成可执行的改进建议 |
| 3 | **A/B 实验验证** | 将改进建议转化为可回滚的实验，用数据判断是否有效 |
| 4 | **归因验证** | 防止被单次巧合误导，样本不足时输出 `uncertain` 而非强行下结论 |
| 5 | **策略自适应** | 根据系统健康信号自动切换进化策略（激进/保守/修复） |
| 6 | **外部学习** | 定期从 8+ 个信息源主动学习，两阶段过滤产出结构化知识笔记 |
| 7 | **冷热记忆管理** | 追踪记忆访问频率，自动建议归档冷数据 |

## 架构

三层架构，每层职责独立：

```
┌──────────────────────────────────────────────────────┐
│  进化层                                                │
│  evolution_strategy · evolution_executor               │
│  策略选择 · 信号检测 · 实验管理 · 自适应反思频率         │
├──────────────────────────────────────────────────────┤
│  分析层                                                │
│  feedback_loop · causal_validator                      │
│  失败模式分析 · 改进建议生成 · 4维加权归因验证           │
├──────────────────────────────────────────────────────┤
│  记忆层                                                │
│  memory_db · memory_store · memory_retrieval           │
│  memory_service · memory_embedding · memory_lru        │
│  结构化存储 · FTS5搜索 · 语义检索 · 冷热管理            │
└──────────────────────────────────────────────────────┘
```

### 核心闭环

```
feedback_loop 发现失败模式
        │
        ▼
evolution_executor 生成候选实验
        │
        ▼
    创建实验 → 激活
        │
        ▼
    任务执行时自动录入结果
        │
        ▼
    causal_validator 样本够了自动验证
        │
        ▼
    effective → 固化    uncertain → 继续观察    ineffective → 回滚
```

`evolution_strategy` 持续监控系统信号，自动切换策略。

## 项目结构

```
self-evolution/
├── modules/
│   ├── db_common.py            # SQLite 连接管理（WAL 模式）
│   ├── memory_db.py            # 核心记忆数据库 — FTS5 中英文双路径搜索
│   ├── memory_store.py         # 写入层 — 标签/时间/任务类型过滤
│   ├── memory_retrieval.py     # 智能检索 — 查询改写、时间衰减、动态阈值
│   ├── memory_service.py       # 统一接口：remember / recall / reflect
│   ├── memory_embedding.py     # 可选语义搜索（SiliconFlow BGE-M3，免费无需 GPU）
│   ├── memory_lru.py           # 访问频率追踪，归档建议
│   ├── file_registry.py        # 文件/文档元信息台账
│   ├── feedback_loop.py        # 任务结果记录、失败模式分析、改进建议生成
│   ├── causal_validator.py     # 纯函数归因验证 — 4维度加权，三档判定
│   ├── evolution_executor.py   # 实验生命周期：draft → active → concluded/cancelled
│   ├── evolution_strategy.py   # 5种策略预设、6种信号检测、自适应反思
│   ├── agent_bridge.py         # 子Agent结果一键录入
│   └── DESIGN.md               # 内部设计规范与编码约定
├── skills/
│   └── external-learning/      # 两阶段外部学习（广筛→深读）
│       ├── SKILL.md
│       └── references/         # 各信息源模板（arXiv、HN、GitHub 等）
├── DESIGN.md                   # 顶层设计文档
├── LICENSE                     # MIT
├── README.md                   # English
└── README_CN.md                # 中文
```

**14 个模块，约 4,350 行 Python 代码。** 零外部依赖。

## 快速开始

### 安装

```bash
git clone https://github.com/upsightx/self-evolution.git
cd self-evolution
```

无需 `pip install`，纯标准库 Python。

### 初始化

```bash
python3 modules/memory_db.py init
```

### 录入任务结果

```bash
# 记录成功
python3 modules/feedback_loop.py record coding gpt-4 1 --notes "重构成功"

# 记录失败
python3 modules/feedback_loop.py record coding gpt-4 0 --notes "只输出意图没写代码"
```

### 分析失败模式

```bash
python3 modules/feedback_loop.py analyze
```

### 检测系统信号与策略

```bash
python3 modules/evolution_strategy.py signals
python3 modules/evolution_strategy.py strategy
```

### 运行实验

```bash
# 创建实验
python3 modules/evolution_executor.py create \
  --source feedback_loop --task-type coding \
  --problem "子Agent只描述计划不执行" \
  --proposal "指令首段加强制执行提示"

# 验证实验（样本收集够后）
python3 modules/causal_validator.py validate 1
```

### Python 集成

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

### 配置

```bash
# 自定义数据库路径（默认在 modules/ 目录下）
export SELF_EVOLUTION_DB=/path/to/your/memory.db

# 可选：启用语义搜索（免费 SiliconFlow BGE-M3 API）
export SILICONFLOW_API_KEY=your_key_here
python3 modules/memory_db.py embed
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

**信号类型：** `high_failure_rate` · `repair_loop` · `elevated_failure_rate` · `recent_big_change` · `capability_gap` · `stagnation` · `all_healthy`

## 归因验证

实验结论靠工程规则，不靠直觉：

- **样本门槛：** < 3 次 → `uncertain`（拒绝下结论）
- **4维度加权评分：**
  - 成功率 (0.4) + 返工率 (0.25) + Critic 分 (0.25) + 耗时 (0.1)
- **三档判定：** `effective` / `uncertain` / `ineffective`
- **设计原则：** 敢说"不确定"比乱自信强

## 外部学习

两阶段流程，从 8+ 个信息源主动学习：

```
广筛（子Agent并行扫描）
    → 深读（主Agent逐条读原文）
        → 落地评估（自动过滤噪声）
```

**信息源：** GitHub Trending · Hacker News · arXiv · TechCrunch · 量子位 · Product Hunt · Papers With Code · 行业深度

每条深读笔记包含：来源等级标签（摘要级/原文级/多源验证级）、二次验证、落地评估（相关模块/改动规模/优先级）。P0 条目自动进入实验队列。

## 数据库

单文件 SQLite，WAL 模式。10 万条级别无性能压力。

| 表 | 用途 |
|----|------|
| `observations` | 观察、发现、教训 |
| `decisions` | 决策记录（含被拒方案和理由） |
| `session_summaries` | 会话摘要 |
| `task_outcomes` | 任务执行结果（成功/失败、模型、评分） |
| `experiments` | 进化实验（完整生命周期追踪） |
| `embeddings` | 向量索引（可选） |

## 设计原则

- **零依赖** — Python 3.8+ 和 SQLite，不依赖 LangChain / LlamaIndex
- **全持久化** — 所有状态存 SQLite，重启、崩溃、重部署不丢失
- **可回滚** — 所有实验可取消/回滚
- **诚实的不确定性** — 样本不足输出 `uncertain`，绝不过度自信
- **查询不崩溃** — 读操作失败返回空值，写操作失败返回 `None` 并打印警告

## 适用场景

Self-Evolution 不绑定特定框架，任何能调用 Python 函数的 Agent 系统都能用。

**适合：**
- 多 Agent 调度系统（需要追踪子 Agent 表现）
- 长期运行的 Agent 部署（积累运行数据后持续优化）
- 任何需要知道"哪个 prompt / 模型 / 策略效果最好"的场景

**不适合：**
- 单轮对话机器人（没有运行历史可学习）
- 纯 RAG 系统（用向量数据库即可）
- 分布式多节点共享记忆（单 SQLite 文件）

**已在 [OpenClaw](https://github.com/openclaw/openclaw) 生产环境验证**，4,300+ 行 Python 代码日常运行。

## FAQ

**Q: 和 LangChain Memory / Mem0 有什么区别？**
它们解决对话上下文记忆（说了什么），Self-Evolution 解决经验积累和自我改进（什么有效、什么失败、为什么）。两者不冲突，可以同时使用。

**Q: 语义搜索怎么配？**
可选功能，基于 [SiliconFlow](https://siliconflow.cn) BGE-M3 Embedding（免费，无需 GPU）。设置 `SILICONFLOW_API_KEY` 环境变量后运行 `python3 modules/memory_db.py embed`。不配置时自动降级为 FTS5 关键词搜索，大多数场景够用。

**Q: 数据量大了会慢吗？**
SQLite + FTS5 + WAL，10 万条级别无压力。`memory_lru` 自动识别冷数据建议归档，保持工作集精简。

**Q: 能换其他 Embedding 服务商吗？**
`memory_embedding.py` 是一个约 200 行的薄封装，替换 API 调用即可对接任何返回浮点向量的服务商。系统其余部分不关心向量来源。

## Roadmap

- [ ] `tests/` — 完整测试套件 + CI
- [ ] `pyproject.toml` — 标准打包，支持 `pip install`
- [ ] Dashboard — 终端 UI，实验监控面板
- [ ] 多数据库支持 — PostgreSQL 适配器，支持团队部署
- [ ] 插件系统 — 自定义信号检测器和策略预设

## 贡献

欢迎贡献。提交 PR 前请阅读 [`DESIGN.md`](DESIGN.md) 了解编码规范。

```bash
# 提交前运行测试
python3 tests/run_all.py

# 代码风格：遵循 modules/ 中的现有模式
# - 所有函数签名加类型注解
# - Docstring 写明"做什么 / 不做什么"
# - 新模块使用 CLI 子命令模式
```

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1–v5 | 2026-03-17 | 记忆系统 + 反馈闭环 + LRU + Critic 审查 |
| v6 | 2026-03-20 | 检索层重构（查询改写 + 时间衰减 + 动态阈值） |
| v7 | 2026-03-28 | 进化执行器 + 归因验证器 + 策略引擎 |
| v7.1 | 2026-03-28 | Agent Bridge + 时间感知检索 |
| v7.2 | 2026-03-28 | 外部学习模块 + 落地评估机制 |

## 致谢

部分设计思想借鉴自以下项目（仅思想参考，未复制代码）：

- [Capability-Evolver](https://github.com/EvoMap/evolver)（MIT）— 策略预设、信号检测、自适应反思
- [FreeTodo](https://github.com/FreeU-group/FreeTodo)（FreeU Community License）— 结构化任务上下文管理

## 许可证

[MIT](LICENSE) © 2026 UpsightX
