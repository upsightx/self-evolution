# 🧬 Self-Evolution Engine for AI Agents

> 让 AI Agent 自主进化的开源框架 — 结构化记忆、智能调度、质量控制、自我审计

## 为什么需要这个？

大多数 AI Agent 每次会话都从零开始。它们没有长期记忆，不会从错误中学习，无法自我改进。

Self-Evolution Engine 解决这个问题。它给 Agent 装上：

- **结构化记忆** — 不只是存文本，而是存决策、教训、发现，支持高效检索
- **自动压缩** — 会话结束自动提取关键信息，不依赖人工维护
- **质量控制** — 借鉴 SAGE 论文的 Critic 机制，子 Agent 输出自动审查
- **自我审计** — 定期回顾工作模式，发现改进点
- **智能调度** — 心跳不再是机械轮询，而是根据上下文动态决策

## 设计灵感

| 来源 | 借鉴了什么 |
|------|-----------|
| [claude-mem](https://github.com/thedotmack/claude-mem) | 结构化记忆 + 渐进式披露检索 |
| [SAGE](https://arxiv.org/abs/2603.15255) | 四角色闭环自进化（Challenger/Planner/Solver/Critic） |
| [Lore](https://arxiv.org/abs/2603.15566) | 决策记录格式（rejected alternatives + rationale） |
| [agency-agents](https://github.com/msitarzewski/agency-agents) | Agent 人格化 + 可交付成果导向 |

## 快速开始

### 1. 安装

```bash
git clone https://github.com/upsightx/self-evolution.git
cd self-evolution

# 初始化记忆数据库
python3 memory_db.py init
```

无额外依赖，只需 Python 3.8+ 和 SQLite（系统自带）。

### 2. 记录你的第一条决策

```bash
python3 memory_db.py decision \
  "选择 SQLite 作为记忆存储" \
  "使用 SQLite + FTS5 全文搜索" \
  "用 PostgreSQL 或 ChromaDB" \
  "零依赖，系统自带，FTS5 足够用"
```

### 3. 记录一条发现

```bash
python3 memory_db.py add discovery \
  "MiniMax 比 GLM5 更稳定" \
  "GLM5 偶尔 403，MiniMax 作为子 Agent 模型更可靠"
```

### 4. 搜索记忆（三层渐进式披露）

```bash
# L1 索引 — 最省 token，只返回 id + title + type + date
python3 memory_db.py search "Agent"

# L2 上下文 — 返回 narrative + facts
python3 memory_db.py l2 1 2 3

# L3 完整 — 返回所有字段
python3 memory_db.py l3 1

# 搜索决策
python3 memory_db.py decisions "部署"

# 统计
python3 memory_db.py stats
```

## 架构

```
self-evolution/
├── memory_db.py          # 结构化记忆数据库（SQLite + FTS5）
├── SKILL.md              # OpenClaw Skill 定义（可直接安装）
├── templates/            # 子 Agent 指令模板
│   ├── critic.md         # Critic 审查模板
│   ├── compress.md       # 记忆压缩模板
│   ├── code-dev.md       # 代码开发模板
│   └── info-search.md    # 信息搜索模板
├── examples/             # 使用示例
│   └── session_end.py    # 会话结束自动提取示例
└── README.md
```

## 核心模块

### 1. 结构化记忆数据库

三张表，覆盖 Agent 需要记住的一切：

| 表 | 存什么 | 关键字段 |
|---|--------|---------|
| `observations` | 发现、教训、变更 | type, title, narrative, facts, concepts |
| `decisions` | 关键决策 | decision, rejected_alternatives, rationale |
| `session_summaries` | 会话摘要 | request, learned, completed, next_steps |

**Observation 类型：**
- `decision` — 架构/策略决策
- `bugfix` — Bug 修复和踩坑教训
- `feature` — 新功能实现
- `refactor` — 重构
- `discovery` — 新发现的知识
- `change` — 一般变更

**渐进式披露检索：**

传统 RAG 一次返回所有内容，浪费 token。我们分三层：

| 层级 | 返回内容 | Token 成本 |
|------|---------|-----------|
| L1 | id + title + type + date | ~50/条 |
| L2 | + narrative + facts | ~200/条 |
| L3 | 所有字段 | ~500/条 |

先用 L1 定位，再按需深入，节省 50-75% token。

### 2. 决策记录（Lore 格式）

每次重要决策，不只记录"选了什么"，还记录"为什么"和"拒绝了什么"：

```python
add_decision(
    title="选择子 Agent 协作模式",
    decision="便宜模型干活，贵模型把关",
    rejected_alternatives=["全部用贵模型", "全部用便宜模型"],
    rationale="90/10 法则：子 Agent 完成 90%，最强模型做最终质量把关"
)
```

这样未来的你（或其他 Agent）不会重复踩坑。

### 3. 质量控制（SAGE Critic）

复杂任务完成后，派一个 Critic Agent 审查输出：

```
Solver Agent → 完成任务 → Critic Agent 评估 → 通过/打回修改
```

评估维度：完整性、正确性、安全性、效率、可维护性。

### 4. 智能心跳调度

不再机械轮询，而是根据上下文打分决定该关注什么：

```
基础分 + 上下文加分 → 选择得分最高的 1-3 项执行
```

### 5. 自动记忆压缩

会话结束时自动提取结构化信息，定期压缩旧日志：

```
原始日志 → LLM 提取 → 结构化数据库
超过 30 天 → 归档
```

## Python API

```python
from memory_db import *

# 初始化
init_db()

# 写入
add_observation('discovery', '标题', narrative='描述', 
    facts=['事实1'], concepts=['概念1'])

add_decision('标题', '决策内容', 
    rejected_alternatives=['方案B'], rationale='原因')

add_session_summary('用户请求', 
    learned='学到了什么', completed='完成了什么')

# 检索
results = search_l1('关键词')       # L1 索引
details = search_l2([1, 2, 3])      # L2 上下文
full = search_l3(1)                 # L3 完整
decs = search_decisions('关键词')    # 搜索决策
info = stats()                      # 统计
```

## 作为 OpenClaw Skill 使用

直接复制到 OpenClaw skills 目录：

```bash
cp -r self-evolution ~/.openclaw/skills/
cd ~/.openclaw/workspace/memory/structured
python3 ~/.openclaw/skills/self-evolution/memory_db.py init
```

## 适用场景

- **个人 AI 助手** — 让助手记住你的偏好、决策、教训
- **编码 Agent** — 记住代码库的架构决策，避免重复踩坑
- **多 Agent 系统** — Solver + Critic 闭环，提升输出质量
- **长期运行的 Agent** — 自动压缩记忆，保持高效

## 设计原则

1. **零依赖** — 只用 Python 标准库 + SQLite，不引入重型基础设施
2. **渐进式** — 从简单开始，按需深入
3. **可组合** — 每个模块独立可用，也可以组合使用
4. **记录"为什么"** — 不只记录结果，还记录决策过程

## License

MIT
