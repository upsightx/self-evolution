# Self-Evolution：主动能力进化引擎

## 是什么

`self-evolution` 是一套主动能力进化系统，把"发现缺口 → 创建提案 → 执行实验 → 验证效果 → 固化能力"串成自主运行的闭环。

它在 X-Memory 记忆底座之上，构建了一条持续运行的进化主链：
- 从任务结果和能力检测中发现问题
- 把问题路由成结构化 proposal
- 用统一状态机推进 proposal 生命周期
- 在 auto_evolve 中执行变更（含保护、备份、回滚）
- 用 causal_validator 做归因验证
- 把结果写回 X-Memory，更新 goal_tree 进度

## 核心链路

```text
task_outcomes / 能力检测 / 外部学习
        ↓
evolution_orchestrator（统一编排入口）
        ↓
proposal_bridge（外部学习桥接）
        ↓
proposal_lifecycle_manager（状态机唯一真源）
        ↓
auto_evolve（自动进化主循环）
        ↓
evolution_executor（执行变更，备份+回滚+py_compile校验）
        ↓
causal_validator（归因验证）
        ↓
goal_tree（目标进度更新）
        ↓
X-Memory（持久化记忆）
```

## 模块总览

### 编排与状态
| 文件 | 职责 |
|------|------|
| `evolution_orchestrator.py` | **唯一大入口**：信号路由、外部学习桥接、提案推进、目标更新、日志清理 |
| `proposal_lifecycle_manager.py` | proposal 状态唯一真源，14 种状态转换，全事件日志 |
| `auto_evolve.py` | 自动进化主循环：能力扫描 → 缺口检测 → 提案创建 → 执行 → 验证 |
| `evolution_runtime.py` | 事件日志、CLI 入口，heartbeat_check 重定向到 orchestrator |
| `agenda_planner.py` | 动态议程调度（参考工具，不直接用于心跳） |

### 执行与验证
| 文件 | 职责 |
|------|------|
| `evolution_executor.py` | 执行提案、应用代码变更、Docker sandbox 测试、备份+回滚 |
| `causal_validator.py` | 变更前后成功率对比，输出 effective/ineffective/uncertain 结论 |
| `evidence_validator.py` | 结构/能力双 track 分流，即时证据审查 |
| `evolution_benchmarks.py` | 进化性能基准测试 |
| `llm_provider.py` | 统一模型调用与 fallback |

### 采集与治理
| 文件 | 职责 |
|------|------|
| `capability_detector.py` | 主动探测能力缺口（missing / struggling / reliable / strengths） |
| `capability_model.py` | 能力自画像，从 task_outcomes 自动评分 |
| `task_outcome_hook.py` | 任务结果记录 + 自动系统活动记录 |
| `memory_governor.py` | 去重、lineage 溯源、反自激保护 |
| `proposal_bridge.py` | 外部学习 → 自进化的桥接层 |

### 路由与清理
| 文件 | 职责 |
|------|------|
| `controlled_loop_router.py` | 只读路由建议，不修改状态 |
| `proposal_fusion.py` | 相似提案融合建议 |
| `proposal_janitor.py` | 垃圾提案清理（测试残留、重复草案） |
| `proposal_triage.py` | 提案分流（keep / delete / fuse） |
| `proposal_governance.py` | 治理动作兼容层 |

### 目标与学习
| 文件 | 职责 |
|------|------|
| `goal_tree.py` | 目标树管理，自动进度更新，4 目标追踪 |
| `learning_conversion.py` | 外部学习转化率追踪 |
| `critic_engine.py` | 外部学习提案可行性审查 |
| `skillify.py` | 重复任务模式挖掘 → 自动生成 Skill 草稿 |

### 基础设施
| 文件 | 职责 |
|------|------|
| `bootstrap.py` | 统一 sys.path 管理 |
| `db_common.py` | 数据库 thin adapter（代理 X-Memory/db_common.py） |
| `memory_db.py` | 记忆层 thin adapter（代理 X-Memory/memory_db.py） |
| `evolution_history.py` | 进化历史报告生成 |
| `arch_audit.py` | 架构合规审计 |

## 快速开始

```bash
# 记录任务结果
python3 modules/task_outcome_hook.py record coding opus 1 --desc "完成代码修复"

# 运行编排器心跳（全链路一次跑通）
cd self-evolution
PYTHONPATH=".:modules:../X-Memory" python3 modules/evolution_orchestrator.py heartbeat

# 推进 proposal
python3 modules/proposal_lifecycle_manager.py list --status draft
python3 modules/proposal_lifecycle_manager.py transition <proposal_id> pending_review

# 自动进化（周日用，auto_execute=True, max_changes=1）
python3 -c "
import sys; sys.path.insert(0,'modules')
from auto_evolve import evolve
evolve(min_pattern_count=3, auto_execute=True, max_rounds=1, max_changes=1)
"
```

## 测试

```bash
cd self-evolution
python3 ../tests/run_all.py
```

46 个测试全绿，覆盖 proposal 生命周期、路由、证据验证、融合、熔断、benchmark。

## 安全保护

| 机制 | 说明 |
|------|------|
| `_PROTECTED_FILES` | 8 个关键文件禁止自动修改 |
| 自动备份 | 修改前备份到 `memory/evolution_backups/` |
| py_compile 校验 | 修改后立即编译检查，失败自动回滚 |
| `max_changes=1` | 每次最多改 1 个文件，限制爆炸半径 |
| 确定性哈希去重 | 同一目标不重复创建提案 |

## 设计原则

1. **proposal_lifecycle_manager 是唯一状态真源** — 其他模块只能通过它读写 proposal 状态
2. **evolution_orchestrator 是唯一编排入口** — 信号路由、提案推进、进度更新统一走 heartbeat
3. **所有路径通过 runtime_config 解析** — 无硬编码，环境变量可覆盖
4. **X-Memory 是唯一数据底座** — 所有持久化走 X-Memory，不自建独立数据库

## 2026-04-27 大修

### 闭环打通
- auto_evolve 提案去重（确定性哈希替代随机 UUID）
- goal_tree 目标进度从真实数据推算（4 目标全部有值：85/90/50/90）
- 外部学习桥接：orchestrator 自动读 gather.py JSONL → X-Memory → 提案
- capability_model 维度从 2 扩展到 4（coding/research/deploy/file_ops）
- evolution_runtime.heartbeat_check() 重定向到 orchestrator

### 安全加固
- auto_evolve 新增 `_PROTECTED_FILES`（8 个关键文件拦截）
- 执行后 py_compile 校验 + 失败自动回滚
- critic_engine.py 从备份恢复（曾被 auto_evolve 损坏）

### 数据管道
- task_outcome_hook.auto_record_system_activity() 心跳自动记录
- proposal_bridge 深读筛选：≥8 分才进提案
- orchestrator 心跳新增日志清理（/tmp 7 天 + 备份 14 天）
- 系统 cron 部署（每日 08:30 gather + 08:35 heartbeat + 周日 02:30 auto_evolve）

### 代码清理
- 删除演化执行器中 58 行 LEGACY 代码
- 清理 4 个文件中 evolution_changes 过时引用
- 6 个 external-learning 文件硬编码路径统一走 runtime_config
- proposal_fusion ID 生成从字符串拼接改为 MD5 哈希
- learning_conversion 函数重命名消除误导
- memory_governor BRIDGE_MODULES 更新
