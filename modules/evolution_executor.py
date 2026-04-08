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

# Protected files that require manual approval
PROTECTED_FILES = {
    "X记忆/memory_db.py",
    "X记忆/memory_store.py",
    "X记忆/memory_retrieval.py",
    "X记忆/memory_service.py",
    "modules/goal_tree.py",
    "modules/capability_model.py",
    "modules/feedback_loop.py",
    "modules/causal_validator.py",
    "modules/auto_evolve.py",
    "runtime_config.py",
    ".gitignore",
    "openclaw.json",
}

# Dangerous operations to block
DANGEROUS_PATTERNS = [
    "os.remove(",
    "os.unlink(",
    "shutil.rmtree(",
    "subprocess.run(",
    "urllib.request",
    "requests.",
    "socket.",
]


def register_external_learning_proposal(
    proposal_id: str,
    summary: str,
    target_module: str = "",
    change_description: str = "",
) -> dict:
    """Register an external learning proposal as an evolution change.

    Creates a pending entry in evolution_changes table for later execution.

    Args:
        proposal_id: Unique ID for the proposal (e.g., from external learning)
        summary: Proposal summary
        target_module: Target module to improve (e.g., 'curiosity_engine')
        change_description: Human-readable description

    Returns:
        {
            "success": bool,
            "change_id": str or None,
            "message": str,
        }
    """
    _ensure_table()
    db = get_db()

    change_id = f"ext_{proposal_id}_{datetime.now().strftime('%Y%m%d')}"

    try:
        # Check if already exists
        existing = db.execute(
            "SELECT change_id FROM evolution_changes WHERE change_id = ?",
            (change_id,),
        ).fetchone()

        if existing:
            return {
                "success": False,
                "change_id": change_id,
                "message": f"Proposal already registered: {change_id}",
            }

        # Insert as pending
        db.execute(
            """INSERT INTO evolution_changes
               (change_id, task_type, suggestion, target_file, change_description, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (change_id, "external_learning", summary, target_module, change_description),
        )
        db.commit()

        print(f"[evolution_executor] ✅ Registered external proposal: {change_id}")
        print(f"  Summary: {summary[:60]}...")
        print(f"  Target: {target_module or 'TBD'}")

        return {
            "success": True,
            "change_id": change_id,
            "message": f"Proposal registered. Use apply_improvement() to execute.",
        }

    except Exception as e:
        print(f"[evolution_executor] ❌ Failed to register: {e}")
        return {
            "success": False,
            "change_id": None,
            "message": str(e),
        }
    finally:
        db.close()


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


def _check_safety(target_file: str, new_content: str) -> dict:
    """Check if the change is safe to apply.

    Args:
        target_file: Path to the file being modified
        new_content: New content to write

    Returns:
        {
            "safe": bool,
            "reason": str,
        }
    """
    # Check 1: Protected files
    if target_file in PROTECTED_FILES:
        return {
            "safe": False,
            "reason": f"Protected file '{target_file}' requires manual approval",
        }

    # Check 2: Dangerous operations
    for pattern in DANGEROUS_PATTERNS:
        if pattern in new_content:
            return {
                "safe": False,
                "reason": f"Contains dangerous operation: '{pattern}'",
            }

    return {"safe": True, "reason": "Passed safety check"}


def apply_improvement(
    task_type: str,
    suggestion: str,
    target_file: str,
    change_description: str = "",
    max_iterations: int = 3,
    test_script: str | None = None,
) -> dict:
    """Apply an improvement to a target file with interactive feedback loop.

    Inspired by MiroThinker's interactive scaling: instead of single-shot
    patch generation, iterate: generate → test → feedback → refine.

    Args:
        task_type: Task type being improved (e.g., 'coding')
        suggestion: Improvement suggestion from feedback_loop
        target_file: Path to the file to modify (relative to workspace)
        change_description: Human-readable description of the change
        max_iterations: Max refinement iterations (default 3)
        test_script: Optional test code to run in sandbox after each iteration

    Returns:
        {
            "success": bool,
            "change_id": str,
            "backup_path": str or None,
            "message": str,
            "iterations": int,
            "test_results": list,
        }
    """
    _ensure_table()
    db = get_db()

    change_id = f"chg_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    target_path = WORKSPACE / target_file
    iterations_used = 0
    test_results = []

    try:
        if not target_file or not target_file.strip():
            return {
                "success": False,
                "change_id": change_id,
                "backup_path": None,
                "message": "target_file is empty — cannot apply improvement without a specific file target",
                "iterations": 0,
                "test_results": [],
            }

        if not target_path.exists():
            return {
                "success": False,
                "change_id": change_id,
                "backup_path": None,
                "message": f"Target file not found: {target_path}",
                "iterations": 0,
                "test_results": [],
            }

        # Read current content
        current_content = target_path.read_text(encoding="utf-8")
        original_content = current_content

        # Create backup (once, before any changes)
        backup_dir = WORKSPACE / "memory" / "evolution_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_name = f"{target_path.stem}_{datetime.now().strftime('%Y%m%d%H%M%S')}{target_path.suffix}"
        backup_path = backup_dir / backup_name
        shutil.copy2(target_path, backup_path)

        # Interactive loop: generate → test → feedback → refine
        refined_suggestion = suggestion
        for iteration in range(1, max_iterations + 1):
            iterations_used = iteration
            print(f"[evolution_executor] Iteration {iteration}/{max_iterations}...")

            # Generate patch with LLM
            print(f"  Generating patch for '{refined_suggestion}'...")
            new_content = _generate_patch_with_llm(refined_suggestion, current_content, task_type)

            if not new_content:
                test_results.append({"iteration": iteration, "status": "llm_failed"})
                print(f"  ⚠️ LLM generation failed")
                break

            # Safety check BEFORE writing to disk
            safety = _check_safety(target_file, new_content)
            if not safety["safe"]:
                test_results.append({"iteration": iteration, "status": "blocked", "reason": safety["reason"]})
                print(f"  🛑 Safety check failed: {safety['reason']}")
                return {
                    "success": False,
                    "change_id": change_id,
                    "backup_path": str(backup_path),
                    "message": f"Safety check failed: {safety['reason']}",
                    "iterations": iteration,
                    "test_results": test_results,
                }

            # Apply change (safe content only)
            target_path.write_text(new_content, encoding="utf-8")

            # Test in sandbox if test_script provided
            test_passed = True
            if test_script:
                print(f"  Testing in sandbox...")
                sandbox_result = run_in_sandbox(test_script)
                test_results.append({
                    "iteration": iteration,
                    "status": "passed" if sandbox_result["success"] else "failed",
                    "stderr": sandbox_result["stderr"][:200],
                })
                if not sandbox_result["success"]:
                    test_passed = False
                    print(f"  ❌ Test failed: {sandbox_result['stderr'][:100]}")
                    # Feed back error to LLM for next iteration
                    refined_suggestion = f"""
Previous attempt failed with error:
{sandbox_result['stderr'][:500]}

Original suggestion: {suggestion}

Please fix the issue and regenerate the patch.
"""
                    current_content = new_content  # Use last attempt as base for refinement
                    continue
                else:
                    print(f"  ✅ Test passed")
                    break  # Success, exit loop
            else:
                # No test script, assume success
                print(f"  ✅ Patch generated (no test)")
                break

        # Final result
        if test_passed and new_content:
            # Record in database
            db.execute(
                """INSERT INTO evolution_changes
                   (change_id, task_type, suggestion, target_file, change_description, backup_path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (change_id, task_type, suggestion, target_file, change_description, str(backup_path)),
            )
            db.commit()

            print(f"[evolution_executor] ✅ Applied change #{change_id} ({iterations_used} iteration(s))")
            print(f"  File: {target_file}")
            print(f"  Backup: {backup_path}")

            return {
                "success": True,
                "change_id": change_id,
                "backup_path": str(backup_path),
                "message": f"Change applied in {iterations_used} iteration(s). Backup at {backup_path}",
                "iterations": iterations_used,
                "test_results": test_results,
            }
        else:
            # Rollback to original
            target_path.write_text(original_content, encoding="utf-8")
            print(f"[evolution_executor] ❌ All iterations failed, rolled back")

            return {
                "success": False,
                "change_id": change_id,
                "backup_path": str(backup_path),
                "message": f"Failed after {iterations_used} iteration(s). Rolled back.",
                "iterations": iterations_used,
                "test_results": test_results,
            }

    except Exception as e:
        print(f"[evolution_executor] ❌ Failed: {e}")
        # Rollback on exception
        try:
            target_path.write_text(original_content, encoding="utf-8")
        except:
            pass
        return {
            "success": False,
            "change_id": change_id,
            "backup_path": None,
            "message": str(e),
            "iterations": iterations_used,
            "test_results": test_results,
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
