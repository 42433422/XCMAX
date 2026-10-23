"""Dispatch deployment and record verified post-merge receipts."""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from modstore_server import models
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, store


def _auto_dispatch_deploy_envs() -> List[str]:
    """Return ordered deploy envs when auto-dispatch master switch is on.

    默认仅 staging；production 必须显式写在 ENVS 中才会出现。
    staging always precedes production when both are requested.
    """
    if not config._auto_dispatch_deploy_enabled():
        return []
    raw = str(
        os.environ.get("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY_ENVS", "") or ""
    ).strip()
    if not raw:
        return ["staging"]
    requested: List[str] = []
    for part in raw.split(","):
        env = part.strip().lower()
        if env in {"staging", "production"} and env not in requested:
            requested.append(env)
    return [env for env in ("staging", "production") if env in requested]


def _dispatch_fhd_deploy_action(*, environment: str, action: str, action_id: str) -> Dict[str, Any]:
    """Dispatch ``fhd-deploy.yml`` via ``gh workflow run`` (or dry-run skip)."""
    gh_command = f"gh workflow run fhd-deploy.yml -f environment={environment} -f action={action} -f action_id={action_id}"
    deploy_cwd = os.environ.get("MODSTORE_GIT_REPO_ROOT") or None
    if config._env_flag_enabled("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY_DRY_RUN"):
        return {
            "ok": True,
            "reason": "dry_run_skipped",
            "environment": environment,
            "action": action,
            "gh_command": gh_command,
            "gh_output": "",
            "gh_exit_code": 0,
            "action_id": action_id,
            "deploy_cwd": deploy_cwd,
        }
    try:
        proc = subprocess.run(
            [
                "gh",
                "workflow",
                "run",
                "fhd-deploy.yml",
                "-f",
                f"environment={environment}",
                "-f",
                f"action={action}",
                "-f",
                f"action_id={action_id}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            cwd=deploy_cwd,
        )
        ok = proc.returncode == 0
        output = f"{proc.stdout or ''}{proc.stderr or ''}".strip()
        return {
            "ok": ok,
            "reason": "dispatched" if ok else "gh_non_zero_exit",
            "environment": environment,
            "action": action,
            "gh_command": gh_command,
            "gh_output": output,
            "gh_exit_code": int(proc.returncode),
            "action_id": action_id,
            "deploy_cwd": deploy_cwd,
        }
    except RECOVERABLE_ERRORS as exc:
        return {
            "ok": False,
            "reason": f"dispatch_threw:{exc}",
            "environment": environment,
            "action": action,
            "gh_command": gh_command,
            "gh_output": str(exc),
            "gh_exit_code": -1,
            "action_id": action_id,
        }


def _dispatch_deploy_for_merge(
    *, run_id: str, branch: str, environments: List[str]
) -> List[Dict[str, Any]]:
    """Apply-latest per env after low-risk merge; freeze and stop on first failure."""
    results: List[Dict[str, Any]] = []
    for environment in environments:
        action_id = f"loop:{run_id}:deploy:{environment}"
        result = _dispatch_fhd_deploy_action(
            environment=environment, action="apply-latest", action_id=action_id
        )
        record = {
            "event": "deploy_dispatch",
            "run_id": run_id,
            "branch": branch,
            "environment": environment,
            "action": "apply-latest",
            "ok": bool(result.get("ok")),
            "reason": result.get("reason"),
            "action_id": action_id,
            "gh_command": result.get("gh_command"),
            "gh_exit_code": result.get("gh_exit_code"),
        }
        try:
            store._append_ledger(record)
        except RECOVERABLE_ERRORS:
            config.logger.exception("failed to append deploy_dispatch ledger")
        try:
            store._append_governance_audit({**record, "kind": "deploy_dispatch"})
        except RECOVERABLE_ERRORS:
            config.logger.exception("failed to append deploy_dispatch governance audit")
        results.append(result)
        if result.get("ok"):
            continue
        freeze_id = f"loop:{run_id}:freeze:{environment}"
        freeze_result = _dispatch_fhd_deploy_action(
            environment=environment, action="freeze-manifest", action_id=freeze_id
        )
        freeze_record = {
            "event": "deploy_freeze",
            "run_id": run_id,
            "branch": branch,
            "environment": environment,
            "action": "freeze-manifest",
            "ok": bool(freeze_result.get("ok")),
            "reason": freeze_result.get("reason"),
            "action_id": freeze_id,
            "triggered_by": action_id,
        }
        try:
            store._append_ledger(freeze_record)
        except RECOVERABLE_ERRORS:
            config.logger.exception("failed to append deploy_freeze ledger")
        try:
            store._append_governance_audit({**freeze_record, "kind": "deploy_freeze"})
        except RECOVERABLE_ERRORS:
            config.logger.exception("failed to append deploy_freeze governance audit")
        try:
            _emit_deploy_callback(
                phase="dispatch_failed",
                payload={
                    **record,
                    "freeze_ok": bool(freeze_result.get("ok")),
                    "freeze_action_id": freeze_id,
                },
                action_id=action_id,
            )
            _emit_deploy_callback(
                phase="freeze_manifest", payload=freeze_record, action_id=freeze_id
            )
        except RECOVERABLE_ERRORS:
            config.logger.exception("failed to emit deploy_callback after freeze")
        break
    return results


def _emit_deploy_callback(
    *,
    phase: str,
    payload: Dict[str, Any],
    action_id: Optional[str] = None,
) -> None:
    """Fail-open 调用 FHD autonomy deploy_callback（或等价 ingest HTTP）。"""
    try:
        autonomy_scripts = Path(__file__).resolve().parents[4] / "FHD" / "scripts" / "autonomy"
        candidates = [
            autonomy_scripts,
            Path(os.environ.get("XCAGI_FHD_RUNTIME_ROOT", "")) / "scripts" / "autonomy",
            Path(__file__).resolve().parents[3] / "FHD" / "scripts" / "autonomy",
        ]
        for candidate in candidates:
            if candidate and (candidate / "autonomy_callback.py").is_file():
                if str(candidate) not in sys.path:
                    sys.path.insert(0, str(candidate))
                callback_module = importlib.import_module("autonomy_callback")
                deploy_callback = getattr(callback_module, "deploy_callback")
                deploy_callback(phase, payload, source="self_maintenance", action_id=action_id)
                return
    except RECOVERABLE_ERRORS:
        config.logger.debug("deploy_callback import path failed", exc_info=True)
    base_url = (os.environ.get("FHD_API_BASE_URL") or "").strip()
    token = (
        os.environ.get("AUTONOMY_WEBHOOK_TOKEN")
        or os.environ.get("MODSTORE_OPS_INGEST_TOKEN")
        or ""
    ).strip()
    if not base_url or not token:
        return
    body: Dict[str, Any] = {
        "action": f"deploy:{phase}",
        "payload": {**payload, "callback_event": f"deploy:{phase}"},
        "source": "self_maintenance",
    }
    if action_id:
        body["action_id"] = action_id
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(
                f"{base_url.rstrip('/')}/api/ops/autonomy/actions/ingest",
                headers={"X-Autonomy-Token": token, "Content-Type": "application/json"},
                json=body,
            )
    except RECOVERABLE_ERRORS:
        config.logger.debug("deploy_callback HTTP fallback failed", exc_info=True)


def _record_verified_deploy_employee_metric(
    record: Dict[str, Any],
) -> bool:
    """Credit the release officer only for an exact verified production deploy.

    Dispatch acceptance, staging success and uncorrelated health checks are not
    employee evidence.  The deterministic task marker makes callback retries
    idempotent.
    """
    if not (
        str(record.get("event") or "") == "post_deploy_verified"
        and str(record.get("environment") or "").strip().lower() == "production"
        and (record.get("ok") is True)
        and (record.get("identity_verified") is True)
        and (str(record.get("status") or "").strip().lower() == "verified")
    ):
        return False
    run_id = str(record.get("run_id") or "").strip()
    merge_sha = str(record.get("merge_sha") or "").strip().lower()
    workflow_run_id = str(record.get("workflow_run_id") or "").strip()
    if not run_id or not re.fullmatch("[0-9a-f]{40,64}", merge_sha) or (not workflow_run_id):
        return False
    marker = f"[deploy-receipt:{run_id}:{merge_sha[:12]}:{workflow_run_id}]"[:128]
    try:
        sf = models.get_session_factory()
        with sf() as session:
            exists = (
                session.query(models.EmployeeExecutionMetric.id)
                .filter(
                    models.EmployeeExecutionMetric.employee_id == "deploy-release-officer",
                    models.EmployeeExecutionMetric.task == marker,
                    models.EmployeeExecutionMetric.status == "success",
                )
                .first()
            )
            if exists:
                return False
            user = (
                session.query(models.User)
                .filter(models.User.is_admin.is_(True))
                .order_by(models.User.id.asc())
                .first()
                or session.query(models.User).order_by(models.User.id.asc()).first()
            )
            if user is None:
                config.logger.warning("deploy receipt metric skipped: no user row")
                return False
            session.add(
                models.EmployeeExecutionMetric(
                    user_id=int(user.id),
                    employee_id="deploy-release-officer",
                    task=marker,
                    status="success",
                    duration_ms=0.0,
                    llm_tokens=0,
                    error="",
                    failure_kind="",
                )
            )
            session.commit()
        return True
    except RECOVERABLE_ERRORS:
        config.logger.exception("failed to record verified deploy release employee metric")
        return False


def _append_deploy_receipt_event(record: Dict[str, Any]) -> None:
    """Write the same deployment receipt to loop and governance ledgers."""
    store._append_ledger(record)
    store._append_governance_audit(
        {**record, "kind": str(record.get("event") or "deployment_receipt")}
    )
    _record_verified_deploy_employee_metric(record)


def _run_deploy_receipts_after_merge(
    *, run_id: str, merge_result: Dict[str, Any]
) -> Dict[str, Any]:
    """Run staging receipts only after a concrete pushed merge.

    This path is inert by default. It uses a new switch so a legacy dispatch
    flag cannot silently activate it. Production requires its own explicit
    switch and remains gated on a verified staging receipt.
    """
    if not config._env_bool("MODSTORE_SELF_MAINTENANCE_DEPLOY_RECEIPTS_ENABLED", False):
        return {"enabled": False, "reason": "deploy_receipts_disabled"}
    if bool(merge_result.get("merge_requested")):
        return {"enabled": True, "ok": False, "reason": "merge_not_completed"}
    merge_sha = str(merge_result.get("merge_commit_sha") or "").strip()
    if not merge_sha:
        return {"enabled": True, "ok": False, "reason": "merge_sha_missing"}
    repo_root_text = str(os.environ.get("MODSTORE_GIT_REPO_ROOT") or "").strip()
    deploy_ref = str(
        os.environ.get("MODSTORE_SELF_MAINTENANCE_DEPLOY_REF")
        or os.environ.get("MODSTORE_PARA_BRANCH")
        or ""
    ).strip()
    try:
        from modstore_server.self_maintenance_deploy_receipts import (
            GhActionsDeploymentGateway,
            run_staged_deployment_chain,
        )

        gateway = GhActionsDeploymentGateway.from_environment(
            repo_root=Path(repo_root_text).expanduser(), ref=deploy_ref
        )
        result = run_staged_deployment_chain(
            gateway=gateway,
            record_event=_append_deploy_receipt_event,
            run_id=run_id,
            merge_sha=merge_sha,
            allow_production=config._env_bool(
                "MODSTORE_SELF_MAINTENANCE_PRODUCTION_DEPLOY_ENABLED", False
            ),
        )
        return {"enabled": True, **result}
    except RECOVERABLE_ERRORS as exc:
        failure = {
            "event": "deploy_verification_failed",
            "phase": "deployment",
            "run_id": run_id,
            "merge_sha": merge_sha,
            "environment": "staging",
            "status": "failed",
            "ok": False,
            "reason": "deploy_receipt_setup_failed",
            "error_type": type(exc).__name__,
        }
        _append_deploy_receipt_event(failure)
        return {"enabled": True, "ok": False, "reason": "deploy_receipt_setup_failed"}
