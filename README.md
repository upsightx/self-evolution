# Self-Evolution — AI Agent 自我进化系统

零外部依赖（纯 Python stdlib + SQLite + PyYAML），为 AI Agent 提供结构化记忆、动态策略和自主进化能力。

## 架构

```
记忆层（记住什么、为什么）
├── db_common.py          公共数据库连接（统一 DB_PATH + WAL 模式）
├── memory_db.py          SQLite+FTS5 结构化记忆库 + 向量语义搜索
├── auto_memory.py        跨会话记忆自动提取（8种观察+7种决策模式）
└── memory_lru.py         记忆冷热管理（LRU归档建议）

策略层（怎么做更好）
├── model_router.py       多模型动态路由（关键词+模糊匹配分层分类）
├── feedback_loop.py      反馈闭环（预期vs实际，失败模式分析）
├── decision_review.py    决策事后验证（定期回顾，追踪后悔率）
├── skill_discovery.py    技能缺口扫描（从失败中识别能力短板）
├── template_evolution.py 模板自进化（分析成功率，生成改进建议）
└── data_accumulator.py   数据积累（从日志提取历史记录，回填路由数据）

执行层（派活更精准）
├── orchestrator.py       统一编排层（EventBus + Scheduler，串联全部模块）
├── template_manager.py   子Agent指令模板（6个YAML模板+变量替换）
├── todo_extractor.py     对话待办提取（规则引擎+LLM兜底，三级置信度）
├── prompt_loader.py      YAML Prompt 加载器（单例+点号路径）
└── record_agent_stat.py  子Agent成功率记录（原子写入）
```

## 核心理念

- **记住 WHY，不只是 WHAT** — 每个决策记录被拒绝的替代方案和理由
- **规则优先，LLM 兜底** — 零成本关键词匹配先行，长尾走便宜模型
- **数据驱动进化** — 基于历史成功率动态调整模型选择和任务策略
- **事件驱动编排** — EventBus + Scheduler 统一调度，模块间松耦合
- **零外部依赖** — 纯 Python stdlib + SQLite + PyYAML，任何环境即插即用

## 快速开始

```bash
# 初始化记忆数据库
python3 modules/memory_db.py init

# 记录一个决策（含被拒绝的替代方案）
python3 modules/memory_db.py decision \
  "选择 SQLite 作为记忆存储" \
  "使用 SQLite + FTS5" \
  "Redis,MongoDB,纯文件" \
  "零依赖、支持全文搜索、单文件部署"

# 语义搜索（需设置 SILICONFLOW_API_KEY）
export SILICONFLOW_API_KEY=your_key
python3 modules/memory_db.py embed        # 构建向量索引
python3 modules/memory_db.py semantic "模型选择策略"

# 任务意图分类 + 模型推荐
python3 -c "
from modules.model_router import recommend_for_description
print(recommend_for_description('帮我写一个爬虫脚本'))
# → {'task_type': 'coding', 'model': 'opus', 'alias': 'LtCraft', 'confidence': 0.9}
"

# 从对话中提取待办（规则+LLM兜底）
export MINIMAX_API_KEY=your_key  # LLM兜底需要
python3 -c "
from modules.todo_extractor import extract_todos_from_text
todos = extract_todos_from_text('帮我查一下红杉的投资人\n明天记得提醒我开会', use_llm=True)
for t in todos:
    print(f'[{t[\"confidence\"]:.1f}] {t[\"title\"]}  time={t.get(\"time_hint\", \"-\")}')
"

# 统一编排（一行串联所有模块）
python3 -c "
from modules.orchestrator import Orchestrator
orch = Orchestrator()
orch.on_agent_completed('coding', 'opus', True, '写了个爬虫')  # 自动记录统计
todos = orch.on_message('帮我查一下经纬的合伙人')              # 自动提取待办
result = orch.on_heartbeat()                                    # 自动执行定时任务
print(orch.status())                                            # 查看全局状态
"

# 跨会话记忆自动提取
python3 modules/auto_memory.py "发现BGE-M3效果很好\n决定统一用db_common管理连接"

# 模板自进化报告
python3 modules/template_evolution.py report

# 数据积累（从日志回填历史数据）
python3 modules/data_accumulator.py scan     # 扫描日志
python3 modules/data_accumulator.py backfill --apply  # 回填
```

## 模块详情

### 记忆层

| 模块 | 说明 |
|------|------|
| `db_common.py` | 公共数据库连接，统一 DB_PATH 和 WAL 模式，所有模块共享 |
| `memory_db.py` | 三表结构（observations/decisions/session_summaries），FTS5+LIKE 双路CJK检索，SiliconFlow BGE-M3 向量语义搜索，支持 keyword/semantic/hybrid 三种模式 |
| `auto_memory.py` | 纯规则从对话中提取观察（8种模式）和决策（7种模式），自动分类（discovery/bugfix/lesson/change），与近7天记录去重 |
| `memory_lru.py` | 按访问频率分冷热区，建议归档候选，生成访问热力图 |

### 策略层

| 模块 | 说明 |
|------|------|
| `model_router.py` | 分层分类（关键词→模糊匹配→默认），基于历史成功率推荐最优模型（cost/quality/balanced 三种策略） |
| `feedback_loop.py` | 记录任务预期vs实际结果，自动发现失败模式（>30%失败率报警），生成改进建议 |
| `decision_review.py` | 定期回顾历史决策效果，追踪后悔率，支持 pending/review/report 工作流 |
| `skill_discovery.py` | 从失败记录中提取关键词，匹配预定义能力→skill映射，生成缺口报告 |
| `template_evolution.py` | 分析各任务类型成功率，提取常见失败原因，生成模板改进建议 |
| `data_accumulator.py` | 从三个数据源（agent-stats.json + memory.db + daily logs）积累数据，去重合并，回填路由训练数据 |

### 执行层

| 模块 | 说明 |
|------|------|
| `orchestrator.py` | EventBus 事件总线 + Scheduler 心跳调度，串联全部模块。5种事件：agent.task.completed/failed、conversation.message、heartbeat.tick、memory.updated |
| `template_manager.py` | 6个YAML模板（coding/research/skill/doc/compress/critic），支持{变量}替换，system+constraints+user 三段式拼接 |
| `todo_extractor.py` | 规则引擎（三级置信度：明确承诺0.8-0.9/时间约定0.7-0.8/计划讨论0.6-0.7）+ MiniMax LLM 兜底，支持去重 |
| `prompt_loader.py` | YAML prompt 加载器，单例模式，支持点号路径访问和变量替换 |
| `record_agent_stat.py` | 记录子Agent成功/失败到JSON，原子写入，错误处理 |

## 数据流

```
对话 → todo_extractor 提取待办 → auto_memory 提取记忆
  ↓
orchestrator 编排
  ↓
model_router 选模型 → template_manager 生成指令 → 派子Agent
  ↓
record_agent_stat 记录结果 → feedback_loop 分析模式
  ↓
template_evolution 改进模板 → data_accumulator 积累数据
  ↓
decision_review 回顾决策 → skill_discovery 扫描缺口
  ↓
memory_lru 管理冷热 → memory_db 语义搜索
```

## 参考资料

`prompts/` — 可复用的 prompt 模板（待办提取、RAG、任务拆解、意图分类）
`code/` — 通用工具代码（prompt加载器、查询解析器、上下文构建器、模块注册器）
`patterns.md` — 5个可复用的设计模式
`reviews/` — 多角色审查报告（安全/代码质量/CTO/测试）

## 测试

```bash
cd tests && python3 -m pytest -v
# 218 passed, 2 skipped
```

## 环境变量

| 变量 | 用途 | 必需 |
|------|------|------|
| `SILICONFLOW_API_KEY` | 向量语义搜索（BGE-M3 embedding） | 语义搜索时需要 |
| `MINIMAX_API_KEY` | 待办提取 LLM 兜底 | use_llm=True 时需要 |
| `SELF_EVOLUTION_DB` | 自定义数据库路径 | 可选，默认 modules/memory.db |

## 致谢

- [FreeTodo](https://github.com/upsightx/FreeTodo) — 待办提取、RAG 流程、上下文构建等设计模式源自该项目的精华提炼

## License

MIT
