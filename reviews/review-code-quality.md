# 代码质量审查报告

**审查日期:** 2026-03-19
**审查范围:** `/root/.openclaw/workspace/memory/structured/` 下 14 个非 test_ 的 .py 文件
**审查员:** Senior Code Reviewer (AI)

---

## 总体评分（1-10）

- 可读性: 7/10
- 错误处理: 6/10
- 代码复用: 5/10
- 最佳实践: 6/10

---

## 必须修复

### 1. [memory_db.py] API Key 硬编码在源码中
- **行:** `SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "sk-ruyxdchpuehfctomvgncmvqvcvooddwxrxzvqdkawybgfhmq")`
- **问题:** API Key 作为默认值硬编码在源码中，存在严重安全隐患。如果代码被提交到公开仓库，密钥将泄露。
- **修复建议:** 移除默认值，改为 `os.environ.get("SILICONFLOW_API_KEY", "")` 并在调用时检查是否为空，为空则抛出明确错误。

### 2. [todo_extractor.py] API Key 硬编码在源码中
- **行:** `api_key = os.environ.get("MINIMAX_API_KEY", "sk-cp-u1k_OwlMj4mK0zm_Xq46unCO0Bu-AKwZ71aVhiypE5CQPXTZSoNrw4s_P0utnrVEM7y5JH7TZmfXa3B2XA_EotgWhMFknR-430MMZ2J18dbvf91BlNxomEM")`
- **问题:** 同上，MiniMax API Key 硬编码。
- **修复建议:** 同上，移除默认值。

### 3. [record_agent_stat.py] 无任何错误处理
- **问题:** `record()` 函数中 `open(STATS_PATH)` 和 `json.load(f)` 均无 try/except。文件不存在或 JSON 损坏时会直接崩溃，且不会给调用方有意义的错误信息。
- **修复建议:** 添加 FileNotFoundError 和 json.JSONDecodeError 处理，文件不存在时自动初始化默认结构。

### 4. [record_agent_stat.py] 写入文件无原子性保护
- **问题:** 直接 `open(STATS_PATH, "w")` 写入。如果写入过程中崩溃，文件会被截断为空，丢失所有历史数据。
- **修复建议:** 先写入临时文件，再 `os.replace()` 原子替换。

### 5. [memory_db.py] DB 连接未使用 context manager
- **问题:** `add_observation()`、`add_decision()`、`add_session_summary()` 等函数中 `db = get_db()` 后手动 `db.close()`，但如果中间抛异常，连接不会被关闭。
- **修复建议:** 使用 `with contextlib.closing(get_db()) as db:` 或将 `get_db()` 改为 context manager。

### 6. [memory_db.py:add_observation] `last_insert_rowid()` 在 commit 后调用不可靠
- **问题:** `db.commit()` 后再调用 `db.execute("SELECT last_insert_rowid()")` 在并发场景下可能返回错误的 ID。
- **修复建议:** 使用 `cursor.lastrowid`：`cur = db.execute("INSERT ..."); rid = cur.lastrowid`。`add_decision()` 同样存在此问题。

### 7. [decision_review.py] DB 连接在异常时可能泄漏
- **问题:** `get_unreviewed_decisions()`、`record_review()`、`get_review_history()` 等函数中 `conn.close()` 不在 finally 块中。如果 SQL 执行抛异常，连接不会被关闭。
- **修复建议:** 使用 try/finally 或 context manager 确保连接关闭。

### 8. [data_accumulator.py] 裸 `except Exception` 吞掉所有错误
- **行:** `_load_task_outcomes()` 中 `except Exception: pass`
- **问题:** 数据库读取失败时静默忽略，不记录任何日志，调试时无法发现问题。
- **修复建议:** 至少 `print(f"[WARN] ...: {e}", file=sys.stderr)` 或使用 logging。

---

## 建议改进

### 代码重复（跨文件）

#### 9. DB 连接模式重复
- **涉及文件:** `memory_db.py`、`feedback_loop.py`、`decision_review.py`、`memory_lru.py`、`template_evolution.py`、`data_accumulator.py`、`skill_discovery.py`
- **问题:** 每个文件都有自己的 `_get_conn()` / `_get_db()` / `get_db()` 函数，逻辑几乎相同（连接同一个 `memory.db`，设置 `row_factory`）。共 7 处重复。
- **改进建议:** 抽取公共模块 `db_utils.py`，提供统一的 `get_connection(db_path=None)` 函数和 context manager。

#### 10. 路径常量重复定义
- **涉及文件:** `data_accumulator.py`、`model_router.py`、`record_agent_stat.py`、`template_evolution.py`、`skill_discovery.py`
- **问题:** `STATS_PATH`（agent-stats.json 路径）在 5 个文件中重复定义；`DB_PATH`（memory.db 路径）在 7 个文件中重复定义。
- **改进建议:** 抽取 `config.py` 或 `paths.py` 统一管理路径常量。

#### 11. agent-stats.json 读写逻辑重复
- **涉及文件:** `record_agent_stat.py`、`data_accumulator.py`、`model_router.py`
- **问题:** 三个文件都有加载和解析 agent-stats.json 的逻辑，且结构假设不一致。
- **改进建议:** 抽取 `stats_store.py` 提供 `load_stats()` / `save_stats()` 统一接口。

### 函数设计

#### 12. [memory_db.py:search_with_context] 函数过长（~60 行）
- **问题:** keyword 模式的 `search_with_context` 内联了分组、截断、格式化逻辑，与 `_search_with_context_hybrid` 和 `_search_with_context_semantic` 有大量重复。
- **改进建议:** keyword 模式也应使用 `_build_context_from_entries()` 辅助函数，消除重复。

#### 13. [memory_db.py:search_with_metadata] 调用 search_with_context 两次
- **问题:** 为了判断 `truncated`，先调用一次正常的 `search_with_context`，再调用一次 `max_chars=999999` 的版本。这导致双倍的搜索开销。
- **改进建议:** 让 `search_with_context` 返回元数据（是否截断），或在内部记录截断状态。

#### 14. [orchestrator.py:_record_task] 延迟导入在每次调用时执行
- **问题:** `from record_agent_stat import record` 和 `from feedback_loop import record_task_outcome` 在每次任务完成时都执行 import。
- **改进建议:** 延迟导入本身没问题（避免循环依赖），但可以在 `__init__` 中做一次性导入并缓存引用。

#### 15. [model_router.py:cost_report] 查找最便宜/最贵模型的方式不优雅
- **行:** `cheapest_name = [k for k, v in MODELS.items() if v is cheapest][0]`
- **问题:** 先 `min(MODELS.values())` 再反查 key，用 `is` 比较 dict 对象。虽然能工作，但不直观。
- **改进建议:** 直接 `min(MODELS.items(), key=lambda x: x[1]["cost_per_task"])` 一步获取 (name, config)。

### 类型注解与 Docstring

#### 16. [record_agent_stat.py] 完全缺少类型注解和 docstring
- **问题:** `record()` 函数无类型注解、无 docstring，参数含义需要看代码才能理解。
- **改进建议:** 添加类型注解和 docstring。

#### 17. [prompt_loader.py] 单例模式实现有隐患
- **问题:** `_prompts` 是类变量 `dict`，所有实例共享。`reload()` 清空后影响所有引用。且单例模式在测试中难以隔离。
- **改进建议:** 将 `_prompts` 改为实例变量（在 `__init__` 中初始化），或提供 `reset()` 方法用于测试。

#### 18. [template_manager.py] VALID_TYPES 硬编码
- **问题:** 有效模板类型硬编码为 set，新增模板类型需要同时修改 YAML 文件和 Python 代码。
- **改进建议:** 动态扫描 `TEMPLATES_DIR` 下的 `.yaml` 文件名来确定有效类型。

### 魔法数字

#### 19. [feedback_loop.py] 多处魔法数字
- `0.7`（成功率阈值）、`0.3`（gap 出现频率阈值）、`10`（top patterns 数量）、`5`（recent gaps 数量）
- **改进建议:** 提取为模块级常量，如 `SUCCESS_RATE_THRESHOLD = 0.7`。

#### 20. [auto_memory.py] `MIN_CONTENT_LENGTH = 10` 和 `threshold=0.7`
- 已经提取为常量，但 `_make_title` 中的 `max_len=20` 和 `_get_recent_titles` 中的 `days=7` 也应考虑提取。

#### 21. [memory_lru.py] `days_unused=30`、`limit=50`、`days=7`
- **改进建议:** 提取为模块级常量 `DEFAULT_COLD_DAYS`、`DEFAULT_COLD_LIMIT`、`RECENT_CUTOFF_DAYS`。

#### 22. [model_router.py] `FUZZY_THRESHOLD = 0.3` 和 `calculate_success_rate` 中的 `3`（最小样本数）
- `FUZZY_THRESHOLD` 已提取，但 `3` 应提取为 `MIN_SAMPLES = 3`。

### 日志和调试

#### 23. [memory_db.py:init_db] 使用 print 而非 logging
- **行:** `print(f"Database initialized at {DB_PATH}")`
- **问题:** 生产代码中使用 print 输出状态信息。当作为库被导入时，这些 print 会污染 stdout。
- **改进建议:** 全项目统一使用 `logging` 模块。涉及文件：`memory_db.py`、`feedback_loop.py`、`record_agent_stat.py`、`prompt_loader.py`。

#### 24. [data_accumulator.py] CLI 输出使用 emoji
- **问题:** `✅`/`❌` 在某些终端或日志系统中可能显示异常。
- **改进建议:** 提供 `--no-emoji` 选项或在非 TTY 环境下自动降级。

### 资源管理

#### 25. [memory_lru.py] ensure_columns 在每次操作时都被调用
- **问题:** `record_access()`、`get_hot_memories()`、`get_cold_memories()`、`memory_heatmap()` 每次都调用 `ensure_columns()`，每次都打开一个新连接执行 ALTER TABLE。
- **改进建议:** 使用模块级标志位 `_columns_ensured = False`，只在首次调用时执行。

#### 26. [memory_lru.py] ensure_columns 内部打开连接但外部函数也打开连接
- **问题:** `record_access()` 先调用 `ensure_columns(db_path)` 打开一次连接，然后自己又 `_get_db(db_path)` 打开第二次。一次操作两次连接。
- **改进建议:** 将 `ensure_columns` 改为接受已有连接，或合并到 `_get_db` 中。

### Python 最佳实践

#### 27. [memory_db.py] `search()` 函数参数名 `type` 遮蔽内置函数
- **行:** `def search(query=None, type=None, limit=20)`
- **问题:** `type` 是 Python 内置函数名，作为参数名会遮蔽它。
- **改进建议:** 改为 `obs_type` 或 `type_filter`。

#### 28. [memory_db.py] `add_observation()` 参数名 `type` 同样遮蔽内置函数
- **改进建议:** 同上。

#### 29. [orchestrator.py] `__import__` 用于模块健康检查
- **行:** `module_checks = {"memory_db": lambda: __import__("memory_db"), ...}`
- **问题:** `__import__` 是低级 API，且依赖 `sys.path` 包含当前目录。
- **改进建议:** 使用 `importlib.import_module()`。

#### 30. [data_accumulator.py] `_detect_success` 返回 `bool | None` 但类型注解不完整
- **行:** `def _detect_success(text: str) -> bool | None:`
- **问题:** 类型注解正确，但调用方 `_parse_log_block` 中 `if success is None: continue` 后直接将 `success` 放入 dict，此时 `success` 的类型已被收窄为 `bool`，这是正确的。但 `_parse_structured_entries` 中 `success = "失败" not in result_text` 直接赋值 bool，绕过了 `_detect_success`，逻辑不一致。
- **改进建议:** 统一使用 `_detect_success` 进行成功/失败判断。

#### 31. [feedback_loop.py] SQL 字符串拼接
- **行:** `f"SELECT * FROM task_outcomes{where} ORDER BY timestamp DESC LIMIT ?"`
- **问题:** 虽然 WHERE 子句使用了参数化查询，但 `{where}` 是字符串拼接。此处安全（因为 where 来自内部逻辑），但风格上不够一致。
- **改进建议:** 可接受，但建议添加注释说明 where 子句来源可信。

#### 32. [memory_lru.py / memory_db.py] SQL 中使用 f-string 拼接表名
- **行:** `f"UPDATE {table} SET access_count = ..."`
- **问题:** 表名通过 f-string 拼接进 SQL。虽然有 `SUPPORTED_TABLES` 白名单验证，但这是 SQL 注入的常见模式。
- **改进建议:** 当前的白名单验证是正确的防护，建议添加注释说明已做验证。

---

## 代码亮点

1. **feedback_loop.py 的设计很优秀** — 完整的 CLI + 测试 + 清晰的函数职责分离。`_compute_gap()` 的差异分析和 `generate_template_improvements()` 的规则引擎设计思路清晰。错误处理使用 try/finally 确保连接关闭，是所有文件中做得最好的。

2. **memory_db.py 的双路径搜索（FTS5 + LIKE）** — `_dual_search()` 巧妙地结合了 FTS5 全文索引和 LIKE 模糊匹配，解决了 CJK 内容的搜索问题。去重逻辑（seen set）简洁有效。

3. **model_router.py 的分层分类策略** — `classify_task()` 采用关键词精确匹配 → 模糊字符重叠 → 兜底的三层策略，零 LLM 成本实现了不错的分类效果。测试覆盖全面，mock 数据设计合理。

4. **auto_memory.py 的去重机制** — 提取时的 `seen_narratives` 集合去重 + 保存时的 `_is_duplicate()` 相似度去重（SequenceMatcher），两层防护避免重复记忆。

5. **orchestrator.py 的事件总线设计** — `EventBus` + `Scheduler` + `Orchestrator` 三层架构清晰，松耦合。Scheduler 基于 heartbeat-state.json 的持久化调度简单可靠。

6. **todo_extractor.py 的规则引擎** — 三级置信度（承诺 0.8-0.9 / 时间 0.7-0.8 / 计划 0.6-0.7）+ 排除模式 + LLM 兜底的分层设计很实用。

7. **整体项目零外部依赖（除 pyyaml）** — 纯 stdlib + SQLite 的技术选型非常适合 Agent 场景，部署简单、可靠性高。

8. **所有模块都提供 CLI 入口** — 每个 .py 文件都可以独立运行和测试，便于调试和验证。

---

## 优先级总结

| 优先级 | 数量 | 说明 |
|--------|------|------|
| 🔴 必须修复 | 8 项 | API Key 泄露（2）、无错误处理（1）、无原子写入（1）、DB 连接泄漏（3）、静默吞错误（1） |
| 🟡 建议改进 | 24 项 | 代码重复（3）、函数设计（4）、类型注解（3）、魔法数字（4）、日志（2）、资源管理（2）、最佳实践（6） |

**最高优先级行动项：**
1. 立即移除两处硬编码的 API Key
2. 为 `record_agent_stat.py` 添加错误处理和原子写入
3. 抽取公共 `db_utils.py` 消除 7 处 DB 连接重复代码
4. 统一使用 try/finally 或 context manager 管理 DB 连接
