"""公共数据库连接模块

所有模块统一通过此模块获取 DB 连接，避免重复定义 DB_PATH 和连接逻辑。
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("SELF_EVOLUTION_DB", Path(__file__).parent / "memory.db"))


def get_db(db_path=None):
    """获取数据库连接，启用 WAL 模式和 Row 工厂"""
    path = str(db_path or DB_PATH)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db
