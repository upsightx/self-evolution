# Self-Evolution：主动能力进化引擎

## 是什么

`self-evolution` 是一套主动能力进化系统，用来把“发现缺口、创建提案、执行实验、验证效果、固化能力”串成闭环。

它不是简单的自动修 bug 脚本，而是一条持续运行的进化主链：
- 从信号里发现问题
- 把问题路由成 proposal
- 用统一状态机推进 proposal
- 在执行后做归因验证
- 把结果写回统一记忆层

## 这次收口后的核心原则

- `proposal_lifecycle_manager.py` 是 proposal 状态的唯一真源
- proposal 相关表只有一个 writer
- `evolution_changes` 只保留为 legacy 只读兼容面
- 统一通过 `X-Memory` 提供的记忆底座落数据

## 核心链路

```text
外部信号 / 任务结果 / 能力缺口
        ↓
proposal_bridge / capability_detector
        ↓
evolution_orchestrator
        ↓
proposal_lifecycle_manager
        ↓
evolution_executor
        ↓
causal_validator
        ↓
memory_governor / X-Memory
```

## 主要模块

### 编排与状态

| 模块 | 职责 |
|------|------|
| `evolution_orchestrator.py` | 统一编排入口：收信号、去重、路由、推进 |
| `proposal_lifecycle_manager.py` | proposal 状态唯一真源 |
| `evolution_runtime.py` | 统一事件日志与运行时入口 |
| `auto_evolve.py` | 自动进化主循环 |

### 执行与验证

| 模块 | 职责 |
|------|------|
| `evolution_executor.py` | 执行提案、应用变更、做 sandbox 测试 |
| `causal_validator.py` | 验证变更是否真的有效 |
| `llm_provider.py` | 统一模型调用与 fallback |

### 采集与治理

| 模块 | 职责 |
|------|------|
| `capability_detector.py` | 主动发现能力缺口 |
| `task_outcome_hook.py` | 记录任务结果 |
| `memory_governor.py` | 去重、lineage、反自激 |
| `proposal_bridge.py` | external-learning 到 self-evolution 的桥接 |

### 辅助模块

| 模块 | 职责 |
|------|------|
| `goal_tree.py` | 目标树管理 |
| `capability_model.py` | 能力画像 |
| `critic_engine.py` | 质量审查 |
| `learning_conversion.py` | 学习转化率追踪 |
| `agenda_planner.py` | 动态议程调度 |

## 快速开始

### 1. 记录任务结果

```bash
python3 self-evolution/modules/task_outcome_hook.py record coding opus 1 --desc "完成代码修复"
```

### 2. 检测能力缺口

```bash
python3 self-evolution/modules/capability_detector.py detect
```

### 3. 推进 proposal 状态机

```bash
python3 self-evolution/modules/proposal_lifecycle_manager.py list --status draft
python3 self-evolution/modules/proposal_lifecycle_manager.py transition <proposal_id> pending_review
```

### 4. 运行编排器心跳

```bash
python3 self-evolution/modules/evolution_orchestrator.py heartbeat
```

## 测试

```bash
cd /root/.openclaw/workspace/self-evolution
python3 -m pytest -q \
  test_proposal_lifecycle.py \
  test_legacy_readonly_contract.py \
  test_proposals_single_writer.py \
  test_legacy_readers_whitelist.py
```

当前测试重点：
- proposal 状态机是否按规则推进
- proposal 相关表是否仍保持单写入口
- `evolution_changes` 是否仍为只读兼容层
- 哪些模块允许读取 legacy 表，是否越界

## 设计说明

### 为什么不直接删掉 `evolution_changes`

因为系统里仍有一部分 legacy 读取路径依赖它。现在更稳的做法是：
- 先切断写路径
- 再把读路径白名单化
- 最后视迁移情况再考虑彻底退役

### 为什么要强调 proposal 单写入口

如果多个模块都能直接写 `proposals`、`proposal_transitions`、`proposal_evidence`，状态机会很快漂移，最后谁也说不清“哪个状态是真的”。

所以这次重构最重要的一刀就是：
- 只有 `proposal_lifecycle_manager.py` 能直接写 proposal 相关表
- 其他模块只能通过它来改状态

## 当前状态

这版已经完成：
- proposal 状态真源收口
- proposal 单写入口护栏化
- legacy 只读边界测试化
- 与 `X-Memory` 的统一底座关系更清晰

剩下保留的是可控兼容层，不是主链上的结构性问题。
