"""订单查询验收走生产规划器和已注册工具，结果用 SQLite 里的订单核对。"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.db.models
from app.application.agent_orchestrator.tool_spec import validate_tool_call
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.planner import LLMWorkflowPlanner, get_tool_registry
from app.db.db_base import Base
from app.db.models import Customer, Product, SalesOrder, SalesOrderItem
from app.domain.shared_services.tools_workflow_registered import execute_registered_workflow_tool
from app.infrastructure.tenant_scope import tenant_scope

TODAY = "2026-11-06"
SENTENCE = "查询11月1日到11月5日成都地区未付款且超过5000的订单并导出Excel"


@pytest.fixture()
def orders(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'orders.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    with tenant_scope(1):
        db = factory()
        chengdu = Customer(customer_name="成都客户", contact_address="成都市高新区")
        beijing = Customer(customer_name="北京客户", contact_address="北京市朝阳区")
        product = Product(name="门", unit="套")
        db.add_all([chengdu, beijing, product])
        db.flush()
        rows = [
            ("IN", chengdu, "6000", datetime(2026, 11, 3, 10), "unpaid"),
            ("EDGE", chengdu, "5000.01", datetime(2026, 11, 1, 10), "unpaid"),
            ("HIGH", chengdu, "7000", datetime(2026, 11, 5, 18), "unpaid"),
            ("EQUAL", chengdu, "5000", datetime(2026, 11, 2, 10), "unpaid"),
            ("PAID", chengdu, "8000", datetime(2026, 11, 2, 11), "paid"),
            ("OTHER", beijing, "9000", datetime(2026, 11, 2, 12), "unpaid"),
            ("LATE", chengdu, "10000", datetime(2026, 11, 7, 9), "unpaid"),
            ("LOW", chengdu, "4000", datetime(2026, 11, 4, 9), "unpaid"),
            ("TODAY", chengdu, "100", datetime(2026, 11, 6, 11), "unpaid"),
            ("TODAY-PAID", chengdu, "200", datetime(2026, 11, 6, 12), "paid"),
        ]
        for order_no, customer, amount, created, payment in rows:
            order = SalesOrder(
                order_no=order_no,
                customer_id=customer.id,
                customer_name=customer.customer_name,
                state="confirmed",
                status="confirmed",
                payment_state=payment,
                total_amount=Decimal(amount),
                created_at=created,
            )
            db.add(order)
            db.flush()
            db.add(
                SalesOrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    product_name=product.name,
                    quantity=Decimal("1"),
                    ordered_quantity=Decimal("1"),
                    unit_price=Decimal(amount),
                    amount=Decimal(amount),
                    created_at=created,
                )
            )
        db.commit()
        db.close()
    yield factory
    engine.dispose()


def _plan(message: str, context: dict | None = None):
    planner = object.__new__(LLMWorkflowPlanner)
    payload = {"today": TODAY}
    payload.update(context or {})
    return planner._fallback_plan("wp-orders", message, get_tool_registry(), payload)


def _run(plan):
    engine = WorkflowEngine(tool_dispatcher=execute_registered_workflow_tool)
    context: dict = {}
    with tenant_scope(1):
        result = engine.run(plan, runtime_context=context, parallel=True)
    return result, context


def _excel_amount(output: dict) -> float:
    book = load_workbook(BytesIO(output["data"]))
    sheet = book.active
    header = [cell.value for cell in next(sheet.iter_rows(max_row=1))]
    index = header.index("amount")
    return float(sum(row[index] or 0 for row in sheet.iter_rows(min_row=2, values_only=True)))


def test_filtered_query_and_export_match_database(orders):
    plan = _plan(SENTENCE)
    assert [node.tool_id for node in plan.nodes] == ["sales", "reports"]
    assert plan.nodes[0].params["min_amount_exclusive"] == 5000
    assert plan.nodes[0].params["payment_state"] == "unpaid"
    assert plan.nodes[0].params["region"] == "成都"
    assert plan.nodes[1].depends_on == ["query_orders"]
    result, _context = _run(plan)
    assert result.success
    query = next(item for item in result.node_results if item.node_id == "query_orders")
    exported = next(item for item in result.node_results if item.node_id == "export_orders")
    assert query.output["summary"]["count"] == 3
    assert query.output["summary"]["amount"] == pytest.approx(18000.01)
    assert {row["order_no"] for row in query.output["data"]} == {"IN", "EDGE", "HIGH"}
    assert _excel_amount(exported.output) == pytest.approx(18000.01)
    assert query.started_at and query.finished_at
    evidence = {
        "task_id": plan.plan_id,
        "tool_name": query.tool_id,
        "arguments": query.params,
        "execution_status": "success" if query.success else "failed",
        "started_at": query.started_at,
        "finished_at": query.finished_at,
        "retry_count": query.retries,
        "result": {
            "count": query.output["summary"]["count"],
            "amount": query.output["summary"]["amount"],
            "orders": sorted(row["order_no"] for row in query.output["data"]),
        },
        "excel_amount": _excel_amount(exported.output),
    }
    path = "/opt/cursor/artifacts/business-turn-evidence.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(evidence, handle, ensure_ascii=False, indent=2)


def test_exact_boundary_region_and_payment_are_not_widened(orders):
    plan = _plan("查询11月1日到11月5日的订单")
    result, _context = _run(plan)
    numbers = {row["order_no"] for row in result.node_results[0].output["data"]}
    assert "EQUAL" in numbers
    assert "PAID" in numbers
    assert "OTHER" in numbers
    assert "LATE" not in numbers


def test_followup_export_uses_previous_filters(orders):
    first = _plan("查询今天未付款的订单")
    result, _context = _run(first)
    assert {row["order_no"] for row in result.node_results[0].output["data"]} == {"TODAY"}
    second = _plan("把这些订单导出成 Excel", {"tool_turn_filters": first.metadata["tool_turn_filters"]})
    exported, _context = _run(second)
    assert exported.node_results[0].tool_id == "reports"
    assert _excel_amount(exported.node_results[0].output) == pytest.approx(100)


def test_parallel_reads_use_the_workflow_scheduler(orders):
    plan = _plan("同时查询订单、客户和库存流水")
    assert [node.tool_id for node in plan.nodes] == ["sales", "customers", "inventory"]
    assert all(node.depends_on == [] and node.idempotent and node.risk == "low" for node in plan.nodes)
    result, _context = _run(plan)
    assert result.success
    assert result.final_context["parallel_batches"][0]["node_ids"] == [
        "query_orders",
        "query_customers",
        "query_inventory",
    ]


def test_incomplete_create_chitchat_negation_and_inverted_dates_do_not_execute(orders):
    before = _count(orders)
    create = _plan("创建订单 5000")
    assert create.nodes[0].tool_id == "clarify"
    refused = validate_tool_call("sales", "create_order", {"amount": 5000})
    assert refused.ok is False
    concept = _plan("什么是订单？")
    assert concept.nodes == []
    assert concept.intent == "chitchat"
    negation = _plan("不要查订单")
    assert negation.nodes == []
    vague = _plan("把订单处理一下")
    assert [node.tool_id for node in vague.nodes] == ["clarify"]
    inverted = _plan("查询11月5日到11月1日的订单")
    assert inverted.nodes[0].tool_id == "clarify"
    missing = _plan("把这些订单导出成 Excel")
    assert missing.nodes[0].tool_id == "clarify"
    assert _count(orders) == before


def test_same_sentence_twenty_times_returns_the_same_database_total(orders):
    totals = []
    for _ in range(20):
        result, _context = _run(_plan(SENTENCE))
        assert result.success
        totals.append(result.node_results[0].output["summary"]["amount"])
    assert totals == [pytest.approx(18000.01)] * 20
    assert _count(orders) == 10


def test_one_hundred_distinct_queries_match_rows_read_back_from_sqlite(orders):
    with tenant_scope(1):
        db = orders()
        try:
            stored = db.query(SalesOrder, Customer).join(Customer).all()
        finally:
            db.close()
    catalog = [
        {
            "created": order.created_at,
            "payment": order.payment_state,
            "amount": float(order.total_amount),
            "address": customer.contact_address or "",
            "order_no": order.order_no,
        }
        for order, customer in stored
    ]
    sentences = []
    windows = (("11月1日", "11月5日", 1, 5), ("11月6日", "11月7日", 6, 7), ("11月1日", "11月7日", 1, 7))
    for region in ("成都", "北京"):
        for payment, state in (("未付款", "unpaid"), ("已付款", "paid")):
            for amount in (0, 100, 200, 4000, 5000, 6000, 7000, 8000, 9000, 10000):
                for label_start, label_end, start_day, end_day in windows:
                    sentences.append((region, state, amount, start_day, end_day, label_start, label_end, payment))
    assert len({item[0:5] for item in sentences}) >= 100
    for region, state, amount, start_day, end_day, label_start, label_end, payment in sentences:
        sentence = f"查询{label_start}到{label_end}{region}地区{payment}且超过{amount}的订单"
        plan = _plan(sentence)
        assert plan.nodes[0].tool_id == "sales"
        assert plan.nodes[0].action == "query"
        with tenant_scope(1):
            output = execute_registered_workflow_tool("sales", "query", plan.nodes[0].params)
        start = datetime(2026, 11, start_day)
        end = datetime(2026, 11, end_day, 23, 59, 59)
        expected = {
            row["order_no"]
            for row in catalog
            if start <= row["created"].replace(tzinfo=None) <= end
            and row["payment"] == state
            and row["amount"] > amount
            and region in row["address"]
        }
        assert {row["order_no"] for row in output["data"]} == expected


def test_missing_sales_tool_does_not_invent_a_query():
    registry = {
        name: spec
        for name, spec in get_tool_registry().items()
        if name not in {"sales", "reports"}
    }
    planner = object.__new__(LLMWorkflowPlanner)
    plan = planner._fallback_plan("wp-missing", "查询今天的订单", registry, {"today": TODAY})
    assert all(node.tool_id != "sales" for node in plan.nodes)


def test_closed_loop_sentence_is_not_replaced_by_order_query():
    plan = _plan("把 A 产品卖给客户B，10 个，单价 100，开票收款")
    assert any(node.tool_id == "sales" and node.action == "execute_closed_loop" for node in plan.nodes)


def _count(factory) -> int:
    with tenant_scope(1):
        db = factory()
        try:
            return db.query(SalesOrder).count()
        finally:
            db.close()
