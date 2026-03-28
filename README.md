# 🧬 AI Agent 自我进化引擎

帮助 AI Agent 从经验中学习、持续改进的轻量级自我进化系统。零外部依赖，只需 Python 3.8+ 和 SQLite。

## 模块

### 记忆层

| 模块 | 功能 |
|------|------|
| `memory_db` | 结构化记忆（观察/决策/会话摘要），FTS5 中英文双路径搜索 |
| `memory_store` | 记忆的持久化层，CRUD + 标签/时间过滤 |
| `memory_retrieval` | 记忆的检索层，查询改写 + 动态阈值 + 时间衰减 |
| `memory_service` | 记忆的统一接口层，remember/recall/reflect |
| `memory_embedding` | 向量化 + 语义搜索（需 SiliconFlow API） |
| `memory_lru` | 记忆冷热追踪，归档建议 |
| `file_registry` | 文件/文档记忆台账 |
| `db_common` | 共享 SQLite 连接（WAL 模式） |

### 分析层

| 模块 | 功能 |
|------|------|
| `feedback_loop` | 任务结果记录、失败模式分析、改进建议生成 |
| `causal_validator` | 实验归因验证（有效/存疑/无效），纯函数，不依赖数据库 |

### 进化层

| 模块 | 功能 |
|------|------|
| `evolution_executor` | 进化实验管理（创建→激活→录入→自动验证→结论/回滚） |
| `evolution_strategy` | 策略自动选择 + 多维信号检测 + 自适应反思频率 |

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                      进化层                              │
│  evolution_strategy    evolution_executor                │
│  (策略+信号+反思)       (实验生命周期)                     │
├─────────────────────────────────────────────────────────┤
│                      分析层                              │
│  feedback_loop         causal_validator                  │
│  (失败模式分析)         (归因验证)                         │
├─────────────────────────────────────────────────────────┤
│                      记忆层                              │
│  memory_service → memory_retrieval → memory_store        │
│  memory_db    memory_embedding    memory_lru             │
│  file_registry    db_common                              │
└─────────────────────────────────────────────────────────┘
```

## 核心闭环

```
feedback_loop 发现问题
    ↓
evolution_executor.pending_candidates() 生成候选实验
    ↓
创建实验 (draft) → 激活 (active)
    ↓
任务执行时调用 record_and_maybe_conclude() 录入结果
    ↓
baseline + experiment 样本够了 → causal_validator 自动验证
    ↓
结论写回 SQLite (effective / uncertain / ineffective)
    ↓
effective → 固化改进    ineffective → 回滚    uncertain → 继续观察
```

## 进化策略

系统根据运行状态自动选择策略：

| 策略 | 修复 | 优化 | 创新 | 触发条件 |
|------|------|------|------|----------|
| balanced | 20% | 30% | 50% | 默认/系统健康 |
| innovate | 5% | 15% | 80% | 停滞/修复循环 |
| harden | 40% | 40% | 20% | 近期大改动 |
| repair_only | 80% | 20% | 0% | 高失败率 |
| steady_state | 60% | 30% | 10% | 进化饱和 |

## 信号检测

从运行数据中自动提取 6 种信号：

- 🔴 `high_failure_rate` — 某类任务失败率 ≥ 50%
- 🔴 `repair_loop` — 连续 3 次失败，修了但没改善
- 🟡 `elevated_failure_rate` — 失败率 30%~50%
- 🟡 `recent_big_change` — 近 3 天大量新观察记录
- 🟡 `capability_gap` — 失败原因含依赖缺失/能力缺口
- 🟢 `stagnation` — 成功率高但无新进展
- ℹ️ `all_healthy` — 无异常

## 归因验证

实验结论不靠感觉，靠工程规则：

- 样本量门槛：< 3 次直接 `uncertain`
- 4 维度加权：成功率(0.4) + 返工率(0.25) + Critic分(0.25) + 耗时(0.1)
- 样本量置信度调整：样本越多，置信度越高
- 三档判定：`effective` / `uncertain` / `ineffective`
- 核心原则：**敢说"不知道"比乱自信强**

## 自适应反思

反思频率根据系统状态动态调整：

- 系统健康 → 每 5 天反思一次
- 正常状态 → 每 3 天
- 有问题 → 每 1 天

## 快速开始

```bash
# 初始化数据库
python3 modules/memory_db.py init

# 检测当前信号
python3 modules/evolution_strategy.py signals

# 查看当前策略
python3 modules/evolution_strategy.py strategy

# 查看实验候选
python3 modules/evolution_executor.py candidates

# 创建实验
python3 modules/evolution_executor.py create \
  --source feedback_loop \
  --task-type coding \
  --problem "子Agent指令太长导致漏掉关键约束" \
  --proposal "首段加入负面清单"

# 验证实验
python3 modules/causal_validator.py validate 1

# 查看反思上下文
python3 modules/evolution_strategy.py reflection-context
```

## 设计原则

- **零依赖**：只需 Python 3.8+ 和 SQLite，不依赖任何外部框架
- **全持久化**：所有状态存 SQLite，session 重启不丢失
- **可回滚**：所有实验都可取消/回滚，不做不可逆操作
- **敢说不知道**：样本不足时输出 `uncertain`，不强行下结论
- **贴着现实长**：不做过度抽象，Phase 1 只改模板和配置，不自动改代码

## 历史

- v1~v5: 记忆系统 + 反馈闭环 + LRU + 子Agent统计
- v6 (2026-03-20): 检索层重构（三层分离 + 查询改写 + 时间衰减）
- v7 (2026-03-28): 进化执行器 + 归因验证器 + 策略引擎（从 Evolver 迁移核心思想）

## License

MIT
