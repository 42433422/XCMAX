"""Server-side print capabilities for generated business documents.

Printing is a physical side effect.  A local file path is not an authority to
submit a print job: paths can be guessed, copied from an old chat response, or
supplied by a compromised renderer.  The shipment generator therefore issues
a short-lived, owner-bound capability for each generated document.  The UI
spends that capability only when the user clicks its print button.

The implementation is deliberately process-local for the desktop app.  It is
not a durable business record and is invalidated on restart, which is the safe
failure mode: the user can regenerate the document and click print again.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from typing import Any

PRINT_CAPABILITY_TTL_SECONDS = 15 * 60
POST_PRINT_RECEIPT_TTL_SECONDS = 5 * 60

_lock = threading.RLock()
_print_capabilities: dict[str, dict[str, Any]] = {}
_post_print_receipts: dict[str, dict[str, Any]] = {}


def _positive_user_id(value: object) -> int | None:
    try:
        user_id = int(value) if value is not None else 0
    except (TypeError, ValueError):
        return None
    return user_id if user_id > 0 else None


def _normalized_order_id(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        order_id = int(value)
    except (TypeError, ValueError):
        return None
    return order_id if order_id > 0 else None


def normalize_printable_path(file_path: object) -> str | None:
    """Return an existing regular file's canonical path, or ``None``.

    This module does not accept user paths as an authority.  It only compares a
    path supplied at print time against a path registered by the trusted
    document generator.  Canonicalisation still prevents a symlink or spelling
    variant from bypassing that exact comparison.
    """

    raw = str(file_path or "").strip()
    if not raw:
        return None
    try:
        normalized = os.path.realpath(os.path.abspath(raw))
    except (OSError, TypeError, ValueError):
        return None
    return normalized if os.path.isfile(normalized) else None


def _cleanup_locked() -> None:
    now = time.time()
    for mapping in (_print_capabilities, _post_print_receipts):
        expired = [
            token
            for token, record in mapping.items()
            if float(record.get("expires_at", 0.0)) <= now
        ]
        for token in expired:
            mapping.pop(token, None)


def issue_document_print_capability(
    *,
    file_path: object,
    owner_user_id: object,
    order_id: object = None,
) -> dict[str, Any] | None:
    """Register a generated shipment document and return its print capability.

    The caller is the application service that just generated the document.
    Nothing in this function derives an owner from a request header or JSON
    body; callers must provide the trusted, middleware-authenticated owner.
    """

    owner = _positive_user_id(owner_user_id)
    path = normalize_printable_path(file_path)
    if owner is None or path is None:
        return None

    normalized_order = _normalized_order_id(order_id)
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + PRINT_CAPABILITY_TTL_SECONDS
    with _lock:
        _cleanup_locked()
        _print_capabilities[token] = {
            "owner_user_id": owner,
            "file_path": path,
            "order_id": normalized_order,
            "expires_at": expires_at,
            "reserved": False,
        }
    return {
        "document_token": token,
        "expires_at": int(expires_at),
        "order_id": normalized_order,
    }


def reserve_document_print_capability(
    token: object,
    *,
    owner_user_id: object,
    file_path: object,
    order_id: object = None,
) -> dict[str, Any]:
    """Atomically reserve an owner-bound capability for one document print."""

    raw_token = str(token or "").strip()
    owner = _positive_user_id(owner_user_id)
    path = normalize_printable_path(file_path)
    requested_order = _normalized_order_id(order_id)
    if owner is None:
        return {
            "success": False,
            "error_code": "PRINT_AUTH_REQUIRED",
            "message": "登录身份无效，无法打印受保护的发货单",
        }
    if not raw_token:
        return {
            "success": False,
            "error_code": "PRINT_CONFIRMATION_REQUIRED",
            "message": "请从刚生成的发货单点击打印，不能直接提交文件路径",
        }
    if path is None:
        return {
            "success": False,
            "error_code": "PRINT_ARTIFACT_INVALID",
            "message": "发货单文件不存在或不可打印",
        }

    with _lock:
        _cleanup_locked()
        record = _print_capabilities.get(raw_token)
        if not record:
            return {
                "success": False,
                "error_code": "PRINT_CONFIRMATION_INVALID",
                "message": "打印确认已过期或无效，请重新生成发货单后再试",
            }
        if int(record.get("owner_user_id") or 0) != owner:
            return {
                "success": False,
                "error_code": "PRINT_CONFIRMATION_OWNER_MISMATCH",
                "message": "该发货单不属于当前登录用户，不能打印",
            }
        if str(record.get("file_path") or "") != path:
            return {
                "success": False,
                "error_code": "PRINT_CONFIRMATION_ARTIFACT_MISMATCH",
                "message": "打印确认与发货单不匹配",
            }
        expected_order = _normalized_order_id(record.get("order_id"))
        if expected_order != requested_order:
            return {
                "success": False,
                "error_code": "PRINT_CONFIRMATION_ORDER_MISMATCH",
                "message": "打印确认与发货记录不匹配",
            }
        if bool(record.get("reserved")):
            return {
                "success": False,
                "error_code": "PRINT_CONFIRMATION_IN_PROGRESS",
                "message": "该发货单正在提交打印，请不要重复点击",
            }
        record["reserved"] = True
        return {
            "success": True,
            "capability_token": raw_token,
            "file_path": path,
            "owner_user_id": owner,
            "order_id": expected_order,
        }


def finish_document_print_capability(
    reservation: dict[str, Any],
    *,
    print_succeeded: bool,
) -> str | None:
    """Release a failed reservation or turn a successful one into a receipt."""

    token = str((reservation or {}).get("capability_token") or "").strip()
    if not token:
        return None
    with _lock:
        _cleanup_locked()
        record = _print_capabilities.get(token)
        if not record:
            return None
        if not print_succeeded:
            record["reserved"] = False
            return None

        _print_capabilities.pop(token, None)
        receipt = secrets.token_urlsafe(32)
        _post_print_receipts[receipt] = {
            "owner_user_id": int(record["owner_user_id"]),
            "file_path": str(record["file_path"]),
            "order_id": _normalized_order_id(record.get("order_id")),
            "expires_at": time.time() + POST_PRINT_RECEIPT_TTL_SECONDS,
        }
        return receipt


def consume_post_print_receipt(
    receipt: object,
    *,
    owner_user_id: object,
    file_path: object,
    order_id: object = None,
) -> dict[str, Any]:
    """Consume the receipt that proves this exact artifact was printed.

    Shipment-record marking calls this after a successful physical print.  It
    is deliberately independent of any body/header user identity; the caller
    must pass the middleware-authenticated owner id.
    """

    raw_receipt = str(receipt or "").strip()
    owner = _positive_user_id(owner_user_id)
    path = normalize_printable_path(file_path)
    requested_order = _normalized_order_id(order_id)
    if owner is None:
        return {
            "success": False,
            "error_code": "PRINT_RECEIPT_OWNER_MISMATCH",
            "message": "登录身份无效，不能更新打印状态",
        }
    if not raw_receipt:
        return {
            "success": False,
            "error_code": "PRINT_RECEIPT_INVALID",
            "message": "缺少打印回执，不能直接更新打印状态",
        }
    if path is None:
        return {
            "success": False,
            "error_code": "PRINT_RECEIPT_ARTIFACT_MISMATCH",
            "message": "发货单文件不存在或与打印回执不匹配",
        }

    with _lock:
        _cleanup_locked()
        record = _post_print_receipts.get(raw_receipt)
        if not record:
            return {
                "success": False,
                "error_code": "PRINT_RECEIPT_INVALID",
                "message": "打印回执已过期、已使用或无效",
            }
        if int(record.get("owner_user_id") or 0) != owner:
            return {
                "success": False,
                "error_code": "PRINT_RECEIPT_OWNER_MISMATCH",
                "message": "打印回执不属于当前登录用户",
            }
        if str(record.get("file_path") or "") != path:
            return {
                "success": False,
                "error_code": "PRINT_RECEIPT_ARTIFACT_MISMATCH",
                "message": "打印回执与发货单不匹配",
            }
        expected_order = _normalized_order_id(record.get("order_id"))
        if expected_order != requested_order:
            return {
                "success": False,
                "error_code": "PRINT_RECEIPT_ORDER_MISMATCH",
                "message": "打印回执与发货记录不匹配",
            }
        _post_print_receipts.pop(raw_receipt, None)
        return {
            "success": True,
            "file_path": path,
            "order_id": expected_order,
        }


def _clear_print_authorizations_for_tests() -> None:
    """Test-only reset hook; not imported by production routes."""

    with _lock:
        _print_capabilities.clear()
        _post_print_receipts.clear()


__all__ = [
    "POST_PRINT_RECEIPT_TTL_SECONDS",
    "PRINT_CAPABILITY_TTL_SECONDS",
    "consume_post_print_receipt",
    "finish_document_print_capability",
    "issue_document_print_capability",
    "normalize_printable_path",
    "reserve_document_print_capability",
]
