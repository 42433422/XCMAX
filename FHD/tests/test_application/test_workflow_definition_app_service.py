"""``WorkflowDefinitionAppService`` 单元测试。

使用内存 SQLite + 全量 ``Base.metadata`` 验证 CRUD + 运行管理的完整链路。
autouse ``tenant_scope(1)`` 由根 conftest 注入，与生产租户隔离行为一致。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.workflow_definition_app_service import (
    WorkflowDefinitionAppService,
)
from app.db.base import Base
from app.db.models.workflow import (
    WorkflowRunStatus,
    WorkflowRunStepStatus,
    WorkflowTriggerSource,
    WorkflowTriggerType,
)
from app.errors import WorkflowError


@pytest.fixture()
def session_factory():
    """内存 SQLite + 全量 metadata（StaticPool 共享单连接）。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # 确保所有 ORM 模型映射完成（conftest 已 import app.db.models）
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def service(session_factory) -> WorkflowDefinitionAppService:
    """注入内存 session_factory 的被测服务实例。"""
    return WorkflowDefinitionAppService(session_factory=session_factory)


def _sample_nodes() -> list[dict[str, Any]]:
    return [
        {
            "node_id": "n1",
            "tool_id": "products",
            "action": "query",
            "params": {"keyword": "ABC"},
            "risk": "low",
            "idempotent": True,
            "description": "查询产品",
            "depends_on": [],
        },
        {
            "node_id": "n2",
            "tool_id": "customers",
            "action": "query",
            "params": {"keyword": "X"},
            "risk": "low",
            "idempotent": True,
            "description": "查询客户",
            "depends_on": ["n1"],
        },
    ]


class TestWorkflowDefinitionCRUD:
    """定义 CRUD：create / get / list / update / delete。"""

    def test_create_definition_returns_full_dict(self, service: WorkflowDefinitionAppService):
        data = service.create_definition(
            tenant_id=1,
            name="订单查询流程",
            description="按客户名查产品与客户",
            trigger_type=WorkflowTriggerType.MANUAL.value,
            trigger_config={"k": "v"},
            nodes=_sample_nodes(),
            edges=[{"from": "n1", "to": "n2"}],
            created_by=42,
        )
        assert data["id"] > 0
        assert data["name"] == "订单查询流程"
        assert data["trigger_type"] == "manual"
        assert data["is_active"] is True
        assert data["version"] == 1
        assert data["tenant_id"] == 1
        assert data["created_by"] == 42
        assert len(data["nodes"]) == 2
        assert data["nodes"][0]["node_id"] == "n1"
        assert data["edges"] == [{"from": "n1", "to": "n2"}]
        assert data["trigger_config"] == {"k": "v"}

    def test_create_definition_rejects_empty_name(self, service: WorkflowDefinitionAppService):
        with pytest.raises(WorkflowError) as exc:
            service.create_definition(tenant_id=1, name="  ")
        assert "名称" in exc.value.message

    def test_create_definition_rejects_invalid_trigger_type(
        self, service: WorkflowDefinitionAppService
    ):
        with pytest.raises(WorkflowError) as exc:
            service.create_definition(
                tenant_id=1, name="x", trigger_type="bogus"
            )
        assert "触发类型" in exc.value.message

    def test_get_definition_returns_stored_data(self, service: WorkflowDefinitionAppService):
        created = service.create_definition(
            tenant_id=1, name="d1", nodes=_sample_nodes()
        )
        fetched = service.get_definition(created["id"])
        assert fetched["id"] == created["id"]
        assert fetched["name"] == "d1"
        assert len(fetched["nodes"]) == 2

    def test_get_definition_not_found_raises_404(
        self, service: WorkflowDefinitionAppService
    ):
        with pytest.raises(WorkflowError) as exc:
            service.get_definition(9999)
        assert exc.value.status_code == 404

    def test_list_definitions_filters_active_only(
        self, service: WorkflowDefinitionAppService
    ):
        a = service.create_definition(tenant_id=1, name="a")
        b = service.create_definition(tenant_id=1, name="b")
        service.update_definition(b["id"], is_active=False)

        active = service.list_definitions(tenant_id=1, active_only=True)
        assert {d["name"] for d in active} == {"a"}

        all_defs = service.list_definitions(tenant_id=1, active_only=False)
        assert {d["name"] for d in all_defs} == {"a", "b"}

    def test_update_definition_increments_version_and_applies_fields(
        self, service: WorkflowDefinitionAppService
    ):
        created = service.create_definition(
            tenant_id=1, name="orig", nodes=_sample_nodes()
        )
        updated = service.update_definition(
            created["id"],
            name="renamed",
            description="new desc",
            trigger_type=WorkflowTriggerType.SCHEDULE.value,
            trigger_config={"cron": "0 8 * * *"},
        )
        assert updated["version"] == 2
        assert updated["name"] == "renamed"
        assert updated["description"] == "new desc"
        assert updated["trigger_type"] == "schedule"
        assert updated["trigger_config"] == {"cron": "0 8 * * *"}

    def test_update_definition_rejects_invalid_trigger_type(
        self, service: WorkflowDefinitionAppService
    ):
        created = service.create_definition(tenant_id=1, name="x")
        with pytest.raises(WorkflowError):
            service.update_definition(created["id"], trigger_type="invalid")

    def test_update_definition_not_found_raises_404(
        self, service: WorkflowDefinitionAppService
    ):
        with pytest.raises(WorkflowError) as exc:
            service.update_definition(9999, name="x")
        assert exc.value.status_code == 404

    def test_delete_definition_removes_record_and_cascades(
        self, service: WorkflowDefinitionAppService
    ):
        created = service.create_definition(tenant_id=1, name="to-delete")
        run = service.start_run(created["id"])
        assert run["id"] > 0

        service.delete_definition(created["id"])
        with pytest.raises(WorkflowError):
            service.get_definition(created["id"])
        # 级联：run 也应不再可查
        with pytest.raises(WorkflowError):
            service.get_run(run["id"])

    def test_delete_definition_not_found_raises_404(
        self, service: WorkflowDefinitionAppService
    ):
        with pytest.raises(WorkflowError) as exc:
            service.delete_definition(9999)
        assert exc.value.status_code == 404


class TestWorkflowDefinitionActivation:
    """activate / deactivate。"""

    def test_activate_sets_active_true(self, service: WorkflowDefinitionAppService):
        created = service.create_definition(tenant_id=1, name="x")
        service.update_definition(created["id"], is_active=False)
        assert service.get_definition(created["id"])["is_active"] is False

        activated = service.activate_definition(created["id"])
        assert activated["is_active"] is True
        assert service.get_definition(created["id"])["is_active"] is True

    def test_deactivate_sets_active_false(self, service: WorkflowDefinitionAppService):
        created = service.create_definition(tenant_id=1, name="x")
        assert created["is_active"] is True

        deactivated = service.deactivate_definition(created["id"])
        assert deactivated["is_active"] is False
        # version 应自增（deactivate 复用 update）
        assert deactivated["version"] == 2


class TestWorkflowRunManagement:
    """start_run / get_run / list_runs / cancel_run。"""

    def test_start_run_creates_pending_run_and_steps(
        self, service: WorkflowDefinitionAppService
    ):
        created = service.create_definition(
            tenant_id=1, name="r1", nodes=_sample_nodes()
        )
        run = service.start_run(
            created["id"],
            triggered_by=WorkflowTriggerSource.USER.value,
            trigger_payload={"user_msg": "查 ABC"},
        )
        assert run["id"] > 0
        assert run["definition_id"] == created["id"]
        assert run["status"] == WorkflowRunStatus.PENDING.value
        assert run["triggered_by"] == "user"
        assert run["trigger_payload"] == {"user_msg": "查 ABC"}
        # steps_snapshot 应等于 definition.nodes
        assert len(run["steps_snapshot"]) == 2
        assert run["steps_snapshot"][0]["node_id"] == "n1"

        # 验证 step 记录已创建
        detail = service.get_run(run["id"])
        assert len(detail["steps"]) == 2
        step_statuses = {s["status"] for s in detail["steps"]}
        assert step_statuses == {WorkflowRunStepStatus.PENDING.value}
        assert {s["node_id"] for s in detail["steps"]} == {"n1", "n2"}

    def test_start_run_on_inactive_definition_raises_409(
        self, service: WorkflowDefinitionAppService
    ):
        created = service.create_definition(tenant_id=1, name="r2", nodes=_sample_nodes())
        service.deactivate_definition(created["id"])
        with pytest.raises(WorkflowError) as exc:
            service.start_run(created["id"])
        assert exc.value.status_code == 409

    def test_start_run_definition_not_found_raises_404(
        self, service: WorkflowDefinitionAppService
    ):
        with pytest.raises(WorkflowError) as exc:
            service.start_run(9999)
        assert exc.value.status_code == 404

    def test_start_run_rejects_invalid_triggered_by(
        self, service: WorkflowDefinitionAppService
    ):
        created = service.create_definition(tenant_id=1, name="r3", nodes=_sample_nodes())
        with pytest.raises(WorkflowError):
            service.start_run(created["id"], triggered_by="bogus")

    def test_start_run_with_empty_nodes_creates_run_without_steps(
        self, service: WorkflowDefinitionAppService
    ):
        created = service.create_definition(tenant_id=1, name="r4", nodes=[])
        run = service.start_run(created["id"])
        assert run["id"] > 0
        detail = service.get_run(run["id"])
        assert detail["steps"] == []

    def test_list_runs_returns_recent_first(
        self, service: WorkflowDefinitionAppService
    ):
        created = service.create_definition(
            tenant_id=1, name="r5", nodes=_sample_nodes()
        )
        run1 = service.start_run(created["id"])
        run2 = service.start_run(created["id"])
        run3 = service.start_run(created["id"])

        runs = service.list_runs(created["id"], limit=10)
        assert [r["id"] for r in runs] == [run3["id"], run2["id"], run1["id"]]

    def test_list_runs_respects_limit(self, service: WorkflowDefinitionAppService):
        created = service.create_definition(
            tenant_id=1, name="r6", nodes=_sample_nodes()
        )
        for _ in range(5):
            service.start_run(created["id"])
        runs = service.list_runs(created["id"], limit=2)
        assert len(runs) == 2

    def test_get_run_not_found_raises_404(self, service: WorkflowDefinitionAppService):
        with pytest.raises(WorkflowError) as exc:
            service.get_run(9999)
        assert exc.value.status_code == 404

    def test_cancel_run_marks_cancelled_and_skips_pending_steps(
        self, service: WorkflowDefinitionAppService
    ):
        created = service.create_definition(
            tenant_id=1, name="r7", nodes=_sample_nodes()
        )
        run = service.start_run(created["id"])
        cancelled = service.cancel_run(run["id"])
        assert cancelled["status"] == WorkflowRunStatus.CANCELLED.value
        assert cancelled["finished_at"] is not None

        detail = service.get_run(run["id"])
        # 两个 step 都应被标 skipped
        assert {s["status"] for s in detail["steps"]} == {
            WorkflowRunStepStatus.SKIPPED.value
        }

    def test_cancel_run_on_terminal_state_raises_409(
        self, service: WorkflowDefinitionAppService
    ):
        created = service.create_definition(
            tenant_id=1, name="r8", nodes=_sample_nodes()
        )
        run = service.start_run(created["id"])
        service.cancel_run(run["id"])
        with pytest.raises(WorkflowError) as exc:
            service.cancel_run(run["id"])
        assert exc.value.status_code == 409

    def test_cancel_run_not_found_raises_404(
        self, service: WorkflowDefinitionAppService
    ):
        with pytest.raises(WorkflowError) as exc:
            service.cancel_run(9999)
        assert exc.value.status_code == 404


class TestPlanGraphIntegration:
    """``create_definition_from_plan_graph`` 从 dataclass 持久化。"""

    def test_persist_plan_graph_extracts_nodes_and_edges(
        self, service: WorkflowDefinitionAppService
    ):
        from app.application.workflow.types import PlanGraph, WorkflowNode

        plan = PlanGraph(
            plan_id="plan-1",
            intent="dynamic_workflow",
            todo_steps=["s1", "s2"],
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="products",
                    action="query",
                    params={"keyword": "X"},
                    risk="low",
                    idempotent=True,
                    description="查 X",
                    depends_on=[],
                ),
                WorkflowNode(
                    node_id="n2",
                    tool_id="customers",
                    action="query",
                    params={"k": "v"},
                    risk="medium",
                    idempotent=False,
                    description="查客户",
                    depends_on=["n1"],
                ),
            ],
            risk_level="medium",
            metadata={},
        )

        data = service.create_definition_from_plan_graph(
            plan,
            tenant_id=1,
            name="auto_plan_1",
            description="auto",
            trigger_type=WorkflowTriggerType.ONE_TIME.value,
            trigger_config={"plan_id": "plan-1"},
        )
        assert data["name"] == "auto_plan_1"
        assert data["trigger_type"] == "one_time"
        assert len(data["nodes"]) == 2
        # edges 应由 depends_on 反推生成
        assert {"from": "n1", "to": "n2"} in data["edges"]
        # nodes 字段应可 JSON 反序列化
        assert data["nodes"][0]["node_id"] == "n1"
        assert data["nodes"][0]["params"] == {"keyword": "X"}
        assert data["nodes"][1]["risk"] == "medium"


class TestTenantIsolation:
    """多租户隔离：tenant=1 写入的数据 tenant=2 不可见。"""

    def test_list_definitions_scoped_by_tenant(
        self, service: WorkflowDefinitionAppService
    ):
        from app.infrastructure.tenant_scope import tenant_scope

        service.create_definition(tenant_id=1, name="t1-def")
        with tenant_scope(2):
            # tenant=2 上下文里看不到 tenant=1 的定义
            visible = service.list_definitions(tenant_id=2, active_only=False)
            assert visible == []
        # 回到 tenant=1 上下文（根 conftest autouse）应可见
        assert any(d["name"] == "t1-def" for d in service.list_definitions(tenant_id=1))

    def test_get_definition_under_other_tenant_returns_404(
        self, service: WorkflowDefinitionAppService
    ):
        from app.infrastructure.tenant_scope import tenant_scope

        created = service.create_definition(tenant_id=1, name="t1-only")
        with tenant_scope(2):
            with pytest.raises(WorkflowError) as exc:
                service.get_definition(created["id"])
            assert exc.value.status_code == 404
