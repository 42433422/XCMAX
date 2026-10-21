"""#2290: actionable stock failure text without exposing tool error payloads."""

import contextlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.public_step_errors import public_step_error
from app.db.base import Base
from app.db.models import InventoryLedger, InventoryTransaction, Product, Warehouse
from app.services.inventory_service import InventoryService
from tests.test_application.ai_chat_test_helpers import (
    _make_node_result,
    _make_plan,
    _make_run_result,
    _make_svc,
)
from tests.test_application.test_ai_chat_app_service_branch_cov import (
    _make_agent_run,
    _make_step,
)


@pytest.fixture
def inventory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()
    engine.dispose()


def _format(output, kind, *, tool_id="inventory", action="stock_out"):
    svc, plan = _make_svc(), _make_plan()
    if kind == "agent":
        step = _make_step(
            status="failed",
            tool_id=tool_id,
            action=action,
            output=output,
            error="synthetic-secret-in-error",
        )
        run = _make_agent_run(status="failed", steps=[step])
        return svc._format_agent_run_response(plan, run)
    node = _make_node_result(
        success=False,
        tool_id=tool_id,
        action=action,
        output=output,
        error="synthetic-secret-in-error",
        retryable=False,
    )
    return svc._format_workflow_run_response(
        plan, _make_run_result(success=False, node_results=[node])
    )


@pytest.mark.parametrize("condition", ["no-ledger", "insufficient", "no-warehouse", "ambiguous"])
@pytest.mark.parametrize("kind", ["agent", "workflow"])
def test_real_inventory_failure_has_safe_actionable_response(inventory_db, condition, kind):
    db = inventory_db
    product = Product(name="Synthetic stock", model_number="STOCK-GUIDANCE")
    db.add(product)
    warehouse = Warehouse(name="默认仓库", code="GUIDANCE-W1", status="active")
    if condition != "no-warehouse":
        db.add(warehouse)
    if condition == "ambiguous":
        db.add(Warehouse(name="二号仓", code="GUIDANCE-W2", status="active"))
    db.flush()
    if condition == "insufficient":
        db.add(
            InventoryLedger(
                product_id=product.id,
                warehouse_id=warehouse.id,
                quantity=1,
                available_quantity=1,
                reserved_quantity=0,
                unit="个",
            )
        )
    db.commit()

    @contextlib.contextmanager
    def session():
        yield db

    with patch("app.services.inventory_service.get_db", session):
        result = InventoryService().inventory_out(product.id, "default_warehouse", 2)
    assert result["success"] is False
    assert db.query(InventoryTransaction).count() == 0
    assert db.query(InventoryLedger).count() == (1 if condition == "insufficient" else 0)
    if condition == "insufficient":
        assert float(db.query(InventoryLedger).one().available_quantity) == 1
    result["message"] = "synthetic-secret SQL SELECT * /private/path"
    response = _format(result, kind)
    encoded = json.dumps(response, ensure_ascii=False)
    assert response["success"] is False
    assert "synthetic-secret" not in encoded and "SELECT *" not in encoded
    if condition == "ambiguous":
        assert result["error_code"] == "invalid_warehouse_reference"
        assert "初始化默认仓库" not in encoded
        assert "详细信息已记录" in response["response"]
    elif condition == "no-warehouse":
        assert result["error_code"] == "inventory_warehouse_missing"
        assert "初始化默认仓库" in response["response"]
    else:
        assert result["error_code"] == "inventory_insufficient_stock"
        assert "库存管理 → 入库" in response["response"]


@pytest.mark.parametrize("kind", ["agent", "workflow"])
@pytest.mark.parametrize(
    "tool_id,action,code",
    [
        ("products", "stock_out", "inventory_insufficient_stock"),
        ("inventory", "query", "inventory_insufficient_stock"),
        ("inventory", "stock_out", "unknown_code"),
        ("products", "query", "inventory_warehouse_missing"),
    ],
)
def test_untrusted_or_unrelated_tool_failures_remain_generic(kind, tool_id, action, code):
    output = {"success": False, "error_code": code, "message": "synthetic-secret private error"}
    response = _format(output, kind, tool_id=tool_id, action=action)
    encoded = json.dumps(response, ensure_ascii=False)
    assert "synthetic-secret" not in encoded
    assert "详细信息已记录" in response["response"]
    assert "初始化默认仓库" not in encoded and "库存管理 → 入库" not in encoded


def test_existing_parameter_reference_guidance_is_preserved():
    step = SimpleNamespace(
        tool_id="inventory",
        action="stock_out",
        output={"error_code": "unresolved_param_reference", "message": "前序结果为空"},
    )
    assert public_step_error(step) == "前序结果为空"


def test_legacy_workflow_does_not_gain_raw_reference_message_passthrough():
    response = _format(
        {"error_code": "unresolved_param_reference", "message": "synthetic-secret reference"},
        "workflow",
        tool_id="products",
        action="query",
    )
    assert "synthetic-secret" not in json.dumps(response)
    assert "详细信息已记录" in response["response"]


def test_desktop_business_summary_uses_safe_inventory_guidance():
    from app.application.agent_orchestrator.business_harness import _result_summary
    from app.application.agent_orchestrator.public_step_errors import public_run_error

    step = _make_step(
        status="failed",
        tool_id="inventory",
        action="stock_out",
        output={"error_code": "inventory_insufficient_stock", "message": "synthetic-secret"},
    )
    run = _make_agent_run(status="failed", steps=[step])
    assert "库存管理 → 入库" in public_run_error(run)
    assert "库存管理 → 入库" in _result_summary(run, [])
    assert "synthetic-secret" not in _result_summary(run, [])
