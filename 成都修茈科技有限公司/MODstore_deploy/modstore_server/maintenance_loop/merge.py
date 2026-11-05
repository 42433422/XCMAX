"""Execute only policy-authorized branch merges and record exact receipts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server import self_maintenance_subprocess
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, merge_policy, para_client, review, store
from . import workspace as workspace_domain


def _auto_merge_low_risk_branch(
    *,
    run_id: str,
    task_id: Optional[str],
    branch: Optional[str],
    steps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not task_id or not branch:
        return {"ok": False, "reason": "missing_task_or_branch"}
    repo_url = os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
    api_base = os.environ.get("MODSTORE_PARA_API_BASE", "").strip()
    allow_remote = config._env_bool("MODSTORE_AUTO_MERGE_ALLOW_REMOTE", False)
    if not repo_url.startswith("file://") and (
        not (allow_remote and repo_url.startswith(("http://", "https://")))
    ):
        return {"ok": False, "reason": "repo_url_not_file_url", "repo_url": repo_url}
    if not base_branch:
        return {"ok": False, "reason": "missing_base_branch"}
    if not api_base:
        return {"ok": False, "reason": "missing_api_base"}
    if repo_url.startswith(("http://", "https://")):
        report_gate = review._structured_report_gate(steps or [], branch)
        if not report_gate.get("ok"):
            return {
                "ok": False,
                "reason": report_gate.get("reason") or "structured_reports_not_passed",
                "structured_report_gate": report_gate,
            }
        branch_head_sha = workspace_domain._remote_branch_head(repo_url, branch)
        base_head_sha = workspace_domain._remote_branch_head(repo_url, base_branch)
        if base_head_sha and branch_head_sha == base_head_sha:
            return {
                "ok": False,
                "reason": "remote_branch_not_advanced",
                "branch": branch,
                "branch_head_sha": branch_head_sha,
            }
        head_verification = (
            "verified_on_cvm" if branch_head_sha else "delegated_to_para_merge_worker"
        )
        from modstore_server.autonomy_guard_delegate import evaluate_risk

        decision = evaluate_risk(
            "self_maintenance_l1_merge",
            action_id=f"loop:{run_id}:self_maintenance_l1_merge",
            source="self_maintenance_loop.remote_merge_request",
        )
        if not decision.allowed:
            return {
                "ok": False,
                "reason": "autonomy_guard_blocked",
                "risk_decision": decision.to_dict(),
            }
        try:
            request_result = para_client._request_para_task_merge(
                api_base=api_base, task_id=task_id
            )
        except RECOVERABLE_ERRORS as exc:
            return {
                "ok": False,
                "error": str(exc)[:500],
                "reason": "para_merge_request_failed",
                "risk_decision": decision.to_dict(),
            }
        merge_request_record = {
            "base_branch": base_branch,
            "base_head_sha": base_head_sha or "",
            "branch": branch,
            "branch_head_sha": branch_head_sha or "",
            "created_at": config._iso(config._utc_now()),
            "event": "merge_requested",
            "head_verification": head_verification,
            "ok": True,
            "para_task_id": task_id,
            "phase": "merge",
            "run_id": run_id,
            "status": "pending",
        }
        store._append_ledger(merge_request_record)
        store._append_governance_audit({**merge_request_record, "kind": "merge_requested"})
        return {
            "ok": True,
            "base_head_sha": base_head_sha or "",
            "branch_head_sha": branch_head_sha or "",
            "head_verification": head_verification,
            "merge_requested": True,
            "para_request": request_result,
            "reason": "merge_requested_after_loop_risk_gate",
            "risk_decision": decision.to_dict(),
            "structured_report_gate": report_gate,
        }
    workspace = config._runtime_dir() / config.DEFAULT_MERGE_WORKSPACE_ROOT / run_id
    try:
        return _auto_merge_local_repo(
            api_base=api_base,
            base_branch=base_branch,
            branch=branch,
            repo_url=repo_url,
            run_id=run_id,
            steps=steps,
            task_id=task_id,
            workspace=workspace,
        )
    finally:
        workspace_domain._cleanup_merge_workspace(workspace)


def _auto_merge_local_repo(
    *,
    api_base: str,
    base_branch: str,
    branch: str,
    repo_url: str,
    run_id: str,
    steps: Optional[List[Dict[str, Any]]],
    task_id: str,
    workspace: Path,
) -> Dict[str, Any]:
    from modstore_server.autonomy_guard_delegate import evaluate_risk

    decision = evaluate_risk(
        "self_maintenance_l1_merge",
        action_id=f"loop:{run_id}:self_maintenance_l1_merge",
        source="self_maintenance_loop.auto_merge",
    )
    if not decision.allowed:
        return {
            "ok": False,
            "reason": "autonomy_guard_blocked",
            "risk_decision": decision.to_dict(),
        }
    files = workspace_domain._changed_files_for_branch(
        repo_url=repo_url, base_branch=base_branch, branch=branch, workspace=workspace
    )
    if not files:
        return {
            "ok": False,
            "reason": "branch_not_on_remote_or_empty",
            "branch": branch,
            "changed_files": [],
        }
    diff_stats = workspace_domain._diff_numstat_for_branch(
        base_branch=base_branch, branch=branch, workspace=workspace
    )
    diff_excerpt = self_maintenance_subprocess.run_cmd_excerpt(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--find-renames",
            "--unified=3",
            f"origin/{base_branch}...origin/{branch}",
        ],
        cwd=workspace,
        timeout=180,
        max_chars=20000,
    )
    kb_validation = workspace_domain._validate_kb_json_changes_for_auto_merge(
        branch=branch, files=files, workspace=workspace
    )
    if not kb_validation.get("ok"):
        return {
            "changed_files": files,
            "kb_validation": kb_validation,
            "ok": False,
            "reason": "kb_json_schema_validation_failed",
        }
    policy = merge_policy._assess_branch_auto_merge_policy(
        files,
        diff_stats,
        diff_excerpt=diff_excerpt,
        kb_validation=kb_validation,
        memory=store._load_loop_memory(),
        steps=steps,
    )
    if not policy.get("ok"):
        return policy
    workspace_domain._run_cmd(
        ["git", "merge", "--no-ff", "--no-edit", f"origin/{branch}"], cwd=workspace
    )
    merge_sha = workspace_domain._run_cmd(["git", "rev-parse", "HEAD"], cwd=workspace)
    _push_proc = subprocess.run(
        ["git", "push", "origin", f"HEAD:{base_branch}"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if _push_proc.returncode != 0:
        return {
            "ok": False,
            "reason": "push_to_origin_failed",
            "merge_sha": merge_sha,
            "push_stderr": (_push_proc.stderr or "")[:500],
            "branch": branch,
        }
    para_update = para_client._mark_para_task_merged(
        api_base=api_base, task_id=task_id, merge_sha=merge_sha
    )
    return {
        **policy,
        "diff_excerpt": diff_excerpt,
        "kb_validation": kb_validation,
        "merge_commit_sha": merge_sha,
        "ok": True,
        "para_update": para_update,
        "reason": "merged_low_risk_branch",
        "workspace": str(workspace),
    }
