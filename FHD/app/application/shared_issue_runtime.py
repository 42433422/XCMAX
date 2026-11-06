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


async def _market_token(request: Request) -> str:
    get_logged_in_user(request)
    token = await _private_delivery_market_token(request)
    if not token:
        raise HTTPException(401, "请登录市场账号查看修复交付")
    return token


async def pending_issues(request: Request) -> dict[str, Any]:
    token = await _market_token(request)
    sha = build_identity()["git_sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return {"items": [], "runtime_unverified": True}
    return await custom_delivery_remote_json(
        token,
        f"/api/customer-service/issues/pending-runtime?host_sha={sha}",
    )


async def list_issues(request: Request) -> dict[str, Any]:
    """The owner's product issues, flagged where the released fix runs on this client."""
    mine = await custom_delivery_remote_json(
        await _market_token(request), "/api/customer-service/issues/mine"
    )
    pending = await pending_issues(request)
    ready = {row.get("id") for row in pending.get("items", []) if row.get("ready")}
    local = _ticket_load(_owner(request))["tickets"]
    items = []
    for row in mine.get("items", []):
        saved = local.get(str(row.get("id"))) if isinstance(local, dict) else None
        remote_status = str((saved or {}).get("status") or row.get("status") or "")
        items.append({**row, "ready": row.get("id") in ready, "state": _ticket_state(remote_status)})
    return {
        "items": items,
        "runtime_unverified": bool(pending.get("runtime_unverified")),
    }


async def decide_issue(
    request: Request, ticket_id: int, *, decision: str, note: str, idempotency_key: str
) -> dict[str, Any]:
    if len(note.strip()) < 4:
        raise HTTPException(400, "请说明原问题现在的使用结果（至少4个字）")
    owner = _owner(request)
    gate = _ticket_gate(owner, ticket_id, decision, idempotency_key, note.strip())
    if gate.get("action") == "deny":
        raise HTTPException(409, str(gate.get("reason") or "工单状态不允许该决定"))
    if gate.get("action") == "replay":
        return dict(gate.get("result") or {})
    result = await custom_delivery_remote_json(
        await _market_token(request),
        f"/api/customer-service/issues/{int(ticket_id)}/decision",
        method="POST",
        payload={"decision": decision, "note": note.strip(), "idempotency_key": idempotency_key},
    )
    _ticket_commit(owner, ticket_id, decision, idempotency_key, note.strip(), result)
    stored = _ticket_load(owner)["tickets"].get(str(ticket_id)) or {}
    return {**result, "state": _ticket_state(str(stored.get("status") or ""))}


def _ticket_state(status: str) -> str:
    from app.domain.task_lifecycle.adapters import LegacyTransitionError, canonicalize

    try:
        return canonicalize("ticket", status or "open")
    except LegacyTransitionError:
        return status or "queued"


def _ticket_path(owner: str):
    from app.application.mod_delivery_receipt_outbox import _digest
    from app.utils.path_io.path_utils import get_app_data_dir

    directory = Path(get_app_data_dir()) / "shared-issue-receipts" / _digest(owner)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory / "decisions.json"


def _ticket_load(owner: str) -> dict[str, Any]:
    path = _ticket_path(owner)
    if not path.exists():
        return {"tickets": {}, "idem": {}}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"tickets": {}, "idem": {}}
    if not isinstance(loaded, dict):
        return {"tickets": {}, "idem": {}}
    loaded.setdefault("tickets", {})
    loaded.setdefault("idem", {})
    return loaded


def _ticket_save(owner: str, payload: dict[str, Any]) -> None:
    path = _ticket_path(owner)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _ticket_gate(
    owner: str, ticket_id: int, decision: str, idempotency_key: str, note: str
) -> dict[str, Any]:
    from app.domain.task_lifecycle.adapters import legacy_transition_allowed

    book = _ticket_load(owner)
    idem = book["idem"].get(idempotency_key)
    fingerprint = json.dumps([ticket_id, decision, note], ensure_ascii=False)
    if isinstance(idem, dict):
        if idem.get("fingerprint") != fingerprint:
            return {"action": "deny", "reason": "幂等键与已有工单决定冲突"}
        return {"action": "replay", "result": idem.get("result") or {}}
    targets = {
        "approve": "queued",
        "approved": "queued",
        "reject": "rejected",
        "rejected": "rejected",
        "reopen": "queued",
        "cancel": "cancelled",
        "resolve": "succeeded",
    }
    target = targets.get(decision)
    current = str((book["tickets"].get(str(ticket_id)) or {}).get("status") or "waiting_approval")
    if target is not None and not legacy_transition_allowed(
        "ticket", current, target, retryable=decision == "reopen"
    ):
        return {"action": "deny", "reason": f"工单不能从 {current} 改为 {decision}"}
    return {"action": "allow"}


def _ticket_commit(
    owner: str,
    ticket_id: int,
    decision: str,
    idempotency_key: str,
    note: str,
    result: dict[str, Any],
) -> None:
    targets = {
        "approve": "queued",
        "approved": "queued",
        "reject": "rejected",
        "rejected": "rejected",
        "reopen": "queued",
        "cancel": "cancelled",
        "resolve": "succeeded",
    }
    book = _ticket_load(owner)
    current = book["tickets"].get(str(ticket_id)) or {"status": "created", "history": []}
    target = targets.get(decision, current.get("status") or "created")
    current.setdefault("history", []).append(
        {"from": current.get("status"), "to": target, "decision": decision}
    )
    current["status"] = target
    book["tickets"][str(ticket_id)] = current
    book["idem"][idempotency_key] = {
        "fingerprint": json.dumps([ticket_id, decision, note], ensure_ascii=False),
        "result": result,
    }
    _ticket_save(owner, book)


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
