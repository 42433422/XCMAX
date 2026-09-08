from datetime import date
from unittest.mock import patch

from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.sales_report_planning import monthly_sales_report_node
from app.services.tools_execution.registry import get_workflow_tool_registry


def test_monthly_report_dates_and_routing():
    node = monthly_sales_report_node("本月销售汇总", today=date(2024, 2, 15))
    assert node.params == {
        "start_date": "2024-02-01",
        "end_date": "2024-02-29 23:59:59.999999",
        "group_by": "product",
    }
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = planner._fallback_plan("report", "本月销售汇总", get_workflow_tool_registry())
    assert [(n.tool_id, n.action) for n in plan.nodes] == [("reports", "sales_summary")]
    assert monthly_sales_report_node("本月销售汇总然后删除订单") is None


def test_month_end_order_included_and_next_month_excluded(monkeypatch):
    from contextlib import contextmanager
    from datetime import datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.models import SalesOrder, SalesOrderItem
    from app.infrastructure.tenant_scope import tenant_scope
    from app.services.report_service import ReportService

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        for ident, tenant, when in [
            (1, 1, datetime(2024, 2, 29, 23, 59, 59)),
            (2, 1, datetime(2024, 3, 1)),
            (3, 2, datetime(2024, 2, 29, 12)),
        ]:
            db.add(
                SalesOrder(
                    id=ident,
                    tenant_id=tenant,
                    order_no=str(ident),
                    created_at=when,
                    total_amount=10,
                )
            )
            db.flush()
            db.add(
                SalesOrderItem(
                    tenant_id=tenant, order_id=ident, product_name="A100", quantity=1, amount=10
                )
            )

    @contextmanager
    def database():
        with factory() as db:
            yield db

    monkeypatch.setattr("app.services.report_service.get_db", database)
    node = monthly_sales_report_node("本月销售汇总", today=date(2024, 2, 15))
    with tenant_scope(1):
        report = ReportService().get_sales_report(**node.params)
        assert report["success"]
        assert report["summary"] == {"total_quantity": 1.0, "total_amount": 10.0}
    engine.dispose()


def test_unspecified_export_waits_for_valid_report_dates():
    from app.application.workflow.clarification_fields import resolve_missing_field

    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    registry = get_workflow_tool_registry()
    plan = planner._fallback_plan("export", "导出销售报表", registry)
    assert [(n.tool_id, n.action) for n in plan.nodes] == [
        ("clarify", "ask"),
        ("reports", "sales_summary"),
        ("reports", "export"),
    ]
    report = plan.nodes[1]
    item = {"reason": "report_scope", "field": "日期范围"}
    for answer in ("不要导出", "2024-03-01至2024-02-01", "2024-02-30至2024-03-01"):
        assert resolve_missing_field(report, item, answer) is None
    updates = resolve_missing_field(report, item, "2024-02-01至2024-02-29")
    assert updates == {"start_date": "2024-02-01", "end_date": "2024-02-29 23:59:59.999999"}
    assert "start_date" not in report.params
    report.params.update(updates)
    assert resolve_missing_field(report, item, "本月")["start_date"].endswith("-01")


def test_bare_sales_report_phrasings_route_to_summary_not_products():
    from app.application.workflow.sales_report_planning import sales_report_query_node

    for message in ("销售报表", "看下销售", "销售情况", "查一下销售汇总"):
        assert sales_report_query_node(message) is not None, message
        node = sales_report_query_node(message)
        assert (node.tool_id, node.action) == ("reports", "sales_summary")
    for message in ("本月销售汇总", "导出销售报表", "销售订单列表", "你好"):
        assert sales_report_query_node(message) is None, message


def test_monthly_report_accepts_variants_and_rejects_bare():
    assert monthly_sales_report_node("本月销售怎么样") is not None
    assert monthly_sales_report_node("看下这个月的销售报表") is not None
    assert monthly_sales_report_node("销售报表") is None
