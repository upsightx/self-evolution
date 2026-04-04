#!/usr/bin/env python3
"""
Evolution Executor — 进化执行器。

职责：
- 根据改进建议自动生成代码/配置补丁
- 执行变更前创建备份
- 支持回滚

工作流程：
1. 接收改进建议（来自 feedback_loop）
2. 确定目标文件（模块模板、配置文件等）
3. 用 LLM 生成具体变更
4. 写入文件（带备份）
5. 记录变更日志

设计原则：
- 每次只改一个文件
- 变更前有备份，支持回滚
- 变更日志写入 SQLite（供 causal_validator 查询）
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.request
from datetime import datetime
from pathlib import Path

from db_common import get_db, DB_PATH

# Workspace root
WORKSPACE = Path(__file__).parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS evolution_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id TEXT NOT NULL UNIQUE,
    task_type TEXT NOT NULL,
    suggestion TEXT NOT NULL,
    target_file TEXT NOT NULL,
    change_description TEXT,
    status TEXT NOT NULL DEFAULT 'applied',
    applied_at TEXT DEFAULT (datetime('now')),
    verified_at TEXT,
    verdict TEXT,
    backup_path TEXT
);
"""


def _ensure_table():
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()
    db.close()


def _generate_patch_with_llm(suggestion: str, target_content: str, task_type: str) -> str | None:
    """Use LLM to generate a code patch based on the suggestion.

    Fallback chain:
    1. SILICONFLOW_API_KEY → Qwen/Qwen2.5-7B-Instruct
    2. OPENROUTER_API_KEY → openrouter/qwen/qwen3.6-plus:free
    3. Return None if no API key available

    Args:
        suggestion: Improvement suggestion from feedback_loop
        target_content: Current content of the target file
        task_type: Task type being improved (e.g., 'coding')

    Returns:
        Modified content, or None if generation failed
    """
    prompt = f"""You are an AI Agent framework engineer. Improve the following template/code based on the suggestion.

Task Type: {task_type}
Improvement Suggestion: {suggestion}

Current Code:
```
{target_content[:3000]}
```

Instructions:
1. Apply the suggestion to improve the code.
2. Return ONLY the complete modified code.
3. Do not include explanations, just the code.
4. Keep the same structure and style.
5. If the suggestion is about prompts/templates, modify the relevant strings.

Return the full modified code below:
"""

    # Try SiliconFlow first
    api_key = os.environ.get("SILICONFLOW_API_KEY")
    if api_key:
        try:
            data = json.dumps({
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            }).encode()
            req = urllib.request.Request("https://api.siliconflow.cn/v1/chat/completions", data=data, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())
                content = result["choices"][0]["message"]["content"].strip()
                content = content.replace("```python", "").replace("```", "").strip()
                return content
        except Exception as e:
            print(f"[evolution_executor] SiliconFlow failed: {e}, trying OpenRouter...")

    # Fallback to OpenRouter
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if api_key:
        try:
            data = json.dumps({
                "model": "openrouter/qwen/qwen3.6-plus:free",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            }).encode()
            req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=data, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://openclaw.ai",
                "X-Title": "OpenClaw Self-Evolution",
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())
                content = result["choices"][0]["message"]["content"].strip()
                content = content.replace("```python", "").replace("```", "").strip()
                return content
        except Exception as e:
            print(f"[evolution_executor] OpenRouter failed: {e}")

    print("[evolution_executor] No LLM API available, skipping patch generation")
    return None


def apply_improvement(
    task_type: str,
    suggestion: str,
    target_file: str,
    change_description: str = "",
) -> dict:
    """Apply an improvement to a target file.

    Args:
        task_type: Task type being improved (e.g., 'coding')
        suggestion: Improvement suggestion from feedback_loop
        target_file: Path to the file to modify (relative to workspace)
        change_description: Human-readable description of the change

    Returns:
        {
            "success": bool,
            "change_id": str,
            "backup_path": str or None,
            "message": str,
        }
    """
    _ensure_table()
    db = get_db()

    change_id = f"chg_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    target_path = WORKSPACE / target_file

    try:
        if not target_path.exists():
            return {
                "success": False,
                "change_id": change_id,
                "backup_path": None,
                "message": f"Target file not found: {target_path}",
            }

        # Read current content
        current_content = target_path.read_text(encoding="utf-8")

        # Generate patch with LLM
        print(f"[evolution_executor] Generating patch for '{suggestion}'...")
        new_content = _generate_patch_with_llm(suggestion, current_content, task_type)

        if not new_content:
            return {
                "success": False,
                "change_id": change_id,
                "backup_path": None,
                "message": "LLM patch generation failed",
            }

        # Create backup
        backup_dir = WORKSPACE / "memory" / "evolution_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_name = f"{target_path.stem}_{datetime.now().strftime('%Y%m%d%H%M%S')}{target_path.suffix}"
        backup_path = backup_dir / backup_name
        shutil.copy2(target_path, backup_path)

        # Apply change
        target_path.write_text(new_content, encoding="utf-8")

        # Record in database
        db.execute(
            """INSERT INTO evolution_changes
               (change_id, task_type, suggestion, target_file, change_description, backup_path)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (change_id, task_type, suggestion, target_file, change_description, str(backup_path)),
        )
        db.commit()

        print(f"[evolution_executor] ✅ Applied change #{change_id}")
        print(f"  File: {target_file}")
        print(f"  Backup: {backup_path}")

        return {
            "success": True,
            "change_id": change_id,
            "backup_path": str(backup_path),
            "message": f"Change applied successfully. Backup at {backup_path}",
        }

    except Exception as e:
        print(f"[evolution_executor] ❌ Failed: {e}")
        return {
            "success": False,
            "change_id": change_id,
            "backup_path": None,
            "message": str(e),
        }
    finally:
        db.close()


# ============ Docker Sandbox ============

def run_in_sandbox(
    script_content: str,
    dependencies: list[str] | None = None,
    timeout: int = 60,
    image: str = "python:3.11-slim",
) -> dict:
    """Execute Python code in a Docker sandbox.

    Args:
        script_content: Python code to execute
        dependencies: List of pip packages to install (e.g., ["requests", "numpy"])
        timeout: Execution timeout in seconds
        image: Docker image to use

    Returns:
        {
            "success": bool,
            "stdout": str,
            "stderr": str,
            "exit_code": int,
            "message": str,
        }
    """
    import subprocess
    import tempfile

    tmp_dir = Path(tempfile.mkdtemp(prefix="sandbox_"))
    script_path = tmp_dir / "script.py"

    try:
        # Write script
        script_path.write_text(script_content, encoding="utf-8")

        # Build Docker run command
        cmd = [
            "docker", "run", "--rm",
            "--network", "none",  # No network access for safety
            "--memory", "512m",    # Memory limit
            "--cpus", "1.0",       # CPU limit
            "-v", f"{tmp_dir}:/workspace",
            "-w", "/workspace",
            image,
            "bash", "-c",
        ]

        # Install dependencies if specified
        install_cmd = ""
        if dependencies:
            install_cmd = f"pip install {' '.join(dependencies)} && "

        # Execute script
        exec_cmd = f"{install_cmd}python script.py"
        cmd.append(exec_cmd)

        print(f"[sandbox] Running in Docker ({image})...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "exit_code": result.returncode,
            "message": "Executed successfully" if result.returncode == 0 else f"Exit code: {result.returncode}",
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Timeout after {timeout}s",
            "exit_code": -1,
            "message": f"Execution timed out after {timeout}s",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "stdout": "",
            "stderr": "Docker not installed or not in PATH",
            "exit_code": -1,
            "message": "Docker not available",
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
            "message": str(e),
        }
    finally:
        # Cleanup
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass


def test_change_in_sandbox(
    change_id: str,
    test_script: str,
    dependencies: list[str] | None = None,
) -> dict:
    """Test a previously applied change in Docker sandbox.

    Args:
        change_id: The change ID to test
        test_script: Python test code to run
        dependencies: Optional pip dependencies

    Returns:
        Test result dict (same format as run_in_sandbox)
    """
    _ensure_table()
    db = get_db()

    try:
        # Get change info
        row = db.execute(
            "SELECT target_file, backup_path FROM evolution_changes WHERE change_id = ?",
            (change_id,),
        ).fetchone()

        if not row:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Change {change_id} not found",
                "exit_code": -1,
                "message": f"Change {change_id} not found",
            }

        print(f"[sandbox] Testing change {change_id}...")
        result = run_in_sandbox(test_script, dependencies=dependencies)

        # Update verification status
        db.execute(
            "UPDATE evolution_changes SET verified_at = datetime('now'), verdict = ? WHERE change_id = ?",
            ("passed" if result["success"] else "failed", change_id),
        )
        db.commit()

        result["change_id"] = change_id
        return result

    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
            "message": str(e),
        }
    finally:
        db.close()


def rollback(change_id: str) -> dict:
    """Rollback a previously applied change.

    Args:
        change_id: The change ID to rollback

    Returns:
        {
            "success": bool,
            "message": str,
        }
    """
    _ensure_table()
    db = get_db()

    try:
        row = db.execute(
            "SELECT * FROM evolution_changes WHERE change_id = ?",
            (change_id,),
        ).fetchone()

        if not row:
            return {"success": False, "message": f"Change {change_id} not found"}

        backup_path = row["backup_path"]
        target_file = row["target_file"]
        target_path = WORKSPACE / target_file

        if not Path(backup_path).exists():
            return {"success": False, "message": f"Backup not found: {backup_path}"}

        # Restore from backup
        shutil.copy2(backup_path, target_path)

        # Update status
        db.execute(
            "UPDATE evolution_changes SET status = 'rolled_back', verified_at = ? WHERE change_id = ?",
            (datetime.now().isoformat(), change_id),
        )
        db.commit()

        print(f"[evolution_executor] ✅ Rolled back change #{change_id}")
        return {"success": True, "message": f"Rolled back to {backup_path}"}

    except Exception as e:
        return {"success": False, "message": str(e)}
    finally:
        db.close()


def list_changes(status: str | None = None) -> list[dict]:
    """List evolution changes.

    Args:
        status: Filter by status (applied, verified, rolled_back)

    Returns:
        List of change records
    """
    _ensure_table()
    db = get_db()

    try:
        if status:
            rows = db.execute(
                "SELECT * FROM evolution_changes WHERE status = ? ORDER BY applied_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM evolution_changes ORDER BY applied_at DESC"
            ).fetchall()

        return [dict(r) for r in rows]
    finally:
        db.close()


# ============ CLI ============

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Evolution Executor")
    sub = parser.add_subparsers(dest="command")

    # apply
    p_apply = sub.add_parser("apply", help="Apply an improvement")
    p_apply.add_argument("task_type", help="Task type (e.g., coding)")
    p_apply.add_argument("suggestion", help="Improvement suggestion")
    p_apply.add_argument("target_file", help="Target file path (relative to workspace)")
    p_apply.add_argument("--desc", default="", help="Change description")

    # rollback
    p_rollback = sub.add_parser("rollback", help="Rollback a change")
    p_rollback.add_argument("change_id")

    # list
    p_list = sub.add_parser("list", help="List changes")
    p_list.add_argument("--status", default=None)

    args = parser.parse_args()

    if args.command == "apply":
        result = apply_improvement(args.task_type, args.suggestion, args.target_file, args.desc)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    elif args.command == "rollback":
        result = rollback(args.change_id)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    elif args.command == "list":
        changes = list_changes(args.status)
        for c in changes:
            status_icon = {"applied": "🟡", "verified": "✅", "rolled_back": "❌"}.get(c["status"], "•")
            print(f"  {status_icon} [{c['status']}] #{c['change_id']}: {c['task_type']} → {c['target_file']}")
            print(f"     Suggestion: {c['suggestion'][:60]}")

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
