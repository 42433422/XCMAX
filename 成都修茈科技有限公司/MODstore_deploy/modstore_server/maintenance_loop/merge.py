"""Execute only policy-authorized branch merges and record exact receipts."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import unquote, urlparse

from modstore_server import self_maintenance_subprocess
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, merge_policy, para_client, review, store
from . import workspace as workspace_domain


def _github_repository(repo_url: str) -> Optional[str]:
    try:
        parsed = urlparse(repo_url)
    except ValueError:
        return None
    repository = parsed.path.strip("/").removesuffix(".git")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.params
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
        or any(part in {".", ".."} for part in repository.split("/"))
    ):
        return None
    return repository


def _auto_merge_low_risk_branch(
    *,
    run_id: str,
    task_id: Optional[str],
    branch: Optional[str],
    steps: Optional[List[Dict[str, Any]]] = None,
    checkpoint: Optional[Callable[[dict], None]] = None,
    deployment_scope: Optional[dict] = None,
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
        if checkpoint is not None and (
            _github_repository(repo_url) is None
            or not re.fullmatch(r"[0-9a-f]{40}", str(branch_head_sha or ""))
            or not re.fullmatch(r"[0-9a-f]{40}", str(base_head_sha or ""))
        ):
            return {"ok": False, "reason": "original_merge_readback_unavailable"}
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
        if checkpoint is not None:
            checkpoint(
                {
                    "kind": "remote_merge",
                    "run_id": run_id,
                    "task_id": task_id,
                    "repo_url": repo_url,
                    "api_base": api_base,
                    "base_branch": base_branch,
                    "branch": branch,
                    "base_head_sha": base_head_sha or "",
                    "branch_head_sha": branch_head_sha or "",
                    "risk_decision": decision.to_dict(),
                }
            )
        try:
            request_result = para_client._request_para_task_merge(
                api_base=api_base, task_id=task_id
            )
        except RECOVERABLE_ERRORS as exc:
            if checkpoint is not None:
                # The original request may already be accepted. Its durable
                # intent is recovered only by exact task/commit readback.
                raise
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
            **({"deployment_scope": deployment_scope} if deployment_scope is not None else {}),
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
            checkpoint=checkpoint,
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
    checkpoint: Optional[Callable[[dict], None]] = None,
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
    if checkpoint is not None:
        checkpoint(
            {
                "kind": "local_merge",
                "run_id": run_id,
                "task_id": task_id,
                "repo_url": repo_url,
                "api_base": api_base,
                "base_branch": base_branch,
                "branch": branch,
                "merge_commit_sha": merge_sha,
                "branch_head_sha": workspace_domain._run_cmd(
                    ["git", "rev-parse", f"origin/{branch}"], cwd=workspace
                ),
                "base_head_sha": workspace_domain._run_cmd(
                    ["git", "rev-parse", f"origin/{base_branch}"], cwd=workspace
                ),
                "risk_decision": decision.to_dict(),
                "policy": {**policy, "diff_excerpt": diff_excerpt, "kb_validation": kb_validation},
            }
        )
    _push_proc = subprocess.run(
        ["git", "push", "origin", f"HEAD:{base_branch}"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if _push_proc.returncode != 0:
        if checkpoint is not None:
            raise RuntimeError("original_merge_push_requires_readback")
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


def _readback_original_merge(intent: dict) -> dict:
    """Recover a frozen authorized merge from its original repository, read-only."""
    repo_url = str(intent.get("repo_url") or "")
    api_base = str(intent.get("api_base") or "")
    base = str(intent.get("base_branch") or "")
    branch = str(intent.get("branch") or "")
    task_id = str(intent.get("task_id") or "")
    head = str(intent.get("branch_head_sha") or "")
    authorization = intent.get("risk_decision") or {}
    if (
        not task_id
        or not branch
        or not base
        or repo_url != os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
        or api_base != os.environ.get("MODSTORE_PARA_API_BASE", "").strip()
        or base != os.environ.get("MODSTORE_PARA_BRANCH", "").strip()
        or not re.fullmatch(r"[0-9a-f]{40}", head)
        or not re.fullmatch(r"[0-9a-f]{40}", str(intent.get("base_head_sha") or ""))
        or not isinstance(authorization, dict)
        or authorization.get("allowed") is not True
        or authorization.get("prohibited") is True
        or authorization.get("action") != "self_maintenance_l1_merge"
        or authorization.get("action_id")
        != f"loop:{intent.get('run_id')}:self_maintenance_l1_merge"
    ):
        raise ValueError("original_merge_binding_unavailable")
    if intent.get("kind") == "local_merge" and repo_url.startswith("file://"):
        sha = str(intent.get("merge_commit_sha") or "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("original_merge_sha_unavailable")
        parsed = urlparse(repo_url)
        if parsed.netloc not in {"", "localhost"}:
            raise ValueError("original_local_merge_repository_mismatch")
        repo = Path(unquote(parsed.path))
        # Check the actual published base, not an abandoned candidate workspace.
        workspace_domain._run_cmd(
            ["git", "merge-base", "--is-ancestor", sha, f"refs/heads/{base}"], cwd=repo
        )
        parents = workspace_domain._run_cmd(["git", "show", "-s", "--format=%P", sha], cwd=repo)
        if parents.split() != [intent["base_head_sha"], head]:
            raise ValueError("original_merge_parent_mismatch")
        result = {**(intent.get("policy") or {}), "merge_commit_sha": sha}
    elif intent.get("kind") == "remote_merge":
        from modstore_server.self_maintenance_deploy_receipts import GhActionsDeploymentGateway

        repository = _github_repository(repo_url)
        if repository is None:
            raise ValueError("original_merge_repository_unverifiable")
        task = para_client._fetch_para_task_state(api_base, task_id)
        sha = str(task.get("merge_commit_sha") or "")
        if (
            task.get("id") != task_id
            or task.get("status") != "merged"
            or not re.fullmatch(r"[0-9a-f]{40}", sha)
        ):
            raise ValueError("original_merge_not_observed")
        gateway = GhActionsDeploymentGateway(
            repo_root=Path(os.environ.get("MODSTORE_GIT_REPO_ROOT") or "."),
            repository=repository,
            ref=base,
        )
        prs = gateway._json(["gh", "api", f"repos/{repository}/commits/{sha}/pulls?per_page=100"])
        if not isinstance(prs, list) or len(prs) >= 100:
            raise ValueError("original_merge_attestation_incomplete")
        matches = [
            pr
            for pr in prs
            if isinstance(pr, dict)
            and pr.get("merged_at")
            and pr.get("merge_commit_sha") == sha
            and (pr.get("head") or {}).get("ref") == branch
            and (pr.get("head") or {}).get("sha") == head
            and (pr.get("base") or {}).get("ref") == base
            and all(
                ((pr.get(side) or {}).get("repo") or {}).get("full_name") == repository
                for side in ("head", "base")
            )
        ]
        comparison = gateway._json(["gh", "api", f"repos/{repository}/compare/{sha}...{base}"])
        base_comparison = gateway._json(
            ["gh", "api", f"repos/{repository}/compare/{intent['base_head_sha']}...{sha}"]
        )
        if (
            len(matches) != 1
            or not isinstance(comparison, dict)
            or (
                comparison.get("status") not in {"ahead", "identical"}
                or (comparison.get("merge_base_commit") or {}).get("sha") != sha
            )
            or not isinstance(base_comparison, dict)
            or base_comparison.get("status") not in {"ahead", "identical"}
            or (base_comparison.get("merge_base_commit") or {}).get("sha")
            != intent["base_head_sha"]
        ):
            raise ValueError("original_merge_attestation_mismatch")
        result = {"merge_commit_sha": sha, "github_pull_request": matches[0].get("number")}
    else:
        raise ValueError("original_merge_kind_unavailable")
    return {
        **result,
        "ok": True,
        "recovered": True,
        "branch": branch,
        "branch_head_sha": head,
        "base_head_sha": intent["base_head_sha"],
        "reason": "original_published_merge_verified",
    }
