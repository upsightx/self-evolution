"""公共数据库连接模块 — self-evolution/modules

统一通过 runtime_config 获取 DB 路径，禁止本地硬编码。
与 X记忆/db_common.py 指向同一个 memory.db。
"""

import os
import re
import sys
import sqlite3
from pathlib import Path

# 优先从 runtime_config 获取统一路径
try:
    _workspace = Path(__file__).resolve().parent.parent
    # Handle symlink: if modules/ -> self-evolution/modules/, go up one more
    if not (_workspace / "runtime_config.py").exists() and (_workspace.parent / "runtime_config.py").exists():
        _workspace = _workspace.parent
    if str(_workspace) not in sys.path:
        sys.path.insert(0, str(_workspace))
    from runtime_config import MEMORY_DB_PATH
    DB_PATH = MEMORY_DB_PATH
except ImportError:
    # Fallback: 环境变量 > 智能检测 > 本地硬编码
    _env_db = os.environ.get("OPENCLAW_MEMORY_DB", "")
    if _env_db:
        DB_PATH = Path(_env_db)
    else:
        # Try multiple candidate locations
        _base = Path(__file__).resolve().parent.parent
        _candidates = [
            _base / "X记忆" / "memory.db",
            _base.parent / "X记忆" / "memory.db",
        ]
        DB_PATH = next((c for c in _candidates if c.exists()), _candidates[0])


def get_db(db_path=None):
    """获取数据库连接，启用 WAL 模式和 Row 工厂"""
    path = str(db_path or DB_PATH)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


# ============ Time hint parsing ============

_TIME_PATTERNS = {
    r"今天|today": 0,
    r"昨天|yesterday": 1,
    r"前天": 2,
    r"上午": 0,
    r"下午": 0,
    r"最近|近期": 7,
    r"上周|last\s*week": 7,
    r"这周|this\s*week": 7,
    r"上个月|last\s*month": 30,
    r"这个月|this\s*month": 30,
}


def parse_time_hint(query: str) -> dict | None:
    """从查询中提取时间暗示。"""
    if not query:
        return None
    for pattern, days in _TIME_PATTERNS.items():
        if re.search(pattern, query, re.IGNORECASE):
            return {"days_ago": days, "matched": pattern}
    return None
