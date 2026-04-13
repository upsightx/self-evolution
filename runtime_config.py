"""
OpenClaw Self-Evolution Runtime Config — 统一配置层。

所有模块通过此文件获取共享资源路径，禁止各自硬编码。
这是三插件（X-Memory、self-evolution、external-learning）的唯一配置真源。

环境变量覆盖（可选）：
  OPENCLAW_MEMORY_DB  — 覆盖 memory.db 路径
  OPENCLAW_WORKSPACE  — 覆盖 workspace 根目录
"""
from __future__ import annotations

import os
from pathlib import Path

# Workspace root: 所有模块的公共根目录
# self-evolution/ 是 workspace 的子目录，需要往上跳一级
_SELF_DIR = Path(__file__).resolve().parent
_CANDIDATES = [
    _SELF_DIR,                 # runtime_config.py 在 workspace 根（如 /root/.openclaw/workspace/）
    _SELF_DIR.parent,          # runtime_config.py 在子目录（如 self-evolution/）
]
_DEFAULT_WORKSPACE = next(
    (c for c in _CANDIDATES if (c / "X记忆").exists() or (c / "X-Memory").exists()),
    _SELF_DIR,
)
WORKSPACE = Path(os.environ.get(
    "OPENCLAW_WORKSPACE",
    _DEFAULT_WORKSPACE,
))

# 统一 memory.db 路径 — 唯一真源
# 默认指向 X记忆/memory.db（主记忆库）
MEMORY_DB_PATH = Path(os.environ.get(
    "OPENCLAW_MEMORY_DB",
    WORKSPACE / "X记忆" / "memory.db",
))

# X-Memory 模块路径
XMEMORY_PATH = WORKSPACE / "X记忆"

# Self-Evolution 模块路径
MODULES_PATH = WORKSPACE / "modules"
