"""Authenticated completion receipt recording workflow."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping

from modstore_server.deployment_receipt_history import completed_receipt
from modstore_server.self_maintenance_deploy_receipts import (
    AncestorCheck,
    BuildIdentity,
    DeploymentReceiptError,
    EventSink,
    _environment,
    _merge_sha,
    _sha,
    resolve_pending_merge_request,
    verify_deployed_identity,
)


def record_completed_deployment_receipt(
    *,
    rows: Iterable[Mapping[str, Any]],
    record_event: EventSink,
    merge_sha: str,
    environment: str,
    workflow_run_id: str,
    workflow_status: str,
    workflow_conclusion: str,
    release: BuildIdentity,
    health: BuildIdentity,
    is_ancestor: AncestorCheck,
    requested_run_id: str = "",
    attested_branch: str = "",
    attested_branch_head_sha: str = "",
    attested_pr_number: str = "",
    workflow_url: str = "",
    action_id: str = "",
    observed_at: str = "",
) -> Dict[str, Any]:
    """Record an authenticated workflow completion against one pending loop.

    GitHub's callback is only an execution attestation.  The deployed release
    and health identities are independently read by the server and must expose
    the same exact merge SHA and artifact digest before any scoreable rows are
    appended.
    """

    normalized_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
    merge_sha = _merge_sha(merge_sha)
    environment = _environment(environment)
    workflow_run_id = str(workflow_run_id or "").strip()
    if not workflow_run_id:
        raise DeploymentReceiptError("dispatch_missing_workflow_run_id")
    if str(workflow_status or "").strip().lower() != "completed":
        raise DeploymentReceiptError("workflow_not_completed")
    if str(workflow_conclusion or "").strip().lower() != "success":
        raise DeploymentReceiptError("workflow_not_successful")

    existing = completed_receipt(
        normalized_rows,
        merge_sha=merge_sha,
        environment=environment,
        workflow_run_id=workflow_run_id,
        requested_run_id=requested_run_id,
    )
    if existing is not None:
        previous_workflow_run_id = str(existing.get("workflow_run_id") or "")
        if previous_workflow_run_id != workflow_run_id:
            # A second successful deployment for the same loop/SHA is a valid
            # idempotent retry, but it must still expose the exact runtime
            # identity before the new workflow may be acknowledged.
            verify_deployed_identity(merge_sha=merge_sha, release=release, health=health)
        run_id = str(existing.get("run_id") or "")
        merge_recorded = any(
            row.get("event") == "merge_completed"
            and row.get("ok") is True
            and str(row.get("run_id") or "") == run_id
            and _sha(row.get("merge_sha")) == merge_sha
            for row in normalized_rows
        )
        if not merge_recorded:
            record_event(
                {
                    **existing,
                    "event": "merge_completed",
                    "phase": "merge",
                    "status": "completed_merged",
                    "ok": True,
                }
            )
        return {
            "ok": True,
            "recorded": False,
            "idempotent": True,
            "run_id": run_id,
            "merge_sha": merge_sha,
            "environment": environment,
            "workflow_run_id": workflow_run_id,
            "previous_workflow_run_id": previous_workflow_run_id,
        }

    pending = resolve_pending_merge_request(
        normalized_rows,
        merge_sha=merge_sha,
        is_ancestor=is_ancestor,
        requested_run_id=requested_run_id,
        attested_branch=attested_branch,
        attested_branch_head_sha=attested_branch_head_sha,
    )
    identity = verify_deployed_identity(merge_sha=merge_sha, release=release, health=health)
    run_id = str(pending.get("run_id") or "").strip()
    branch_head_sha = _sha(pending.get("branch_head_sha"))
    action_id = str(action_id or "").strip() or (
        f"loop:{run_id}:deploy:{environment}:{merge_sha[:12]}"
    )
    correlation: Dict[str, Any] = {
        "action_id": action_id,
        "attested_pr_number": str(attested_pr_number or "").strip(),
        "branch": str(pending.get("branch") or ""),
        "branch_head_sha": branch_head_sha,
        "created_at": str(observed_at or ""),
        "environment": environment,
        "merge_sha": merge_sha,
        "para_task_id": str(pending.get("para_task_id") or ""),
        "head_verification": str(pending.get("head_verification") or "git_ancestry"),
        "run_id": run_id,
        "workflow_run_id": workflow_run_id,
        "workflow_url": str(workflow_url or ""),
    }
    events = [
        {
            **correlation,
            "event": "deploy_dispatch",
            "phase": "deployment",
            "status": "accepted",
            "ok": True,
            "verification_state": "completed",
        },
        {
            **correlation,
            **identity,
            "event": "post_deploy_verified",
            "phase": "deployment",
            "status": "verified",
            "ok": True,
            "identity_verified": True,
        },
        {
            **correlation,
            "event": "merge_completed",
            "phase": "merge",
            "status": "completed_merged",
            "ok": True,
        },
    ]
    for event in events:
        record_event(event)
    return {
        "ok": True,
        "recorded": True,
        "idempotent": False,
        "run_id": run_id,
        "merge_sha": merge_sha,
        "environment": environment,
        "workflow_run_id": workflow_run_id,
        **identity,
    }
