"""Settlement and one-use receipt handling for pending print jobs."""

from __future__ import annotations

import secrets
import time
from typing import Any

from app.application.print_authorization import (
    POST_PRINT_RECEIPT_TTL_SECONDS,
    _cleanup_locked,
    _lock,
    _normalized_order_id,
    _pending_document_print_jobs,
    _positive_user_id,
    _post_print_receipts,
    _print_capabilities,
    normalize_printable_path,
)


def settle_pending_document_print_job(
    print_job_token: object,
    *,
    owner_user_id: object,
    state: object,
    reason: object = "",
) -> dict[str, Any]:
    """Persist one read-only CUPS state observation and issue a receipt once.

    The caller has already owner-validated the tracker via
    :func:`get_pending_document_print_job`.  This function repeats that check
    while holding the lock so concurrent status polls cannot mint two receipts.
    """

    token = str(print_job_token or "").strip()
    owner = _positive_user_id(owner_user_id)
    normalized_state = str(state or "pending").strip().lower()
    if normalized_state not in {"pending", "completed", "aborted", "unknown"}:
        normalized_state = "pending"
    if owner is None or not token:
        return {
            "success": False,
            "error_code": "PRINT_PENDING_TRACKER_INVALID",
            "message": "打印状态查询凭据无效",
        }

    with _lock:
        _cleanup_locked()
        record = _pending_document_print_jobs.get(token)
        if not record:
            return {
                "success": False,
                "error_code": "PRINT_PENDING_TRACKER_INVALID",
                "message": "打印状态查询凭据已过期或无效，请重新生成发货单",
            }
        if int(record.get("owner_user_id") or 0) != owner:
            return {
                "success": False,
                "error_code": "PRINT_PENDING_TRACKER_OWNER_MISMATCH",
                "message": "该打印任务不属于当前登录用户",
            }

        existing_state = str(record.get("state") or "pending")
        if existing_state == "completed":
            return {
                "success": True,
                "state": "completed",
                "post_print_receipt": str(record.get("post_print_receipt") or ""),
            }
        if existing_state == "aborted":
            return {
                "success": False,
                "state": "aborted",
                "reason": str(record.get("reason") or ""),
            }

        record["reason"] = str(reason or "").strip()
        if normalized_state == "completed":
            receipt = secrets.token_urlsafe(32)
            _post_print_receipts[receipt] = {
                "owner_user_id": int(record["owner_user_id"]),
                "file_path": str(record["file_path"]),
                "order_id": _normalized_order_id(record.get("order_id")),
                "expires_at": time.time() + POST_PRINT_RECEIPT_TTL_SECONDS,
            }
            record["state"] = "completed"
            record["post_print_receipt"] = receipt
            return {
                "success": True,
                "state": "completed",
                "post_print_receipt": receipt,
            }
        if normalized_state == "aborted":
            record["state"] = "aborted"
            return {
                "success": False,
                "state": "aborted",
                "reason": str(record.get("reason") or ""),
            }

        record["state"] = "pending"
        return {
            "success": True,
            "state": "pending",
            "reason": str(record.get("reason") or ""),
        }


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
        for pending in _pending_document_print_jobs.values():
            if str(pending.get("post_print_receipt") or "") == raw_receipt:
                pending["receipt_consumed"] = True
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
        _pending_document_print_jobs.clear()


__all__ = [
    "_clear_print_authorizations_for_tests",
    "consume_post_print_receipt",
    "settle_pending_document_print_job",
]
