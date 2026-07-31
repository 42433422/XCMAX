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
PENDING_PRINT_JOB_TTL_SECONDS = 15 * 60

_lock = threading.RLock()
_print_capabilities: dict[str, dict[str, Any]] = {}
_post_print_receipts: dict[str, dict[str, Any]] = {}
# A pending CUPS job is not a print receipt.  It is an owner-bound, opaque
# tracker which permits a *read-only* IPP status check after the bounded
# submission monitor times out.  Keeping it process-local follows the same
# safe-on-restart semantics as one-click print capabilities.
_pending_document_print_jobs: dict[str, dict[str, Any]] = {}


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
    for mapping in (
        _print_capabilities,
        _post_print_receipts,
        _pending_document_print_jobs,
    ):
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
    print_completed: bool = True,
) -> str | None:
    """Finish a print reservation without falsely claiming physical completion.

    ``print_succeeded`` means the OS accepted the submission.  On macOS CUPS
    that is not equivalent to pages leaving the printer: a bounded IPP monitor
    supplies ``print_completed``.  A queued/pending job consumes the one-click
    capability so a repeat click cannot duplicate it, but yields no receipt and
    therefore cannot move the shipment record to ``printed``.
    """

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
        if not print_completed:
            return None
        receipt = secrets.token_urlsafe(32)
        _post_print_receipts[receipt] = {
            "owner_user_id": int(record["owner_user_id"]),
            "file_path": str(record["file_path"]),
            "order_id": _normalized_order_id(record.get("order_id")),
            "expires_at": time.time() + POST_PRINT_RECEIPT_TTL_SECONDS,
        }
        return receipt


def defer_document_print_capability(
    reservation: dict[str, Any],
    *,
    printer_name: object,
    job_id: object,
) -> dict[str, Any]:
    """Turn a submitted-but-unconfirmed print into an owner-bound tracker.

    CUPS can acknowledge ``lp`` while a device is offline.  The original
    capability must still be consumed (otherwise a second click would submit
    a duplicate job), but no shipment receipt may exist until a later,
    authenticated status check sees ``completed``.  A missing job id is kept
    as an explicitly untrackable terminal-pending record rather than allowing
    a blind retry of an already submitted document.
    """

    capability_token = str((reservation or {}).get("capability_token") or "").strip()
    if not capability_token:
        return {
            "success": False,
            "error_code": "PRINT_PENDING_TRACKER_INVALID",
            "message": "打印任务状态无法追踪",
        }

    normalized_printer = str(printer_name or "").strip()
    normalized_job = str(job_id or "").strip()
    with _lock:
        _cleanup_locked()
        record = _print_capabilities.get(capability_token)
        if not record:
            return {
                "success": False,
                "error_code": "PRINT_PENDING_TRACKER_INVALID",
                "message": "打印确认已失效，无法追踪状态",
            }
        if not bool(record.get("reserved")):
            return {
                "success": False,
                "error_code": "PRINT_PENDING_TRACKER_INVALID",
                "message": "打印任务未处于可追踪状态",
            }

        _print_capabilities.pop(capability_token, None)
        tracker = secrets.token_urlsafe(32)
        expires_at = min(
            float(record.get("expires_at") or 0.0),
            time.time() + PENDING_PRINT_JOB_TTL_SECONDS,
        )
        _pending_document_print_jobs[tracker] = {
            "owner_user_id": int(record["owner_user_id"]),
            "file_path": str(record["file_path"]),
            "order_id": _normalized_order_id(record.get("order_id")),
            "printer_name": normalized_printer,
            "job_id": normalized_job,
            "tracking_available": bool(normalized_printer and normalized_job),
            "state": "pending",
            "reason": "",
            "post_print_receipt": "",
            "expires_at": expires_at,
        }
        return {
            "success": True,
            "print_job_token": tracker,
            "tracking_available": bool(normalized_printer and normalized_job),
            "expires_at": int(expires_at),
        }


def get_pending_document_print_job(
    print_job_token: object,
    *,
    owner_user_id: object,
) -> dict[str, Any]:
    """Get trusted pending-job metadata for an authenticated owner only."""

    token = str(print_job_token or "").strip()
    owner = _positive_user_id(owner_user_id)
    if owner is None:
        return {
            "success": False,
            "error_code": "PRINT_AUTH_REQUIRED",
            "message": "登录身份无效，不能查询打印状态",
        }
    if not token:
        return {
            "success": False,
            "error_code": "PRINT_PENDING_TRACKER_INVALID",
            "message": "缺少打印状态查询凭据",
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
        return {
            "success": True,
            "print_job_token": token,
            "printer_name": str(record.get("printer_name") or ""),
            "job_id": str(record.get("job_id") or ""),
            "tracking_available": bool(record.get("tracking_available")),
            "state": str(record.get("state") or "pending"),
            "reason": str(record.get("reason") or ""),
            "post_print_receipt": str(record.get("post_print_receipt") or ""),
        }


from app.application.print_authorization_settlement import (
    _clear_print_authorizations_for_tests,
    consume_post_print_receipt,
    settle_pending_document_print_job,
)

__all__ = [
    "POST_PRINT_RECEIPT_TTL_SECONDS",
    "PENDING_PRINT_JOB_TTL_SECONDS",
    "PRINT_CAPABILITY_TTL_SECONDS",
    "consume_post_print_receipt",
    "defer_document_print_capability",
    "finish_document_print_capability",
    "get_pending_document_print_job",
    "issue_document_print_capability",
    "normalize_printable_path",
    "reserve_document_print_capability",
    "settle_pending_document_print_job",
]
