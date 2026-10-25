"""管理员：运维 shell/ssh 操作审计只读 API。"""

from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends, Query

from modstore_server.api.deps import require_admin
from modstore_server.models import (
    OpsActionAuditLog,
    OpsApprovalToken,
    OpsStagedChange,
    User,
    get_session_factory,
)

router = APIRouter(prefix="/api/admin/ops", tags=["admin-ops"])


@router.get("/audit")
def list_ops_audit_logs(
    employee_id: str | None = Query(None, description="按员工包 id 过滤"),
    limit: int = Query(50, ge=1, le=200),
    _admin_user: User = Depends(require_admin),
) -> dict[str, Any]:
    _ = _admin_user
    sf = get_session_factory()
    with sf() as session:
        q = session.query(OpsActionAuditLog).order_by(OpsActionAuditLog.id.desc())
        if employee_id and employee_id.strip():
            q = q.filter(OpsActionAuditLog.employee_id == employee_id.strip())
        rows: List[OpsActionAuditLog] = q.limit(limit).all()
        items = [
            {
                "id": r.id,
                "user_id": r.user_id,
                "employee_id": r.employee_id,
                "handler": r.handler,
                "command_id": r.command_id,
                "args_json": r.args_json,
                "host_id": r.host_id,
                "exit_code": r.exit_code,
                "stdout_excerpt": (r.stdout_excerpt or "")[:4000],
                "stderr_excerpt": (r.stderr_excerpt or "")[:2000],
                "duration_ms": r.duration_ms,
                "approval_required": bool(r.approval_required),
                "dry_run": bool(r.dry_run),
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    return {"items": items, "count": len(items)}


@router.get("/staged-changes")
def list_ops_staged_changes(
    status: str | None = Query(None, description="pending|approved|rejected|deployed|failed"),
    limit: int = Query(50, ge=1, le=200),
    _admin_user: User = Depends(require_admin),
) -> dict[str, Any]:
    _ = _admin_user
    sf = get_session_factory()
    with sf() as session:
        q = session.query(OpsStagedChange).order_by(OpsStagedChange.id.desc())
        if status and status.strip():
            q = q.filter(OpsStagedChange.status == status.strip())
        rows = q.limit(limit).all()
        items = [
            {
                "id": r.id,
                "branch": r.branch,
                "base_commit": r.base_commit,
                "head_commit": r.head_commit,
                "files_changed_count": r.files_changed_count,
                "diff_summary": (r.diff_summary or "")[:4000],
                "created_by_employee_id": r.created_by_employee_id,
                "status": r.status,
                "deploy_audit_id": r.deploy_audit_id,
                "approval_token_id": r.approval_token_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "approved_at": r.approved_at.isoformat() if r.approved_at else None,
                "deployed_at": r.deployed_at.isoformat() if r.deployed_at else None,
            }
            for r in rows
        ]
    return {"items": items, "count": len(items)}


@router.get("/approval-tokens")
def list_ops_approval_tokens(
    limit: int = Query(50, ge=1, le=200),
    _admin_user: User = Depends(require_admin),
) -> dict[str, Any]:
    _ = _admin_user
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(OpsApprovalToken).order_by(OpsApprovalToken.id.desc()).limit(limit).all()
        )
        items = [
            {
                "id": r.id,
                "token_hash_prefix": (r.token_hash or "")[:12] + "…",
                "kind": r.kind,
                "payload_json": r.payload_json,
                "authorized_email": r.authorized_email,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "used_at": r.used_at.isoformat() if r.used_at else None,
                "consumed_message_id": (r.consumed_message_id or "")[:200],
                "dispatched_audit_ids_json": r.dispatched_audit_ids_json,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    return {"items": items, "count": len(items)}
