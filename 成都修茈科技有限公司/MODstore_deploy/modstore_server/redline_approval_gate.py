"""红线审批门控系统：将硬阻断改为 AI 执行 + 人工审批。

红线领域（原硬阻断 → 现审批门控）：
1. 支付变更 — payment-billing-reconciler 执行，admin 审批后落盘
2. 安全变更 — security-secrets-guard 执行，admin 审批后落盘
3. 数据库变更 — dbops-engineer 执行，admin 审批后落盘
4. 生产发布 — deploy-release-officer 执行，admin 审批后推进
5. 文件删除 — retention-officer 执行，admin 审批后删除

审批流程：
  AI 员工执行 → 创建 RedlineApprovalRequest → 等待 admin 审批
  → 审批通过 → apply_employee_change_request 落盘
  → 审批拒绝 → 回滚变更
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

REDLINE_DOMAINS = {
    "payment": {
        "employee_id": "payment-billing-reconciler",
        "description": "支付相关变更",
        "approval_timeout_hours": 24,
        "auto_rollback": True,
    },
    "security": {
        "employee_id": "security-secrets-guard",
        "description": "安全相关变更",
        "approval_timeout_hours": 12,
        "auto_rollback": True,
    },
    "database": {
        "employee_id": "dbops-engineer",
        "description": "数据库 schema 变更",
        "approval_timeout_hours": 48,
        "auto_rollback": True,
    },
    "deploy": {
        "employee_id": "deploy-release-officer",
        "description": "生产环境发布",
        "approval_timeout_hours": 4,
        "auto_rollback": False,
    },
    "deletion": {
        "employee_id": "retention-officer",
        "description": "文件/数据删除",
        "approval_timeout_hours": 24,
        "auto_rollback": True,
    },
}


def create_redline_request(
    domain: str,
    source_employee_id: str,
    change_description: str,
    change_details: Dict[str, Any],
    *,
    affected_paths: Optional[List[str]] = None,
    risk_assessment: str = "high",
    rollback_plan: str = "",
) -> Dict[str, Any]:
    """创建红线审批请求。

    AI 员工已经生成了变更内容，但需要 admin 审批才能落盘。
    """
    if domain not in REDLINE_DOMAINS:
        return {"ok": False, "error": f"unknown redline domain: {domain}"}

    domain_config = REDLINE_DOMAINS[domain]

    try:
        from modstore_server.models import get_session_factory

        sf = get_session_factory()

        with sf() as session:
            from modstore_server.models import EmployeeChangeRequest

            cr = EmployeeChangeRequest(
                source_employee_id=source_employee_id,
                status="pending",
                risk_level="high",
                diff_blob=json.dumps(
                    {
                        "domain": domain,
                        "description": change_description,
                        "details": change_details,
                        "affected_paths": affected_paths or [],
                        "risk_assessment": risk_assessment,
                        "rollback_plan": rollback_plan,
                        "redline": True,
                        "domain_config": domain_config,
                    },
                    ensure_ascii=False,
                ),
            )
            session.add(cr)
            session.flush()
            cr_id = int(cr.id)
            session.commit()

        from modstore_server.incident_bus import publish

        publish(
            "redline.approval.requested",
            {
                "cr_id": cr_id,
                "domain": domain,
                "source_employee_id": source_employee_id,
                "description": change_description,
            },
            source="redline_approval_gate",
        )

        return {
            "ok": True,
            "cr_id": cr_id,
            "domain": domain,
            "status": "awaiting_approval",
            "message": f"红线变更 [{domain}] 已提交，等待 admin 审批",
        }

    except Exception as exc:
        logger.exception("create_redline_request failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def approve_redline_request(
    cr_id: int,
    admin_user_id: int,
    *,
    comment: str = "",
) -> Dict[str, Any]:
    """审批通过红线请求 → 落盘变更。"""
    try:
        from modstore_server.employee_change_request_service import apply_employee_change_request

        result = apply_employee_change_request(cr_id, admin_user_id)

        from modstore_server.incident_bus import publish

        publish(
            "redline.approval.approved",
            {"cr_id": cr_id, "admin_user_id": admin_user_id, "comment": comment},
            source="redline_approval_gate",
        )

        return {"ok": True, "cr_id": cr_id, "result": result}

    except Exception as exc:
        logger.exception("approve_redline_request failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def reject_redline_request(
    cr_id: int,
    admin_user_id: int,
    *,
    reason: str = "",
) -> Dict[str, Any]:
    """审批拒绝红线请求 → 回滚变更。"""
    try:
        from modstore_server.employee_change_request_service import reject_employee_change_request

        result = reject_employee_change_request(
            cr_id,
            rejected_reason=reason,
            rejected_by_user_id=admin_user_id,
        )

        from modstore_server.incident_bus import publish

        publish(
            "redline.approval.rejected",
            {"cr_id": cr_id, "admin_user_id": admin_user_id, "reason": reason},
            source="redline_approval_gate",
        )

        return {"ok": True, "cr_id": cr_id, "result": result}

    except Exception as exc:
        logger.exception("reject_redline_request failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def get_pending_redline_requests() -> List[Dict[str, Any]]:
    """获取所有待审批的红线请求。"""
    try:
        from modstore_server.models import EmployeeChangeRequest, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            pending = (
                session.query(EmployeeChangeRequest)
                .filter(EmployeeChangeRequest.status == "pending")
                .filter(EmployeeChangeRequest.risk_level == "high")
                .order_by(EmployeeChangeRequest.created_at.desc())
                .limit(50)
                .all()
            )
            results = []
            for cr in pending:
                try:
                    data = json.loads(cr.diff_blob or "{}")
                except json.JSONDecodeError:
                    data = {}
                if data.get("redline"):
                    results.append(
                        {
                            "cr_id": int(cr.id),
                            "domain": data.get("domain", "unknown"),
                            "source_employee_id": cr.source_employee_id,
                            "description": data.get("description", ""),
                            "risk_assessment": data.get("risk_assessment", "high"),
                            "affected_paths": data.get("affected_paths", []),
                            "created_at": str(cr.created_at) if hasattr(cr, "created_at") else "",
                        }
                    )
            return results
    except Exception:
        logger.exception("get_pending_redline_requests failed")
        return []


def check_redline_timeout() -> Dict[str, Any]:
    """检查超时的红线审批请求，自动回滚。"""
    expired_count = 0
    try:
        from modstore_server.models import EmployeeChangeRequest, get_session_factory

        sf = get_session_factory()
        now = datetime.now(timezone.utc)

        with sf() as session:
            pending = (
                session.query(EmployeeChangeRequest)
                .filter(EmployeeChangeRequest.status == "pending")
                .filter(EmployeeChangeRequest.risk_level == "high")
                .all()
            )
            for cr in pending:
                try:
                    data = json.loads(cr.diff_blob or "{}")
                except json.JSONDecodeError:
                    continue
                if not data.get("redline"):
                    continue

                domain = data.get("domain", "")
                domain_config = REDLINE_DOMAINS.get(domain, {})
                timeout_hours = domain_config.get("approval_timeout_hours", 24)

                created = getattr(cr, "created_at", None)
                if created and hasattr(created, "tzinfo"):
                    if created.tzinfo is None:
                        from datetime import timezone as _tz

                        created = created.replace(tzinfo=_tz.utc)
                    elapsed = (now - created).total_seconds() / 3600
                    if elapsed > timeout_hours and domain_config.get("auto_rollback"):
                        reject_redline_request(
                            int(cr.id),
                            admin_user_id=0,
                            reason=f"红线审批超时（{timeout_hours}h），自动回滚",
                        )
                        expired_count += 1
                session.commit()

    except Exception:
        logger.exception("check_redline_timeout failed")

    return {"ok": True, "expired_rolled_back": expired_count}
