"""
OpenClaw Self-Evolution Runtime Config — 统一配置层（薄代理）。

直接导入 workspace 根目录的 runtime_config.py（唯一真源）。
此文件仅为 self-evolution/ 目录下的模块提供便捷导入路径，
不维护独立配置副本。
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure parent workspace is on path
_parent = Path(__file__).resolve().parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from runtime_config import (
    WORKSPACE,
    MEMORY_DB_PATH,
    XMEMORY_PATH,
    MODULES_PATH,
)

__all__ = ["WORKSPACE", "MEMORY_DB_PATH", "XMEMORY_PATH", "MODULES_PATH"]
