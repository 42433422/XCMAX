"""Synchronize already accepted private deliveries for the current account."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from app.application.delivery_entitlements import refresh_delivery_entitlements
from app.application.mod_delivery_receipt_outbox import retry_delivery_receipts
from app.application.private_mod_delivery_artifacts import (
    fetch_private_mod_library,
    is_newer_version,
    update_private_mod_from_library,
)
from app.application.session_account_meta import load_session_account_meta
from app.application.shared_issue_runtime import report_ready_issue_identities
from app.enterprise.private_delivery_binding import (
    load_session_private_delivery_binding,
)
from app.fastapi_routes.private_mod_delivery_context import (
    _private_delivery_market_token,
)
from app.infrastructure.auth.dependencies import session_id_from_request
from app.infrastructure.mods.install_receipts import read_verified_install
from app.infrastructure.mods.mod_manager import get_mod_manager
from app.infrastructure.mods.state_lock import state_lock
from app.mod_sdk.industry_mod_aliases import is_retired_runtime_mod_id
from app.mod_sdk.owner_workspace import authenticated_owner, owner_workspace
from app.utils.operational_errors import RECOVERABLE_ERRORS

_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_INSTALLS_PER_SYNC = 3
_SYNC_ERRORS: tuple[type[Exception], ...] = RECOVERABLE_ERRORS + (HTTPException,)


def _identity(request: Request) -> tuple[str, int]:
    owner = authenticated_owner(request)
    meta = load_session_account_meta(session_id_from_request(request)) or {}
    if meta.get("impersonating_market_user_id") or meta.get("impersonating_username"):
        raise HTTPException(403, "代管期间暂停自动私有交付，请退出代管后同步本人扩展")
    binding = load_session_private_delivery_binding(session_id_from_request(request))
    market = int(binding.get("market_user_id") or 0)
    if market <= 0:
        raise HTTPException(401, "请登录已绑定市场的账号")
    return owner, market


def _positive_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return 0
    raw = str(value)
    return int(raw) if raw.isascii() and raw.isdecimal() and len(raw) < 20 else 0


def _metadata(row: dict[str, Any], market: int) -> tuple[str, str, str] | None:
    if row.get("installable") is not True:
        return None
    mid = str(row.get("id") or "")
    version = str(row.get("version") or "").strip()
    digest = str(row.get("package_sha256") or row.get("sha256") or "")
    if (
        not _ID.fullmatch(mid)
        or is_retired_runtime_mod_id(mid)
        or not version
        or not _SHA.fullmatch(digest)
        or row.get("publication_status") != "signed_release"
        or _positive_id(row.get("delivery_ticket_id")) <= 0
        or _positive_id(row.get("owner_user_id")) != market
    ):
        raise ValueError("私有交付目录缺少匹配账号的正式验收签包身份")
    return mid, version, digest


def _local_action(manager: Any, mid: str, version: str, digest: str, owner: str) -> str:
    current = read_verified_install(mid, mods_root=manager.mods_root)
    local_path = manager.resolve_mod_directory(mid)
    if not current:
        if local_path is not None:
            raise ValueError("已有本地模块未验证为当前账号私包，不能自动覆盖")
        return "install"
    if current.get("owner_scope") != owner:
        raise ValueError("本地扩展属于其他工作空间，不能自动覆盖")
    # The verified receipt attests the actual bytes read here, including scope.
    manifest_path = Path(current["installed_root"]) / "manifest.json"
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != current.get("file_sha256", {}).get("manifest.json"):
        raise ValueError("本地扩展清单与签包身份不一致")
    if json.loads(raw).get("scope") != "account":
        raise ValueError("公共模块不能通过客户私有交付自动替换")
    if current.get("requires_restart"):
        return "restart"
    installed_version = str(current.get("package_version") or "")
    if installed_version == version:
        if current.get("package_sha256") != digest:
            raise ValueError("同一私包版本对应不同摘要，等待发布方修正")
        return "current"
    return "install" if is_newer_version(version, installed_version) else "current"


def _error(result: dict[str, Any], mid: str, exc: Exception) -> None:
    result["pending"] += 1
    if len(result["errors"]) < 10:
        result["errors"].append({"mod_id": mid, "message": str(exc)[:240]})


async def _sync_locked(
    request: Request, identity: tuple[str, int], token: str, result: dict[str, Any]
) -> dict[str, Any]:
    owner, market = identity
    manager = get_mod_manager()
    try:
        rows = await fetch_private_mod_library(token)
    except _SYNC_ERRORS as exc:
        rows = []
        _error(result, "", exc)
    attempts = 0
    seen: set[str] = set()
    for row in rows:
        mid = str(row.get("id") or "")
        if mid in seen:
            continue
        seen.add(mid)
        try:
            if _identity(request) != identity or await request.is_disconnected():
                result["pending"] += 1
                return result
            metadata = _metadata(row, market)
            if metadata is None:
                continue
            mid, version, digest = metadata
            action = _local_action(manager, mid, version, digest, owner)
            if action == "restart":
                result["restart_required"].append(mid)
            if action != "install":
                continue
            if attempts >= MAX_INSTALLS_PER_SYNC:
                result["pending"] += 1
                continue
            attempts += 1
            update = await update_private_mod_from_library(
                mid,
                token,
                expected_version=version,
                owner_scope=owner,
                require_account_scope=True,
            )
            if update.get("success") is not True:
                raise RuntimeError(str(update.get("message") or "私有交付安装未完成"))
            if update.get("updated"):
                result["installed"].append(mid)
                result["routes_changed"] = True
            if update.get("requires_restart"):
                result["restart_required"].append(mid)
        except _SYNC_ERRORS as exc:
            _error(result, mid, exc)
    if _identity(request) != identity or await request.is_disconnected():
        result["pending"] += 1
        return result
    rights_before = load_session_private_delivery_binding(session_id_from_request(request)).get(
        "mod_ids"
    )
    if not await refresh_delivery_entitlements(request, token):
        result["pending"] += 1
    if _identity(request) != identity or await request.is_disconnected():
        result["pending"] += 1
        return result
    rights_after = load_session_private_delivery_binding(session_id_from_request(request)).get(
        "mod_ids"
    )
    if rights_before != rights_after:
        result["routes_changed"] = True
    try:
        receipts = await retry_delivery_receipts(request, token)
        result["pending"] += receipts.get("pending", 0)
    except _SYNC_ERRORS as exc:
        _error(result, "", exc)
    try:
        # This retries saved explicit confirmations and otherwise reports only
        # the current identity. It never invents customer confirmation.
        await report_ready_issue_identities(request)
    except _SYNC_ERRORS as exc:
        _error(result, "", exc)
    return result


async def sync_private_deliveries(request: Request) -> dict[str, Any]:
    identity = _identity(request)
    token = await _private_delivery_market_token(request)
    if not token or _identity(request) != identity:
        raise HTTPException(401, "当前市场会话已变化，请重新登录")
    result: dict[str, Any] = {
        "routes_changed": False,
        "installed": [],
        "restart_required": [],
        "pending": 0,
        "errors": [],
    }
    directory = owner_workspace("private-delivery-sync", owner_id=identity[0]).root
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with state_lock(directory):
            return await _sync_locked(request, identity, token, result)
    except OSError:
        result["pending"] += 1
        return result
