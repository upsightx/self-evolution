# Self-Evolution — AI Agent 自我进化系统

零外部依赖（纯 Python stdlib + SQLite + PyYAML），为 AI Agent 提供结构化记忆、动态策略和自主进化能力。

## 架构

```
记忆层（记住什么、为什么）
├── memory_db.py          SQLite+FTS5 结构化记忆库（观察/决策/会话摘要）
├── search_with_context   记忆检索+上下文构建（日期分组+截断）
└── memory_lru.py         记忆冷热管理（LRU归档建议）

策略层（怎么做更好）
├── model_router.py       多模型动态路由（关键词+模糊匹配分层分类）
├── feedback_loop.py      反馈闭环（预期vs实际，失败模式分析）
├── decision_review.py    决策事后验证（定期回顾，追踪后悔率）
└── skill_discovery.py    技能缺口扫描（从失败中识别能力短板）

执行层（派活更精准）
├── template_manager.py   子Agent指令模板（YAML+变量替换）
├── todo_extractor.py     对话待办提取（纯规则，三级置信度）
└── record_agent_stat.py  子Agent成功率记录
```

## 核心理念

- **记住 WHY，不只是 WHAT** — 每个决策记录被拒绝的替代方案和理由
- **规则优先，LLM 兜底** — 零成本关键词匹配先行，降低 API 开销
- **数据驱动进化** — 基于历史成功率动态调整模型选择和任务策略
- **零外部依赖** — 纯 Python stdlib + SQLite，任何环境即插即用

## 快速开始

```bash
# 初始化记忆数据库
python3 modules/memory_db.py init

# 记录一个决策
python3 modules/memory_db.py decision \
  "选择 SQLite 作为记忆存储" \
  "使用 SQLite + FTS5" \
  "Redis,MongoDB,纯文件" \
  "零依赖、支持全文搜索、单文件部署"

# 记录一个观察
python3 modules/memory_db.py add discovery \
  "Opus 子Agent一次通过率100%" \
  "4个重构任务全部一次通过，MiniMax历史上经常返工"

# 搜索记忆（带上下文构建）
python3 -c "
from modules.memory_db import search_with_context
print(search_with_context('模型选择策略', max_chars=2000))
"

# 任务意图分类 + 模型推荐
python3 -c "
from modules.model_router import recommend_for_description
print(recommend_for_description('帮我写一个爬虫脚本'))
# → {'task_type': 'coding', 'model': 'opus', 'alias': 'LtCraft', 'confidence': 0.9}
"

# 从对话中提取待办
python3 -c "
from modules.todo_extractor import extract_todos_from_text
todos = extract_todos_from_text('帮我查一下红杉的投资人\n明天记得提醒我开会')
for t in todos:
    print(f'[{t[\"confidence\"]:.1f}] {t[\"title\"]}  time={t.get(\"time_hint\", \"-\")}')
"

# 生成子Agent指令
python3 -c "
from modules.template_manager import TemplateManager
tm = TemplateManager()
print(tm.get_template('coding', task='写CSV解析器', files='parser.py', test_command='pytest'))
"
```

## 模块详情

### 记忆层

| 模块 | 说明 |
|------|------|
| `memory_db.py` | 三表结构（observations/decisions/session_summaries），FTS5全文搜索+LIKE双路径检索，支持CJK |
| `search_with_context` | 搜索结果按日期分组，每组top-N，硬截断到字符预算，控制送入LLM的上下文质量 |
| `memory_lru.py` | 按访问频率分冷热区，建议归档候选，防止记忆库无限膨胀 |

### 策略层

| 模块 | 说明 |
|------|------|
| `model_router.py` | 分层分类（关键词→模糊匹配→默认），基于历史成功率推荐最优模型（cost/quality/balanced三种策略） |
| `feedback_loop.py` | 记录任务预期vs实际结果，自动发现失败模式（>30%失败率报警），生成改进建议 |
| `decision_review.py` | 定期回顾历史决策效果，追踪后悔率，支持 pending/review/report 工作流 |
| `skill_discovery.py` | 从失败记录中提取关键词，匹配15个预定义能力→skill映射，生成缺口报告 |

### 执行层

| 模块 | 说明 |
|------|------|
| `template_manager.py` | 6个YAML模板（coding/research/skill/doc/compress/critic），支持{变量}替换 |
| `todo_extractor.py` | 纯规则引擎，三级置信度（明确承诺0.8-0.9/时间约定0.7-0.8/计划讨论0.6-0.7），支持去重 |
| `record_agent_stat.py` | 记录子Agent成功/失败到JSON，喂给model_router做路由决策 |

## 参考资料

`prompts/` — 可复用的 prompt 模板（待办提取、RAG、任务拆解、意图分类）
`code/` — 通用工具代码（prompt加载器、查询解析器、上下文构建器、模块注册器）
`patterns.md` — 5个可复用的设计模式

## 测试

```bash
cd tests && python3 -m pytest -v
# 53 tests, 0 failures
```

## License

MIT

## 致谢

- [FreeTodo](https://github.com/upsightx/FreeTodo) — 待办提取、RAG 流程、上下文构建等设计模式源自该项目的精华提炼
