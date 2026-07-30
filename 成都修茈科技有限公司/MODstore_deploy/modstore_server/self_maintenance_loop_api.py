"""Self-maintenance loop runtime status API."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query

from modstore_server.api.deps import require_admin
from modstore_server.models import User
from modstore_server.self_maintenance_loop_runner import (
    get_self_maintenance_runtime_status,
    record_governance_audit_review,
    run_self_maintenance_loop,
)

router = APIRouter(prefix="/api/ops/self-maintenance", tags=["ops"])


def _deployment_receipt_token_valid(
    authorization: str | None,
    x_autonomy_token: str | None,
) -> bool:
    expected = (
        os.environ.get("AUTONOMY_WEBHOOK_TOKEN")
        or os.environ.get("MODSTORE_OPS_INGEST_TOKEN")
        or ""
    ).strip()
    bearer = str(authorization or "").strip()
    if bearer.lower().startswith("bearer "):
        bearer = bearer[7:].strip()
    provided = bearer or str(x_autonomy_token or "").strip()
    return bool(expected and provided and secrets.compare_digest(expected, provided))


def _release_manifest_payload() -> Dict[str, Any]:
    configured = str(os.environ.get("MODSTORE_RELEASE_MANIFEST") or "").strip()
    path = Path(configured) if configured else Path("/opt/xcmax/current/.xcmax-release.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(409, "release_manifest_unavailable") from exc
    if not isinstance(payload, dict):
        raise HTTPException(409, "release_manifest_invalid")
    return payload


def _git_is_ancestor(ancestor: str, descendant: str) -> bool:
    repo_root = Path(
        os.environ.get("MODSTORE_SELF_MAINTENANCE_PROJECT_ROOT") or "/root/XCMAX"
    ).expanduser()
    commits = (str(ancestor or "").strip().lower(), str(descendant or "").strip().lower())
    if any(
        len(commit) not in {40, 64}
        or any(character not in "0123456789abcdef" for character in commit)
        for commit in commits
    ):
        return False

    def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def _commit_available(commit: str) -> bool:
        return _run_git("cat-file", "-e", f"{commit}^{{commit}}").returncode == 0

    try:
        # The production checkout normally fetches only main. A reviewed branch
        # head may therefore be absent after squash/rebase even though the signed
        # GitHub receipt carries its exact SHA. Fetch only missing immutable
        # commit objects, then perform the same local ancestry check.
        for commit in commits:
            if _commit_available(commit):
                continue
            fetched = _run_git("fetch", "--quiet", "--no-tags", "origin", commit)
            if fetched.returncode != 0 or not _commit_available(commit):
                return False
        result = _run_git("merge-base", "--is-ancestor", *commits)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


@router.get("/status", summary="Self-maintenance loop runtime status")
async def get_self_maintenance_status(
    limit: int = Query(default=80, ge=1, le=300),
):
    """Read the scheduler/ledger/memory state consumed by the loop."""

    return get_self_maintenance_runtime_status(limit=limit)


@router.post("/run", summary="Force-run one self-maintenance loop transaction")
async def force_run_self_maintenance_loop(
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
):
    """Admin break-glass: run one loop cycle now (force=True bypasses cooldown gate)."""

    reason = str(body.get("reason") or "admin_force_run").strip() or "admin_force_run"
    # Force break-glass: do not stall on a busy Mac codex currentTask.
    prev_busy = os.environ.get("MODSTORE_SELF_MAINTENANCE_ALLOW_BUSY_DEVICE")
    prev_wait = os.environ.get("MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_WAIT_SEC")
    os.environ["MODSTORE_SELF_MAINTENANCE_ALLOW_BUSY_DEVICE"] = "1"
    os.environ["MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_WAIT_SEC"] = (
        prev_wait if (prev_wait or "").strip() else "15"
    )
    try:
        result = run_self_maintenance_loop(
            triggered_by=f"admin:{getattr(admin_user, 'id', '') or 'unknown'}",
            force=True,
            reason=reason,
        )
    finally:
        if prev_busy is None:
            os.environ.pop("MODSTORE_SELF_MAINTENANCE_ALLOW_BUSY_DEVICE", None)
        else:
            os.environ["MODSTORE_SELF_MAINTENANCE_ALLOW_BUSY_DEVICE"] = prev_busy
        if prev_wait is None:
            os.environ.pop("MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_WAIT_SEC", None)
        else:
            os.environ["MODSTORE_SELF_MAINTENANCE_DEVICE_ONLINE_WAIT_SEC"] = prev_wait
    return {"ok": True, "result": result}


@router.post(
    "/deployment-receipt",
    summary="Record an exact production workflow and runtime identity receipt",
)
async def record_self_maintenance_deployment_receipt(
    body: Dict[str, Any] = Body(default_factory=dict),
    authorization: str | None = Header(default=None),
    x_autonomy_token: str | None = Header(default=None, alias="X-Autonomy-Token"),
):
    """Signed GitHub callback; unrelated deploys are an idempotent no-op."""

    if not _deployment_receipt_token_valid(authorization, x_autonomy_token):
        raise HTTPException(401, "invalid_deployment_receipt_token")

    from modstore_server.deploy_context import health_payload
    from modstore_server.self_maintenance_deploy_receipts import (
        BuildIdentity,
        DeploymentReceiptError,
        record_completed_deployment_receipt,
    )
    from modstore_server.self_maintenance_loop_runner import (
        _append_governance_audit,
        _append_ledger,
        _read_ledger,
        _record_verified_deploy_employee_metric,
    )

    observed_at = datetime.now(timezone.utc).isoformat()

    def _record(event: Dict[str, Any]) -> None:
        event = {**event, "created_at": str(event.get("created_at") or observed_at)}
        _append_ledger(event)
        _append_governance_audit(
            {
                **event,
                "kind": str(event.get("event") or "deployment_receipt"),
            }
        )
        _record_verified_deploy_employee_metric(event)

    try:
        result = record_completed_deployment_receipt(
            rows=_read_ledger(limit=5000),
            record_event=_record,
            merge_sha=str(body.get("merge_sha") or ""),
            environment=str(body.get("environment") or "production"),
            workflow_run_id=str(body.get("workflow_run_id") or ""),
            workflow_status=str(body.get("workflow_status") or ""),
            workflow_conclusion=str(body.get("workflow_conclusion") or ""),
            release=BuildIdentity.from_payload(_release_manifest_payload()),
            health=BuildIdentity.from_payload(health_payload()),
            is_ancestor=_git_is_ancestor,
            requested_run_id=str(body.get("run_id") or ""),
            attested_branch=str(body.get("attested_branch") or ""),
            attested_branch_head_sha=str(body.get("attested_branch_head_sha") or ""),
            attested_pr_number=str(body.get("attested_pr_number") or ""),
            workflow_url=str(body.get("workflow_url") or ""),
            action_id=str(body.get("action_id") or ""),
            observed_at=observed_at,
        )
    except DeploymentReceiptError as exc:
        if exc.reason == "pending_merge_not_found":
            return {
                "ok": True,
                "recorded": False,
                "reason": exc.reason,
            }
        raise HTTPException(409, exc.reason) from exc
    return result


@router.post(
    "/evolution-deployment-receipt",
    summary="Verify changed employee packs against the live production catalog",
)
async def record_modstore_evolution_deployment_receipt(
    body: Dict[str, Any] = Body(default_factory=dict),
    authorization: str | None = Header(default=None),
    x_autonomy_token: str | None = Header(default=None, alias="X-Autonomy-Token"),
):
    """Signed deploy callback; fails closed unless all runtime identities agree."""

    if not _deployment_receipt_token_valid(authorization, x_autonomy_token):
        raise HTTPException(401, "invalid_deployment_receipt_token")
    if str(body.get("workflow_status") or "").lower() != "completed":
        raise HTTPException(409, "workflow_not_completed")
    if str(body.get("workflow_conclusion") or "").lower() != "success":
        raise HTTPException(409, "workflow_not_successful")
    packages = body.get("packages")
    if not isinstance(packages, list) or any(not isinstance(item, dict) for item in packages):
        raise HTTPException(422, "packages_must_be_object_list")

    from modstore_server.deploy_context import health_payload
    from modstore_server.modstore_evolution_deploy_receipts import (
        EvolutionDeploymentReceiptError,
        record_evolution_deployment_receipts,
    )
    from modstore_server.self_maintenance_deploy_receipts import (
        BuildIdentity,
        DeploymentReceiptError,
        verify_deployed_identity,
    )
    from modstore_server.self_maintenance_loop_runner import (
        _append_governance_audit,
        _append_ledger,
        _read_ledger,
    )

    merge_sha = str(body.get("merge_sha") or "")
    try:
        verify_deployed_identity(
            merge_sha=merge_sha,
            release=BuildIdentity.from_payload(_release_manifest_payload()),
            health=BuildIdentity.from_payload(health_payload()),
        )
    except DeploymentReceiptError as exc:
        raise HTTPException(409, exc.reason) from exc

    observed_at = datetime.now(timezone.utc).isoformat()

    def _record(event: Dict[str, Any]) -> None:
        event = {**event, "created_at": str(event.get("created_at") or observed_at)}
        _append_ledger(event)
        _append_governance_audit(
            {
                **event,
                "kind": str(event.get("event_type") or "evolution_deployment_receipt"),
            }
        )

    try:
        return record_evolution_deployment_receipts(
            packages=packages,
            merge_sha=merge_sha,
            workflow_run_id=str(body.get("workflow_run_id") or ""),
            rows=_read_ledger(limit=20_000),
            record_event=_record,
        )
    except EvolutionDeploymentReceiptError as exc:
        raise HTTPException(409, exc.reason) from exc


@router.post("/governance-review", summary="Acknowledge self-maintenance governance audit")
async def review_self_maintenance_governance(
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
):
    """Append a human review audit entry to recover from governance_degraded."""

    return record_governance_audit_review(
        note=str(body.get("note") or ""),
        admin_user_id=getattr(admin_user, "id", None),
    )
