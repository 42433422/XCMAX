"""管理员与 AI 员工共用的真实任务、决策、交付和恢复 API。"""

from __future__ import annotations

import os
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request

from modstore_server.api.deps import get_current_user, require_admin
from modstore_server.management_work_service import (
    WorkItemConflict,
    cancel_work_item,
    claim_work_item,
    create_work_item,
    deliver_work_item,
    fail_work_item,
    get_work_item,
    heartbeat_work_item,
    list_management_employees,
    list_work_items,
    reassign_work_item,
    recover_stale_work_items,
    request_decision,
    resolve_decision,
    retry_work_item,
    review_delivery,
    work_item_summary,
)
from modstore_server.models import User

router = APIRouter(
    prefix="/api/admin/employee-autonomy/work-items",
    tags=["admin-management-work"],
)


def _internal_api_key() -> str:
    return (
        os.environ.get("MODSTORE_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or ""
    ).strip()


def _require_admin_or_internal(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Optional[User]:
    expected = _internal_api_key()
    provided = (request.headers.get("x-internal-api-key") or "").strip()
    if expected and provided and secrets.compare_digest(expected, provided):
        return None
    return require_admin(get_current_user(authorization))


def _handle_error(exc: Exception) -> None:
    if isinstance(exc, KeyError):
        raise HTTPException(404, str(exc).strip("'")) from exc
    if isinstance(exc, WorkItemConflict):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, (TypeError, ValueError)):
        raise HTTPException(400, str(exc)) from exc
    raise exc


def _actor_user_id(auth: Optional[User], _body: dict[str, Any] | None = None) -> int:
    """Resolve an actor only inside the authoritative MODstore user database.

    Internal FHD calls carry ``external_actor_ref`` for audit context.  Their
    numeric user ids belong to a different database and must never be reused as
    a MODstore foreign key.
    """

    if auth is not None:
        return int(auth.id)

    try:
        from modstore_server.models import get_session_factory

        sf = get_session_factory()
        with sf() as session:
            preferred = (
                session.query(User)
                .filter(User.is_admin.is_(True), User.username == "admin")
                .order_by(User.id.asc())
                .first()
            )
            if preferred is not None:
                return int(preferred.id)
            rows = (
                session.query(User).filter(User.is_admin.is_(True)).order_by(User.id.asc()).first()
            )
            if rows is not None:
                return int(rows.id)
    except Exception as exc:
        raise HTTPException(503, "local MODstore administrator lookup failed") from exc
    raise HTTPException(503, "local MODstore administrator is not configured")


def _source_ref(auth: Optional[User], body: dict[str, Any]) -> str:
    """Accept an FHD actor reference only from the authenticated internal bridge."""

    if auth is not None:
        return f"modstore:user:{int(auth.id)}"
    value = str(body.get("external_actor_ref") or body.get("source_ref") or "").strip()
    if not value:
        return ""
    parts = value.split(":")
    if len(parts) != 5 or parts[0:2] != ["fhd", "user"] or parts[3] != "tenant":
        raise ValueError("invalid external actor reference")
    try:
        user_id = int(parts[2])
        tenant_id = int(parts[4])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid external actor reference") from exc
    canonical = f"fhd:user:{user_id}:tenant:{tenant_id}"
    if user_id <= 0 or tenant_id < 0 or value != canonical:
        raise ValueError("invalid external actor reference")
    return canonical


@router.get("")
def list_management_work_items(
    status: str = Query("", description="逗号分隔状态"),
    owner_employee_id: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
    _auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    statuses = [value.strip() for value in status.split(",") if value.strip()]
    items = list_work_items(
        statuses=statuses,
        owner_employee_id=owner_employee_id,
        limit=limit,
    )
    return {"items": items, "count": len(items), "summary": work_item_summary()}


@router.get("/summary")
def get_management_work_summary(
    _auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    return work_item_summary()


@router.get("/employees")
def get_management_employees(
    _auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    employees = list_management_employees()
    return {
        "employee_partition": "management_duty",
        "employees": employees,
        "count": len(employees),
    }


@router.post("")
def create_management_work_item(
    body: dict[str, Any] = Body(default_factory=dict),
    auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    try:
        return create_work_item(
            created_by_user_id=_actor_user_id(auth, body),
            title=str(body.get("title") or ""),
            description=str(body.get("description") or body.get("task") or ""),
            owner_employee_id=str(body.get("owner_employee_id") or "auto"),
            source_kind=str(body.get("source_kind") or "admin"),
            source_ref=_source_ref(auth, body),
            priority=str(body.get("priority") or "P1"),
            risk_level=str(body.get("risk_level") or "medium"),
            acceptance_required=bool(body.get("acceptance_required", True)),
            acceptance_criteria=(
                body.get("acceptance_criteria")
                if isinstance(body.get("acceptance_criteria"), list)
                else []
            ),
            input_data=body.get("input") if isinstance(body.get("input"), dict) else {},
            max_attempts=int(body.get("max_attempts") or 3),
            idempotency_key=str(body.get("idempotency_key") or ""),
        )
    except Exception as exc:  # noqa: BLE001 - normalized to API contract
        _handle_error(exc)
        raise


@router.post("/watchdog")
def run_management_work_watchdog(
    body: dict[str, Any] = Body(default_factory=dict),
    _auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    return recover_stale_work_items(limit=max(1, min(int(body.get("limit") or 100), 500)))


@router.post("/decisions/{decision_id}/resolve")
def decide_management_work_item(
    decision_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    try:
        return resolve_decision(
            decision_id,
            decided_by_user_id=_actor_user_id(auth, body),
            decision_text=str(body.get("decision") or body.get("answer") or ""),
            note=str(body.get("note") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
        raise


@router.get("/{task_id}")
def get_management_work_item(
    task_id: str,
    _auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    item = get_work_item(task_id, include_timeline=True)
    if item is None:
        raise HTTPException(404, "work item not found")
    return item


@router.post("/{task_id}/claim")
def claim_management_work_item(
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    _auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    try:
        return claim_work_item(
            task_id,
            employee_id=str(body.get("employee_id") or ""),
            lease_seconds=int(body.get("lease_seconds") or 300),
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
        raise


@router.post("/{task_id}/heartbeat")
def heartbeat_management_work_item(
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    _auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    try:
        progress = body.get("progress")
        return heartbeat_work_item(
            task_id,
            employee_id=str(body.get("employee_id") or ""),
            lease_token=str(body.get("lease_token") or ""),
            progress=(int(progress) if progress is not None else None),
            stage=str(body.get("stage") or ""),
            message=str(body.get("message") or ""),
            evidence=body.get("evidence") if isinstance(body.get("evidence"), list) else [],
            lease_seconds=int(body.get("lease_seconds") or 300),
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
        raise


@router.post("/{task_id}/request-decision")
def request_management_decision(
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    _auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    try:
        return request_decision(
            task_id,
            employee_id=str(body.get("employee_id") or ""),
            lease_token=str(body.get("lease_token") or ""),
            question=str(body.get("question") or ""),
            options=body.get("options") if isinstance(body.get("options"), list) else [],
            recommendation=str(body.get("recommendation") or ""),
            due_seconds=int(body.get("due_seconds") or 3600),
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
        raise


@router.post("/{task_id}/deliver")
def deliver_management_work_item(
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    _auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    try:
        return deliver_work_item(
            task_id,
            employee_id=str(body.get("employee_id") or ""),
            lease_token=str(body.get("lease_token") or ""),
            summary=str(body.get("summary") or ""),
            artifacts=body.get("artifacts") if isinstance(body.get("artifacts"), list) else [],
            evidence=body.get("evidence") if isinstance(body.get("evidence"), list) else [],
            no_artifact_reason=str(body.get("no_artifact_reason") or ""),
            verification_receipt_id=str(body.get("verification_receipt_id") or ""),
            candidate_result_digest=str(body.get("candidate_result_digest") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
        raise


@router.post("/{task_id}/fail")
def fail_management_work_item(
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    _auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    try:
        return fail_work_item(
            task_id,
            employee_id=str(body.get("employee_id") or ""),
            lease_token=str(body.get("lease_token") or ""),
            error_kind=str(body.get("error_kind") or "unknown"),
            error=str(body.get("error") or ""),
            retryable=bool(body.get("retryable", True)),
            evidence=body.get("evidence") if isinstance(body.get("evidence"), list) else [],
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
        raise


@router.post("/{task_id}/review")
def review_management_work_item(
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    try:
        return review_delivery(
            task_id,
            reviewed_by_user_id=_actor_user_id(auth, body),
            accepted=bool(body.get("accepted")),
            feedback=str(body.get("feedback") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
        raise


@router.post("/{task_id}/retry")
def retry_management_work_item_api(
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    try:
        return retry_work_item(
            task_id,
            requested_by_user_id=_actor_user_id(auth, body),
            note=str(body.get("note") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
        raise


@router.post("/{task_id}/cancel")
def cancel_management_work_item_api(
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    try:
        return cancel_work_item(
            task_id,
            requested_by_user_id=_actor_user_id(auth, body),
            reason=str(body.get("reason") or body.get("note") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
        raise


@router.post("/{task_id}/reassign")
def reassign_management_work_item_api(
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    auth: Optional[User] = Depends(_require_admin_or_internal),
) -> dict[str, Any]:
    try:
        return reassign_work_item(
            task_id,
            new_employee_id=str(body.get("new_employee_id") or body.get("owner_employee_id") or ""),
            requested_by_user_id=_actor_user_id(auth, body),
            reason=str(body.get("reason") or body.get("note") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
        raise
