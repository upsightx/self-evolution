#!/usr/bin/env python3
"""
Agent Dispatch Helper — 串联自我进化模块的核心闭环。

使用方式：
    # 派发前：获取增强指令
    python3 agent_dispatch.py prepare "写一个Python爬虫" --task-type coding

    # 完成后：记录结果
    python3 agent_dispatch.py complete --task-type coding --model minimax --success --label "爬虫任务"
    python3 agent_dispatch.py complete --task-type coding --model opus --fail --label "重构失败" --notes "超时"

    # 查看当前推荐
    python3 agent_dispatch.py recommend "重构memory_db模块"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def prepare_dispatch(task_description: str, task_type: str | None = None) -> dict:
    """派发子agent前调用。返回增强信息：推荐模型、历史教训、改进建议。

    Returns:
        {
            "model": "opus",
            "alias": "LtCraft",
            "task_type": "coding",
            "confidence": 0.9,
            "lessons": ["增加约束：列出所有需要的依赖", ...],
            "context": "相关历史记忆...",
            "injection_prompt": "完整的注入提示文本（直接拼到子agent指令末尾）"
        }
    """
    result = {
        "model": "minimax",
        "alias": "Minimax27",
        "task_type": task_type or "general",
        "confidence": 0.5,
        "lessons": [],
        "context": "",
        "injection_prompt": "",
    }

    # 1. 模型推荐
    try:
        from model_router import recommend_for_description, classify_task
        if not task_type:
            task_type = classify_task(task_description)
            result["task_type"] = task_type
        rec = recommend_for_description(task_description, strategy="balanced")
        result["model"] = rec.get("model", "minimax")
        result["alias"] = rec.get("alias", "Minimax27")
        result["confidence"] = rec.get("confidence", 0.5)
    except Exception:
        pass

    # 2. 历史教训（从feedback_loop获取改进建议）
    try:
        from feedback_loop import generate_template_improvements, analyze_template_effectiveness
        improvements = generate_template_improvements(task_type)
        if improvements:
            result["lessons"] = improvements[:5]

        # 补充：该任务类型的成功率
        analysis = analyze_template_effectiveness(task_type)
        if analysis["total"] > 0:
            result["success_rate"] = analysis["success_rate"]
            result["common_failures"] = analysis["common_failures"]
    except Exception:
        pass

    # 3. 相关记忆上下文
    try:
        from memory_service import recall
        ctx = recall(task_description, task_type=task_type, top_k=3)
        if ctx:
            result["context"] = ctx
    except Exception:
        pass

    # 4. 决策参考摘要（给主Agent看的，不是直接注入子agent的）
    # 主Agent根据这些信息自行决定是否注入、注入什么
    summary_parts = []
    if result["lessons"]:
        summary_parts.append("历史教训: " + "; ".join(result["lessons"][:3]))
    if result.get("common_failures"):
        summary_parts.append("常见失败: " + ", ".join(result["common_failures"][:3]))
    if summary_parts:
        result["decision_brief"] = " | ".join(summary_parts)
    
    # 不再自动生成injection_prompt，由主Agent自行决定

    return result


def record_completion(task_type: str, model: str, success: bool,
                      label: str = "", notes: str = "") -> dict:
    """子agent完成后调用。记录到所有相关系统。

    Returns:
        {"recorded_to": ["agent_stats", "feedback_loop", "memory_db", ...]}
    """
    recorded = []

    # 1. record_agent_stat（双写json+db）
    try:
        from record_agent_stat import record
        record(model, task_type, success, label)
        recorded.append("agent_stats")
    except Exception as e:
        recorded.append(f"agent_stats:error:{e}")

    # 2. feedback_loop（带gap分析）
    try:
        from feedback_loop import record_task_outcome
        record_task_outcome(
            task_id=None,
            task_type=task_type,
            model=model,
            expected=label or task_type,
            actual="success" if success else (notes or "failed"),
            success=success,
            notes=notes,
        )
        recorded.append("feedback_loop")
    except Exception as e:
        recorded.append(f"feedback_loop:error:{e}")

    # 3. memory_service 记录（仅失败时）
    if not success and notes:
        try:
            from memory_service import remember
            remember(
                content=f"子Agent失败: {task_type}/{model} - {label}. {notes}",
                type="lesson",
                task_type=task_type,
                tags=[task_type, model, "failure"],
            )
            recorded.append("memory_service")
        except Exception:
            pass

    # 4. LRU访问记录（触发相关记忆的access_count）
    try:
        from memory_embedding import semantic_search
        from memory_lru import record_access
        related = semantic_search(label or task_type, limit=3)
        for r in related:
            if r["score"] > 0.5:
                record_access(r["source_id"], r["source_table"])
        recorded.append("lru_access")
    except Exception:
        pass

    return {"recorded_to": recorded, "success": success}


def recommend(task_description: str) -> None:
    """CLI: 查看推荐信息。"""
    result = prepare_dispatch(task_description)
    print(f"📋 任务类型: {result['task_type']}")
    print(f"🤖 推荐模型: {result['model']} ({result['alias']})")
    print(f"📊 置信度: {result['confidence']}")
    if result.get("success_rate") is not None:
        print(f"📈 历史成功率: {result['success_rate']:.0%}")
    if result.get("common_failures"):
        print(f"⚠️  常见失败: {', '.join(result['common_failures'])}")
    if result["lessons"]:
        print(f"\n📝 历史教训:")
        for i, l in enumerate(result["lessons"], 1):
            print(f"  {i}. {l}")
    if result["context"]:
        print(f"\n🧠 相关记忆:\n{result['context'][:300]}")
    if result["injection_prompt"]:
        print(f"\n--- 注入提示 ---\n{result['injection_prompt']}")


def cli():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "prepare":
        if len(sys.argv) < 3:
            print("Usage: agent_dispatch.py prepare <task_description> [--task-type TYPE]")
            return
        desc = sys.argv[2]
        task_type = None
        if "--task-type" in sys.argv:
            idx = sys.argv.index("--task-type")
            task_type = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        result = prepare_dispatch(desc, task_type)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif cmd == "complete":
        task_type = model = label = notes = ""
        success = True
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--task-type" and i + 1 < len(args):
                task_type = args[i + 1]; i += 2
            elif args[i] == "--model" and i + 1 < len(args):
                model = args[i + 1]; i += 2
            elif args[i] == "--label" and i + 1 < len(args):
                label = args[i + 1]; i += 2
            elif args[i] == "--notes" and i + 1 < len(args):
                notes = args[i + 1]; i += 2
            elif args[i] == "--success":
                success = True; i += 1
            elif args[i] == "--fail":
                success = False; i += 1
            else:
                i += 1
        result = record_completion(task_type, model, success, label, notes)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif cmd == "recommend":
        if len(sys.argv) < 3:
            print("Usage: agent_dispatch.py recommend <task_description>")
            return
        recommend(sys.argv[2])

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    cli()
