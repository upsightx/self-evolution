# 🧬 AI Agent 自我进化引擎

一套帮助 AI Agent 从经验中学习、持续自我改进的轻量级框架。

不依赖任何外部框架，只需要 Python 3.8+ 和 SQLite。所有状态持久化到本地数据库，Agent 重启不丢失记忆。

---

## 为什么需要这个？

大多数 AI Agent 每次对话都是从零开始。它们不记得上次犯了什么错，不知道哪个模型更适合哪类任务，也不会从失败中总结教训。

这个项目要解决的问题很简单：**让 Agent 能像人一样积累经验、反思失败、验证改进。**

具体来说，它让 Agent 具备以下能力：

- 记住重要的经验、决策和教训，而不是每次重启都归零
- 统计不同方法的成功率，用数据而不是感觉做决策
- 识别重复出现的失败模式，自动生成改进建议
- 把改进建议变成可验证的实验，而不是停留在"下次注意"
- 用工程规则判断实验是否真的有效，防止被单次巧合误导
- 根据系统当前状态自动调整进化策略（该激进还是该保守）

---

## 架构总览

系统分三层，每层职责清晰：

```
┌──────────────────────────────────────────────────────────────┐
│                         进化层                                │
│                                                              │
│  evolution_strategy        evolution_executor                 │
│  ┌──────────────────┐     ┌──────────────────────────┐       │
│  │ 5种策略自动切换    │     │ 实验生命周期管理          │       │
│  │ 6种信号检测       │     │ draft→active→concluded   │       │
│  │ 自适应反思频率     │     │ 自动发现候选+自动结论     │       │
│  └──────────────────┘     └──────────────────────────┘       │
├──────────────────────────────────────────────────────────────┤
│                         分析层                                │
│                                                              │
│  feedback_loop              causal_validator                  │
│  ┌──────────────────┐     ┌──────────────────────────┐       │
│  │ 任务结果记录       │     │ 纯函数归因验证            │       │
│  │ 失败模式分析       │     │ 4维度加权打分             │       │
│  │ 改进建议生成       │     │ 三档判定+置信度           │       │
│  └──────────────────┘     └──────────────────────────┘       │
├──────────────────────────────────────────────────────────────┤
│                         记忆层                                │
│                                                              │
│  memory_service → memory_retrieval → memory_store             │
│  memory_db    memory_embedding    memory_lru                  │
│  file_registry    db_common                                   │
│  ┌──────────────────────────────────────────────────┐        │
│  │ 结构化存储 · FTS5全文搜索 · 语义检索 · 冷热管理    │        │
│  │ 查询改写 · 时间衰减 · 标签过滤 · 文件台账         │        │
│  └──────────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────────┘
```

---

## 模块详解

### 记忆层（7个模块）

记忆层负责"别忘、别丢、别靠感觉"。

| 模块 | 文件 | 功能 |
|------|------|------|
| 结构化记忆 | `memory_db.py` | 核心数据库，存储观察(observations)、决策(decisions)、会话摘要(session_summaries)。支持 FTS5 全文搜索，中英文双路径检索 |
| 持久化层 | `memory_store.py` | 记忆的写入和查询，支持标签过滤、时间范围过滤、任务类型过滤。向后兼容旧接口 |
| 检索层 | `memory_retrieval.py` | 智能检索：查询改写（去口语化+同义词扩展）、动态阈值、时间衰减。最多5个查询角度 |
| 服务层 | `memory_service.py` | 对外统一接口：`remember()` 存入记忆、`recall()` 检索记忆、`reflect()` 反思总结 |
| 向量化 | `memory_embedding.py` | 可选的语义搜索支持，基于 SiliconFlow Embedding API。不配置 API Key 时自动降级为关键词搜索 |
| 冷热管理 | `memory_lru.py` | 追踪每条记忆的访问频率，区分热区/冷区，给出归档候选建议。防止记忆库无限膨胀 |
| 文件台账 | `file_registry.py` | 记录文件/文档的元信息（名称、路径、关联任务），方便按"上次那个文件"这类描述找回 |
| 公共连接 | `db_common.py` | 统一的 SQLite 连接管理，WAL 模式，所有模块共享 |

### 分析层（2个模块）

分析层负责"知道哪里做得好，哪里做得烂"。

#### feedback_loop.py — 反馈闭环

记录每次任务的预期结果和实际结果，自动分析失败模式。

核心功能：
- `record_task_outcome()` — 记录一次任务执行结果（任务类型、模型、成功/失败、差距分析）
- `analyze_patterns()` — 扫描所有任务记录，找出成功率低于 70% 的分组
- `generate_template_improvements()` — 基于失败记录，用规则匹配生成改进建议
- `analyze_template_effectiveness()` — 分析某类任务的模板有效性（成功率、常见失败原因、改进建议）

```python
# 记录一次任务结果
record_task_outcome(
    task_id="sub-agent-42",
    task_type="coding",
    model="minimax",
    expected="完成代码重构",
    actual="只输出了意图，没写代码",
    success=False,
    notes="子Agent没有执行，只描述了计划"
)

# 分析失败模式
patterns = analyze_patterns(min_samples=5)
# → [{"task_type": "coding", "model": "minimax", "failure_rate": 0.4, "pattern": "未执行, 意图"}]

# 生成改进建议
suggestions = generate_template_improvements("coding")
# → ["在指令开头添加强制执行提示", "考虑使用更强的模型"]
```

#### causal_validator.py — 归因验证器

判断一次实验改动是否真的有效。**纯函数模块，不依赖数据库，只接收数据做判断。**

核心原则：**敢说"不知道"比乱自信强。**

验证规则：

1. **样本量门槛** — 实验样本少于 3 次，直接输出 `uncertain`，不冒险下结论
2. **4维度加权打分**：
   - 成功率变化（权重 0.4）
   - 返工率变化（权重 0.25，越低越好）
   - Critic 评分变化（权重 0.25）
   - 耗时变化（权重 0.1，越短越好）
3. **样本量置信度调整** — 样本越多，置信度越高（6条=0.7，10条=0.85，20条=1.0）
4. **三档判定**：
   - `effective` — 改动确实有效，可以固化
   - `uncertain` — 证据不足，继续观察
   - `ineffective` — 改动没用或变差了，应该回滚

```python
from causal_validator import validate

result = validate(
    baseline_results=[
        {"success": True, "critic_score": 72, "rework": False},
        {"success": False, "critic_score": 55, "rework": True},
        {"success": True, "critic_score": 78, "rework": False},
    ],
    experiment_results=[
        {"success": True, "critic_score": 85, "rework": False},
        {"success": True, "critic_score": 88, "rework": False},
        {"success": True, "critic_score": 90, "rework": False},
    ],
    min_samples=3,
)
# result.verdict = "effective"
# result.confidence = 0.7
# result.reason = "成功率提升 +33%；返工率下降 -33%；Critic 分提升 +16.7"
```

### 进化层（2个模块）

进化层负责"决定下一步往哪进化"。

#### evolution_executor.py — 进化执行器

把改进建议变成可回滚的小实验，管理实验的完整生命周期。

实验状态流转：
```
draft（草案）→ active（执行中）→ concluded（已结论）
                                ↘ cancelled（已取消）
```

核心功能：
- `create_experiment()` — 创建实验草案
- `activate_experiment()` — 激活实验，开始收集数据
- `record_and_maybe_conclude()` — 录入结果，样本够了自动触发验证并结论（**最常用的入口**）
- `pending_candidates()` — 自动从 feedback_loop 发现候选实验（failure_rate ≥ 0.3 且无活跃实验）
- `conclude_experiment()` — 手动结论
- `cancel_experiment()` — 取消实验

```python
import evolution_executor as ee

# 自动发现候选
candidates = ee.pending_candidates()
# → [{"task_type": "coding", "failure_rate": 0.4, "sample_count": 12}]

# 创建实验
eid = ee.create_experiment(
    source="feedback_loop",
    task_type="coding",
    problem="子Agent指令太长导致漏掉关键约束",
    proposal="在指令首段加入负面清单（不要做什么）",
    target_type="prompt_template",
    min_samples=5,
)

# 激活
ee.activate_experiment(eid)

# 每次任务完成后录入结果（自动判断是否该结论）
result = ee.record_and_maybe_conclude(
    eid, phase="experiment",
    success=True, critic_score=85, rework=False
)
# 当 baseline 和 experiment 都攒够 min_samples 时，自动返回验证结果：
# {"verdict": "effective", "confidence": 0.7, "reason": "..."}
```

#### evolution_strategy.py — 策略引擎

从运行数据中提取信号，自动选择进化策略，控制反思频率。

**5种策略预设：**

| 策略 | 修复 | 优化 | 创新 | 适用场景 |
|------|------|------|------|----------|
| `balanced` | 20% | 30% | 50% | 系统健康，正常运行 |
| `innovate` | 5% | 15% | 80% | 停滞或修复循环，需要突破 |
| `harden` | 40% | 40% | 20% | 刚做完大改动，需要稳定 |
| `repair_only` | 80% | 20% | 0% | 高失败率，紧急修复 |
| `steady_state` | 60% | 30% | 10% | 进化饱和，维持现状 |

**6种信号检测：**

| 信号 | 严重度 | 含义 |
|------|--------|------|
| `high_failure_rate` | 🔴 高 | 某类任务失败率 ≥ 50% |
| `repair_loop` | 🔴 高 | 连续3次失败，修了但没改善 |
| `elevated_failure_rate` | 🟡 中 | 失败率 30%~50% |
| `recent_big_change` | 🟡 中 | 近3天大量新观察记录 |
| `capability_gap` | 🟡 中 | 失败原因含依赖缺失/能力缺口 |
| `stagnation` | 🟢 低 | 成功率高但无新进展 |
| `all_healthy` | ℹ️ 信息 | 一切正常 |

**自适应反思：**

| 系统状态 | 反思间隔 |
|----------|----------|
| 有问题（高失败率/修复循环） | 每 1 天 |
| 正常 | 每 3 天 |
| 健康 | 每 5 天 |

```python
import evolution_strategy as es

# 检测当前信号
signals = es.detect_signals()
# → [{"signal": "recent_big_change", "severity": "medium", "detail": "近3天新增39条观察记录"}]

# 自动选择策略
strategy = es.resolve_strategy()
# → {"name": "harden", "reasoning": "近期有大改动，优先加固稳定性", ...}

# 检查是否该反思
ref = es.should_reflect()
# → {"should_reflect": true, "reason": "从未反思过", "interval_days": 3}

# 生成反思上下文（聚合信号+实验+失败模式）
context = es.build_reflection_context()
```

---

## 核心闭环

这套系统最重要的不是单个模块，而是它们串起来形成的闭环：

```
                    ┌─────────────────────┐
                    │  feedback_loop      │
                    │  发现失败模式        │
                    └─────────┬───────────┘
                              ↓
                    ┌─────────────────────┐
                    │  evolution_executor  │
                    │  生成候选实验        │
                    └─────────┬───────────┘
                              ↓
                    ┌─────────────────────┐
                    │  创建实验 (draft)    │
                    │  激活实验 (active)   │
                    └─────────┬───────────┘
                              ↓
                    ┌─────────────────────┐
                    │  任务执行时录入结果   │
                    │  record_and_maybe_  │
                    │  conclude()         │
                    └─────────┬───────────┘
                              ↓
                    ┌─────────────────────┐
                    │  causal_validator   │
                    │  样本够了自动验证    │
                    └─────────┬───────────┘
                              ↓
              ┌───────────────┼───────────────┐
              ↓               ↓               ↓
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ effective │   │ uncertain│   │ineffective│
        │ 固化改进   │   │ 继续观察 │   │ 回滚     │
        └──────────┘   └──────────┘   └──────────┘
```

同时，`evolution_strategy` 在旁边持续监控：
- 检测系统信号 → 自动切换策略
- 控制反思频率 → 该反思时反思，不该反思时省资源

---

## 数据库结构

所有数据存储在一个 SQLite 文件中（默认 `memory.db`），WAL 模式。

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `observations` | 观察/发现/教训 | type, title, narrative, tags, task_type |
| `decisions` | 决策记录（含被拒方案） | title, decision, rejected_alternatives, rationale |
| `session_summaries` | 会话摘要 | request, learned, completed, next_steps |
| `task_outcomes` | 任务执行结果 | task_type, model, success, gap_analysis |
| `experiments` | 进化实验 | source, problem, proposal, status, verdict, confidence |
| `embeddings` | 向量索引 | source_table, source_id, embedding |

---

## 快速开始

```bash
# 1. 初始化数据库
python3 modules/memory_db.py init

# 2. 记录一些任务结果
python3 modules/feedback_loop.py record coding minimax 1 --notes "重构成功"
python3 modules/feedback_loop.py record coding minimax 0 --notes "只输出意图没写代码"

# 3. 分析失败模式
python3 modules/feedback_loop.py analyze

# 4. 检测系统信号
python3 modules/evolution_strategy.py signals

# 5. 查看当前策略
python3 modules/evolution_strategy.py strategy

# 6. 查看实验候选
python3 modules/evolution_executor.py candidates

# 7. 创建并激活实验
python3 modules/evolution_executor.py create \
  --source feedback_loop \
  --task-type coding \
  --problem "子Agent只描述计划不执行" \
  --proposal "指令首段加强制执行提示"
python3 modules/evolution_executor.py activate 1

# 8. 录入实验结果（实际使用中由调度层自动调用）
python3 modules/evolution_executor.py record 1 baseline 1 --critic-score 75
python3 modules/evolution_executor.py record 1 experiment 1 --critic-score 88

# 9. 验证实验
python3 modules/causal_validator.py validate 1

# 10. 查看反思上下文
python3 modules/evolution_strategy.py reflection-context
```

---

## 设计原则

1. **零依赖** — 只需 Python 3.8+ 和 SQLite，不依赖 LangChain、LlamaIndex 或任何外部框架
2. **全持久化** — 所有状态存 SQLite，Agent session 重启不丢失任何记忆和实验状态
3. **可回滚** — 所有实验都可取消/回滚，不做不可逆操作
4. **敢说不知道** — 样本不足时输出 `uncertain`，不强行下结论。一个成熟的系统敢说"证据不足"
5. **贴着现实长** — Phase 1 只改模板和配置，不自动改代码。先证明闭环能跑通，再扩展范围
6. **查询不 crash** — 所有查询操作失败时返回空值，不抛异常。写入操作失败时返回 None 并打印警告

---

## 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|----------|
| v1~v5 | 2026-03-17~18 | 记忆系统 + 反馈闭环 + LRU + 子Agent统计 + Critic审查 |
| v6 | 2026-03-20 | 检索层重构（三层分离 + 查询改写 + 时间衰减 + 动态阈值） |
| v7 | 2026-03-28 | 进化执行器 + 归因验证器 + 策略引擎（从 Evolver 迁移核心思想，15000行JS→350行Python） |

---

## License

MIT
