from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable


PythonResolver = Callable[[], str]
GitRootResolver = Callable[[Path], Path | None]
GitCommand = Callable[[Path, str], str]


def run_real_absorption_cli(
    own: Path,
    source: str,
    external_path: Path | None,
    tasks: list[dict[str, str]],
    external_assessment: dict[str, Any],
    payload: dict[str, Any],
    *,
    resolve_python: PythonResolver,
    package_root: Path,
) -> dict[str, Any]:
    if not truthy(payload.get("execute_absorption", True)):
        return {"status": "disabled", "summary": "Real CLI absorption is disabled for this request.", "changed_files": [], "gates": [], "gates_passed": False}
    if external_path is None or not external_path.is_dir():
        return {"status": "skipped_no_external_project", "summary": "External project is not available locally.", "changed_files": [], "gates": [], "gates_passed": False}
    request_dir = own / ".retort" / "execution_requests"
    request_dir.mkdir(parents=True, exist_ok=True)
    request_path = request_dir / f"{os.urandom(16).hex()}.json"
    request_payload = {
        "own_project": str(own),
        "source": source,
        "external_path": str(external_path),
        "tasks": tasks,
        "external_assessment": external_assessment,
        "run_local_gates": bool(payload.get("run_local_gates")),
        "employee_queue": str(payload.get("employee_queue") or ""),
        "history_store": str(payload.get("history_store") or ""),
        "python": resolve_python(),
    }
    request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    cmd = [resolve_python(), "-m", "retort_engine.cli", "apply-absorption", "--payload-file", str(request_path), "--json"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(package_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    timeout = int(payload.get("execution_timeout_sec") or 1800)
    try:
        result = subprocess.run(cmd, cwd=own, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "summary": f"Real CLI absorption exceeded {timeout} seconds.",
            "command": cmd,
            "changed_files": [],
            "gates": [],
            "gates_passed": False,
            "stdout_tail": _timeout_text(exc.stdout),
            "stderr_tail": _timeout_text(exc.stderr),
        }
    parsed = extract_json_from_stdout(result.stdout)
    if not parsed:
        return {
            "status": "failed",
            "summary": "Real CLI absorption did not return JSON.",
            "command": cmd,
            "exit_code": result.returncode,
            "changed_files": [],
            "gates": [],
            "gates_passed": False,
            "stdout_tail": result.stdout[-4000:],
            "stderr_tail": result.stderr[-4000:],
        }
    parsed["command"] = cmd
    parsed["exit_code"] = result.returncode
    if result.stderr:
        parsed["stderr_tail"] = result.stderr[-4000:]
    return parsed


def extract_json_from_stdout(stdout: str) -> dict[str, Any]:
    try:
        parsed = json.loads(stdout.strip())
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and is_complete_absorption_stdout_json(parsed):
        return parsed
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and is_complete_absorption_stdout_json(value):
            candidates.append(value)
    return candidates[-1] if candidates else {}


def is_complete_absorption_stdout_json(value: dict[str, Any]) -> bool:
    required = {
        "status",
        "project",
        "summary",
        "changed_files",
        "gates",
        "gates_passed",
        "review_report_path",
        "employee_results_path",
    }
    return required.issubset(value) and isinstance(value.get("changed_files"), list) and isinstance(value.get("gates"), list)


def commit_absorption_execution(
    own: Path,
    source: str,
    execution: dict[str, Any],
    *,
    git_root: GitRootResolver,
    git_command: GitCommand,
) -> dict[str, Any]:
    root = git_root(own)
    changed_files = [Path(path).expanduser().resolve() for path in execution.get("changed_files") or []]
    if root is None or not changed_files:
        return {"status": "skipped", "reason": "no_git_root_or_no_changed_files"}
    rels = [str(path.relative_to(root)) for path in changed_files if path.is_relative_to(root)]
    if not rels:
        return {"status": "skipped", "reason": "no_changed_files_inside_git_root"}
    git_command(root, "add", "--", *rels)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet", "--", *rels], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, timeout=30, check=False).returncode != 0
    if not staged:
        return {"status": "skipped", "reason": "no_staged_changes"}
    git_command(root, "commit", "-m", f"Retort absorb {source[:80]}")
    commit = git_command(root, "rev-parse", "--short", "HEAD").strip()
    return {"status": "committed", "commit": commit, "files": rels}


def block_merge_after_failed_gates(
    own: Path,
    branch_state: dict[str, Any],
    *,
    git_root: GitRootResolver,
    git_command: GitCommand,
) -> dict[str, Any]:
    root = git_root(own)
    updated = {
        **branch_state,
        "merged": False,
        "status": "merge_blocked_by_gates",
        "error": "Absorption gates failed; refusing to merge absorption branch into the main project.",
    }
    base = str(branch_state.get("base_branch") or "")
    if root is None or not base:
        return updated
    try:
        git_command(root, "checkout", base)
        return {**updated, "returned_to_base_branch": True}
    except RuntimeError as exc:
        return {**updated, "returned_to_base_branch": False, "return_error": str(exc)}


def absorption_status(tasks: list[dict[str, str]], execution: dict[str, Any]) -> str:
    if execution.get("status") == "applied":
        return "absorption_execution_applied"
    if execution.get("status") in {"failed", "timeout"}:
        return "absorption_execution_failed"
    return "tasks_generated" if tasks else "no_external_advantage_found"


def absorption_summary(tasks: list[dict[str, str]], execution: dict[str, Any]) -> str:
    if execution.get("status") == "applied":
        return f"Real CLI absorption changed {len(execution.get('changed_files') or [])} file(s) after generating {len(tasks)} task(s)."
    if execution.get("status") in {"failed", "timeout"}:
        return f"Generated {len(tasks)} task(s), but real CLI absorption failed: {execution.get('summary', '')}"
    return f"Generated {len(tasks)} absorption task(s). Retort now requires PaiBi LLM reassessment before any score is shown."


def truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "no", "disabled"}
    return bool(value)


def _timeout_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")[-4000:]
    if isinstance(value, str):
        return value[-4000:]
    return ""
