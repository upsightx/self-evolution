# 安全审查报告

审查时间: 2026-03-19
审查范围: /root/.openclaw/workspace/memory/structured/ 下 14 个非 test_ 的 .py 文件

---

## 严重（必须修复）

- [memory_db.py:~行330] **API Key 硬编码** — `SILICONFLOW_API_KEY` 的默认值直接硬编码为 `"sk-ruyxdchpuehfctomvgncmvqvcvooddwxrxzvqdkawybgfhmq"`。任何能读取源码的人都可获取此密钥。环境变量 fallback 不应包含真实密钥。
  → 修复建议: 移除硬编码默认值，改为 `os.environ.get("SILICONFLOW_API_KEY", "")` 并在缺失时抛出明确错误或跳过 embedding 功能。

- [todo_extractor.py:~行130] **API Key 硬编码** — `MINIMAX_API_KEY` 的默认值直接硬编码了完整的 API Key `"sk-cp-u1k_OwlMj4mK0zm_..."` (约 80 字符)。与上条同理，泄露风险极高。
  → 修复建议: 同上，移除硬编码默认值，改为 `os.environ.get("MINIMAX_API_KEY", "")` 并在缺失时优雅降级。

## 中等（建议修复）

- [memory_lru.py:~行40-46] **SQL 表名拼接（受限风险）** — `record_access()` 中使用 f-string 拼接表名 `f"UPDATE {table} SET ..."`, 虽然有 `SUPPORTED_TABLES` 白名单校验在前，但这种模式容易在后续维护中被绕过。`get_hot_memories()`、`get_cold_memories()`、`memory_heatmap()` 中也存在同样的 f-string 表名拼接。
  → 修复建议: 当前白名单校验已提供保护，但建议添加 `assert table in SUPPORTED_TABLES` 作为防御性编程，或将表名映射为常量避免直接拼接。

- [memory_db.py:~行215] **SQL 表名拼接（受限风险）** — `count_by_type()` 函数接受 `table` 参数并用 f-string 拼接 SQL，虽有 `valid_tables` 白名单校验，但模式同上。
  → 修复建议: 同上，保持白名单校验，考虑用字典映射替代 f-string。

- [memory_db.py:~行370] **SSRF 风险** — `embed_text()` 使用 `urllib.request.urlopen()` 调用外部 API (`SILICONFLOW_ENDPOINT`)。虽然 endpoint 是硬编码常量，但如果未来改为可配置，则存在 SSRF 风险。当前 `timeout=60` 设置合理。
  → 修复建议: 确保 endpoint URL 始终为硬编码常量或经过严格校验，不接受用户输入。

- [todo_extractor.py:~行155] **SSRF 风险** — `extract_todos_with_llm()` 使用 `urllib.request.urlopen()` 调用 MiniMax API。endpoint 为硬编码常量 `"https://api.minimaxi.com/v1/chat/completions"`，当前风险可控，`timeout=10` 设置合理。
  → 修复建议: 同上，确保 URL 不可被外部输入覆盖。

- [auto_memory.py:~行120-130] **路径遍历（受限风险）** — `auto_save()` 的 `--from-file` 参数直接用 `open(args.from_file)` 读取文件，无路径校验。攻击者可通过 CLI 参数读取任意文件（如 `/etc/shadow`）。
  → 修复建议: 由于这是本地 CLI 工具，风险较低，但建议限制读取路径在 workspace 目录内，或至少记录警告。

- [data_accumulator.py:~行230] **文件写入无原子性保护** — `backfill_stats()` 直接 `open(stats_path, "w")` 写入 JSON。如果写入过程中崩溃，文件会被截断损坏。
  → 修复建议: 使用 "写入临时文件 + rename" 的原子写入模式：先写入 `stats_path.tmp`，再 `os.rename()` 覆盖。

- [record_agent_stat.py:全文件] **文件写入无原子性保护** — 同上，`record()` 函数直接 `open(STATS_PATH, "w")` 写入。
  → 修复建议: 同上，使用原子写入模式。

- [orchestrator.py:~行110] **Scheduler 文件写入无原子性保护** — `Scheduler._save()` 直接写入 `heartbeat-state.json`，存在同样的截断风险。
  → 修复建议: 同上。

## 低（可以改进）

- [memory_db.py:全文件] **数据库连接未使用 context manager** — `get_db()` 返回的连接在多处手动 `db.close()`，如果中间抛异常则连接泄漏。`add_observation()`、`add_decision()` 等函数均存在此问题。
  → 修复建议: 使用 `with` 语句或 contextlib 确保连接始终关闭。

- [feedback_loop.py:全文件] **数据库连接管理改进** — `_get_conn()` 返回连接后在各函数中用 `try/finally` 关闭，这比 memory_db.py 好，但建议统一使用 context manager 模式。
  → 修复建议: 将 `_get_conn()` 改为 context manager。

- [data_accumulator.py:~行170] **异常静默吞没** — `_load_task_outcomes()` 中 `except Exception: pass` 会吞掉所有异常（包括权限错误、磁盘满等），导致问题难以排查。
  → 修复建议: 至少记录 warning 日志，或缩小 except 范围为 `sqlite3.Error`。

- [model_router.py:~行95] **异常静默吞没** — `load_stats()` 中 DB 读取部分 `except Exception: pass`，同上。
  → 修复建议: 同上。

- [skill_discovery.py:~行75] **异常静默吞没** — `_load_bugfix_observations()` 中 `except Exception: return []`，同上。
  → 修复建议: 同上。

- [template_evolution.py:~行30,40] **异常静默吞没** — `_load_stats()` 和 `_get_db()` 中异常被静默处理。
  → 修复建议: 同上。

- [record_agent_stat.py:全文件] **无错误处理** — `record()` 函数没有任何 try/except，如果 `agent-stats.json` 不存在、格式错误或磁盘满，会直接抛出未处理异常。
  → 修复建议: 添加基本的错误处理和降级逻辑。

- [prompt_loader.py:~行25] **YAML 安全加载** — 使用了 `yaml.safe_load()` 而非 `yaml.load()`，这是正确的做法。但 `template_manager.py` 中也使用了 `yaml.safe_load()`，同样正确。
  → 无需修复，仅记录确认。

- [memory_db.py:~行400] **Embedding 全表扫描** — `semantic_search()` 每次查询都从 `embeddings` 表加载所有向量到内存做余弦相似度计算。数据量大时性能会急剧下降。
  → 修复建议: 当前数据量小可接受，未来考虑使用 ANN 索引（如 sqlite-vss）或限制扫描范围。

- [data_accumulator.py:~行50-60] **日志文件读取无大小限制** — `scan_daily_logs()` 用 `f.read_text()` 一次性读取整个 .md 文件，如果某个日志文件异常大（如被恶意写入），可能导致内存耗尽。
  → 修复建议: 添加文件大小检查，超过阈值（如 10MB）则跳过。

- [decision_review.py:全文件] **无显著安全问题** — 使用参数化查询，有输入校验（`VALID_OUTCOMES`），连接管理合理。
  → 无需修复。

## 通过项

- **SQL 注入防护**: 所有文件中的 SQL 查询均使用参数化查询（`?` 占位符），未发现字符串拼接构造 SQL 值的情况。表名拼接虽存在但均有白名单校验。
- **YAML 安全加载**: `prompt_loader.py` 和 `template_manager.py` 均使用 `yaml.safe_load()` 而非不安全的 `yaml.load()`。
- **SQLite WAL 模式**: `memory_db.py` 和 `memory_lru.py` 启用了 WAL 模式，提升了并发读写安全性。
- **输入校验**: `decision_review.py` 对 `outcome` 参数有白名单校验；`memory_lru.py` 对 `table` 参数有白名单校验；`memory_db.py` 的 `count_by_type()` 和 `recent_by_days()` 对 `table` 参数有白名单校验；`template_manager.py` 对 `task_type` 有 `VALID_TYPES` 校验。
- **外部 API 超时设置**: `memory_db.py` 的 `embed_text()` 设置了 `timeout=60`；`todo_extractor.py` 的 LLM 调用设置了 `timeout=10`。
- **FTS5 使用安全**: `memory_db.py` 的全文搜索使用 FTS5 MATCH 语法，通过 try/except 处理了无效查询。
- **无 `eval()`/`exec()` 调用**: 所有文件均未使用动态代码执行。
- **无 `subprocess` 调用**: 所有文件均未调用外部命令，无命令注入风险。
- **JSON 反序列化安全**: 所有文件使用 `json.load()`/`json.loads()` 而非 `eval()`。
- **依赖最小化**: 大部分模块仅依赖 stdlib + sqlite3，攻击面小。`prompt_loader.py` 和 `template_manager.py` 依赖 `pyyaml`，使用了安全加载。
- **竞态条件（部分通过）**: SQLite WAL 模式提供了基本的并发保护。但文件写入（agent-stats.json、heartbeat-state.json）缺乏原子性保护（已在中等问题中列出）。
