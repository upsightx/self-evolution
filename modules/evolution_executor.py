#!/usr/bin/env python3
"""
Evolution Executor — 进化执行器。

职责：
- 根据改进建议自动生成代码/配置补丁
- 执行变更前创建备份
- 支持回滚

工作流程：
1. 接收改进建议（来自 auto_evolve / proposal_lifecycle_manager）
2. 确定目标文件（模块模板、配置文件等）
3. 用 LLM 生成具体变更
4. 写入文件（带备份）
5. 记录变更日志

设计原则：
- 每次只改一个文件
- 变更前有备份，支持回滚
- 变更日志写入 proposals 表（via proposal_lifecycle_manager）

- 所有状态操作委托 proposal_lifecycle_manager
"""
from __future__ import annotations

import ast
import json
import os
import py_compile
import sys
import shutil
from datetime import datetime
from pathlib import Path

from bootstrap import ensure_workspace_on_path, ensure_xmemory_on_path, module_dir, module_workspace

_workspace = ensure_workspace_on_path()
_modules = module_dir()
ensure_xmemory_on_path()

from db_common import get_db

# Workspace root
WORKSPACE = module_workspace()

# Protected files that require manual approval
PROTECTED_FILES = {
    "X-Memory/memory_db.py",
    "X-Memory/memory_store.py",
    "X-Memory/memory_retrieval.py",
    "X-Memory/memory_service.py",
    "self-evolution/modules/goal_tree.py",
    "self-evolution/modules/capability_model.py",
    "self-evolution/modules/feedback_loop.py",
    "self-evolution/modules/causal_validator.py",
    "self-evolution/modules/auto_evolve.py",
    "self-evolution/modules/critic_engine.py",
    "self-evolution/modules/evolution_executor.py",
    "self-evolution/modules/evolution_orchestrator.py",
    "self-evolution/modules/proposal_lifecycle_manager.py",
    "HEARTBEAT.md",
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

PLACEHOLDER_PATTERNS = [
    "TODO: implement",
    "pass  # placeholder",
    "pass # placeholder",
    "your code here",
    "implementation omitted",
    "pseudo-code",
    "pseudocode",
]

MAX_SIZE_SHRINK_RATIO = 0.40
MAX_LINE_CHANGE_RATIO = 0.50



def classify_change_risk(target_file: str, operation: str = "modify") -> str:
    """Classify change risk for future automation gates.

    This is advisory only: it does not grant execution permission.
    High-risk changes still require explicit human approval.
    """
    normalized = (target_file or "").strip()
    op = (operation or "modify").lower()

    if op in {"delete", "move", "overwrite"}:
        return "high"

    if normalized in PROTECTED_FILES:
        return "high"

    if normalized.startswith("self-evolution/modules/") and normalized.endswith(".py"):
        return "high"

    if normalized in {"AGENTS.md", "SOUL.md", "HEARTBEAT.md", "runtime_config.py"}:
        return "high"

    if normalized.startswith("memory/") and normalized.endswith(".md"):
        return "low"

    if normalized.startswith("memory/learning/") and normalized.endswith(".md"):
        return "low"

    if normalized.startswith("tmp/") or normalized.startswith("projects/"):
        return "low"

    if normalized.endswith(("README.md", ".md")):
        return "medium"

    if normalized.startswith("skills/") or "/skills/" in normalized:
        return "medium"

    if normalized.startswith("tests/"):
        return "medium"

    return "medium"

def register_external_learning_proposal(
    proposal_id: str,
    summary: str,
    target_scope: str = "",  # COMPAT: param named target_module historically; renamed to target_scope per schema
    change_description: str = "",
) -> dict:
    """Register an external learning proposal.

    Delegates to proposal_lifecycle_manager (single source of truth).

    Args:
        proposal_id: Unique ID for the proposal
        summary: Proposal summary
        target_scope: Target file path (schema: target_scope = file path, target_module = task type)
        change_description: Human-readable description

    Returns:
        {"success": bool, "change_id": str or None, "message": str}
    """
    change_id = f"ext_{proposal_id}_{datetime.now().strftime('%Y%m%d')}"

    try:
        from proposal_lifecycle_manager import create_proposal
        result = create_proposal(
            proposal_id=change_id,
            title=summary[:100],
            summary=summary,
            category="external_learning",
            source_type="external_learning",
            source_ref=proposal_id,
            target_scope=target_scope,
            target_module="external_learning",
            change_description=change_description,
            initial_status="draft",
        )
        if result.get("success"):
            print(f"[evolution_executor] ✅ Registered proposal: {change_id}")
        return {
            "success": result.get("success", False),
            "change_id": change_id,
            "message": result.get("message", ""),
        }
    except Exception as e:
        return {"success": False, "change_id": None, "message": str(e)}


def _generate_patch_with_llm(suggestion: str, target_content: str, task_type: str) -> str | None:
    """Use LLM to generate a code patch based on the suggestion.

    Delegates to llm_provider for unified provider management and fallback.

    Args:
        suggestion: Improvement suggestion from auto_evolve / proposal lifecycle
        target_content: Current content of the target file
        task_type: Task type being improved (e.g., 'coding')

    Returns:
        Modified content, or None if generation failed
    """
    try:
        from llm_provider import generate_code_patch
        return generate_code_patch(
            suggestion=suggestion,
            current_code=target_content,
            task_type=task_type,
        )
    except ImportError:
        print("[evolution_executor] llm_provider not available, skipping patch generation")
        return None


def _validate_workspace_path(target_file: str) -> dict:
    """Ensure target_file stays inside the workspace."""
    try:
        target_path = (WORKSPACE / target_file).resolve()
        target_path.relative_to(WORKSPACE.resolve())
        return {"safe": True, "path": target_path, "reason": "Path is inside workspace"}
    except Exception:
        return {"safe": False, "path": None, "reason": f"Path escapes workspace: {target_file}"}


def _check_diff_sanity(original_content: str, new_content: str) -> dict:
    """Block truncation, noisy rewrites, and placeholder-only patches."""
    if not new_content.strip():
        return {"safe": False, "reason": "New content is empty"}

    original_len = len(original_content)
    new_len = len(new_content)
    if original_len and new_len < original_len * MAX_SIZE_SHRINK_RATIO:
        return {"safe": False, "reason": "New content shrinks file by more than 60%"}

    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.lower() in new_content.lower():
            return {"safe": False, "reason": f"Contains placeholder pattern: {pattern}"}

    if "�" in new_content:
        return {"safe": False, "reason": "Contains Unicode replacement characters"}

    old_lines = original_content.splitlines()
    new_lines = new_content.splitlines()
    if old_lines:
        changed = sum(1 for i, line in enumerate(new_lines[:len(old_lines)]) if old_lines[i] != line)
        changed += abs(len(new_lines) - len(old_lines))
        if changed / max(len(old_lines), 1) > MAX_LINE_CHANGE_RATIO:
            return {"safe": False, "reason": "Line changes exceed 30% of file"}

    return {"safe": True, "reason": "Diff sanity passed"}


def _validate_syntax_or_format(target_file: str, new_content: str) -> dict:
    """Run cheap syntax checks before writing generated content."""
    if target_file.endswith(".py"):
        try:
            ast.parse(new_content)
        except SyntaxError as e:
            return {"safe": False, "reason": f"Python syntax error: {e}"}
    elif target_file.endswith(".json"):
        try:
            json.loads(new_content)
        except json.JSONDecodeError as e:
            return {"safe": False, "reason": f"JSON syntax error: {e}"}

    return {"safe": True, "reason": "Syntax check passed"}


def _check_safety(target_file: str, new_content: str, original_content: str = "") -> dict:
    """Check if the change is safe to apply.

    Args:
        target_file: Path to the file being modified
        new_content: New content to write
        original_content: Existing file content for diff sanity checks

    Returns:
        {
            "safe": bool,
            "reason": str,
        }
    """
    path_check = _validate_workspace_path(target_file)
    if not path_check["safe"]:
        return path_check

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

    if original_content:
        diff_check = _check_diff_sanity(original_content, new_content)
        if not diff_check["safe"]:
            return diff_check

    syntax_check = _validate_syntax_or_format(target_file, new_content)
    if not syntax_check["safe"]:
        return syntax_check

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
        suggestion: Improvement suggestion from auto_evolve / proposal lifecycle
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
        test_passed = False
        new_content = None
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
            safety = _check_safety(target_file, new_content, current_content)
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
            if target_file.endswith(".py"):
                try:
                    py_compile.compile(str(target_path), doraise=True)
                except py_compile.PyCompileError as e:
                    test_passed = False
                    test_results.append({
                        "iteration": iteration,
                        "status": "failed",
                        "stderr": str(e)[:200],
                    })
                    print(f"  ❌ py_compile failed: {str(e)[:100]}")
                    refined_suggestion = f"""
Previous attempt failed Python compilation:
{str(e)[:500]}

Original suggestion: {suggestion}

Please fix the issue and regenerate the patch.
"""
                    current_content = new_content
                    continue

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
                    test_passed = True
                    print(f"  ✅ Test passed")
                    break  # Success, exit loop
            else:
                # No test script, assume success
                test_passed = True
                print(f"  ✅ Patch generated (no test)")
                break

        # Final result
        if test_passed and new_content:
            # Record in proposals table (primary) via lifecycle manager
            # NOTE: Stay in 'experimenting' — do NOT advance to 'validated'.
            # Validation requires post-deployment sample collection by causal_validator.
            try:
                from proposal_lifecycle_manager import create_proposal
                create_proposal(
                    proposal_id=change_id,
                    title=f"Applied: {change_description or suggestion[:60]}",
                    summary=suggestion,
                    category=task_type,
                    source_type="evolution_executor",
                    target_scope=target_file,
                    change_description=change_description,
                    initial_status="experimenting",
                )
            except Exception:
                pass

            print(f"[evolution_executor] ✅ Applied change #{change_id} ({iterations_used} iteration(s))")
            print(f"  File: {target_file}")
            print(f"  Backup: {backup_path}")

            # Log event
            try:
                from evolution_runtime import log_event
                log_event("change_applied", change_id, {
                    "target_file": target_file,
                    "task_type": task_type,
                    "iterations": iterations_used,
                })
            except Exception:
                pass

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
            if 'original_content' in dir():
                target_path.write_text(original_content, encoding="utf-8")
        except Exception:
            pass
        return {
            "success": False,
            "change_id": change_id,
            "backup_path": None,
            "message": str(e),
            "iterations": iterations_used,
            "test_results": test_results,
        }


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


def rollback(change_id: str) -> dict:
    """Rollback a previously applied change.

    Uses proposals table (via proposal_lifecycle_manager) for status.
    Uses backup files for actual file restoration.

    Args:
        change_id: The change ID to rollback

    Returns:
        {
            "success": bool,
            "message": str,
        }
    """
    try:
        from proposal_lifecycle_manager import get_proposal
        proposal = get_proposal(change_id)
    except Exception:
        return {"success": False, "message": f"Proposal {change_id} not found"}

    if not proposal or not proposal.get("proposal_id"):
        return {"success": False, "message": f"Change {change_id} not found"}

    # Schema contract: target_scope = file path, target_module = task/capability type
    target_scope = proposal.get("target_scope", "") or proposal.get("target_module", "")
    if not target_scope:
        return {"success": False, "message": f"No target file (target_scope) recorded for {change_id}"}

    target_path = WORKSPACE / target_scope

    # Find backup
    backup_dir = WORKSPACE / "memory" / "evolution_backups"
    if not backup_dir.exists():
        return {"success": False, "message": "Backup directory not found"}

    # Find most recent backup for this target
    stem = Path(target_scope).stem
    candidates = sorted(backup_dir.glob(f"{stem}_*{Path(target_scope).suffix}"), reverse=True)
    if not candidates:
        return {"success": False, "message": f"No backup found for {target_scope}"}

    backup_path = candidates[0]

    try:
        shutil.copy2(backup_path, target_path)
    except Exception as e:
        return {"success": False, "message": f"Restore failed: {e}"}

    # Transition via proposal_lifecycle_manager
    try:
        from proposal_lifecycle_manager import transition
        transition(change_id, "failed", actor="evolution_executor",
                  reason="Rolled back by executor")
    except Exception:
        pass

    print(f"[evolution_executor] ✅ Rolled back change #{change_id}")

    # Log event
    try:
        from evolution_runtime import log_event
        log_event("change_rolled_back", change_id, {"backup_path": str(backup_path)})
    except Exception:
        pass

    return {"success": True, "message": f"Rolled back to {backup_path}"}


# ============ LEGACY READ-ONLY: evolution_changes queries ============
# These functions read from evolution_changes for backward compatibility
# with historical data. NO WRITES to this table.

def list_changes(status: str | None = None) -> list[dict]:
    """List evolution changes (LEGACY READ-ONLY from evolution_changes table).

    Args:
        status: Filter by status (applied, verified, rolled_back)

    Returns:
        List of change records from legacy table
    """
    db = get_db()
    try:
        # Check if table exists
        cols = {r[1] for r in db.execute("PRAGMA table_info(evolution_changes)").fetchall()}
        if not cols:
            return []

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


def test_change_in_sandbox(
    change_id: str,
    test_script: str,
    dependencies: list[str] | None = None,
) -> dict:
    """Test a previously applied change in Docker sandbox.

    Uses proposals table for lookup. Sandbox execution only.

    Args:
        change_id: The change ID to test
        test_script: Python test code to run
        dependencies: Optional pip dependencies

    Returns:
        Test result dict (same format as run_in_sandbox)
    """
    print(f"[sandbox] Testing change {change_id}...")
    result = run_in_sandbox(test_script, dependencies=dependencies)
    result["change_id"] = change_id
    return result


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
    p_list = sub.add_parser("list", help="List changes (legacy)")
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
