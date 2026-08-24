from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application import erp_hr_management_app_service as service
from app.db.base import Base
from app.db.models.hr_attendance import ErpDepartment, ErpEmployee
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture()
def host_db_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(service, "HostSessionLocal", factory)
    return factory


def _seed(factory, *, tenant_id: int, suffix: str = "") -> tuple[int, int]:
    db = factory()
    try:
        department = ErpDepartment(
            tenant_id=tenant_id,
            name=f"生产部{suffix}",
            parent_name="总部",
            attendance_group="标准考勤",
            source_system="test",
            source_key=f"dept-{tenant_id}{suffix}",
            is_active=True,
        )
        db.add(department)
        db.flush()
        employee = ErpEmployee(
            tenant_id=tenant_id,
            identity_key=f"number:{tenant_id}{suffix}",
            employee_name=f"张三{suffix}",
            department_id=department.id,
            department=department.name,
            main_department="总部",
            attendance_group="标准考勤",
            employee_no=f"{tenant_id}{suffix}",
            position="操作员",
            external_user_id="",
            source_system="test",
            source_key=f"employee-{tenant_id}{suffix}",
            is_active=True,
        )
        db.add(employee)
        db.commit()
        return int(employee.id), int(department.id)
    finally:
        db.close()


def test_hr_intent_distinguishes_business_personnel_from_ai_employee_pack():
    from app.application.chat_tool_intent import looks_like_erp_hr_management_intent

    assert looks_like_erp_hr_management_intent("删除所有部门和人员") is True
    assert looks_like_erp_hr_management_intent("查看员工档案") is True
    assert looks_like_erp_hr_management_intent("调用 AI员工 quality-validator 检查代码") is False


def test_registry_and_planner_route_bulk_hr_deactivation_without_llm():
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.services.tools_execution.registry import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    assert registry["erp_hr"]["actions"]["bulk_deactivate"]["risk"] == "high"
    with (
        patch("app.application.workflow.planner.get_ai_conversation_service"),
        patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
        patch(
            "app.application.erp_hr_management_app_service.preview_erp_hr_change",
            return_value={
                "active_employees": 80,
                "active_departments": 11,
                "history_preserved": {"attendance_records": 2000, "leave_records": 8},
            },
        ),
    ):
        plan = LLMWorkflowPlanner().plan(
            "u1", "删除所有部门和人员", registry, context={"tenant_id": "1"}
        )

    assert plan.intent == "erp_hr_management"
    assert len(plan.nodes) == 1
    node = plan.nodes[0]
    assert node.tool_id == "erp_hr"
    assert node.action == "bulk_deactivate"
    assert node.params["expected_active_employees"] == 80
    assert node.params["expected_active_departments"] == 11
    assert any("80 名员工、11 个部门" in item for item in plan.todo_steps)


def test_bulk_deactivation_is_tenant_scoped_and_uses_soft_delete(host_db_factory):
    employee_id, department_id = _seed(host_db_factory, tenant_id=1)
    other_employee_id, other_department_id = _seed(host_db_factory, tenant_id=2, suffix="二")

    with tenant_scope(1):
        preview = service.execute_erp_hr_management(
            "preview", {"scope": "employees_and_departments", "all": True}
        )
        result = service.execute_erp_hr_management(
            "bulk_deactivate",
            {
                "scope": "employees_and_departments",
                "all": True,
                "expected_active_employees": 1,
                "expected_active_departments": 1,
            },
        )

    assert preview["active_employees"] == 1
    assert preview["active_departments"] == 1
    assert result["success"] is True
    assert result["transaction"] == "committed"
    assert result["physical_delete"] is False
    with tenant_scope(1):
        db = host_db_factory()
        try:
            assert (
                db.query(ErpEmployee).filter(ErpEmployee.id == employee_id).one().is_active is False
            )
            assert (
                db.query(ErpDepartment).filter(ErpDepartment.id == department_id).one().is_active
                is False
            )
            assert db.query(ErpEmployee).count() == 1
            assert db.query(ErpDepartment).count() == 1
        finally:
            db.close()
    with tenant_scope(2):
        db = host_db_factory()
        try:
            assert (
                db.query(ErpEmployee).filter(ErpEmployee.id == other_employee_id).one().is_active
                is True
            )
            assert (
                db.query(ErpDepartment)
                .filter(ErpDepartment.id == other_department_id)
                .one()
                .is_active
                is True
            )
        finally:
            db.close()


def test_bulk_failure_rolls_back_employee_changes(host_db_factory, monkeypatch):
    employee_id, department_id = _seed(host_db_factory, tenant_id=3)
    original_department_query = service._department_query
    calls = 0

    def fail_after_employee_update(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("模拟部门写入失败")
        return original_department_query(*args, **kwargs)

    monkeypatch.setattr(service, "_department_query", fail_after_employee_update)
    with tenant_scope(3):
        result = service.execute_erp_hr_management(
            "bulk_deactivate",
            {
                "scope": "employees_and_departments",
                "all": True,
                "expected_active_employees": 1,
                "expected_active_departments": 1,
            },
        )

    assert result["success"] is False
    assert result["rolled_back"] is True
    assert result["transaction"] == "rolled_back"
    assert "模拟部门写入失败" in result["message"]
    with tenant_scope(3):
        db = host_db_factory()
        try:
            assert (
                db.query(ErpEmployee).filter(ErpEmployee.id == employee_id).one().is_active is True
            )
            assert (
                db.query(ErpDepartment).filter(ErpDepartment.id == department_id).one().is_active
                is True
            )
        finally:
            db.close()


def test_workflow_response_shows_each_failure_reason_and_redacts_secret():
    from app.application.ai_chat.workflow_response_builder import AIChatWorkflowResponseMixin

    mixin = AIChatWorkflowResponseMixin()
    reason = mixin._workflow_failure_reason(
        SimpleNamespace(
            output={
                "success": False,
                "message": "审批期间员工数量已变化；token=private-value",
            },
            error="",
        )
    )

    assert "审批期间员工数量已变化" in reason
    assert "private-value" not in reason
    assert "[已隐藏]" in reason
