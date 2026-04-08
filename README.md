# Self-Evolution — 目标驱动的自主进化引擎

> 让 AI 系统从"被动修补"升级为"目标驱动的自主进化"。

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 是什么

Self-Evolution 是一个目标驱动的自主进化引擎，核心使命是：**让 AI 系统能够自主识别能力缺口、分析失败模式、生成改进措施、验证效果，形成闭环成长**。

传统 AI 助手每次执行失败后需要人工干预修复。Self-Evolution 让系统能够：
- **自动识别目标缺口**：从长期目标树中发现未达成的目标
- **能力自画像**：从历史任务执行记录中自动计算各维度能力评分
- **反馈闭环分析**：分析失败模式，统计每组成功率，生成改进建议
- **归因验证**：对比变更前后成功率，判断改进是否真正有效
- **动态议程调度**：根据目标+能力+机会，生成最优下一步行动清单

## 核心架构

```
goal_tree(要什么) 
  ↓ 识别缺口
capability_model(缺什么)
  ↓ 能力短板
feedback_loop(分析失败)
  ↓ 改进建议
evolution_executor(试一试)
  ↓ 执行变更
causal_validator(有没有用)
  ↓ 归因结论
goal_tree(更新进度)
  ↓ 循环
agenda_planner(下一步做什么)
```

## 模块一览

| 模块 | 职责 | 核心能力 |
|------|------|----------|
| `goal_tree.py` | 目标树管理 | 定义长期目标、分解子目标、追踪进度、与能力模型联动 |
| `capability_model.py` | 能力自画像 | 从 task_outcomes 自动评分、识别短板、输出能力缺口 |
| `feedback_loop.py` | 反馈闭环分析 | 记录任务结果、分析失败模式、生成改进建议 |
| `causal_validator.py` | 归因验证 | 对比变更前后成功率、输出 effective/uncertain/ineffective |
| `evolution_executor.py` | 进化执行器 | 根据建议生成补丁、备份支持回滚、记录变更日志 |
| `evolution_history.py` | 历史追踪 | 变更记录时间线、按条件查询、支持回滚 |
| `agenda_planner.py` | 动态议程 | 混合目标更新+例行检查、优先级排序、静默时段过滤 |
| `auto_evolve.py` | 一键自动进化 | 闭环流程：缺口→失败分析→改进→验证→更新进度 |
| `change_applier.py` | 改进执行器 | 接收改进建议、执行可自动化变更、记录到 memory_db |
| `improvement_suggestions.py` | 建议生成器 | 基于目标缺口和能力短板生成可执行改进建议 |
| `learning_conversion.py` | 学习转化追踪 | 追踪外部学习内容是否转化为实际进化变更、计算转化率 |
| `skillify.py` | 自动技能化 | 检测重复任务模式、自动生成 Skill 草稿 |
| `validation.py` | 效果验证 | 验证改进变更是否生效、前后能力对比 |

## 快速开始

```python
from modules.auto_evolve import evolve

# 一键自动进化
result = evolve(min_pattern_count=3, auto_execute=False)

print(f"目标缺口: {len(result['goal_gaps'])}")
print(f"能力短板: {len(result['capability_weaknesses'])}")
print(f"失败模式: {len(result['failure_patterns'])}")
print(f"改进建议: {result['improvement_suggestions']}")
```

## 数据库结构

所有模块共享一个 SQLite 数据库（`memory.db`），复用 X-Memory 的 `task_outcomes` 表记录任务执行结果：

```sql
CREATE TABLE task_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    model TEXT,
    success BOOLEAN NOT NULL,
    description TEXT,
    notes TEXT,
    tags TEXT,
    critic_score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

各模块自建表：
- `goals` — 目标树
- `capabilities` — 能力画像
- `evolution_changes` — 变更记录

## 设计原则

1. **目标驱动**：从长期目标出发，而非随机扫描
2. **归因严谨**：因果验证，避免把巧合当因果
3. **可回滚**：任何变更都有备份，随时可撤回
4. **零依赖**：纯 Python + SQLite，无外部库
5. **不自动执行**：只生成建议，不擅自修改核心文件（L2 级别需审批）

## 与 X-Memory 的关系

- **X-Memory**：结构化记忆系统（存储、检索、压缩）
- **Self-Evolution**：自主进化引擎（目标→能力→改进→验证）

两者共用同一个 SQLite 数据库（`memory.db`），Self-Evolution 读取 X-Memory 的 `task_outcomes` 表进行能力分析。

## 与 External Learning 的关系

- **External Learning**：外部情报扫描器，从 arXiv、GitHub Trending、Hacker News、36kr 等 6 个信息源抓取最新技术动态
- **Self-Evolution**：内部进化引擎，将外部学到的新知识转化为系统能力的提升

**协作流程**：
```
External Learning 扫描外部情报
    ↓ 发现高价值技术（如 MiroThinker 论文）
生成学习报告到 memory/learning/
    ↓
Self-Evolution 的 curiosity_engine 读取报告
    ↓ 评估落地可行性
生成进化提案（proposal）
    ↓
feedback_loop 分析当前能力缺口
    ↓
evolution_executor 执行改进
    ↓
causal_validator 验证效果
    ↓
系统能力提升
```

**关键区别**：
- External Learning 负责"看外面有什么"（信息输入）
- Self-Evolution 负责"我需要什么、怎么改进"（内部成长）
- 两者通过 `memory/learning/` 目录和 SQLite 数据库连接

## 更新日志

### 2026-04-08 — 外部学习打通 + 模块补全
- 新增 6 个模块：`change_applier`、`improvement_suggestions`、`learning_conversion`、`skillify`、`validation`、`usage_stats`
- `learning_conversion`：追踪外部学习内容转化为进化变更的比率
- `skillify`：自动检测重复任务模式，生成 Skill 草稿
- 外部学习模块（External Learning）现在直接写入 `memory_db` observations 表，P0 提案自动触发 `auto_evolve`
- 修复 `auto_evolve` 启动时 `task_outcomes` 表不存在的问题（加入 `init_db()` 保障）
- 完整闭环：External Learning → memory_db → Self-Evolution → causal_validator

### 2026-04-04 — 目标驱动架构重写
- 从"软件工程流水线"重构为"目标驱动的自主进化"
- 8 个核心模块完成（3777行代码）
- 完整的闭环链路：目标缺口 → 能力画像 → 反馈分析 → 执行变更 → 归因验证

### 2026-03-30 — 旧版（已废弃）
- 7 个模块（architect、builder、critic_engine 等）
- 从论文/博客生成软件模块的流水线
- 依赖 OpenClaw sessions_spawn 派子 Agent 写代码

---

_Built with [OpenClaw](https://github.com/openclaw/openclaw)_
