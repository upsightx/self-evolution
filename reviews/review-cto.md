# CTO 架构审查报告

## 架构评分（1-10）
- 模块化: 7/10
- 扩展性: 6/10
- 可维护性: 6/10
- 性能: 5/10
- 整体: 6/10

## 架构概述

系统由 14 个 Python 模块 + 6 个 YAML 模板 + 2 个 Markdown 文档组成，围绕一个 SQLite 数据库（memory.db）构建了一套 AI Agent 自我进化框架。三层架构大致为：

- **记忆层**：memory_db.py（核心存储）、memory_lru.py（冷热分析）、auto_memory.py（自动提取）
- **策略层**：model_router.py（模型路由）、feedback_loop.py（反馈分析）、template_evolution.py（模板进化）、decision_review.py（决策回顾）、skill_discovery.py（能力缺口）、data_accumulator.py（数据积累）
- **执行层**：orchestrator.py（编排器）、template_manager.py（模板管理）、prompt_loader.py（Prompt加载）、record_agent_stat.py（统计记录）、todo_extractor.py（待办提取）

## 架构优势

- **零外部依赖原则**：除 PyYAML 外，全部使用 Python stdlib + SQLite，部署极简，无依赖地狱风险。这是一个非常正确的架构决策。
- **数据库设计合理**：memory.db 使用 FTS5 全文索引 + LIKE 双路搜索，对 CJK 内容的处理考虑周到。WAL 模式保证并发读写性能。
- **关注点分离清晰**：每个模块职责单一，文件命名直观，新人看文件名就能猜到功能。
- **CLI 优先设计**：每个模块都有独立 CLI 入口，方便调试和手动操作，这对 Agent 系统尤其重要。
- **内置测试**：多数模块内嵌了测试函数（使用临时数据库），虽然不是标准 pytest，但保证了基本可测试性。
- **EventBus + Scheduler 模式**：orchestrator.py 的事件驱动 + 心跳调度设计简洁有效，避免了复杂的异步框架。
- **混合搜索策略**：memory_db.py 支持 keyword/semantic/hybrid 三种搜索模式，且 hybrid 模式的加权融合设计合理（0.4 keyword + 0.6 semantic）。
- **模板系统**：YAML 模板 + TemplateManager 的 system/constraints/user 三段式拼接，结构清晰，易于扩展新任务类型。

## 架构风险

### 严重（P0）

- **[API Key 硬编码]** memory_db.py 第 280 行硬编码了 SiliconFlow API Key，todo_extractor.py 硬编码了 MiniMax API Key。一旦代码泄露（如开源），密钥立即暴露。→ **建议**：所有 API Key 必须从环境变量读取，硬编码值仅作为开发占位符并在 .env.example 中说明。

- **[Embedding 全量扫描]** semantic_search() 每次查询都从数据库加载全部 embedding 到内存，逐一计算余弦相似度。当记录数超过 1 万条时，延迟将显著增加（每次查询 O(N) 次向量运算 + O(N) 次 DB 读取）。→ **建议**：短期用 SQLite 内存缓存 + 批量加载；中期引入 FAISS 或 hnswlib 做 ANN 索引（仍可零服务依赖，纯 Python 包）；或使用 sqlite-vss 扩展。

- **[数据一致性风险]** 三个数据源（agent-stats.json、memory.db task_outcomes 表、memory/*.md 日志）记录同一事件，但没有事务保证。orchestrator._record_task() 分别调用 record_agent_stat 和 feedback_loop，任一失败不会回滚另一个。data_accumulator 的 merge 逻辑用 (date, model, task_type, success) 做去重，粒度太粗——同一天同模型同类型的两次不同任务会被误判为重复。→ **建议**：统一为单一数据源（memory.db），agent-stats.json 改为 memory.db 的视图/缓存，消除双写问题。

### 高（P1）

- **[单点故障：memory.db]** 整个系统依赖单个 SQLite 文件。文件损坏 = 全部记忆丢失。没有备份策略，没有降级方案。→ **建议**：添加定期备份（WAL checkpoint + 文件复制）；关键操作加 try/except 降级到日志文件。

- **[record_agent_stat.py 无错误处理]** 直接 open/json.load/json.dump，文件不存在或 JSON 损坏会直接崩溃。作为高频调用的统计记录模块，这是不可接受的。→ **建议**：添加 try/except，文件不存在时自动初始化，JSON 损坏时从备份恢复或重建。

- **[模块间导入耦合]** orchestrator.py 使用延迟 import（函数内 `from xxx import yyy`），这避免了循环依赖但隐藏了依赖关系。多个模块各自硬编码 DB_PATH / STATS_PATH，路径不一致时会静默使用不同数据源。→ **建议**：引入统一的 config.py 管理所有路径常量；或使用依赖注入模式。

### 中（P2）

- **[model_router 模型列表硬编码]** MODELS 字典写死了 4 个模型（opus/minimax/glm5/sonnet），新增模型需要改代码。→ **建议**：从配置文件加载模型列表，或从 agent-stats.json 中自动发现。

- **[auto_memory.py 规则过于简单]** 纯正则匹配中文触发词（"发现了"、"决定了"等），误报率高（如"我发现你说得对"会被提取为 observation），漏报率也高（不匹配的表述方式被忽略）。→ **建议**：增加上下文窗口判断；或直接用 LLM 做提取（已有 todo_extractor 的 LLM 兜底模式可参考）。

- **[template_manager VALID_TYPES 硬编码]** 新增模板类型需要同时修改 YAML 文件和 Python 代码中的 VALID_TYPES 集合。→ **建议**：自动扫描 templates 目录下的 .yaml 文件名作为有效类型。

- **[feedback_loop 与 template_evolution 功能重叠]** 两个模块都做"分析失败模式 → 生成改进建议"，且都从 memory.db task_outcomes 表读数据。template_evolution 额外读 agent-stats.json。→ **建议**：合并为一个模块，或明确分工（feedback_loop 只做数据记录和模式分析，template_evolution 只做建议生成）。

## 技术债务清单

1. **API Key 硬编码**（P0）— memory_db.py L280, todo_extractor.py L148
2. **路径硬编码分散**（P1）— 至少 5 个模块各自定义 DB_PATH/STATS_PATH/MEMORY_DIR，值相同但不共享常量
3. **测试不标准**（P2）— 测试内嵌在模块中（`if __name__ == "__main__"` 或 `_run_tests()`），无法被 pytest 自动发现和运行
4. **类型注解不一致**（P2）— 部分模块用 `str | None`（Python 3.10+），部分用无注解，record_agent_stat.py 完全无注解
5. **record_agent_stat.py 代码质量**（P1）— 无错误处理、无类型注解、无文档字符串、硬编码路径、recent 数组上限 50 与 data_accumulator 的 100 不一致
6. **prompt_loader.py 与 template_manager.py 功能重叠**（P2）— 都是加载 YAML 模板，但接口不同。prompt_loader 是通用的点号路径访问，template_manager 是任务类型专用。实际只有 template_manager 被 orchestrator 使用
7. **skill_discovery.py SKILL_MAP 硬编码**（P2）— 关键词到技能的映射写死在代码中，无法动态更新
8. **data_accumulator.py 日志解析脆弱**（P2）— 依赖正则匹配 markdown 日志中的"子Agent"关键词和模型名，日志格式稍有变化就会失效
9. **memory_db.py 过于庞大**（P2）— 单文件 500+ 行，混合了数据库操作、搜索逻辑、embedding 管理、上下文构建、CLI，应拆分

## 演进建议

### 短期（1-2 周）

1. **消除 P0 风险**：API Key 移入环境变量；为 memory.db 添加每日自动备份
2. **统一配置管理**：创建 `config.py`，集中管理所有路径常量和配置项
3. **加固 record_agent_stat.py**：添加错误处理、文件初始化逻辑、统一 recent 上限
4. **统一数据源**：将 agent-stats.json 的写入改为从 memory.db 生成（单一写入源），消除双写一致性问题

### 中期（1-3 月）

5. **Embedding 索引优化**：引入 FAISS 或 sqlite-vss，将 semantic_search 从 O(N) 降到 O(log N)
6. **拆分 memory_db.py**：分为 db_core.py（连接/初始化）、search.py（搜索逻辑）、embedding.py（向量管理）、context.py（上下文构建）
7. **标准化测试**：将内嵌测试迁移到 tests/ 目录，使用 pytest，添加 CI
8. **合并重叠模块**：feedback_loop + template_evolution 合并；评估 prompt_loader 是否可以废弃
9. **模型配置外部化**：model_router 的 MODELS 和 DEFAULT_RECOMMENDATIONS 从 YAML/JSON 配置文件加载
10. **template_manager 自动发现**：扫描 templates/ 目录自动注册类型，消除 VALID_TYPES 硬编码

### 长期（3-6 月）

11. **多 Agent 协作支持**：当前架构是单 Agent 视角（一个 memory.db、一个 agent-stats.json）。多 Agent 场景需要：共享记忆层（可能需要从 SQLite 迁移到 PostgreSQL 或使用文件锁）、Agent 间消息传递、冲突解决策略
12. **开源准备**：移除所有硬编码密钥和个人路径；添加 setup.py/pyproject.toml；编写 README 和 API 文档；添加 LICENSE；CI/CD pipeline
13. **规模扩展**：当记忆条目超过 10 万时，SQLite 单文件可能成为瓶颈。评估分库分表策略或迁移到嵌入式数据库（如 DuckDB 用于分析查询）
14. **可观测性**：添加结构化日志（而非 print）、metrics 收集、健康检查端点，为生产部署做准备

## 总结

这是一个设计思路清晰、实用主义导向的系统。零依赖原则和 CLI 优先设计是正确的架构决策，使得系统在 Agent 环境中易于部署和调试。主要风险集中在数据一致性（多数据源双写）、性能（embedding 全量扫描）和安全（API Key 硬编码）三个方面。短期内通过统一配置和数据源即可显著降低风险。中长期需要关注模块拆分和规模化能力。

整体而言，作为一个 AI Agent 自我进化的原型系统，当前架构足够支撑单 Agent 场景下的迭代开发。但如果要走向多 Agent 协作或开源发布，需要在数据层和配置管理上做较大重构。
