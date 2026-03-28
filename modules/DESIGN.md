# Self-Evolution Module — 设计规范

所有模块必须遵守以下约定。新增或修改代码前先读这个文件。

## 1. 路径与配置

```python
# 统一使用 db_common
from db_common import DB_PATH, get_db

# 所有可配置项集中在 config.py（如果需要）
# 不要在模块内硬编码路径、阈值、模型名
```

- DB 路径：统一用 `db_common.DB_PATH`
- Memory 目录：`Path(__file__).resolve().parent.parent`（即 `memory/`）
- Workspace 目录：`Path(__file__).resolve().parent.parent.parent`（即 workspace root）
- 函数参数中的 `db_path` 仅用于测试覆盖，生产代码不传

## 2. 函数签名约定

```python
# 查询类：返回 list[dict]
def search(...) -> list[dict]: ...

# 写入类：返回记录 ID (int) 或 None
def add_xxx(...) -> int | None: ...

# 分析类：返回 dict，包含明确的 key
def analyze_xxx(...) -> dict: ...

# 报告类：返回 str (markdown)
def generate_report(...) -> str: ...

# 布尔操作：返回 bool
def record_access(...) -> bool: ...
```

## 3. 错误处理

```python
# 原则：查询操作不 crash，返回空值；写入操作可以抛异常

# 查询：失败返回空
def search(query):
    try:
        ...
    except Exception:
        return []

# 写入：失败返回 None，打印警告
def add_observation(...):
    try:
        ...
        return row_id
    except Exception as e:
        print(f"Warning: {e}")
        return None

# 绝不静默吞掉写入错误
```

## 4. 日志

```python
# 统一用 print，前缀标识来源
print(f"[memory_db] Initialized at {DB_PATH}")
print(f"[feedback_loop] Warning: no data for {task_type}")

# CLI 输出用 emoji 前缀
print(f"✅ Done")
print(f"⚠️  Warning")
print(f"❌ Error")
```

## 5. 测试

- 测试文件统一放 `tests/test_*.py`
- 生产代码不包含测试函数
- 每个测试文件开头：`sys.path.insert(0, str(Path(__file__).parent.parent))`
- 测试用临时 DB：`tempfile.NamedTemporaryFile(suffix=".db")`
- 需要外部 API 的测试用 `@unittest.skipUnless(os.environ.get("KEY"), "reason")`

## 6. 导入规则

```python
# 标准库在前，本地模块在后，之间空一行
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from db_common import DB_PATH, get_db
```

- 跨模块导入用延迟导入（在函数内 import），避免循环依赖
- 不要 `from module import *`

## 7. CLI 约定

每个模块的 CLI 入口统一格式：

```python
if __name__ == "__main__":
    cli()  # 或 main()
```

子命令风格：`python3 module.py <command> [args]`

## 8. 数据表约定

| 表名 | 用途 | 主键 |
|------|------|------|
| observations | 观察/发现/教训 | id (autoincrement) |
| decisions | 决策+被拒方案 | id (autoincrement) |
| session_summaries | 会话摘要 | id (autoincrement) |
| task_outcomes | 任务执行结果 | id (autoincrement) |
| embeddings | 向量索引 | id, UNIQUE(source_table, source_id) |
| decision_reviews | 决策回顾 | id, FK→decisions |
| experiments | 进化实验（A/B对比） | id (autoincrement) |

新增表前先确认是否能复用现有表。

## 9. 模块职责边界

| 模块 | 职责 | 不做什么 |
|------|------|----------|
| memory_db | CRUD + 搜索 | 不做分析、不做推荐 |
| memory_embedding | 向量化 + 语义搜索 | 不做 CRUD |
| memory_context | 构建上下文字符串 | 不做写入 |
| feedback_loop | 任务反馈分析 + 改进建议 | 不做模型推荐 |
| model_router | 模型推荐 + 路由表 | 不做任务记录 |
| agent_dispatch | 串联闭环（prepare/complete） | 不做具体分析 |
| orchestrator | 调度 + 状态面板 | 不做具体业务逻辑 |
| evolution_executor | 实验生命周期管理（创建/激活/记录/结论） | 不做因果判断、不自动改代码 |
| causal_validator | 实验归因验证（有效/存疑/无效） | 不做 CRUD、不访问外部 API |
| evolution_strategy | 策略选择 + 信号检测 + 自适应反思 | 不做实验管理、不做外部通信 |

## 10. 版本与变更

修改模块时：
1. 先跑 `python3 tests/run_all.py` 确认基线
2. 改完再跑一次确认没破坏
3. 重大变更记入 memory_db（add_decision）
