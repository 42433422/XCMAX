# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _run_deploy_receipts_after_merge(
    *, run_id: str, merge_result: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    """Run staging receipts only after a concrete pushed merge.

    This path is inert by default. It uses a new switch so a legacy dispatch
    flag cannot silently activate it. Production requires its own explicit
    switch and remains gated on a verified staging receipt.
    """
    if not _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_DEPLOY_RECEIPTS_ENABLED", False):
        return {"enabled": False, "reason": "deploy_receipts_disabled"}
    if bool(merge_result.get("merge_requested")):
        return {"enabled": True, "ok": False, "reason": "merge_not_completed"}
    merge_sha = str(merge_result.get("merge_commit_sha") or "").strip()
    if not merge_sha:
        return {"enabled": True, "ok": False, "reason": "merge_sha_missing"}
    repo_root_text = str(_facade().os.environ.get("MODSTORE_GIT_REPO_ROOT") or "").strip()
    deploy_ref = str(
        _facade().os.environ.get("MODSTORE_SELF_MAINTENANCE_DEPLOY_REF")
        or _facade().os.environ.get("MODSTORE_PARA_BRANCH")
        or ""
    ).strip()
    try:
        from modstore_server.self_maintenance_deploy_receipts import (
            GhActionsDeploymentGateway,
            run_staged_deployment_chain,
        )

        gateway = GhActionsDeploymentGateway.from_environment(
            repo_root=_facade().Path(repo_root_text).expanduser(), ref=deploy_ref
        )
        result = run_staged_deployment_chain(
            gateway=gateway,
            record_event=_facade()._append_deploy_receipt_event,
            run_id=run_id,
            merge_sha=merge_sha,
            allow_production=_facade()._env_bool(
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
        _facade()._append_deploy_receipt_event(failure)
        return {"enabled": True, "ok": False, "reason": "deploy_receipt_setup_failed"}
