"""Playwright adapter using the existing Agent authority, ledger and artifact store."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from app.application.tools.surface_authority import require_surface_authority
from app.domain.browser_contract import BrowserExecute, BrowserObserve
from app.domain.browser_receipt import mark_delivery_incomplete
from app.utils.operational_errors import RECOVERABLE_ERRORS

MAX_ARTIFACT_BYTES = 25 * 1024 * 1024


def allowed_origins(tenant_id: str) -> frozenset[str]:
    """Operator policy is per tenant, never supplied by the model or webpage."""
    policy = json.loads(os.environ.get("XCAGI_BROWSER_ALLOWED_ORIGINS", "{}"))
    raw = policy.get(tenant_id, []) if isinstance(policy, dict) else []
    if not isinstance(raw, list) or not raw:
        raise ValueError("browser sites are not configured for this tenant")
    origins: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("invalid browser origin policy")
        url = urlsplit(item)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or "*" in item
        ):
            raise ValueError("browser policy must contain exact HTTP(S) origins")
        origins.add(f"{url.scheme}://{url.netloc.lower()}")
    return frozenset(origins)


def _uploads(plan: dict, owner_id: int, tenant_id: str) -> None:
    from app.application.agent_orchestrator.artifact_files import (
        artifact_path,
        read_verified_run_file,
    )
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository

    total = 0
    for step in plan.get("steps", []):
        if step["action"] != "upload":
            continue
        files = []
        for reference in step["files"]:
            run = get_agent_run_repository().get(reference["run_id"])
            context = run.metadata.get("runtime_context", {}) if run else {}
            if (
                run is None
                or str(context.get("user_id") or "") != str(owner_id)
                or str(context.get("tenant_id") or "") != tenant_id
            ):
                raise PermissionError("upload artifact belongs to another account or tenant")
            artifact = next(
                (a for a in run.artifacts if a.artifact_id == reference["artifact_id"]), None
            )
            if artifact is None or artifact.artifact_type != "file":
                raise ValueError("upload artifact is not available")
            if (
                artifact_path(run.run_id, artifact.artifact_id).stat().st_size
                > MAX_ARTIFACT_BYTES - total
            ):
                raise ValueError("browser upload limit exceeded")
            content = read_verified_run_file(run.run_id, artifact.to_dict())
            total += len(content)
            if total > MAX_ARTIFACT_BYTES:
                raise ValueError("browser upload limit exceeded")
            files.append(
                {"name": artifact.name, "mime_type": artifact.mime_type, "buffer": content}
            )
        step["files"] = files


def _persist_artifacts(
    result: dict,
    root: Path,
    run_id: str,
    owner_id: int,
    tenant_id: str,
    binding: dict | None = None,
) -> None:
    from app.application.agent_orchestrator.artifact_files import (
        RUN_FILE_MIME_TYPES,
        store_run_file,
    )

    persisted: list[dict] = []
    binding = binding or {}

    def store(content: bytes, name: str) -> dict:
        artifact = store_run_file(
            run_id, content, name=name, owner_user_id=owner_id, tenant_id=tenant_id
        )
        artifact["metadata"].update(
            run_id=run_id,
            owner_user_id=str(owner_id),
            tenant_id=tenant_id,
            step_id=binding.get("step_id"),
            call_id=binding.get("call_id"),
            params_sha256=binding.get("input_sha256"),
        )
        return artifact

    unsaved = []
    for item in result.pop("artifacts", []):
        evidence: dict = {"name": Path(item["name"]).name, "status": "not_saved"}
        error_code = "browser_artifact_invalid"
        try:
            path = Path(item["path"])
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("browser artifact is outside its task directory")
            if not path.is_file() or path.stat().st_size > MAX_ARTIFACT_BYTES:
                raise ValueError("browser artifact size is invalid")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError("browser artifact checksum mismatch")
            evidence.update(sha256=item["sha256"], size_bytes=len(content))
            if Path(item["name"]).suffix.lower() not in RUN_FILE_MIME_TYPES:
                error_code = "browser_artifact_format_unsupported"
                raise ValueError("unsupported run file format")
            error_code = "browser_artifact_storage_failed"
            persisted.append(store(content, item["name"]))
        except RECOVERABLE_ERRORS:
            unsaved.append({**evidence, "error_code": error_code})
    result["artifacts"] = persisted
    if unsaved:
        result["unsaved_artifacts"] = unsaved
        mark_delivery_incomplete(result, "browser_artifact_persistence_failed")
    # An attachment failure must not discard evidence of completed browser effects.
    receipt = {k: v for k, v in result.items() if k not in {"artifacts", "snapshot"}}
    from app.domain.browser_receipt import evidence_hash

    receipt.update(run_id=run_id, artifacts=persisted, binding=binding)
    if "snapshot" in result:
        receipt["snapshot_sha256"] = evidence_hash(result["snapshot"])
    try:
        persisted.append(
            store(
                json.dumps(receipt, ensure_ascii=False, allow_nan=False).encode(),
                "browser-receipt.json",
            )
        )
    except RECOVERABLE_ERRORS:
        mark_delivery_incomplete(result, "browser_receipt_persistence_failed")


def execute_browser(action: str, params: dict, context: dict) -> dict:
    if action not in {"observe", "execute"}:
        return {"success": False, "error_code": "browser_action_unknown"}
    try:
        request = (BrowserObserve if action == "observe" else BrowserExecute).model_validate(params)
        actor, run = require_surface_authority(
            "browser", action, params, context, approval_required=action == "execute"
        )
        origins = allowed_origins(str(context["tenant_id"]))
        from app.application.tool_execution_deadline import remaining_invocation_seconds
        from app.infrastructure.browser.runtime import execute_browser_plan

        plan = request.model_dump(exclude_none=True)
        plan["observe"] = action == "observe"
        _uploads(plan, int(actor.id), str(context["tenant_id"]))
    except (ValidationError, ValueError, PermissionError, ImportError):
        return {
            "success": False,
            "error_code": "browser_not_authorized_or_configured",
            "execution_status": "not_started",
            "retryable": False,
            "message": "浏览器任务的参数、身份、审批或站点配置未通过校验，未执行。",
        }

    def recheck_authority() -> None:
        require_surface_authority(
            "browser", action, params, context, approval_required=action == "execute"
        )

    try:
        budget = remaining_invocation_seconds(120.0)
        if budget <= 0:
            raise TimeoutError("browser deadline expired")
        with tempfile.TemporaryDirectory(prefix="xcagi-browser-") as temporary:
            root = Path(temporary)
            result = asyncio.run(
                execute_browser_plan(
                    plan,
                    artifact_dir=root,
                    allowed_origins=origins,
                    deadline_monotonic=time.monotonic() + budget,
                    executable_path=os.environ.get("XCAGI_BROWSER_EXECUTABLE") or None,
                    before_action=recheck_authority,
                )
            )
            from app.application.agent_orchestrator.verification_surface import (
                execution_surface_binding,
            )

            _persist_artifacts(
                result,
                root,
                run.run_id,
                int(actor.id),
                str(context["tenant_id"]),
                execution_surface_binding(run, params, context),
            )
        return {**result, "run_id": run.run_id, "untrusted_page_content": True}
    except RECOVERABLE_ERRORS:
        return {
            "success": False,
            "error_code": "browser_execution_or_receipt_failed",
            "run_id": run.run_id,
            "outcome": "unknown",
            "retryable": False,
            "reconciliation_required": True,
            "message": "浏览器执行或产物回执未确认，必须核对原任务后再继续。",
        }
