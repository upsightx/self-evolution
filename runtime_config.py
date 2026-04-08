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
WORKSPACE = Path(os.environ.get(
    "OPENCLAW_WORKSPACE",
    Path(__file__).parent,  # 默认: runtime_config.py 所在目录
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
