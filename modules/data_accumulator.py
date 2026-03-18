#!/usr/bin/env python3
"""
数据积累器 — 从多个数据源自动积累子Agent执行数据，丰富 model_router 训练数据。

数据源：
1. agent-stats.json — 现有统计（recent 数组）
2. memory.db task_outcomes 表 — feedback_loop 记录
3. memory/*.md 日志文件 — 历史日志中的子Agent执行记录

CLI:
    python3 data_accumulator.py scan              # 扫描日志
    python3 data_accumulator.py merge             # 合并所有源
    python3 data_accumulator.py backfill          # 回填（dry_run）
    python3 data_accumulator.py backfill --apply  # 实际回填
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

STATS_PATH = str(Path(__file__).parent.parent / "agent-stats.json")
MEMORY_DIR = str(Path(__file__).parent.parent)
DB_PATH = str(Path(__file__).parent / "memory.db")

# --- 模型名正则 ---
MODEL_PATTERNS = {
    "opus": re.compile(r'\bopus\b', re.IGNORECASE),
    "minimax": re.compile(r'\bminimax\b', re.IGNORECASE),
    "sonnet": re.compile(r'\bsonnet\b', re.IGNORECASE),
    "glm5": re.compile(r'\bglm[\s\-]?5\b', re.IGNORECASE),
    "kimi": re.compile(r'\bkimi\b', re.IGNORECASE),
}

# --- 任务类型关键词 ---
TASK_TYPE_KEYWORDS = {
    "coding": ["写代码", "代码", "coding", "模块", "实现", "开发", "测试", "单元测试",
                "脚本", "函数", "类", "API", "接口", "bug", "修复bug"],
    "research": ["调研", "research", "搜索", "分析", "对比", "评估", "学习",
                 "信息搜集", "搜集"],
    "refactor": ["重构", "refactor", "优化", "重写", "升级", "迁移", "清理"],
    "file_ops": ["文件", "file", "归档", "压缩", "整理", "导入", "导出",
                 "记忆压缩", "备份"],
    "skill_creation": ["skill", "技能", "创建skill", "安装skill", "skill创建"],
}

# --- 成功/失败关键词 ---
SUCCESS_KEYWORDS = ["完成", "通过", "成功", "一次通过", "全部通过", "测试通过", "已完成"]
FAIL_KEYWORDS = ["失败", "超时", "返工", "重试", "摸鱼", "没写代码", "没执行"]

# --- 子Agent提及模式 ---
SUBAGENT_PATTERN = re.compile(
    r'(子\s*Agent|sub[\-\s]?agent|subagent)',
    re.IGNORECASE
)


def _extract_date_from_filename(filename: str) -> str:
    """从文件名提取日期，如 2026-03-18.md -> 2026-03-18"""
    m = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    return m.group(1) if m else ""


def _detect_model(text: str) -> str:
    """从文本中检测模型名"""
    for model, pattern in MODEL_PATTERNS.items():
        if pattern.search(text):
            return model
    return "unknown"


def _detect_task_type(text: str) -> str:
    """从文本中推断任务类型"""
    scores = {}
    for task_type, keywords in TASK_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text.lower())
        if score > 0:
            scores[task_type] = score
    if not scores:
        return "unknown"
    return max(scores, key=scores.get)


def _detect_success(text: str) -> bool | None:
    """检测成功/失败，返回 True/False/None(无法判断)"""
    has_success = any(kw in text for kw in SUCCESS_KEYWORDS)
    has_fail = any(kw in text for kw in FAIL_KEYWORDS)
    if has_fail and not has_success:
        return False
    if has_success and not has_fail:
        return True
    if has_fail and has_success:
        # 同时有成功和失败关键词，看哪个更靠后（最终结果）
        last_success = max((text.rfind(kw) for kw in SUCCESS_KEYWORDS if kw in text), default=-1)
        last_fail = max((text.rfind(kw) for kw in FAIL_KEYWORDS if kw in text), default=-1)
        return last_success > last_fail
    return None


def _parse_log_block(block: str, date: str, source: str) -> list[dict]:
    """解析一个文本块，提取子Agent执行记录"""
    records = []
    lines = block.split('\n')

    for i, line in enumerate(lines):
        if not SUBAGENT_PATTERN.search(line):
            continue

        # 取当前行及上下文（前2行后2行）
        context_start = max(0, i - 2)
        context_end = min(len(lines), i + 3)
        context = '\n'.join(lines[context_start:context_end])

        model = _detect_model(context)
        task_type = _detect_task_type(context)
        success = _detect_success(context)

        if success is None:
            continue  # 无法判断成功/失败，跳过

        records.append({
            "model": model,
            "task_type": task_type,
            "success": success,
            "date": date,
            "source": source,
        })

    return records


def _parse_structured_entries(content: str, date: str, source: str) -> list[dict]:
    """解析结构化的子Agent执行记录（如列表项、编号项）"""
    records = []

    # 匹配 "N 个 Model 子 Agent" 模式
    batch_pattern = re.compile(
        r'(\d+)\s*个?\s*(Opus|MiniMax|Sonnet|GLM5|Kimi)\s*子?\s*Agent',
        re.IGNORECASE
    )
    for m in batch_pattern.finditer(content):
        count = int(m.group(1))
        model = m.group(2).lower()
        if model.startswith('glm'):
            model = 'glm5'

        # 获取周围上下文判断成功/失败
        start = max(0, m.start() - 100)
        end = min(len(content), m.end() + 200)
        context = content[start:end]

        success = _detect_success(context)
        task_type = _detect_task_type(context)

        if success is not None:
            for _ in range(count):
                records.append({
                    "model": model,
                    "task_type": task_type,
                    "success": success,
                    "date": date,
                    "source": source,
                })

    # 匹配 "模块 N/N 一次通过" 或 "模块 N 首次...失败，重试后通过"
    module_pattern = re.compile(
        r'模块\s*(\d+(?:/\d+)*)\s*(一次通过|通过|失败|重试后通过)',
        re.IGNORECASE
    )
    for m in module_pattern.finditer(content):
        nums_str = m.group(1)
        result_text = m.group(2)

        start = max(0, m.start() - 200)
        context = content[start:m.end() + 100]
        model = _detect_model(context)
        task_type = _detect_task_type(context)

        nums = nums_str.split('/')
        for _ in nums:
            success = "失败" not in result_text
            records.append({
                "model": model,
                "task_type": task_type,
                "success": success,
                "date": date,
                "source": source,
            })

    return records


def scan_daily_logs(days: int = 30, memory_dir: str = MEMORY_DIR) -> list[dict]:
    """
    扫描 memory/YYYY-MM-DD.md 文件，提取子Agent执行记录。

    Args:
        days: 扫描最近多少天的日志
        memory_dir: memory 目录路径

    Returns:
        [{"model": "opus", "task_type": "coding", "success": True,
          "date": "2026-03-18", "source": "memory/2026-03-18.md"}]
    """
    records = []
    cutoff = datetime.now() - timedelta(days=days)
    memory_path = Path(memory_dir)

    # 只匹配 YYYY-MM-DD.md 格式
    date_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2})\.md$')

    for f in sorted(memory_path.glob("*.md")):
        m = date_pattern.match(f.name)
        if not m:
            continue

        date_str = m.group(1)
        try:
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        if file_date < cutoff:
            continue

        try:
            content = f.read_text(encoding='utf-8')
        except Exception:
            continue

        rel_source = f"memory/{f.name}"

        # 方法1: 逐行扫描子Agent提及
        block_records = _parse_log_block(content, date_str, rel_source)

        # 方法2: 结构化模式提取
        struct_records = _parse_structured_entries(content, date_str, rel_source)

        # 合并去重（同一source+model+task_type+success 只保留一条）
        seen = set()
        for r in block_records + struct_records:
            key = (r["model"], r["task_type"], r["success"], r["date"])
            if key not in seen:
                seen.add(key)
                records.append(r)

    return records


def _load_agent_stats(stats_path: str = STATS_PATH) -> list[dict]:
    """从 agent-stats.json 加载 recent 记录"""
    records = []
    try:
        with open(stats_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return records

    for entry in data.get("stats", {}).get("recent", []):
        time_str = entry.get("time", "")
        date = time_str[:10] if len(time_str) >= 10 else ""
        records.append({
            "model": entry.get("model", "unknown"),
            "task_type": entry.get("task_type", "unknown"),
            "success": bool(entry.get("success", False)),
            "date": date,
            "source": "agent_stats",
        })
    return records


def _load_task_outcomes(db_path: str = DB_PATH) -> list[dict]:
    """从 memory.db task_outcomes 表加载记录"""
    records = []
    if not os.path.exists(db_path):
        return records

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT task_type, model, success, timestamp FROM task_outcomes"
        )
        for row in cursor:
            task_type, model, success, timestamp = row
            date = timestamp[:10] if timestamp and len(timestamp) >= 10 else ""
            records.append({
                "model": (model or "unknown").lower(),
                "task_type": task_type or "unknown",
                "success": bool(success),
                "date": date,
                "source": "task_outcomes",
            })
        conn.close()
    except Exception:
        pass

    return records


def _compute_stats(records: list[dict]) -> dict:
    """从记录列表计算统计汇总"""
    by_model = {}
    by_task_type = {}
    by_model_task = {}

    for r in records:
        model = r["model"]
        task_type = r["task_type"]
        success = r["success"]
        key = f"{model}:{task_type}"

        # by_model
        if model not in by_model:
            by_model[model] = {"total": 0, "success": 0}
        by_model[model]["total"] += 1
        if success:
            by_model[model]["success"] += 1

        # by_task_type
        if task_type not in by_task_type:
            by_task_type[task_type] = {"total": 0, "success": 0}
        by_task_type[task_type]["total"] += 1
        if success:
            by_task_type[task_type]["success"] += 1

        # by_model_task
        if key not in by_model_task:
            by_model_task[key] = {"total": 0, "success": 0}
        by_model_task[key]["total"] += 1
        if success:
            by_model_task[key]["success"] += 1

    # 计算 rate
    for d in [by_model, by_task_type, by_model_task]:
        for v in d.values():
            v["rate"] = round(v["success"] / v["total"], 3) if v["total"] > 0 else 0.0

    return by_model, by_task_type, by_model_task


def merge_all_sources(
    stats_path: str = STATS_PATH,
    db_path: str = DB_PATH,
    memory_dir: str = MEMORY_DIR,
    days: int = 30,
) -> dict:
    """
    合并三个数据源，去重，返回统计汇总。

    Returns:
        {
            "total_records": N,
            "by_model": {...},
            "by_task_type": {...},
            "by_model_task": {...},
            "sources": {"agent_stats": N, "task_outcomes": N, "daily_logs": N}
        }
    """
    stats_records = _load_agent_stats(stats_path)
    outcome_records = _load_task_outcomes(db_path)
    log_records = scan_daily_logs(days=days, memory_dir=memory_dir)

    # 去重：(date, model, task_type, success) 作为 key
    seen = set()
    merged = []
    source_counts = {"agent_stats": 0, "task_outcomes": 0, "daily_logs": 0}

    # 优先级：agent_stats > task_outcomes > daily_logs
    for records, source_name in [
        (stats_records, "agent_stats"),
        (outcome_records, "task_outcomes"),
        (log_records, "daily_logs"),
    ]:
        for r in records:
            key = (r["date"], r["model"], r["task_type"], r["success"])
            if key not in seen:
                seen.add(key)
                merged.append(r)
                source_counts[source_name] += 1

    by_model, by_task_type, by_model_task = _compute_stats(merged)

    return {
        "total_records": len(merged),
        "by_model": by_model,
        "by_task_type": by_task_type,
        "by_model_task": by_model_task,
        "sources": source_counts,
    }


def backfill_stats(
    dry_run: bool = True,
    stats_path: str = STATS_PATH,
    db_path: str = DB_PATH,
    memory_dir: str = MEMORY_DIR,
    days: int = 30,
) -> dict:
    """
    从 daily_logs 和 task_outcomes 中提取的记录写入 agent-stats.json 的 recent 数组。

    Args:
        dry_run: True 只预览，不写入
        stats_path: agent-stats.json 路径
        db_path: memory.db 路径
        memory_dir: memory 目录路径
        days: 扫描天数

    Returns:
        {"new_records": N, "duplicates_skipped": N}
    """
    # 加载现有 stats
    try:
        with open(stats_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"new_records": 0, "duplicates_skipped": 0, "error": "cannot load stats"}

    existing_recent = data.get("stats", {}).get("recent", [])

    # 构建已有记录的指纹集合
    existing_keys = set()
    for entry in existing_recent:
        time_str = entry.get("time", "")
        date = time_str[:10] if len(time_str) >= 10 else ""
        key = (date, entry.get("model", ""), entry.get("task_type", ""), entry.get("success", False))
        existing_keys.add(key)

    # 收集新记录
    log_records = scan_daily_logs(days=days, memory_dir=memory_dir)
    outcome_records = _load_task_outcomes(db_path)
    all_new = log_records + outcome_records

    new_entries = []
    duplicates = 0

    for r in all_new:
        key = (r["date"], r["model"], r["task_type"], r["success"])
        if key in existing_keys:
            duplicates += 1
            continue
        existing_keys.add(key)
        new_entries.append({
            "time": f"{r['date']}T00:00:00.000000",
            "model": r["model"],
            "task_type": r["task_type"],
            "success": r["success"],
            "label": f"backfill from {r['source']}",
        })

    if not dry_run and new_entries:
        data["stats"]["recent"].extend(new_entries)
        # 保留最近 100 条
        data["stats"]["recent"] = data["stats"]["recent"][-100:]

        # 更新 by_model 和 by_task_type 汇总
        for entry in new_entries:
            model = entry["model"]
            task_type = entry["task_type"]
            success = entry["success"]

            if model not in data["stats"]["by_model"]:
                data["stats"]["by_model"][model] = {"total": 0, "success": 0, "fail": 0}
            data["stats"]["by_model"][model]["total"] += 1
            data["stats"]["by_model"][model]["success" if success else "fail"] += 1

            if task_type not in data["stats"]["by_task_type"]:
                data["stats"]["by_task_type"][task_type] = {"total": 0, "success": 0, "fail": 0}
            data["stats"]["by_task_type"][task_type]["total"] += 1
            data["stats"]["by_task_type"][task_type]["success" if success else "fail"] += 1

        data["updated"] = datetime.now().strftime("%Y-%m-%d")

        with open(stats_path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return {"new_records": len(new_entries), "duplicates_skipped": duplicates}


# --- CLI ---
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "scan":
        records = scan_daily_logs()
        print(f"Found {len(records)} records from daily logs:\n")
        for r in records:
            status = "✅" if r["success"] else "❌"
            print(f"  {r['date']} | {r['model']:>8} | {r['task_type']:<16} | {status} | {r['source']}")

    elif cmd == "merge":
        result = merge_all_sources()
        print(f"Total records: {result['total_records']}")
        print(f"\nSources: {json.dumps(result['sources'], indent=2)}")
        print(f"\nBy model:")
        for model, stats in sorted(result["by_model"].items()):
            print(f"  {model:>10}: {stats['total']:>3} total, {stats['success']:>3} success, rate={stats['rate']:.1%}")
        print(f"\nBy task type:")
        for tt, stats in sorted(result["by_task_type"].items()):
            print(f"  {tt:>16}: {stats['total']:>3} total, {stats['success']:>3} success, rate={stats['rate']:.1%}")
        print(f"\nBy model:task:")
        for key, stats in sorted(result["by_model_task"].items()):
            print(f"  {key:>25}: {stats['total']:>3} total, {stats['success']:>3} success, rate={stats['rate']:.1%}")

    elif cmd == "backfill":
        apply = "--apply" in sys.argv
        result = backfill_stats(dry_run=not apply)
        mode = "APPLIED" if apply else "DRY RUN"
        print(f"[{mode}] New records: {result['new_records']}, Duplicates skipped: {result['duplicates_skipped']}")

    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python3 data_accumulator.py [scan|merge|backfill [--apply]]")
        sys.exit(1)


if __name__ == "__main__":
    main()
