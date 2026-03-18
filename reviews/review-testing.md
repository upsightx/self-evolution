# 测试审查报告

**审查日期:** 2026-03-19
**审查范围:** /root/.openclaw/workspace/memory/structured/ 下所有 .py 文件

## 源码与测试文件清单

| 源码文件 | 对应测试文件 |
|----------|-------------|
| memory_db.py | test_context_search.py, test_embedding.py |
| auto_memory.py | test_auto_memory.py |
| data_accumulator.py | test_data_accumulator.py |
| orchestrator.py | test_orchestrator.py |
| model_router.py | test_task_classify.py |
| template_manager.py | test_template_manager.py |
| template_evolution.py | test_template_evolution.py |
| todo_extractor.py | test_todo_extractor.py, test_todo_llm.py |
| feedback_loop.py | ❌ 无独立测试文件（内嵌 `_run_tests`） |
| decision_review.py | ❌ 无独立测试文件（内嵌 `run_tests`） |
| memory_lru.py | ❌ 无独立测试文件（内嵌 `_run_tests`） |
| skill_discovery.py | ❌ 无独立测试文件（内嵌 `_run_tests`） |
| record_agent_stat.py | ❌ 无测试 |
| prompt_loader.py | ❌ 无测试 |

---

## 覆盖率分析

| 模块 | 公开函数数 | 已测试 | 未测试 | 覆盖率 |
|------|-----------|--------|--------|--------|
| memory_db.py | 17 | 12 | 5 | 71% |
| auto_memory.py | 2 (+2 internal) | 2 | 0 | 100% |
| data_accumulator.py | 3 (+8 internal) | 3+8 | 0 | 100% |
| orchestrator.py (EventBus) | 2 | 2 | 0 | 100% |
| orchestrator.py (Scheduler) | 3 | 3 | 0 | 100% |
| orchestrator.py (Orchestrator) | 7 | 6 | 1 | 86% |
| model_router.py | 7 | 6 | 1 | 86% |
| template_manager.py | 4 | 4 | 0 | 100% |
| template_evolution.py | 3 | 3 | 0 | 100% |
| todo_extractor.py | 2 | 2 | 0 | 100% |
| feedback_loop.py | 4 | 4 | 0 | 100% |
| decision_review.py | 6 | 6 | 0 | 100% |
| memory_lru.py | 6 | 6 | 0 | 100% |
| skill_discovery.py | 4 | 4 | 0 | 100% |
| record_agent_stat.py | 1 | 0 | 1 | 0% |
| prompt_loader.py | 4 | 0 | 4 | 0% |

### memory_db.py 未测试的公开函数

| 函数 | 说明 |
|------|------|
| `init_db()` | 仅在 test_embedding.py 中作为 setUp 调用，无独立测试 |
| `add_observation()` | 仅在 test_embedding/test_auto_memory 中间接使用，无直接参数边界测试 |
| `add_decision()` | 同上 |
| `add_session_summary()` | 完全未测试 |
| `count_by_type()` | 完全未测试 |
| `recent_by_days()` | 完全未测试 |
| `import_json()` | 完全未测试 |

### model_router.py 未测试的函数

| 函数 | 说明 |
|------|------|
| `load_stats()` | 内嵌测试中使用 mock_stats 绕过，真实文件加载+DB合并逻辑未测试 |

### orchestrator.py 未测试的方法

| 方法 | 说明 |
|------|------|
| `search_memory()` | 完全未测试 |

---

## 严重缺失（必须补充）

### 1. [record_agent_stat.py] 零测试覆盖 → 高风险

`record()` 函数直接读写 `agent-stats.json`，是多个模块的数据源。无任何测试。

**建议：** 创建 `test_record_agent_stat.py`，至少覆盖：
- 正常记录写入（by_model/by_task_type/recent 更新）
- recent 列表超过 50 条时的截断
- 文件不存在或 JSON 格式错误时的行为
- 并发写入安全性（当前实现无锁，存在竞态风险）

### 2. [prompt_loader.py] 零测试覆盖 → 中风险

`PromptLoader` 是 `template_manager.py` 的底层依赖（虽然 template_manager 直接用 yaml 加载，未实际使用 PromptLoader）。4 个公开方法（`load`, `get`, `keys`, `reload`）均无测试。

**建议：** 创建 `test_prompt_loader.py`，覆盖：
- 加载有效 YAML 目录
- 点号路径访问嵌套 key
- 变量替换 `{var}`
- 不存在的 key 抛 KeyError
- 非字符串值抛 TypeError
- 空目录 / 不存在目录的处理
- 单例模式验证

### 3. [memory_db.py] `add_session_summary()` / `count_by_type()` / `recent_by_days()` / `import_json()` 无测试

这些是数据写入和查询的核心函数，直接影响记忆系统的可靠性。

**建议：** 在 `test_context_search.py` 或新建 `test_memory_db.py` 中补充：
- `add_session_summary` 的参数验证和 importance_score 范围
- `count_by_type` 对无效表名的 ValueError
- `recent_by_days` 的时间过滤正确性
- `import_json` 的完整导入流程和格式校验

### 4. [record_agent_stat.py] 无错误处理

`record()` 函数假设 `agent-stats.json` 存在且格式正确，无 try/except。文件损坏或缺失时会直接崩溃，影响所有依赖它的模块（orchestrator、data_accumulator）。

**建议：** 添加防御性代码 + 对应测试。

---

## 边界测试分析

| 模块 | 空输入 | None | 超大输入 | 特殊字符 | 评价 |
|------|--------|------|----------|----------|------|
| auto_memory.py | ✅ | ✅ | ❌ | ❌ | 缺超长文本和特殊字符测试 |
| todo_extractor.py | ✅ | ❌ | ❌ | ❌ | 缺 None 输入和超长文本 |
| memory_db.py (search) | ✅ | ❌ | ✅ (max_chars) | ❌ | 缺 SQL 注入字符测试 |
| model_router.py | ✅ | ❌ | ❌ | ❌ | 缺 None 和超长描述 |
| data_accumulator.py | ✅ | ❌ | ❌ | ❌ | 缺含特殊字符的日志 |
| feedback_loop.py | ✅ | ❌ | ❌ | ❌ | 缺 None 参数和超大数据集 |
| template_manager.py | ✅ (invalid type) | ❌ | ❌ | ❌ | 缺 None task_type |

**关键缺失：**
- `todo_extractor.extract_todos_from_text(None)` — 当前会崩溃（`None.strip()` → AttributeError）
- `model_router.classify_task(None)` — 当前会崩溃（`None.lower()` → AttributeError）
- `memory_db.search()` 未测试 SQL 注入字符如 `'; DROP TABLE --`

---

## 错误路径分析

| 场景 | 是否测试 | 涉及模块 |
|------|----------|----------|
| DB 连接失败 | ✅ feedback_loop | feedback_loop 返回 None/[] |
| DB 文件不存在 | ✅ data_accumulator, skill_discovery | 返回空列表 |
| JSON 文件损坏 | ⚠️ 部分 | data_accumulator 测试了缺失文件，未测试损坏 JSON |
| 网络超时 (API) | ✅ test_todo_llm | extract_todos_with_llm 降级为空列表 |
| 网络超时 (Embedding) | ❌ | embed_text 的 urlopen timeout 未测试 |
| YAML 文件格式错误 | ❌ | template_manager 和 prompt_loader 未测试 |
| 文件权限不足 | ❌ | 所有文件写入操作均未测试 |
| agent-stats.json 不存在 | ❌ | record_agent_stat.record() 会直接崩溃 |

---

## Mock 质量评估

### ✅ 合理的 Mock

| 测试文件 | Mock 对象 | 评价 |
|----------|-----------|------|
| test_embedding.py | `embed_text` | 合理，避免真实 API 调用，同时保留了集成测试类 |
| test_todo_llm.py | `urllib.request.urlopen` | 合理，模拟了多种 LLM 响应格式 |
| test_orchestrator.py | `_record_task`, scheduled runners | 合理，隔离了外部模块依赖 |
| test_template_evolution.py | `_load_stats`, `DB_PATH` | 合理，使用临时 DB + mock stats |

### ⚠️ 需要注意的 Mock

| 测试文件 | 问题 |
|----------|------|
| test_context_search.py | **使用真实 DB**（`memory.db`），不是 Mock。测试结果依赖真实数据内容，不可重复。如果 DB 被清空，多个测试会失败。 |
| test_orchestrator.py TestOrchestratorMessage | `_handle_message` 被完全 mock，绕过了 todo_extractor 集成。虽然有一个 "integration-ish" 测试，但它 skipTest 如果导入失败。 |

### ❌ 过度 Mock 风险

无明显过度 Mock 的情况。大部分 Mock 都是为了隔离外部 API 或文件系统。

---

## 测试隔离分析

### ❌ 已知问题：test_embedding.py 环境变量污染

`test_embedding.py` 在模块级别修改 `os.environ["SELF_EVOLUTION_DB"]` 并 `importlib.reload(memory_db)`。`tearDownModule` 尝试恢复，但：

1. 如果 `test_embedding.py` 和 `test_context_search.py` 在同一进程中运行（如 `pytest`），执行顺序会影响结果
2. `test_context_search.py` 的 `setUpModule` 也修改同一环境变量
3. 两个文件都 `importlib.reload(memory_db)`，可能导致模块状态不一致

**影响：** 单独运行每个测试文件没问题，但 `pytest` 一起运行时可能出现 DB 路径混乱。

**建议：** 
- 统一使用 `unittest.mock.patch.dict(os.environ, ...)` 作为上下文管理器
- 或为每个测试类使用独立的 `patch.object(memory_db, 'DB_PATH', ...)`

### ⚠️ test_auto_memory.py 的 DB 隔离

`test_auto_memory.py` 的 `TestAutoSave` 类在 `setUp` 中修改 `os.environ["SELF_EVOLUTION_DB"]` 并 reload memory_db。`tearDown` 中 pop 环境变量但不 reload。如果后续测试依赖 memory_db 的默认 DB_PATH，会出问题。

### ⚠️ test_context_search.py 依赖真实数据

`TestRealDatabase` 类直接依赖真实 `memory.db` 的内容。这不是单元测试，而是冒烟测试。如果数据库为空或被重建，测试会失败。

---

## 集成测试分析

| 集成场景 | 是否覆盖 | 说明 |
|----------|----------|------|
| orchestrator → feedback_loop | ⚠️ Mock | on_agent_completed 被 mock，未真实调用 feedback_loop |
| orchestrator → model_router | ✅ | recommend_model 有真实调用测试 |
| orchestrator → todo_extractor | ⚠️ | 有条件跳过的集成测试 |
| orchestrator → 所有 scheduled tasks | ❌ Mock | 全部 mock，无真实执行 |
| data_accumulator → agent-stats.json | ✅ | 使用临时文件测试 |
| data_accumulator → memory.db | ✅ | 使用临时 DB 测试 |
| auto_memory → memory_db | ✅ | 使用临时 DB 测试写入和去重 |
| template_evolution → memory.db | ✅ | 使用临时 DB 测试 |
| model_router → agent-stats.json + memory.db | ❌ | load_stats 的真实文件+DB合并未测试 |
| record_agent_stat → agent-stats.json | ❌ | 完全无测试 |
| prompt_loader → YAML 文件 | ❌ | 完全无测试 |

**关键缺失：** `orchestrator` 作为核心编排器，其 `_run_scheduled_tasks` 的端到端流程完全依赖 Mock，没有一个测试验证真实模块间的调用链。

---

## 回归风险分析

| 改动区域 | 风险等级 | 原因 | 建议补充的测试 |
|----------|----------|------|---------------|
| memory_db.py schema 变更 | 🔴 高 | FTS5 触发器、embeddings 表等，变更可能破坏搜索和语义功能 | 添加 schema migration 测试 |
| record_agent_stat.py | 🔴 高 | 零测试，任何改动都无保护网 | 补充完整测试 |
| feedback_loop.py DB schema | 🟡 中 | task_outcomes 表结构变更会影响 data_accumulator、template_evolution | 添加 schema 兼容性测试 |
| model_router.py MODELS/TASK_KEYWORDS | 🟡 中 | 修改模型配置或关键词会影响路由结果 | 已有较好覆盖 |
| orchestrator.py SCHEDULE | 🟡 中 | 添加/修改定时任务可能影响心跳行为 | 已有较好覆盖 |
| todo_extractor.py 正则模式 | 🟡 中 | 修改提取模式可能导致误提取或漏提取 | 已有较好覆盖 |
| prompt_loader.py | 🟢 低 | 当前未被其他模块实际使用 | 但仍应补充测试 |

---

## 测试可维护性

### 重复代码可抽取

1. **临时 DB 创建模式** — `test_template_evolution.py` 的 `_TempDBMixin` 是好的实践，但 `test_data_accumulator.py`、`test_auto_memory.py`、`test_embedding.py` 各自重复实现了类似的临时 DB 创建逻辑。建议抽取为共享 fixture。

2. **内嵌测试 vs 独立测试文件** — `feedback_loop.py`、`decision_review.py`、`memory_lru.py`、`skill_discovery.py` 的测试内嵌在源码中（`_run_tests` / `run_tests`）。这些测试：
   - 无法被 `pytest` 自动发现
   - 无法生成覆盖率报告
   - 无法与 CI 集成
   - 建议迁移为独立的 `test_*.py` 文件

3. **model_router.py 的测试风格** — `run_tests()` 使用自定义 assert 函数而非 unittest/pytest，与其他测试文件风格不一致。`test_task_classify.py` 也使用同样的自定义风格。建议统一为 unittest。

### 测试命名

大部分测试命名清晰，能从名称理解测试意图。`test_embedding.py` 的类名 `TestCosineSimlarity` 有拼写错误（应为 `Similarity`）。

---

## 亮点

1. **test_data_accumulator.py** — 覆盖全面（15+ 测试），包含检测函数、扫描、合并、回填、去重等完整链路，使用临时文件隔离良好。

2. **test_todo_extractor.py + test_todo_llm.py** — 测试设计优秀，覆盖了规则提取、LLM 兜底、置信度降级、错误处理、去重、边界情况。LLM 层的 Mock 设计合理，模拟了多种响应格式（正常 JSON、markdown fenced、think tags）。

3. **test_template_evolution.py** — `_TempDBMixin` 模式值得推广，干净地隔离了 DB 依赖。每个失败原因类型都有对应的建议测试。

4. **test_embedding.py** — 分层设计好：纯单元测试（cosine similarity、pack/unpack）不需要任何外部依赖，Mock 测试隔离 API，集成测试可选运行。

5. **feedback_loop.py / decision_review.py / memory_lru.py 的内嵌测试** — 虽然不是独立文件，但测试本身质量不错，覆盖了核心逻辑。

6. **test_orchestrator.py** — 对 EventBus 的测试非常完整，包括多 handler、异常捕获、kwargs 传递等。Scheduler 的持久化和状态保留测试也很到位。

---

## 总结优先级

| 优先级 | 行动项 |
|--------|--------|
| P0 | 为 `record_agent_stat.py` 创建独立测试文件 |
| P0 | 为 `prompt_loader.py` 创建独立测试文件 |
| P1 | 补充 `memory_db.py` 中 `add_session_summary`、`count_by_type`、`recent_by_days`、`import_json` 的测试 |
| P1 | 修复 test_embedding / test_context_search 的环境变量污染问题 |
| P1 | 将 feedback_loop / decision_review / memory_lru / skill_discovery 的内嵌测试迁移为独立 test_*.py |
| P2 | 补充 None 输入边界测试（todo_extractor、model_router） |
| P2 | 补充 SQL 注入字符测试（memory_db.search） |
| P2 | 添加 orchestrator 端到端集成测试（至少一条真实调用链） |
| P3 | 统一测试风格为 unittest（model_router.run_tests、test_task_classify.py） |
| P3 | 抽取共享的临时 DB fixture |
| P3 | 修复 `TestCosineSimlarity` 拼写错误 |
