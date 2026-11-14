"""宿主管理员工必须在建审批单之前被拒绝，并把真实原因告诉用户。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

HOST_EMPLOYEE = "user-customer-service-officer"


def _employee_node(employee_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        tool_id="employee",
        action="execute",
        params={"employee_id": employee_id, "task": "继续提交原来的工单。"},
    )


def test_host_employee_is_rejected_before_any_approval(trusted_actor):
    from app.application.workflow.approval_policy import precheck_approval_node

    actor = trusted_actor(role="user")
    reason = precheck_approval_node(_employee_node(HOST_EMPLOYEE), actor.context)
    assert "平台管理员" in reason


@pytest.mark.parametrize("action", ["execute", "context"])
def test_every_host_employee_action_is_rejected(trusted_actor, action):
    from app.application.workflow.approval_policy import precheck_approval_node

    actor = trusted_actor(role="user")
    node = SimpleNamespace(
        tool_id="employee", action=action, params={"pack_id": HOST_EMPLOYEE, "task": "x"}
    )
    assert "平台管理员" in precheck_approval_node(node, actor.context)


def test_tenant_employee_is_not_blocked(trusted_actor):
    from app.application.workflow.approval_policy import precheck_approval_node

    actor = trusted_actor(role="user")
    assert precheck_approval_node(_employee_node("quote-agent"), actor.context) == ""


def test_platform_admin_may_precheck_host_employee(trusted_actor):
    from app.application.workflow.approval_policy import precheck_approval_node

    actor = trusted_actor(role="admin", tier="admin", tenant_id=None)
    assert precheck_approval_node(_employee_node(HOST_EMPLOYEE), actor.context) == ""


def test_host_employee_denial_reaches_the_user_instead_of_generic_text():
    from app.application.agent_orchestrator.public_step_errors import public_step_error

    step = SimpleNamespace(
        tool_id="employee",
        action="execute",
        status="failed",
        output={
            "success": False,
            "error_code": "employee_host_admin_required",
            "message": "宿主管理员工和专用工具需要平台管理员权限",
        },
    )
    assert public_step_error(step) == "宿主管理员工和专用工具需要平台管理员权限"
