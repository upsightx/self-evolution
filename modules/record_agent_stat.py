#!/usr/bin/env python3
"""记录子 Agent 执行结果到 agent-stats.json（带文件锁防并发）"""
from __future__ import annotations

import fcntl
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from db_common import DB_PATH

STATS_PATH = str(Path(__file__).parent.parent / "agent-stats.json")


def record(model, task_type, success, label=""):
    """Record agent outcome to both agent-stats.json and memory.db task_outcomes."""
    # 1) Write to agent-stats.json with file lock
    if os.path.exists(STATS_PATH):
        try:
            with open(STATS_PATH, "r+", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    data = json.load(f)

                    if model not in data["stats"]["by_model"]:
                        data["stats"]["by_model"][model] = {"total": 0, "success": 0, "fail": 0}
                    data["stats"]["by_model"][model]["total"] += 1
                    data["stats"]["by_model"][model]["success" if success else "fail"] += 1

                    if task_type not in data["stats"]["by_task_type"]:
                        data["stats"]["by_task_type"][task_type] = {"total": 0, "success": 0, "fail": 0}
                    data["stats"]["by_task_type"][task_type]["total"] += 1
                    data["stats"]["by_task_type"][task_type]["success" if success else "fail"] += 1

                    data["stats"]["recent"].append({
                        "time": datetime.now().isoformat(),
                        "model": model,
                        "task_type": task_type,
                        "success": success,
                        "label": label
                    })
                    data["stats"]["recent"] = data["stats"]["recent"][-50:]
                    data["updated"] = datetime.now().strftime("%Y-%m-%d")

                    f.seek(0)
                    f.truncate()
                    json.dump(data, f, ensure_ascii=False, indent=2)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except (json.JSONDecodeError, IOError, KeyError) as e:
            print(f"Error updating {STATS_PATH}: {e}")

    # 2) Also write to memory.db task_outcomes for unified data source
    try:
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                task_type TEXT NOT NULL,
                model TEXT,
                expected TEXT,
                actual TEXT,
                success INTEGER NOT NULL,
                gap_analysis TEXT,
                notes TEXT,
                timestamp TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "INSERT INTO task_outcomes (task_type, model, success, notes) VALUES (?, ?, ?, ?)",
            (task_type, model, int(success), label or None),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning: failed to write to memory.db: {e}")

    print(f"Recorded: {model}/{task_type} {'✅' if success else '❌'} {label}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: record_agent_stat.py <model> <task_type> <success|fail> [label]")
        sys.exit(1)
    record(sys.argv[1], sys.argv[2], sys.argv[3] == "success",
           sys.argv[4] if len(sys.argv) > 4 else "")
