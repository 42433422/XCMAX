"""Durable caller-scoped delivery receipts, retried after login and page refresh."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.time import utc_now_iso_z

_DELIVERY_ERRORS: tuple[type[Exception], ...] = RECOVERABLE_ERRORS + (HTTPException,)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _directory(owner: str) -> Path:
    from app.utils.path_io.path_utils import get_app_data_dir

    if not owner:
        raise ValueError("Delivery receipt requires an authenticated workspace owner")
    path = Path(get_app_data_dir()) / "mod-delivery-receipts" / _digest(owner)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _save(path: Path, row: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(row, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def record_installed_delivery(
    *,
    owner: str,
    ticket_id: int,
    artifact_kind: str,
    artifact_id: str,
    version: str,
    package_sha256: str,
    receipt_token: str,
) -> str:
    """Persist the signed grant before mutation; sending requires installed proof."""
    from app.application.desktop_delivery_receipt import desktop_installation_id
    from app.build_identity import build_identity

    client = desktop_installation_id()
    identity = _digest([owner, ticket_id, artifact_kind, artifact_id, package_sha256, client])
    path = _directory(owner) / (identity + ".json")
    if path.exists():
        return identity
    payload = {
        "artifact_kind": artifact_kind,
        "artifact_id": artifact_id,
        "installed_version": version,
        "package_sha256": package_sha256,
        "host": "XCAGI Desktop",
        "host_sha": build_identity()["git_sha"],
        "client_instance_id": client,
        "receipt_token": receipt_token,
        "stage": "installed",
        "receipt_id": identity + ":installed",
    }
    _save(
        path,
        {
            "owner": owner,
            "ticket_id": ticket_id,
            "payload": payload,
            "installed_reported": False,
            "runtime_reported": False,
        },
    )
    return identity


async def _runtime_payload(request: Request, row: dict[str, Any]) -> dict[str, Any] | None:
    from app.infrastructure.auth.dependencies import session_id_from_request
    from app.infrastructure.mods.install_receipts import read_verified_install
    from app.infrastructure.mods.mod_manager import (
        ensure_mod_api_ready,
        get_mod_manager,
    )

    installed = row["payload"]
    if installed["artifact_kind"] != "module":
        return None
    mid = installed["artifact_id"]
    current = read_verified_install(mid)
    if (
        not current
        or current.get("requires_restart")
        or current.get("owner_scope") != row["owner"]
        or current.get("package_sha256") != installed["package_sha256"]
        or current.get("package_version") != installed["installed_version"]
    ):
        return None
    if not ensure_mod_api_ready(mid, session_id=session_id_from_request(request)):
        return None
    current = read_verified_install(mid)
    if not current or current.get("runtime_status") != "running":
        return None
    from app.build_identity import build_identity

    host_sha = build_identity()["git_sha"]
    saved = row.get("runtime_payload")
    if (
        saved
        and saved.get("host_sha") == host_sha
        and saved.get("runtime_files_sha256") == _digest(current["file_sha256"])
    ):
        return dict(saved)
    manifest = json.loads((Path(current["installed_root"]) / "manifest.json").read_text())
    probe = manifest.get("delivery_verification") or {}
    case_id = str(probe.get("case_id") or "").strip()
    if not case_id or probe.get("handler") != "verify_delivery":
        return None
    module = get_mod_manager()._backend_entry_modules.get(mid)
    verify = getattr(module, "verify_delivery", None)
    if not callable(verify):
        return None
    result = verify(request)
    if inspect.isawaitable(result):
        result = await result
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("passed"), bool)
        or not isinstance(result.get("observations"), dict)
        or not result["observations"]
    ):
        return None
    evidence = {
        "case_id": case_id,
        "passed": result["passed"],
        "observations": result["observations"],
        "observed_at": utc_now_iso_z(),
    }
    evidence["evidence_sha256"] = _digest(evidence)
    return dict(
        installed,
        stage="running" if result["passed"] else "verification_failed",
        receipt_id=installed["receipt_id"].removesuffix(":installed")
        + (":running:" if result["passed"] else ":failed:")
        + host_sha,
        host_sha=host_sha,
        runtime_files_sha256=_digest(current["file_sha256"]),
        business_verification=evidence,
    )


async def retry_delivery_receipts(request: Request, market_token: str) -> dict[str, int]:
    from app.application.tenant_workspace_prefs import resolve_workspace_owner_id
    from app.infrastructure.auth.dependencies import get_logged_in_user
    from app.infrastructure.mods.state_lock import state_lock

    owner = resolve_workspace_owner_id(request, get_logged_in_user(request))
    summary = {"installed_reported": 0, "runtime_reported": 0, "pending": 0}
    if not owner or not market_token:
        return summary
    try:
        with state_lock(_directory(owner)):
            return await _retry_owner_receipts(request, market_token, owner)
    except OSError:
        # A parallel refresh already owns the retry; leave durable rows intact.
        summary["pending"] = 1
        return summary


async def retry_delivery_receipts_best_effort(
    request: Request, market_token: str
) -> dict[str, int]:

    try:
        async with asyncio.timeout(3):
            return await retry_delivery_receipts(request, market_token)
    except _DELIVERY_ERRORS:
        return {"installed_reported": 0, "runtime_reported": 0, "pending": 1}


async def _retry_owner_receipts(request: Request, market_token: str, owner: str) -> dict[str, int]:
    from app.application.private_mod_delivery_artifacts import (
        custom_delivery_remote_json,
    )
    from app.infrastructure.mods.install_receipts import read_verified_install

    summary = {"installed_reported": 0, "runtime_reported": 0, "pending": 0}
    for path in sorted(_directory(owner).glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
                raise ValueError("Invalid delivery receipt")
            ticket_id = int(row["ticket_id"])
        except (OSError, ValueError, KeyError):
            summary["pending"] += 1
            continue
        if row.get("owner") != owner or row.get("runtime_reported") or row.get("failure_reported"):
            continue
        endpoint = f"/api/customer-service/custom-deliveries/{ticket_id}/installed"
        try:
            if not row.get("installed_reported"):
                payload = row["payload"]
                if payload["artifact_kind"] == "module":
                    installed = read_verified_install(payload["artifact_id"])
                    if (
                        not installed
                        or installed.get("owner_scope") != owner
                        or installed.get("package_sha256") != payload["package_sha256"]
                        or installed.get("package_version") != payload["installed_version"]
                    ):
                        summary["pending"] += 1
                        continue
                await custom_delivery_remote_json(
                    market_token,
                    endpoint,
                    method="POST",
                    payload=row["payload"],
                )
                row["installed_reported"] = True
                _save(path, row)
                summary["installed_reported"] += 1
            runtime = await _runtime_payload(request, row)
            if runtime is None:
                summary["pending"] += 1
                continue
            # Save the probe result before sending, so response loss doesn't change
            # observed_at or evidence under the same idempotency key.
            row["runtime_payload"] = runtime
            _save(path, row)
            response = await custom_delivery_remote_json(
                market_token,
                endpoint,
                method="POST",
                payload=runtime,
            )
            record = response.get("record") or (response.get("receipt") or {}).get("record") or {}
            row["runtime_reported"] = record.get("verified") is True
            row["failure_reported"] = record.get("failure_recorded") is True
            row["runtime_response"] = response
            row.pop("last_error", None)
            _save(path, row)
            if row["runtime_reported"]:
                summary["runtime_reported"] += 1
            elif not row["failure_reported"]:
                summary["pending"] += 1
        except _DELIVERY_ERRORS as exc:
            row["last_error"] = type(exc).__name__
            _save(path, row)
            summary["pending"] += 1
    return summary


async def retry_delivery_receipts_for_session(session_id: str, market_token: str) -> dict[str, int]:
    """Use the just-authenticated host session; never infer an owner from a token."""
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/login",
            "headers": [(b"x-session-id", session_id.encode("utf-8"))],
        }
    )
    result = await retry_delivery_receipts(request, market_token)
    from app.application.shared_issue_runtime import report_ready_issue_identities

    await report_ready_issue_identities(request)
    return result
