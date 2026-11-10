from unittest.mock import Mock, patch

import pytest

from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_workflow_registry_exposes_employee_and_business_db_tools():
    from app.services.tools_execution.registry import get_workflow_tool_registry

    workflow_registry = get_workflow_tool_registry()

    assert "employee" in workflow_registry
    assert "execute" in workflow_registry["employee"]["actions"]
    assert "business_db" in workflow_registry
    assert "read" in workflow_registry["business_db"]["actions"]
    assert "write" in workflow_registry["business_db"]["actions"]

def test_employee_tool_dispatch_calls_local_employee_runtime():
    from app.domain.shared_services.tools_workflow_registered import (
        execute_registered_workflow_tool,
    )

    with (
        patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={
                "employee_pack_tools": [{"pack_id": "quality-validator"}],
                "registered_tool_count": 1,
            },
        ),
        patch(
            "app.application.employee_runtime.executor.execute_employee_task_local",
            return_value={"success": True, "result": {"summary": "ok"}},
        ) as mock_run,
    ):
        result = execute_registered_workflow_tool(
            "employee",
            "execute",
            {
                "employee_id": "quality-validator",
                "task": "inspect package",
                "_runtime_context": {"user_id": "42", "workspace_root": "/tmp/work"},
            },
        )

    assert result["success"] is True
    assert result["employee_id"] == "quality-validator"
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == "quality-validator"
    assert args[1] == "inspect package"
    assert kwargs["user_id"] == 42
    assert kwargs["workspace_root"] == "/tmp/work"


def test_business_db_read_routes_to_business_service_router():
    from app.services import tools_workflow_registered as mod

    with patch.object(
        mod,
        "_registered_router_products",
        return_value={"success": True, "data": [{"name": "A"}]},
    ) as mock_products:
        result = mod.execute_registered_workflow_tool(
            "business_db",
            "read",
            {"entity": "products", "keyword": "A", "_runtime_context": {"message": "read db"}},
        )

    assert result["success"] is True
    mock_products.assert_called_once()
    assert mock_products.call_args.args[0] == "query"
    assert mock_products.call_args.args[1]["keyword"] == "A"


def test_business_db_rejects_raw_sql():
    from app.domain.shared_services.tools_workflow_registered import (
        execute_registered_workflow_tool,
    )

    result = execute_registered_workflow_tool(
        "business_db",
        "read",
        {"entity": "products", "sql": "select * from products"},
    )

    assert result["success"] is False
    assert "SQL" in result["message"]


def test_business_db_write_and_read_use_real_sqlite_services(monkeypatch, tmp_path):
    db_file = tmp_path / "business-tools.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    import app.db as db_mod
    from app.application.business_db_write_verification import verify_business_db_write
    from app.db.db_base import Base
    from app.db.models.product import Product, UomCategory, UomUnit
    from app.db.models.purchase_unit import PurchaseUnit
    from app.domain.shared_services.tools_workflow_registered import (
        execute_registered_workflow_tool,
    )
    from app.infrastructure.tenant_scope import tenant_scope

    db_mod.dispose_and_recreate_engine()
    tables = [
        PurchaseUnit.__table__,
        UomCategory.__table__,
        UomUnit.__table__,
        Product.__table__,
    ]
    Base.metadata.create_all(db_mod.engine, tables=tables)
    try:
        customer_name = "星光贸易集成测试"
        customer_write = execute_registered_workflow_tool(
            "business_db",
            "write",
            {
                "entity": "customers",
                "operation": "upsert",
                "payload": {
                    "unit_name": customer_name,
                    "customer_name": customer_name,
                    "contact_person": "陈经理",
                    "contact_phone": "13800000001",
                },
            },
        )
        assert customer_write["success"] is True
        assert customer_write["business_verification"]["verified"] is True
        assert customer_write["business_verification"]["entity"] == "customers"
        mismatched_readback = verify_business_db_write(
            entity="customers",
            operation="upsert",
            payload={"customer_name": customer_name, "contact_person": "错误联系人"},
            result=customer_write,
        )
        assert mismatched_readback["success"] is False
        assert mismatched_readback["error_code"] == "business_write_verification_failed"
        assert mismatched_readback["business_verification"]["reason"] == "field_mismatch"
        with tenant_scope(2):
            cross_tenant_readback = verify_business_db_write(
                entity="customers",
                operation="upsert",
                payload={"customer_name": customer_name},
                result=customer_write,
            )
        assert cross_tenant_readback["success"] is False
        assert cross_tenant_readback["business_verification"]["reason"] == "record_not_found"

        customer_read = execute_registered_workflow_tool(
            "business_db",
            "read",
            {"entity": "customers", "keyword": customer_name},
        )
        assert customer_read["success"] is True
        matching_customers = [
            row for row in customer_read["data"] if row.get("customer_name") == customer_name
        ]
        assert len(matching_customers) == 1
        assert matching_customers[0]["contact_person"] == "陈经理"
        assert matching_customers[0]["contact_phone"] == "13800000001"

        customer_update = execute_registered_workflow_tool(
            "business_db",
            "write",
            {
                "entity": "customers",
                "operation": "upsert",
                "payload": {
                    "unit_name": customer_name,
                    "customer_name": customer_name,
                    "contact_person": "李经理",
                    "contact_phone": "13900000001",
                },
            },
        )
        assert customer_update["success"] is True
        assert customer_update["business_verification"]["verified"] is True

        updated_customer_read = execute_registered_workflow_tool(
            "business_db",
            "read",
            {"entity": "customers", "keyword": customer_name},
        )
        matching_customers = [
            row
            for row in updated_customer_read["data"]
            if row.get("customer_name") == customer_name
        ]
        assert len(matching_customers) == 1
        assert matching_customers[0]["contact_person"] == "李经理"
        assert matching_customers[0]["contact_phone"] == "13900000001"

        product_write = execute_registered_workflow_tool(
            "business_db",
            "write",
            {
                "entity": "products",
                "operation": "create",
                "payload": {
                    "unit_name": customer_name,
                    "name_or_model": "星光测试产品",
                    "product_name": "星光测试产品",
                    "model_number": "XG-5003",
                    "unit_price": 12.5,
                },
            },
        )
        assert product_write["success"] is True
        assert product_write["business_verification"]["verified"] is True
        assert product_write["business_verification"]["entity"] == "products"

        product_read = execute_registered_workflow_tool(
            "business_db",
            "read",
            {"entity": "products", "keyword": "XG-5003"},
        )
        assert product_read["success"] is True
        assert any(
            row.get("model_number") == "XG-5003" or row.get("name") == "星光测试产品"
            for row in product_read["data"]
        )
    finally:
        Base.metadata.drop_all(db_mod.engine, tables=list(reversed(tables)))
        db_mod.dispose_and_recreate_engine()


def test_business_db_full_crud_matrix_is_tenant_scoped_and_exact(monkeypatch, tmp_path):
    db_file = tmp_path / "business-crud-matrix.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")

    import app.db as db_mod
    from app.db.db_base import Base
    from app.db.models.material import Material
    from app.db.models.product import Product, UomCategory, UomUnit
    from app.db.models.purchase_unit import PurchaseUnit
    from app.db.models.shipment import ShipmentRecord
    from app.db.session import get_db
    from app.domain.shared_services.tools_workflow_registered import (
        execute_registered_workflow_tool,
    )
    from app.infrastructure.tenant_scope import tenant_scope

    tables = [
        PurchaseUnit.__table__,
        UomCategory.__table__,
        UomUnit.__table__,
        Product.__table__,
        Material.__table__,
        ShipmentRecord.__table__,
    ]
    db_mod.dispose_and_recreate_engine()
    Base.metadata.create_all(db_mod.engine, tables=tables)

    def write(entity, operation, payload):
        return execute_registered_workflow_tool(
            "business_db",
            "write",
            {
                "entity": entity,
                "operation": operation,
                "payload": payload,
                "_runtime_context": {"user_id": "7", "message": "test"},
            },
        )

    try:
        prefix = "CHATCRUD-MATRIX"
        customer_name = f"{prefix}-客户"
        product_name = f"{prefix}-环氧底漆"
        material_name = f"{prefix}-环氧树脂"

        customer_create = write(
            "customers",
            "create",
            {"customer_name": customer_name, "contact_person": "张一"},
        )
        assert customer_create["success"] is True
        product_create = write(
            "products",
            "create",
            {
                "product_name": product_name,
                "model_number": "CHATCRUD-EP01",
                "unit": "桶",
                "unit_name": customer_name,
                "price": 128.0,
            },
        )
        assert product_create["success"] is True
        material_create = write(
            "materials",
            "create",
            {
                "name": material_name,
                "material_code": "CHATCRUD-RESIN-01",
                "unit": "千克",
                "quantity": 100,
                "unit_price": 20,
            },
        )
        assert material_create["success"] is True
        shipment_create = write(
            "shipment_records",
            "create",
            {
                "unit_name": customer_name,
                "products": [
                    {
                        "product_name": product_name,
                        "model_number": "CHATCRUD-EP01",
                        "quantity_tins": 10,
                        "tin_spec": 20,
                        "unit_price": 128,
                    }
                ],
            },
        )
        assert shipment_create["success"] is True

        with get_db() as db:
            customer = db.query(PurchaseUnit).filter(PurchaseUnit.unit_name == customer_name).one()
            product = db.query(Product).filter(Product.model_number == "CHATCRUD-EP01").one()
            material = (
                db.query(Material).filter(Material.material_code == "CHATCRUD-RESIN-01").one()
            )
            shipment = (
                db.query(ShipmentRecord).filter(ShipmentRecord.purchase_unit == customer_name).one()
            )
            ids = {
                "customer": customer.id,
                "product": product.id,
                "material": material.id,
                "shipment": shipment.id,
            }
            assert product.unit == "桶"
            assert product.unit != customer_name
            assert {
                customer.tenant_id,
                product.tenant_id,
                material.tenant_id,
                shipment.tenant_id,
            } == {1}

        for entity, record_id in zip(
            ("customers", "products", "materials", "shipment_records"), ids.values(), strict=True
        ):
            params = {"entity": entity, "id": record_id}
            readback = execute_registered_workflow_tool("business_db", "read", params)
            assert [row["id"] for row in readback["data"]] == [record_id]
            with tenant_scope(2):
                assert execute_registered_workflow_tool("business_db", "read", params)["data"] == []

        assert write(
            "customers",
            "update",
            {"selector": {"customer_name": customer_name}, "changes": {"contact_person": "李二"}},
        )["success"]
        assert write(
            "products",
            "update",
            {
                "selector": {"model_number": "CHATCRUD-EP01"},
                "changes": {"specification": "20kg/桶", "price": 138.5},
            },
        )["success"]
        assert write(
            "materials",
            "update",
            {
                "selector": {"material_code": "CHATCRUD-RESIN-01"},
                "changes": {"quantity": 88, "unit_price": 21.5},
            },
        )["success"]
        assert write(
            "shipment_records",
            "update",
            {
                "selector": {"id": ids["shipment"]},
                "changes": {"quantity_tins": 12, "status": "processed"},
            },
        )["success"]

        with get_db() as db:
            assert db.get(PurchaseUnit, ids["customer"]).contact_person == "李二"
            assert str(db.get(Product, ids["product"]).price) == "138.50"
            assert db.get(Material, ids["material"]).quantity == 88
            updated_shipment = db.get(ShipmentRecord, ids["shipment"])
            assert updated_shipment.quantity_tins == 12
            assert updated_shipment.status == "processed"

        duplicate_name = f"{prefix}-重名产品"
        assert write(
            "products", "create", {"product_name": duplicate_name, "model_number": "DUP-01"}
        )["success"]
        assert write(
            "products", "create", {"product_name": duplicate_name, "model_number": "DUP-02"}
        )["success"]
        ambiguous = write(
            "products",
            "update",
            {"selector": {"product_name": duplicate_name}, "changes": {"price": 999}},
        )
        assert ambiguous["success"] is False
        assert ambiguous["reason"] == "ambiguous_target"
        assert len(ambiguous["candidates"]) == 2

        missing = write(
            "materials",
            "delete",
            {"selector": {"material_code": "CHATCRUD-NOT-FOUND"}},
        )
        assert missing["success"] is False
        assert missing["reason"] == "target_not_found"
        assert write("products", "delete", {"sql": "DELETE FROM products"})["success"] is False
        assert (
            write(
                "products",
                "update",
                {
                    "selector": {"id": ids["product"]},
                    "changes": {"raw_sql": "UPDATE products SET price = 1"},
                },
            )["success"]
            is False
        )
        assert (
            write("products", "delete", {"tenant_id": 2, "selector": {"id": ids["product"]}})[
                "success"
            ]
            is False
        )
        assert (
            write(
                "products",
                "update",
                {"selector": {"id": ids["product"]}, "changes": {"tenant_id": 2}},
            )["success"]
            is False
        )

        with tenant_scope(2):
            with get_db() as db:
                other = Product(
                    name=f"{prefix}-其他租户",
                    model_number="CHATCRUD-T2",
                    unit="桶",
                    tenant_id=2,
                )
                db.add(other)
                db.flush()
                other_id = other.id
        cross_tenant = write("products", "delete", {"selector": {"id": other_id}})
        assert cross_tenant["success"] is False
        assert cross_tenant["reason"] == "target_not_found"

        with get_db() as db:
            duplicate_ids = [
                row.id for row in db.query(Product).filter(Product.name == duplicate_name).all()
            ]
        for duplicate_id in duplicate_ids:
            assert write("products", "delete", {"selector": {"id": duplicate_id}})["success"]
        assert write("shipment_records", "delete", {"selector": {"id": ids["shipment"]}})["success"]
        assert write("materials", "delete", {"selector": {"id": ids["material"]}})["success"]
        assert write("products", "delete", {"selector": {"id": ids["product"]}})["success"]
        assert write("customers", "delete", {"selector": {"id": ids["customer"]}})["success"]

        with get_db() as db:
            assert db.query(PurchaseUnit).count() == 0
            assert db.query(Product).count() == 0
            assert db.query(Material).count() == 0
            assert db.query(ShipmentRecord).count() == 0
        with tenant_scope(2):
            with get_db() as db:
                assert db.query(Product).filter(Product.id == other_id).count() == 1
    finally:
        Base.metadata.drop_all(db_mod.engine, tables=list(reversed(tables)))
        db_mod.dispose_and_recreate_engine()


def test_chat_formats_employee_and_business_db_outputs():

    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep

    service = AIChatApplicationService.__new__(AIChatApplicationService)
    plan = PlanGraph(
        plan_id="p-tools",
        intent="employee_and_db",
        todo_steps=["run tools"],
        nodes=[
            WorkflowNode(
                node_id="run_employee",
                tool_id="employee",
                action="execute",
                params={"employee_id": "quality-validator", "task": "inspect"},
                risk="medium",
                idempotent=False,
                description="run employee",
            ),
            WorkflowNode(
                node_id="read_db",
                tool_id="business_db",
                action="read",
                params={"entity": "products", "keyword": "5003A"},
                risk="low",
                idempotent=True,
                description="read products",
            ),
        ],
        risk_level="medium",
    )
    run = AgentRun(
        user_id="u1",
        message="inspect",
        run_id="run-format",
        status="completed",
        plan_id=plan.plan_id,
        steps=[
            AgentStep(
                node_id="run_employee",
                tool_id="employee",
                action="execute",
                status="completed",
                output={
                    "success": True,
                    "employee_id": "quality-validator",
                    "message": "员工执行完成",
                    "data": {"result": {"summary": "ok"}},
                },
            ),
            AgentStep(
                node_id="read_db",
                tool_id="business_db",
                action="read",
                status="completed",
                output={"success": True, "data": [{"name": "A"}, {"name": "B"}]},
            ),
        ],
    )

    result = service._format_agent_run_response(plan, run)

    assert "员工 quality-validator" in result["response"]
    assert "products 查询 2 条" in result["response"]
    node_results = result["data"]["data"]["node_results"]
    assert node_results[0]["message"] == "员工执行完成"
    assert "output_preview" in node_results[0]


def test_ai_chat_dynamic_workflow_executes_employee_tool(local_tools, trusted_actor):

    from app.application.ai_chat_app_service import AIChatApplicationService

    actor = trusted_actor(permissions=["employee.execute"])
    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-employee",
        intent="employee_dispatch",
        todo_steps=["run employee"],
        nodes=[
            WorkflowNode(
                node_id="run_employee",
                tool_id="employee",
                action="execute",
                params={"employee_id": "quality-validator", "task": "inspect package"},
                risk="medium",
                idempotent=False,
                description="run employee",
            )
        ],
        risk_level="medium",
    )

    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch(
            "app.application.workflow.tool_profile.resolve_tool_execution_profile",
            return_value="pro_default",
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
        ) as mock_dispatch,
    ):
        service = AIChatApplicationService()
        service.workflow_planner.plan = Mock(return_value=plan)
        service.risk_gate.evaluate = Mock(
            return_value=Mock(
                requires_confirmation=False,
                allowed=True,
                denied_nodes=[],
                blocking_nodes=[],
                reason="test low enough",
            )
        )
        service.approval_service = Mock()
        service.approval_service.get_approval_required_nodes.return_value = []

        result = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="请调用员工 quality-validator 检查这个包",
            source="pro",
            context={**actor.context, "conversation_id": "u1"},
            file_context={},
        )

        assert result is not None
        assert result["data"]["action"] == "workflow_confirmation_required"
        assert result["run_id"]
        assert repo.get(result["run_id"]).status == "waiting_user"
        mock_dispatch.assert_not_called()

        mock_dispatch.return_value = {
            "success": True,
            "message": "employee ok",
            "data": {"done": True},
        }
        completed = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="确认",
            source="pro",
            context={**actor.context, "conversation_id": "u1"},
            file_context={},
        )

    assert completed is not None
    assert completed["success"] is True
    assert completed["run_id"] == result["run_id"]
    assert completed["data"]["action"] == "workflow_done"
    assert result is not None
    assert repo.get(result["run_id"]).status == "completed"
    mock_dispatch.assert_called_once()
    tool_id, action, params = mock_dispatch.call_args.args
    assert tool_id == "employee"
    assert action == "execute"
    assert params["_runtime_context"]["run_id"] == result["run_id"]


def test_ai_chat_explicit_business_db_read_uses_agent_orchestrator(local_tools, trusted_actor):

    from app.application.ai_chat_app_service import AIChatApplicationService

    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-db-read-agent",
        intent="business_db_read",
        todo_steps=["read customers"],
        nodes=[
            WorkflowNode(
                node_id="read_customers",
                tool_id="business_db",
                action="read",
                params={"entity": "customers", "keyword": "星光"},
                risk="low",
                idempotent=True,
                description="read customers",
            )
        ],
        risk_level="low",
    )

    actor = trusted_actor(role="admin")
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch(
            "app.application.workflow.tool_profile.resolve_tool_execution_profile",
            return_value="normal",
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "data": [{"model_number": "5003"}]},
        ) as mock_dispatch,
    ):
        service = AIChatApplicationService()
        service.workflow_planner.plan = Mock(return_value=plan)
        service.risk_gate.evaluate = Mock(
            return_value=Mock(
                requires_confirmation=False,
                allowed=True,
                denied_nodes=[],
                blocking_nodes=[],
                reason="low risk",
            )
        )
        service.approval_service = Mock()
        service.approval_service.get_approval_required_nodes.return_value = []

        result = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="查数据库客户 星光",
            source=None,
            context={**actor.context, "tool_execution_profile": "normal"},
            file_context={},
        )

    assert result is not None
    run = repo.get(result["run_id"])
    assert result["success"] is True, (
        result,
        run.error if run else None,
        [(step.status, step.error, step.output) for step in run.steps] if run else None,
    )
    assert result["data"]["action"] == "workflow_done"
    assert result["run_id"]
    assert result["data"]["data"]["run_id"] == result["run_id"]
    assert repo.get(result["run_id"]) is not None
    mock_dispatch.assert_called_once()
    tool_id, action, _params = mock_dispatch.call_args.args
    assert tool_id == "business_db"
    assert action == "read"




def test_workflow_engine_does_not_retry_non_idempotent_write():
    from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime as WorkflowEngine

    calls = {"count": 0}

    def dispatch(tool_id, action, params):
        calls["count"] += 1
        return {"success": False, "message": "db busy after partial write"}

    engine = WorkflowEngine(tool_dispatcher=dispatch)
    plan = PlanGraph(
        plan_id="p-write",
        intent="write_db",
        nodes=[
            WorkflowNode(
                node_id="write_product",
                tool_id="business_db",
                action="write",
                params={
                    "entity": "products",
                    "operation": "create",
                    "payload": {"name_or_model": "5003A"},
                },
                risk="low",
                idempotent=False,
            )
        ],
        risk_level="medium",
    )

    result = engine.run(plan, max_retries=3)

    assert result.success is False
    assert calls["count"] == 1
    node_result = result.node_results[0]
    assert node_result.retryable is False
    assert node_result.retries == 0
    assert "幂等" in node_result.recovery_hint
    assert result.final_context["workflow_status"]["failed_node_id"] == "write_product"
    assert result.final_context["workflow_trace"][0]["retryable"] is False


def test_workflow_engine_retries_idempotent_write_once_then_succeeds():
    from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime as WorkflowEngine
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    calls = {"count": 0}

    def dispatch(tool_id, action, params):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"success": False, "message": "temporary lock", "error_code": "timeout"}
        return {"success": True, "message": "customer upserted"}

    engine = WorkflowEngine(tool_dispatcher=dispatch)
    node = WorkflowNode(
        node_id="upsert_customer",
        tool_id="business_db",
        action="write",
        params={
            "entity": "customers",
            "operation": "upsert",
            "payload": {"unit_name": "星光贸易"},
        },
        risk="medium",
        idempotent=True,
    )

    result = engine.run(PlanGraph(plan_id="p-retry", intent="retry", nodes=[node]), max_retries=2)
    node_result = result.node_results[0]

    assert result.success is True
    assert calls["count"] == 2
    assert node_result.retryable is True
    assert node_result.retries == 1
    assert len(node_result.attempts) == 1


def test_chat_formats_recovery_hint_for_non_retryable_failure():
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    service = AIChatApplicationService.__new__(AIChatApplicationService)
    plan = PlanGraph(
        plan_id="p-fail",
        intent="business_db_write",
        nodes=[
            WorkflowNode(
                node_id="write_product",
                tool_id="business_db",
                action="write",
                params={"entity": "products", "operation": "create", "payload": {}},
                risk="medium",
                idempotent=False,
            )
        ],
        risk_level="medium",
    )
    run = AgentRun(
        user_id="u1",
        message="write",
        run_id="run-fail",
        status="failed",
        plan_id=plan.plan_id,
        steps=[
            AgentStep(
                node_id="write_product",
                tool_id="business_db",
                action="write",
                status="failed",
                error="raw database error",
                output={"success": False, "message": "raw database error"},
            )
        ],
    )

    result = service._format_agent_run_response(plan, run)

    assert "raw database error" not in result["response"]
    node_result = result["data"]["data"]["node_results"][0]
    assert node_result["success"] is False
    assert node_result["message"]


def test_ai_chat_explicit_employee_intent_runs_without_pro_source(local_tools, trusted_actor):

    from app.application.ai_chat_app_service import AIChatApplicationService

    actor = trusted_actor(role="admin")
    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-employee-normal",
        intent="employee_dispatch",
        todo_steps=["run employee"],
        nodes=[
            WorkflowNode(
                node_id="run_employee",
                tool_id="employee",
                action="execute",
                params={"employee_id": "quality-validator", "task": "inspect package"},
                risk="medium",
                idempotent=False,
                description="run employee",
            )
        ],
        risk_level="medium",
    )

    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch(
            "app.application.workflow.tool_profile.resolve_tool_execution_profile",
            return_value="normal",
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
        ) as mock_dispatch,
    ):
        service = AIChatApplicationService()
        service.workflow_planner.plan = Mock(return_value=plan)
        service.risk_gate.evaluate = Mock(
            return_value=Mock(
                requires_confirmation=False,
                allowed=True,
                denied_nodes=[],
                blocking_nodes=[],
                reason="explicit employee intent",
            )
        )
        service.approval_service = Mock()
        service.approval_service.get_approval_required_nodes.return_value = []

        result = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="调用员工 quality-validator 检查这个包",
            source=None,
            context={**actor.context, "conversation_id": "u1", "tool_execution_profile": "normal"},
            file_context={},
        )

        assert result is not None
        assert result["data"]["action"] == "workflow_confirmation_required"
        assert result["run_id"]
        assert repo.get(result["run_id"]).status == "waiting_user"
        mock_dispatch.assert_not_called()

        mock_dispatch.return_value = {
            "success": True,
            "message": "employee ok",
            "data": {"done": True},
        }
        completed = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="确认",
            source=None,
            context={**actor.context, "conversation_id": "u1", "tool_execution_profile": "normal"},
            file_context={},
        )

    assert result is not None
    assert completed is not None
    assert completed["success"] is True
    assert completed["run_id"] == result["run_id"]
    mock_dispatch.assert_called_once()
    tool_id, action, params = mock_dispatch.call_args.args
    assert tool_id == "employee"
    assert action == "execute"
    assert params["_runtime_context"]["run_id"] == result["run_id"]


def test_ai_chat_explicit_business_db_intent_skips_excel_shortcut_without_pro_source(
    local_tools,
    trusted_actor,
):

    from app.application.ai_chat_app_service import AIChatApplicationService

    actor = trusted_actor(role="admin")
    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-db-normal",
        intent="business_db_write",
        todo_steps=["write customer"],
        nodes=[
            WorkflowNode(
                node_id="write_customer",
                tool_id="business_db",
                action="write",
                params={
                    "entity": "customers",
                    "operation": "upsert",
                    "payload": {"unit_name": "星光贸易"},
                },
                risk="medium",
                idempotent=True,
                description="write customer",
            )
        ],
        risk_level="medium",
    )

    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch(
            "app.application.workflow.tool_profile.resolve_tool_execution_profile",
            return_value="normal",
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
        ) as mock_dispatch,
    ):
        service = AIChatApplicationService()
        service.workflow_planner.plan = Mock(return_value=plan)
        service.risk_gate.evaluate = Mock(
            return_value=Mock(
                requires_confirmation=False,
                allowed=True,
                denied_nodes=[],
                blocking_nodes=[],
                reason="explicit db intent",
            )
        )
        service.approval_service = Mock()
        service.approval_service.get_approval_required_nodes.return_value = []

        result = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="请把客户 星光贸易 写入数据库",
            source=None,
            context={**actor.context, "conversation_id": "u1", "tool_execution_profile": "normal"},
            file_context={},
        )

        assert result is not None
        assert result["data"]["action"] == "workflow_confirmation_required"
        assert result["run_id"]
        assert repo.get(result["run_id"]).status == "waiting_user"
        mock_dispatch.assert_not_called()

        mock_dispatch.return_value = {
            "success": True,
            "message": "客户已写入",
            "data": {"created": True},
        }
        completed = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="确认",
            source=None,
            context={**actor.context, "conversation_id": "u1", "tool_execution_profile": "normal"},
            file_context={},
        )

    assert result is not None
    assert completed is not None
    assert completed["success"] is True
    assert completed["run_id"] == result["run_id"]
    assert "Excel 分析上下文" not in result["response"]
    mock_dispatch.assert_called_once()
    tool_id, action, params = mock_dispatch.call_args.args
    assert tool_id == "business_db"
    assert action == "write"
    assert params["_runtime_context"]["run_id"] == result["run_id"]


def test_ai_chat_medium_risk_confirmation_stays_pending_until_user_confirms(local_tools, trusted_actor):

    from app.application.ai_chat_app_service import AIChatApplicationService

    actor = trusted_actor(role="admin")
    repo = InMemoryAgentRunRepository()
    plan = PlanGraph(
        plan_id="p-db-confirm-agent",
        intent="business_db_write",
        todo_steps=["write customer"],
        nodes=[
            WorkflowNode(
                node_id="write_customer",
                tool_id="business_db",
                action="write",
                params={
                    "entity": "customers",
                    "operation": "upsert",
                    "payload": {"unit_name": "星光贸易"},
                },
                risk="medium",
                idempotent=True,
                description="write customer",
            )
        ],
        risk_level="medium",
    )

    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch(
            "app.application.workflow.tool_profile.resolve_tool_execution_profile",
            return_value="normal",
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool"
        ) as mock_dispatch,
    ):
        service = AIChatApplicationService()
        service.workflow_planner.plan = Mock(return_value=plan)
        service.risk_gate.evaluate = Mock(
            return_value=Mock(
                requires_confirmation=True,
                allowed=False,
                denied_nodes=[],
                blocking_nodes=["write_customer"],
                reason="explicit db write needs confirmation",
            )
        )
        service.approval_service = Mock()
        service.approval_service.get_approval_required_nodes.return_value = []

        waiting = service._try_handle_dynamic_workflow(
            user_id="u1",
            message="请把客户 星光贸易 写入数据库",
            source=None,
            context={**actor.context, "conversation_id": "u1", "tool_execution_profile": "normal"},
            file_context={},
        )

        assert waiting is not None
        assert waiting["data"]["action"] == "workflow_confirmation_required"
        assert "run_id" not in waiting, waiting
        assert service._pending_workflows["u1"]["plan"].plan_id == plan.plan_id
        assert service._pending_workflows["u1"]["approval_required"] is True
        mock_dispatch.assert_not_called()


@pytest.mark.parametrize("customer_id", [10, 0, -1, "10.5", "unknown"])
def test_customer_workflow_read_never_expands_explicit_id(monkeypatch, customer_id):
    from unittest.mock import MagicMock

    from app.domain.shared_services.tools_workflow_registered import _registered_router_customers

    service = MagicMock()
    service.get_by_id.return_value = {"success": True, "data": {"id": 10}}
    monkeypatch.setattr("app.application.get_customer_app_service", lambda: service)
    result = _registered_router_customers("query", {"id": customer_id}, {}, "pro", "")
    service.get_all.assert_not_called()
    if customer_id == 10:
        assert result["success"] is True
        service.get_by_id.assert_called_once_with(10)
    else:
        assert result["success"] is False
        service.get_by_id.assert_not_called()
