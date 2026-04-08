# Self-Evolution — 主动能力进化引擎

> 发现缺口 → 立即行动 → 找工具/写代码 → 测试验证 → 固化能力

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 是什么

Self-Evolution 是一个主动能力进化引擎。它不等失败积累，而是实时检测能力缺口并立即创建实验去解决。

与 [X-Memory](https://github.com/upsightx/X-Memory)（统一记忆层）和 external-learning（外部学习）配合，形成完整的自我进化闭环。

## 核心理念

**旧思路（被动）：** 等失败积累 5 次 → 分析模式 → 提建议 → 等审批

**新思路（主动）：** 一次失败就记录 → 两次就报警 → 发现缺口立即创建实验 → 找工具写代码测试 → 固化能力

## 架构

```
┌─────────────────────────────────────────────────┐
│                 Evolution Orchestrator            │
│         (统一编排：信号收集 → 路由 → 推进)          │
└──────┬──────────┬──────────┬──────────┬──────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
  Capability   Proposal    Memory    External
  Detector     Lifecycle   Governor  Learning
  (探测缺口)   (状态机)    (去重/治理) (外部信号)
       │          │          │          │
       ▼          ▼          ▼          ▼
  ┌─────────────────────────────────────────┐
  │           X-Memory (统一记忆层)           │
  │    observations · proposals · events     │
  └─────────────────────────────────────────┘
```

## 模块清单

### 核心引擎

| 模块 | 职责 |
|------|------|
| `evolution_orchestrator.py` | 统一编排入口。信号去重、路由、提案推进、心跳调度 |
| `capability_detector.py` | 主动能力探测。检测缺失/衰退/挣扎/可靠能力，立即触发实验 |
| `proposal_lifecycle_manager.py` | 提案状态唯一真源。draft→pending→approved→experimenting→validated→released |
| `evolution_runtime.py` | 统一事件日志 + 生命周期状态机 + 心跳入口 |
| `auto_evolve.py` | 自动进化主循环。能力基线→缺口检测→建议生成→执行→验证 |

### 执行与验证

| 模块 | 职责 |
|------|------|
| `evolution_executor.py` | 文件变更执行器。LLM 生成补丁 + Docker sandbox 测试 + 自动回滚 |
| `causal_validator.py` | 归因验证。对比变更前后成功率，判定 effective/uncertain/ineffective |
| `llm_provider.py` | 统一 LLM 抽象。SiliconFlow → OpenRouter 自动 fallback |

### 数据采集与治理

| 模块 | 职责 |
|------|------|
| `task_outcome_hook.py` | 任务结果自动记录。同时写入 task_outcomes 和 observations |
| `memory_governor.py` | 记忆治理。内容去重 + lineage 追踪 + bridge 标记 + 防自激 |
| `proposal_bridge.py` | external-learning → self-evolution 桥接 |

### 辅助模块

| 模块 | 职责 |
|------|------|
| `goal_tree.py` | 目标树管理 |
| `capability_model.py` | 能力自画像（从 task_outcomes 计算各维度评分）|
| `critic_engine.py` | 外部学习质量审查 |
| `skillify.py` | 自动技能化（高频成功模式 → Skill 草稿）|
| `evolution_history.py` | 进化历史报告生成 |
| `learning_conversion.py` | 学习转化率追踪 |
| `agenda_planner.py` | 动态议程调度 |

### 共享基础

| 模块 | 职责 |
|------|------|
| `runtime_config.py` | 统一配置真源（DB 路径、模块路径）|
| `db_common.py` | 数据库连接（指向 X-Memory 的 memory.db）|
| `memory_db.py` | Thin adapter，委托 X-Memory 的真实实现 |

## 数据流

```
外部学习发现信号
    ↓
proposal_bridge 分流（P0→提案, P1→候选, P2→跳过）
    ↓
evolution_orchestrator 收集信号 + 去重 + 路由
    ↓
capability_detector 检测缺口（缺失/衰退/挣扎）
    ↓
proposal_lifecycle_manager 管理状态机
    ↓
evolution_executor 在 sandbox 中执行补丁
    ↓
causal_validator 验证效果
    ↓
memory_governor 写入记忆（带 lineage，防重复）
```

## 快速开始

```bash
# 记录任务结果
python3 modules/task_outcome_hook.py record coding opus 1 --desc "完成代码修复"

# 检测能力状态
python3 modules/capability_detector.py detect

# 运行编排器心跳
python3 modules/evolution_orchestrator.py heartbeat

# 查看提案
python3 modules/proposal_lifecycle_manager.py list

# 运行自动进化
python3 modules/auto_evolve.py --min-patterns 1
```

## 统一数据库

所有模块共享 X-Memory 的 `memory.db`，通过 `runtime_config.py` 配置：

```python
# runtime_config.py
MEMORY_DB_PATH = WORKSPACE / "X记忆" / "memory.db"  # 唯一真源
```

关键表：
- `observations` — 观察记录（含 description, task_type, embedding_status）
- `task_outcomes` — 任务执行结果
- `proposals` — 提案（单一状态机）
- `evolution_signals` — 进化信号（去重）
- `evolution_events` — 事件日志
- `memory_lineage` — 记忆来源链
- `memory_dedup_hashes` — 内容去重

## 设计原则

1. **主动而非被动** — 不等失败积累，发现缺口立即行动
2. **单一真源** — 每类状态只有一个权威模块和一个权威字段
3. **显式生命周期** — 提案、实验、发布都是显式对象，不散落在 observation 里
4. **防自激** — 系统写回的数据不会被自己重新摄入
5. **优雅降级** — 无 LLM 时降级为诊断模式，不崩溃

## 依赖

- Python 3.10+
- SQLite（内置）
- [X-Memory](https://github.com/upsightx/X-Memory)（统一记忆层）
- Docker（可选，用于 sandbox 测试）
- SiliconFlow / OpenRouter API key（可选，用于 LLM 补丁生成）
