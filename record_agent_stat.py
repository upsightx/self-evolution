#!/usr/bin/env python3
"""记录子 Agent 执行结果到 agent-stats.json"""
import json, sys, os
from datetime import datetime

STATS_PATH = os.environ.get("AGENT_STATS_PATH", os.path.join(os.path.dirname(__file__), "agent-stats.json"))

def record(model, task_type, success, label=""):
    with open(STATS_PATH) as f:
        data = json.load(f)
    
    # 更新 by_model
    if model not in data["stats"]["by_model"]:
        data["stats"]["by_model"][model] = {"total": 0, "success": 0, "fail": 0}
    data["stats"]["by_model"][model]["total"] += 1
    data["stats"]["by_model"][model]["success" if success else "fail"] += 1
    
    # 更新 by_task_type
    if task_type not in data["stats"]["by_task_type"]:
        data["stats"]["by_task_type"][task_type] = {"total": 0, "success": 0, "fail": 0}
    data["stats"]["by_task_type"][task_type]["total"] += 1
    data["stats"]["by_task_type"][task_type]["success" if success else "fail"] += 1
    
    # 添加到 recent（保留最近 50 条）
    data["stats"]["recent"].append({
        "time": datetime.now().isoformat(),
        "model": model,
        "task_type": task_type,
        "success": success,
        "label": label
    })
    data["stats"]["recent"] = data["stats"]["recent"][-50:]
    data["updated"] = datetime.now().strftime("%Y-%m-%d")
    
    with open(STATS_PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"Recorded: {model}/{task_type} {'✅' if success else '❌'} {label}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: record_agent_stat.py <model> <task_type> <success|fail> [label]")
        sys.exit(1)
    record(sys.argv[1], sys.argv[2], sys.argv[3] == "success", 
           sys.argv[4] if len(sys.argv) > 4 else "")
