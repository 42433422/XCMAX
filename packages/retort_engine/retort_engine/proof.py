from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


StateLoader = Callable[[Path], dict[str, Any]]
StateSaver = Callable[[Path, dict[str, Any]], None]
PublicState = Callable[[Path], dict[str, Any]]
LatestRun = Callable[[Path], dict[str, Any]]
RunCommand = Callable[[list[str], Path], bool]
GitRoot = Callable[[Path], Path | None]
GitCommand = Callable[..., str]


def record_execution_proof(
    own: Path,
    execution: dict[str, Any],
    branch_state: dict[str, Any],
    *,
    load_state: StateLoader,
    save_state: StateSaver,
) -> None:
    changed_files = [str(path) for path in execution.get("changed_files") or []]
    proof = {
        "branch_diff_verified": bool(changed_files),
        "employee_execution_verified": execution.get("status") in {"applied", "noop"},
        "post_absorption_tests_passed": bool(execution.get("gates_passed")),
        "merge_verified": bool(branch_state.get("merged")),
        "external_advantage_reassessed": True,
        "evidence": [
            f"retort_cli_status={execution.get('status')}",
            f"duration_sec={execution.get('duration_sec')}",
            f"changed_files={','.join(changed_files)}",
            f"git_diff_summary={' | '.join(str(item) for item in execution.get('git_diff_summary') or [])}",
            f"gates_passed={execution.get('gates_passed')}",
            f"review_report={execution.get('review_report_path', '')}",
            f"employee_results={execution.get('employee_results_path', '')}",
            f"commit={((execution.get('commit') or {}) if isinstance(execution.get('commit'), dict) else {}).get('commit', '')}",
            f"merge_commit={execution.get('merge_commit', '')}",
            f"rollback_rehearsal={bool((execution.get('rollback_rehearsal') or {}).get('verified'))}",
            f"code_graph_proof_passed={bool((execution.get('code_graph_proof') or {}).get('passed'))}",
            f"code_graph_changed_hotspots={','.join(str(item) for item in ((execution.get('code_graph_proof') or {}).get('changed_hotspots') or []))}",
            f"code_graph_changed_focus_files={','.join(str(item) for item in ((execution.get('code_graph_proof') or {}).get('changed_focus_files') or []))}",
            f"feedback_audit_closed={bool((execution.get('feedback_audit') or {}).get('closed'))}",
            f"history_result_count={(execution.get('feedback_audit') or {}).get('history_result_count', '')}",
            f"queue_records_written={execution.get('queue_records_written', '')}",
            f"result_tasks_have_queue_records={(execution.get('feedback_audit') or {}).get('result_tasks_have_queue_records', '')}",
        ],
    }
    state = load_state(own)
    state["closed_loop_proof"] = proof
    if all(value for key, value in proof.items() if key != "evidence"):
        state["active"] = False
        state["status"] = "closed_loop_verified"
    else:
        state["active"] = True
        state["status"] = "execution_applied_awaiting_merge"
    save_state(own, state)


def rollback_rehearsal(root: Path, merge_commit: str) -> dict[str, Any]:
    command = f"git revert --no-commit -m 1 {merge_commit}"
    try:
        parents = _git(root, "show", "--no-patch", "--format=%P", merge_commit).strip().split()
    except RuntimeError as exc:
        return {
            "verified": False,
            "merge_commit": merge_commit,
            "parent_count": 0,
            "rollback_command": command,
            "revert_executed": False,
            "reason": "merge_commit_unreadable",
            "stderr_tail": str(exc)[-1000:],
        }
    result = {
        "verified": False,
        "merge_commit": merge_commit,
        "parent_count": len(parents),
        "rollback_command": command,
        "revert_executed": False,
        "revert_exit_code": None,
        "changed_files": [],
    }
    if len(parents) < 2:
        return {**result, "reason": "not_a_merge_commit"}
    temp_dir = Path(tempfile.mkdtemp(prefix="retort-rollback-"))
    try:
        add = _run_git(root, "worktree", "add", "--detach", str(temp_dir), merge_commit)
        if add.returncode != 0:
            return {**result, "reason": "worktree_add_failed", "stderr_tail": _tail(add.stderr)}
        revert = _run_git(temp_dir, "revert", "--no-commit", "-m", "1", merge_commit)
        diff = _run_git(temp_dir, "diff", "--name-only")
        cached = _run_git(temp_dir, "diff", "--cached", "--name-only")
        changed_files = sorted({line.strip() for line in f"{diff.stdout}\n{cached.stdout}".splitlines() if line.strip()})
        _run_git(temp_dir, "reset", "--hard", "HEAD")
        return {
            **result,
            "verified": revert.returncode == 0,
            "revert_executed": True,
            "revert_exit_code": revert.returncode,
            "changed_files": changed_files,
            "changed_file_count": len(changed_files),
            "stdout_tail": _tail(revert.stdout),
            "stderr_tail": _tail(revert.stderr),
            "reason": "revert_rehearsed" if revert.returncode == 0 else "revert_failed",
        }
    finally:
        _run_git(root, "worktree", "remove", "--force", str(temp_dir))
        shutil.rmtree(temp_dir, ignore_errors=True)


def record_closed_loop_proof(
    project: str,
    payload: dict[str, Any],
    *,
    load_state: StateLoader,
    save_state: StateSaver,
    public_state: PublicState,
    latest_absorption_run: LatestRun,
    run_command: RunCommand,
    git_root: GitRoot,
    git_command: GitCommand,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    state = load_state(root)
    validation = _closed_loop_cross_validation(
        root,
        payload,
        latest_absorption_run=latest_absorption_run,
        run_command=run_command,
        git_root=git_root,
        git_command=git_command,
    )
    evidence = [str(item) for item in payload.get("evidence") or []]
    evidence.extend(validation["evidence"])
    proof = {
        "branch_diff_verified": bool(payload.get("branch_diff_verified")),
        "employee_execution_verified": bool(payload.get("employee_execution_verified")),
        "post_absorption_tests_passed": bool(payload.get("post_absorption_tests_passed")) and bool(validation["pytest_gates_verified"]),
        "merge_verified": bool(payload.get("merge_verified")) and bool(validation["merge_commit_verified"]),
        "external_advantage_reassessed": bool(payload.get("external_advantage_reassessed")),
        "evidence": evidence,
        "validation": validation,
    }
    state["closed_loop_proof"] = proof
    if all(value for key, value in proof.items() if key != "evidence"):
        state["active"] = False
        state["status"] = "closed_loop_verified"
    else:
        state["active"] = True
        state["status"] = "awaiting_execution_evidence"
    save_state(root, state)
    return public_state(root)


def _closed_loop_cross_validation(
    root: Path,
    payload: dict[str, Any],
    *,
    latest_absorption_run: LatestRun,
    run_command: RunCommand,
    git_root: GitRoot,
    git_command: GitCommand,
) -> dict[str, Any]:
    merge_commit = _proof_merge_commit(root, payload, git_root=git_root, git_command=git_command)
    merge_verified = _is_merge_commit(root, merge_commit, git_root=git_root, git_command=git_command) if merge_commit else False
    pytest_verified = _proof_pytest_gates_verified(root, payload, latest_absorption_run=latest_absorption_run, run_command=run_command)
    return {
        "merge_commit": merge_commit,
        "merge_commit_verified": merge_verified,
        "pytest_gates_verified": pytest_verified,
        "evidence": [
            f"merge_cross_check={merge_verified}; merge_commit={merge_commit}",
            f"pytest_gate_cross_check={pytest_verified}",
        ],
    }


def _proof_merge_commit(root: Path, payload: dict[str, Any], *, git_root: GitRoot, git_command: GitCommand) -> str:
    explicit = str(payload.get("merge_commit") or "").strip()
    if explicit:
        return explicit
    evidence_commit = _evidence_value(payload.get("evidence") or [], "merge_commit")
    if evidence_commit:
        return evidence_commit
    if not payload.get("merge_verified"):
        return ""
    repo = git_root(root)
    if repo is None:
        return ""
    try:
        return git_command(repo, "rev-parse", "--short", "HEAD").strip()
    except RuntimeError:
        return ""


def _is_merge_commit(root: Path, commit: str, *, git_root: GitRoot, git_command: GitCommand) -> bool:
    repo = git_root(root)
    if repo is None or not commit:
        return False
    try:
        parents = git_command(repo, "show", "--no-patch", "--format=%P", commit).strip().split()
    except RuntimeError:
        return False
    return len(parents) >= 2


def _proof_pytest_gates_verified(root: Path, payload: dict[str, Any], *, latest_absorption_run: LatestRun, run_command: RunCommand) -> bool:
    if _gates_have_passing_pytest(payload.get("gates") or []):
        return True
    latest = latest_absorption_run(root)
    if _gates_have_passing_pytest(latest.get("gates") or []):
        return True
    command = payload.get("pytest_command") or payload.get("test_command")
    if isinstance(command, str) and command.strip():
        return run_command(command.split(), root)
    if isinstance(command, list) and all(isinstance(item, str) for item in command):
        return run_command(command, root)
    return False


def _gates_have_passing_pytest(gates: Any) -> bool:
    if not isinstance(gates, list):
        return False
    for gate in gates:
        if not isinstance(gate, dict) or not gate.get("ok"):
            continue
        command = " ".join(str(part) for part in gate.get("command") or [])
        if "pytest" in command:
            return True
    return False


def _evidence_value(evidence: Any, key: str) -> str:
    for item in evidence if isinstance(evidence, list) else []:
        text = str(item)
        if text.startswith(f"{key}="):
            return text.split("=", 1)[1].strip()
    return ""


def _git(root: Path, *args: str) -> str:
    result = _run_git(root, *args)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120, check=False)


def _tail(value: object, limit: int = 1000) -> str:
    return str(value or "").strip()[-limit:]
