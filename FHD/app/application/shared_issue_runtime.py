"""Bind customer issue receipts to this host, with explicit customer confirmation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from app.application.desktop_delivery_receipt import desktop_installation_id
from app.application.private_mod_delivery_artifacts import custom_delivery_remote_json
from app.build_identity import build_identity
from app.fastapi_routes.private_mod_delivery_context import (
    _private_delivery_market_token,
)
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.utils.operational_errors import RECOVERABLE_ERRORS

_DELIVERY_ERRORS: tuple[type[Exception], ...] = RECOVERABLE_ERRORS + (HTTPException,)


def _owner(request: Request) -> str:
    from app.application.tenant_workspace_prefs import resolve_workspace_owner_id

    owner = resolve_workspace_owner_id(request, get_logged_in_user(request))
    if not owner:
        raise HTTPException(401, "无法确定当前账号工作空间")
    return owner


def _records(owner: str):
    from app.application.mod_delivery_receipt_outbox import _digest
    from app.utils.path_io.path_utils import get_app_data_dir

    directory = Path(get_app_data_dir()) / "shared-issue-receipts" / _digest(owner)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in directory.glob("*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(row, dict) and row.get("owner") == owner and not row.get("reported"):
            yield path, row


async def _send_saved(request: Request, path: Path, row: dict[str, Any]) -> dict[str, Any]:
    from app.application.mod_delivery_receipt_outbox import _save

    if _owner(request) != row["owner"]:
        raise HTTPException(403, "不能确认其他工作空间的工单")
    result = await custom_delivery_remote_json(
        await _private_delivery_market_token(request),
        f"/api/customer-service/issues/{int(row['ticket_id'])}/runtime-receipt",
        method="POST",
        payload=row["payload"],
    )
    _save(path, dict(row, reported=True))
    return result


async def pending_issues(request: Request) -> dict[str, Any]:
    get_logged_in_user(request)
    token = await _private_delivery_market_token(request)
    if not token:
        raise HTTPException(401, "请登录市场账号查看修复交付")
    sha = build_identity()["git_sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return {"items": [], "runtime_unverified": True}
    return await custom_delivery_remote_json(
        token,
        f"/api/customer-service/issues/pending-runtime?host_sha={sha}",
    )


async def report_issue(
    request: Request,
    ticket_id: int,
    *,
    confirmed: bool = False,
    note: str = "",
) -> dict[str, Any]:
    if confirmed and len(note.strip()) < 4:
        raise HTTPException(400, "请说明原问题现在的使用结果（至少4个字）")
    owner = _owner(request)
    for saved_path, saved in _records(owner):
        payload = saved.get("payload") or {}
        if (
            saved.get("ticket_id") == ticket_id
            and payload.get("customer_confirmed") == confirmed
            and payload.get("confirmation_note") == (note.strip() if confirmed else "")
        ):
            return await _send_saved(request, saved_path, saved)
    pending = await pending_issues(request)
    issue = next((row for row in pending.get("items", []) if row.get("id") == ticket_id), None)
    if not issue or not issue.get("ready"):
        raise HTTPException(409, "修复版本尚未在当前客户端就绪")
    target = issue.get("target") or {}
    identity = build_identity()
    if target.get("host_sha") != identity["git_sha"]:
        raise HTTPException(409, "当前客户端版本与修复交付不一致")
    payload = {
        "client_instance_id": desktop_installation_id(),
        "host_sha": identity["git_sha"],
        "version": identity["product_version"],
        "release_id": target["release_id"],
        "signed_metadata_sha256": target["signed_metadata_sha256"],
        "case_id": target["case_id"],
        "customer_confirmed": confirmed,
        "confirmation_note": note.strip() if confirmed else "",
    }
    payload["receipt_id"] = hashlib.sha256(
        json.dumps(
            [ticket_id, payload],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    from app.application.mod_delivery_receipt_outbox import _digest, _save
    from app.utils.path_io.path_utils import get_app_data_dir

    path = (
        Path(get_app_data_dir())
        / "shared-issue-receipts"
        / _digest(owner)
        / (payload["receipt_id"] + ".json")
    )
    row = {
        "owner": owner,
        "ticket_id": ticket_id,
        "payload": payload,
        "reported": False,
    }
    _save(path, row)
    return await _send_saved(request, path, row)


async def report_ready_issue_identities(request: Request) -> dict[str, int]:

    for path, row in list(_records(_owner(request)))[:20]:
        try:
            await _send_saved(request, path, row)
        except _DELIVERY_ERRORS:
            continue
    pending = await pending_issues(request)
    reported = 0
    for row in pending.get("items", [])[:20]:
        if row.get("ready"):
            await report_issue(request, int(row["id"]), confirmed=False)
            reported += 1
    return {"reported": reported}
