"""公共数据库连接模块 — self-evolution/modules

Thin adapter to X-Memory's canonical db_common.
Self-evolution must not own a second DB path resolution contract.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# ADAPTER EXCEPTION: this file must bootstrap runtime_config before delegating
# to X-Memory/db_common.py. It must not grow its own DB path contract.
_workspace = Path(__file__).resolve().parent.parent
if not (_workspace / "runtime_config.py").exists() and (_workspace.parent / "runtime_config.py").exists():
    _workspace = _workspace.parent
if str(_workspace) not in sys.path:
    sys.path.insert(0, str(_workspace))

from runtime_config import XMEMORY_PATH

_real_db_common_path = Path(XMEMORY_PATH) / "db_common.py"
if not _real_db_common_path.exists():
    raise ImportError(f"X-Memory db_common.py not found at {_real_db_common_path}")

_spec = importlib.util.spec_from_file_location("_xmemory_db_common", str(_real_db_common_path))
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load X-Memory db_common from {_real_db_common_path}")

_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

DB_PATH = _module.DB_PATH
get_db = _module.get_db
parse_time_hint = _module.parse_time_hint
_TIME_PATTERNS = _module._TIME_PATTERNS

__all__ = ["DB_PATH", "get_db", "parse_time_hint", "_TIME_PATTERNS"]
