from contextlib import contextmanager as _shared_scope_contextmanager
from unittest.mock import Mock, patch

import pytest

from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.task_conversation_store import task_conversation_store
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.xiaox_http_runtime import fixture_goal_review
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry


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


def test_business_db_full_crud_matrix_is_tenant_scoped_and_exact(trusted_actor):
    actor = trusted_actor(
        user_id=7,
        tenant_id=1,
        permissions=[
            "customer.view",
            "customer.edit",
            "product.view",
            "product.edit",
            "shipment.view",
            "shipment.edit",
            "business_db.read",
            "business_db.write",
        ],
    )
    from app.db.models.material import Material
    from app.db.models.product import Product
    from app.db.models.purchase_unit import PurchaseUnit
    from app.db.models.shipment import ShipmentRecord
    from app.db.session import get_db
    from app.domain.shared_services.tools_workflow_registered import (
        execute_registered_workflow_tool,
    )
    from app.infrastructure.tenant_scope import tenant_scope

    def write(entity, operation, payload):
        return execute_registered_workflow_tool(
            "business_db",
            "write",
            {
                "entity": entity,
                "operation": operation,
                "payload": payload,
                "_runtime_context": {**actor.context, "message": "test"},
            },
        )

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
        material = db.query(Material).filter(Material.material_code == "CHATCRUD-RESIN-01").one()
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
    assert write("products", "create", {"product_name": duplicate_name, "model_number": "DUP-01"})[
        "success"
    ]
    assert write("products", "create", {"product_name": duplicate_name, "model_number": "DUP-02"})[
        "success"
    ]
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
        write("products", "delete", {"tenant_id": 2, "selector": {"id": ids["product"]}})["success"]
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


def test_workflow_engine_does_not_retry_non_idempotent_write():
    from app.infrastructure.workflow.langgraph_runtime import (
        XCAGILangGraphRuntime as WorkflowEngine,
    )

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
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.infrastructure.workflow.langgraph_runtime import (
        XCAGILangGraphRuntime as WorkflowEngine,
    )

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


@pytest.mark.parametrize("source,profile", [(None, "normal"), ("pro", "pro_default")])
@pytest.mark.parametrize(
    "tool,action,params,message",
    [
        (
            "employee",
            "execute",
            {"employee_id": "quality-validator", "task": "inspect package"},
            "调用员工 quality-validator 检查这个包",
        ),
        (
            "business_db",
            "write",
            {"entity": "customers", "operation": "upsert", "payload": {"unit_name": "星光贸易"}},
            "请把客户 星光贸易 写入数据库",
        ),
    ],
)
def test_xiaox_business_dispatch_requires_real_approval_and_rejects_unproved_success(
    dynamic_chat_runtime, monkeypatch, local_tools, source, profile, tool, action, params, message
):
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.infrastructure.tenant_scope import tenant_scope

    state = dynamic_chat_runtime
    state.actions = [{"tool_id": tool, "action": action, "params": params, "call_id": "operation"}]
    state.review = lambda prompt: fixture_goal_review(prompt, kind="write")
    state.reply = "请求已处理。"
    dispatch = Mock(
        return_value={"success": True, "message": "dispatch accepted", "data": {"done": True}}
    )
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    chat = AIChatApplicationService()
    for name in ("_persist_chat_turn", "_persist_recallable_chat_turn"):
        monkeypatch.setattr(chat, name, Mock())
    context = {
        **state.actor.context,
        "tool_execution_profile": profile,
        "memory_capture_enabled": False,
    }
    with tenant_scope(state.actor.tenant_id):
        waiting = chat.process_chat(
            str(state.actor.user_id), message, source=source, context=context
        )
        assert waiting["execution_state"] == "waiting_user", waiting
        parent_id = waiting["run_id"]
        child_id = waiting["data"]["data"]["approval_card"]["run_id"]
        assert child_id != parent_id
        dispatch.assert_not_called()
        context.update(waiting["runtime_context_update"])
        unchanged = chat.process_chat(
            str(state.actor.user_id), "确认", source=source, context=context
        )
        assert unchanged["run_id"] == parent_id
        assert unchanged["execution_state"] == "waiting_user"
        dispatch.assert_not_called()
        pending = state.client.get(f"/api/agent/runs/{child_id}")
        assert pending.status_code == 200
        approval = state.client.post(
            f"/api/agent/runs/{child_id}/continue",
            json={"approval_grant": pending.json()["approval"]["grant"]},
        )
        assert approval.status_code == 202, approval.text
        child = state.drain(child_id)
        assert child.status == "blocked"
        assert child.tool_calls[0].output["success"] is True
        assert child.metadata["verification"]["accepted"] is False
        parent = state.client.get(f"/api/agent/runs/{parent_id}")
        assert parent.status_code == 200
        saved = state.repository.get(parent_id)
        result = saved.final_output["xiaox_result"]
        assert result["execution_state"] == "unknown"
        assert result["reconciliation_required"] is True and result["retryable"] is False
        assert result["business_completed"] is False
        assert len(state.transports) == 1
    dispatch.assert_called_once()
    called_tool, called_action, called_params = dispatch.call_args.args
    assert (called_tool, called_action) == (tool, action)
    assert called_params["_runtime_context"]["run_id"] == child_id


def test_xiaox_business_database_read_uses_original_authorized_child(
    dynamic_chat_runtime, monkeypatch, local_tools
):
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.infrastructure.tenant_scope import tenant_scope

    state = dynamic_chat_runtime
    state.actions = [
        {
            "tool_id": "business_db",
            "action": "read",
            "params": {"entity": "customers", "keyword": "星光"},
            "call_id": "read",
        }
    ]
    state.review = lambda prompt: fixture_goal_review(prompt, kind="read")
    state.reply = "查询结果为空。"
    dispatch = Mock(return_value={"success": True, "data": [], "total": 0})
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    with tenant_scope(state.actor.tenant_id):
        result = AIChatApplicationService().process_chat(
            str(state.actor.user_id),
            "查数据库客户 星光",
            context={**state.actor.context, "memory_capture_enabled": False},
        )
    assert result["success"] is True and result["execution_state"] == "completed", result
    dispatch.assert_called_once()
    assert dispatch.call_args.args[:2] == ("business_db", "read")
    assert state.repository.get(result["run_id"]).metadata["runtime_type"] == "xiaox"
