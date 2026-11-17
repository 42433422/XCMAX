"""Danger-operation approval bridge, reusing the existing approval tables.

危险操作不在 AIOPEN 内另建审批体系：发起时写入 ``approval_requests``，
由既有审批中心处理；通过后凭 ``approval_id`` 执行一次，执行完标记消费时间防重放。
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime
from typing import Any

from app.application.approval_workspace.repository import ApprovalRepository, ordered_nodes
from app.db.models.approval import ApprovalFlow, ApprovalRequest, ApprovalStatus
from app.db.session import get_db
from app.domain.aiopen.principal import ScreenPrincipal

BUSINESS_TYPE = "aiopen.danger_operation"
FLOW_KEY_ENV = "AIOPEN_APPROVAL_FLOW_KEY"
DEFAULT_FLOW_KEY = "aiopen_danger_operation"


def _repository() -> ApprovalRepository:
    return ApprovalRepository(lambda: get_db())


def request_digest(entry: dict[str, Any], args: dict[str, Any]) -> str:
    payload = {
        "operation_id": entry.get("operation_id"),
        "params": args.get("params") or {},
        "body": args.get("body") or {},
    }
    stable = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _applicant_id(principal: ScreenPrincipal | None) -> int | None:
    if principal is None:
        return None
    raw = str(principal.principal_id or "").strip()
    return int(raw) if raw.isdigit() else None


def _tenant_id(principal: ScreenPrincipal | None) -> int | None:
    if principal is None:
        return None
    raw = str(principal.tenant_id or "").strip()
    return int(raw) if raw.isdigit() else None


def submit(
    entry: dict[str, Any], args: dict[str, Any], principal: ScreenPrincipal | None
) -> dict[str, Any]:
    applicant_id = _applicant_id(principal)
    if applicant_id is None:
        return {
            "status": "identity_required",
            "code": "APPROVAL_IDENTITY_REQUIRED",
            "message": "危险操作需绑定具体用户身份才能发起审批，请使用账号级 Key。",
        }
    flow_key = (os.environ.get(FLOW_KEY_ENV) or DEFAULT_FLOW_KEY).strip()
    with _repository().session() as db:
        flow = (
            db.query(ApprovalFlow)
            .filter(
                ApprovalFlow.flow_key == flow_key,
                ApprovalFlow.is_active == True,
                ApprovalFlow.is_deleted == False,
            )
            .first()
        )
        if flow is None:
            return {
                "status": "flow_missing",
                "code": "APPROVAL_FLOW_NOT_CONFIGURED",
                "message": f"审批流程 {flow_key} 未配置：请先在审批中心创建并启用该流程。",
            }
        nodes = ordered_nodes(db, flow.id)
        if not nodes:
            return {
                "status": "flow_missing",
                "code": "APPROVAL_FLOW_NOT_CONFIGURED",
                "message": f"审批流程 {flow_key} 没有启用的审批节点。",
            }
        request = ApprovalRequest(
            request_no=f"APR{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}",
            flow_id=flow.id,
            business_type=BUSINESS_TYPE,
            business_data=json.dumps(
                {
                    "operation_id": entry.get("operation_id"),
                    "method": entry.get("method"),
                    "path": entry.get("path"),
                    "risk": entry.get("risk"),
                    "args_digest": request_digest(entry, args),
                    "applicant_id": applicant_id,
                },
                ensure_ascii=False,
            ),
            applicant_id=applicant_id,
            title=f"AIOPEN 危险操作审批：{entry.get('operation_id')}",
            description=f"{entry.get('method')} {entry.get('path')}",
            current_node_id=nodes[0].id,
            current_node_order=nodes[0].node_order,
            status=ApprovalStatus.PENDING.value,
            tenant_id=_tenant_id(principal),
        )
        db.add(request)
        db.commit()
        db.refresh(request)
        return {
            "status": "pending",
            "code": "APPROVAL_REQUIRED",
            "approval_id": request.id,
            "request_no": request.request_no,
            "message": (
                "已提交审批；通过后携带 approval_id 重新调用同一操作即可执行。"
                "审批单可在审批中心查看。"
            ),
        }


def consume(
    approval_id: int,
    entry: dict[str, Any],
    args: dict[str, Any],
    principal: ScreenPrincipal | None,
) -> dict[str, Any]:
    with _repository().session() as db:
        request = ApprovalRepository.request(db, approval_id)
        if request is None or str(request.business_type) != BUSINESS_TYPE:
            return {
                "status": "invalid",
                "code": "APPROVAL_INVALID",
                "message": "审批单不存在或不属于 AIOPEN 危险操作。",
            }
        try:
            data = json.loads(request.business_data or "{}")
        except json.JSONDecodeError:
            data = {}
        applicant_id = _applicant_id(principal)
        if data.get("operation_id") != entry.get("operation_id"):
            return {
                "status": "invalid",
                "code": "APPROVAL_MISMATCH",
                "message": "审批单对应的操作与本次调用不一致。",
            }
        if data.get("args_digest") != request_digest(entry, args):
            return {
                "status": "invalid",
                "code": "APPROVAL_MISMATCH",
                "message": "审批单对应的参数与本次调用不一致。",
            }
        if applicant_id is not None and int(data.get("applicant_id") or 0) != applicant_id:
            return {
                "status": "invalid",
                "code": "APPROVAL_MISMATCH",
                "message": "审批单申请人与当前调用者不一致。",
            }
        if data.get("consumed_at"):
            return {
                "status": "consumed",
                "code": "APPROVAL_CONSUMED",
                "message": "该审批单已执行过，不能重复使用。",
            }
        status = str(request.status or "")
        if status != ApprovalStatus.APPROVED.value:
            return {
                "status": "pending",
                "code": "APPROVAL_PENDING",
                "message": f"审批尚未通过（当前状态：{status}）。",
            }
        data["consumed_at"] = datetime.now().isoformat(timespec="seconds")
        request.business_data = json.dumps(data, ensure_ascii=False)
        db.commit()
        return {
            "status": "approved",
            "approval_id": request.id,
            "request_no": request.request_no,
        }
