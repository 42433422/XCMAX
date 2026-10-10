"""销售闭环在「没有仓库 / 没有库存」时给出可操作的固定引导，而不是笼统的失败。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.approval_workspace_app_service import (
    _approve_ai_workflow_request_without_node,
)
from app.application.sales_app_service import ClosedLoopExecutionError, SalesAppService
from app.application.workflow.approval_persistence import (
    INVENTORY_NOT_READY_CODE,
    WAREHOUSE_NOT_INITIALIZED_CODE,
    WORKFLOW_EXECUTION_FAILED_CODE,
    canonical_workflow_outcome,
    closed_loop_setup_failure_code,
)
from app.db.base import Base
from app.db.models import Warehouse
from app.db.models.approval import ApprovalStatus
from app.infrastructure.tenant_scope import tenant_scope


def _run(*outputs):
    return SimpleNamespace(
        steps=[SimpleNamespace(output=o, observations=[]) for o in outputs],
    )


def _failure(step: str, message: str) -> dict:
    return {
        "success": False,
        "error_code": "CLOSED_LOOP_EXECUTION_FAILED",
        "failed_step": step,
        "message": message,
    }


def test_setup_failures_map_to_fixed_guidance_codes():
    assert (
        closed_loop_setup_failure_code(
            _run(_failure("resolve_warehouse", "当前租户下无可用仓库：…"))
        )
        == WAREHOUSE_NOT_INITIALIZED_CODE
    )
    assert (
        closed_loop_setup_failure_code(
            _run(
                {"result": _failure("resolve_inventory", "可交付库存台账匹配数为 0（应为恰好 1）")}
            )
        )
        == INVENTORY_NOT_READY_CODE
    )


@pytest.mark.parametrize(
    "output",
    [
        _failure("resolve_warehouse", "当前租户下仓库不存在: id=3"),
        _failure("resolve_inventory", "可交付库存台账匹配数为 2（应为恰好 1）"),
        _failure("resolve_customer", "当前租户下无可用仓库"),
        {
            "error_code": "OTHER",
            "failed_step": "resolve_warehouse",
            "message": "当前租户下无可用仓库",
        },
        "当前租户下无可用仓库",
        None,
    ],
)
def test_other_failures_stay_generic(output):
    assert closed_loop_setup_failure_code(_run(output)) is None


def test_guidance_codes_are_whitelisted_and_carry_fixed_text_only():
    code, message = canonical_workflow_outcome(success=False, code=WAREHOUSE_NOT_INITIALIZED_CODE)
    assert code == WAREHOUSE_NOT_INITIALIZED_CODE and "初始化默认仓库" in message
    code, message = canonical_workflow_outcome(success=False, code=INVENTORY_NOT_READY_CODE)
    assert code == INVENTORY_NOT_READY_CODE and "入库" in message
    assert canonical_workflow_outcome(success=False, code="raw secret")[0] == (
        WORKFLOW_EXECUTION_FAILED_CODE
    )


def test_resolve_warehouse_without_any_warehouse_explains_how_to_fix(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cl.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with tenant_scope(2), factory.begin() as db:
        db.add(Warehouse(code="OTHER-2", name="别家仓库", status="active"))
    with tenant_scope(1), factory() as db, pytest.raises(ClosedLoopExecutionError) as excinfo:
        SalesAppService._closed_loop_resolve_warehouse(
            SalesAppService.__new__(SalesAppService),
            db,
            {"warehouse_resolution": "current_tenant_default"},
            1,
        )
    assert excinfo.value.step == "resolve_warehouse"
    assert excinfo.value.message.startswith("当前租户下无可用仓库")
    assert "初始化默认仓库" in excinfo.value.message


def test_approval_failure_message_includes_setup_guidance():
    req = Mock()
    req.status = ApprovalStatus.PENDING.value
    req.id = 1
    req.request_no = "req-ai-wh"
    req.business_data = "{}"
    req.applicant_id = None
    with (
        patch(
            "app.application.approval_workspace_app_service._can_review_ai_workflow_request",
            return_value=True,
        ),
        patch(
            "app.application.approval_workspace_app_service._has_pending_ai_workflow",
            return_value=True,
        ),
        patch(
            "app.application.approval_workspace_app_service._ai_workflow_audit_node",
            return_value=SimpleNamespace(id=9, node_name="AI 工作流审批留痕", node_order=1),
        ),
        patch(
            "app.application.approval_workspace_app_service._resume_pending_ai_workflow_after_approval",
            return_value={
                "workflow_executed": True,
                "success": False,
                "code": WAREHOUSE_NOT_INITIALIZED_CODE,
                "message": "raw-db-secret-message",
            },
        ),
        patch(
            "app.application.approval_workspace_app_service._request_to_dict",
            return_value={"id": 1, "status": "cancelled"},
        ),
        patch("app.application.approval_workspace_app_service._audit"),
    ):
        result = _approve_ai_workflow_request_without_node(
            MagicMock(), req=req, actor=1, approver_name="admin", opinion="同意"
        )
    assert result.status_code == 409
    body = json.loads(result.body)
    assert body["message"].startswith("审批通过后 AI 工作流执行失败，审批已取消：")
    assert "初始化默认仓库" in body["message"]
    assert "raw-db-secret-message" not in result.body.decode()
    assert req.status == ApprovalStatus.CANCELLED.value
    persisted = json.loads(req.business_data)["workflow_execution"]
    assert persisted["code"] == WAREHOUSE_NOT_INITIALIZED_CODE
