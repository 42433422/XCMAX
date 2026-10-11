"""#2288: unresolved ``{{step.path}}`` parameters must never reach a business tool."""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.param_references import (
    UNRESOLVED_CODE,
    resolve_references,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.db.base import Base
from app.db.models import InventoryLedger, InventoryTransaction, Product, Warehouse
from app.services.inventory_service import InventoryService

PRODUCT_ROW = {"id": 7, "name": "交付闭环升级标记产品-UP-20260930-OLD-001"}


@pytest.mark.parametrize(
    "template",
    ["{{query_product.data_preview[0].id}}", "{{query_product.id}}", "{{ query_product.data.id }}"],
)
def test_unique_previous_output_resolves_with_type(template):
    problems: list[str] = []
    outputs = {"query_product": {"success": True, "data": [PRODUCT_ROW]}}
    assert resolve_references({"product_id": template}, outputs, problems) == {"product_id": 7}
    assert problems == []


@pytest.mark.parametrize(
    "outputs",
    [
        {"query_product": {"success": True, "data": [PRODUCT_ROW, {"id": 8}]}},
        {"query_product": {"success": True, "data": []}},
        {"other": {"data": [PRODUCT_ROW]}},
        {"query_product": {"success": True, "data": [{"name": "无编号"}]}},
    ],
)
def test_ambiguous_missing_or_unknown_reference_is_reported(outputs):
    problems: list[str] = []
    value = resolve_references(
        {"product_id": "{{query_product.data_preview[0].id}}"}, outputs, problems
    )
    assert value == {"product_id": "{{query_product.data_preview[0].id}}"}
    assert len(problems) == 1


def _orchestrator():
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    repo, executor = MagicMock(), MagicMock()
    repo.save.side_effect = lambda run: run
    return AgentOrchestrator(repository=repo, tool_executor=executor), executor


def _run(product_rows: list[dict]) -> AgentRun:
    run = AgentRun(user_id="u1", message="卖给验收单位 1个，从库存出库发货")
    run.metadata.update(cost_units_total=0, ai_cost_units_total=0)
    query = AgentStep(node_id="query_product", tool_id="products", action="query", risk="low")
    query.status, query.output = "completed", {"success": True, "data": product_rows}
    stock_out = AgentStep(
        node_id="stock_out",
        tool_id="inventory",
        action="stock_out",
        risk="high",
        description="执行库存出库",
        depends_on=["query_product"],
        params={
            "product_id": "{{query_product.data_preview[0].id}}",
            "warehouse_id": "default_warehouse",
            "quantity": 1,
        },
    )
    run.steps = [query, stock_out]
    return run


def test_resolved_reference_is_frozen_before_the_confirmation_gate():
    orchestrator, executor = _orchestrator()
    run = _run([PRODUCT_ROW])
    orchestrator._execute_ready_steps(run, runtime_context={})
    step = run.steps[1]
    assert step.status == "waiting_user"
    assert step.params["product_id"] == 7
    executor.execute.assert_not_called()


def test_unresolvable_reference_fails_before_any_tool_call():
    orchestrator, executor = _orchestrator()
    run = _run([PRODUCT_ROW, {"id": 8, "name": "另一个"}])
    orchestrator._execute_ready_steps(run, runtime_context={}, approved_step_id="stock_out")
    step = run.steps[1]
    assert run.status == "failed" and step.status == "failed"
    assert step.output["error_code"] == UNRESOLVED_CODE
    assert "执行库存出库" in step.error and "未做任何修改" in step.error
    assert "2 条" in step.error
    executor.execute.assert_not_called()


def test_tool_executor_refuses_leftover_placeholder():
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    step = AgentStep(
        node_id="stock_out",
        tool_id="inventory",
        action="stock_out",
        params={"product_id": "{{product_query.id}}", "warehouse_id": 1, "quantity": 1},
    )
    with patch("app.application.facades.tools_facade.execute_registered_workflow_tool") as tool:
        result = AgentToolExecutor().execute(step, runtime_context={})
    assert result["success"] is False and result["error_code"] == UNRESOLVED_CODE
    tool.assert_not_called()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _stock(db, *warehouse_names: str):
    product = Product(name="出库产品", model_number="OUT-1")
    warehouses = [
        Warehouse(code=f"W{i}", name=n, status="active") for i, n in enumerate(warehouse_names)
    ]
    db.add_all([product, *warehouses])
    db.flush()
    db.add(
        InventoryLedger(
            product_id=product.id,
            warehouse_id=warehouses[0].id,
            quantity=4,
            available_quantity=4,
            reserved_quantity=0,
            unit="个",
        )
    )
    db.commit()
    return product, warehouses


def _out(db, product_id, warehouse_id):
    @contextlib.contextmanager
    def _get_db():
        yield db

    with patch("app.services.inventory_service.get_db", _get_db):
        return InventoryService().inventory_out(product_id, warehouse_id, 1)


def test_stock_out_rejects_placeholder_product_without_writing(db):
    product, warehouses = _stock(db, "默认仓库")
    result = _out(db, "{{query_product.data_preview[0].id}}", warehouses[0].id)
    assert result["success"] is False
    assert result["error_code"] == "invalid_product_reference"
    assert db.query(InventoryTransaction).count() == 0


def test_stock_out_resolves_symbolic_default_warehouse_only_when_unique(db):
    product, warehouses = _stock(db, "默认仓库")
    result = _out(db, str(product.id), "default_warehouse")
    assert result["success"] is True
    db.expire_all()
    assert float(db.query(InventoryLedger).one().available_quantity) == 3


def test_stock_out_refuses_symbolic_warehouse_when_ambiguous(db):
    product, _ = _stock(db, "默认仓库", "二号仓")
    result = _out(db, product.id, "default_warehouse")
    assert result["success"] is False
    assert result["error_code"] == "invalid_warehouse_reference"
    assert db.query(InventoryTransaction).count() == 0


def test_refusal_message_reaches_the_chat_summary():
    from app.application.agent_orchestrator.business_harness import _result_summary

    orchestrator, _ = _orchestrator()
    run = _run([])
    orchestrator._execute_ready_steps(run, runtime_context={})
    assert "前序结果为空" in _result_summary(run, [])
