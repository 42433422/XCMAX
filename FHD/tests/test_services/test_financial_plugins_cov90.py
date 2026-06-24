"""Real-behavior coverage tests for app/services/kitten_report/financial_plugins.py.

These exercise the inner DB-query helper methods directly (the ones the existing
phase2 tests stub out) plus the recoverable-error fallbacks. Every external
dependency (the DB session) is mocked; the assertions check the actual returned
shapes / values / rounding produced by the plugin code.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.kitten_report.financial_plugins import (
    FinancialMetrics,
    FinancialReportPlugin,
    InventoryValuationPlugin,
)

GET_DB = "app.db.session.get_db"


def _db_ctx(db: MagicMock):
    """Wrap a MagicMock db as a context manager matching ``with get_db() as db``."""

    @contextmanager
    def _cm():
        yield db

    return _cm


# ---------------------------------------------------------------------------
# FinancialReportPlugin._estimate_cost  (lines 108-130)
# ---------------------------------------------------------------------------


def test_estimate_cost_returns_30pct_of_inventory_value() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = 1000.0
    plugin = FinancialReportPlugin()
    result = plugin._estimate_cost(db)
    # 1000 * 0.3 == 300.0  (line 128)
    assert result == pytest.approx(300.0)


def test_estimate_cost_none_inventory_value_is_zero() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = None
    plugin = FinancialReportPlugin()
    assert plugin._estimate_cost(db) == 0.0


def test_estimate_cost_recoverable_error_returns_zero() -> None:
    db = MagicMock()
    db.query.side_effect = RuntimeError("db down")
    plugin = FinancialReportPlugin()
    # except RECOVERABLE_ERRORS -> 0.0  (lines 129-130)
    assert plugin._estimate_cost(db) == 0.0


# ---------------------------------------------------------------------------
# FinancialReportPlugin._calculate_financial_metrics (profit_margin branch)
# ---------------------------------------------------------------------------


def test_calculate_financial_metrics_computes_profit_margin() -> None:
    row = SimpleNamespace(total_revenue=5000.0, order_count=4, avg_order=1250.0)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = row
    plugin = FinancialReportPlugin()
    with (
        patch(GET_DB, _db_ctx(db)),
        patch.object(plugin, "_estimate_cost", return_value=2000.0),
    ):
        metrics = plugin._calculate_financial_metrics({})
    assert metrics.total_revenue == 5000.0
    assert metrics.order_count == 4
    assert metrics.avg_order_value == 1250.0
    assert metrics.total_cost == 2000.0
    assert metrics.gross_profit == pytest.approx(3000.0)
    # gross_profit / revenue * 100 == 60.0  (line 104)
    assert metrics.profit_margin == pytest.approx(60.0)


def test_calculate_financial_metrics_zero_revenue_no_margin() -> None:
    row = SimpleNamespace(total_revenue=0, order_count=0, avg_order=0)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = row
    plugin = FinancialReportPlugin()
    with (
        patch(GET_DB, _db_ctx(db)),
        patch.object(plugin, "_estimate_cost", return_value=0.0),
    ):
        metrics = plugin._calculate_financial_metrics({})
    # revenue not > 0, profit_margin stays default 0.0
    assert metrics.profit_margin == 0.0
    assert metrics.gross_profit == 0.0


def test_calculate_financial_metrics_no_result_row() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    plugin = FinancialReportPlugin()
    with (
        patch(GET_DB, _db_ctx(db)),
        patch.object(plugin, "_estimate_cost", return_value=0.0),
    ):
        metrics = plugin._calculate_financial_metrics({})
    assert isinstance(metrics, FinancialMetrics)
    assert metrics.total_revenue == 0.0
    assert metrics.order_count == 0


# ---------------------------------------------------------------------------
# FinancialReportPlugin._get_monthly_breakdown  (lines 132-171)
# ---------------------------------------------------------------------------


def test_get_monthly_breakdown_builds_six_reversed_months() -> None:
    db = MagicMock()
    row = SimpleNamespace(revenue=1234.567, count=7)
    db.query.return_value.filter.return_value.first.return_value = row
    plugin = FinancialReportPlugin()
    with patch(GET_DB, _db_ctx(db)):
        out = plugin._get_monthly_breakdown()
    assert len(out) == 6
    # each entry has rounded revenue + int count
    assert out[0]["revenue"] == 1234.57
    assert out[0]["order_count"] == 7
    assert set(out[0].keys()) == {"month", "revenue", "order_count"}
    # months are in ascending order (reversed of newest-first build loop)
    months = [e["month"] for e in out]
    assert months == sorted(months)


def test_get_monthly_breakdown_handles_null_aggregates() -> None:
    db = MagicMock()
    row = SimpleNamespace(revenue=None, count=None)
    db.query.return_value.filter.return_value.first.return_value = row
    plugin = FinancialReportPlugin()
    with patch(GET_DB, _db_ctx(db)):
        out = plugin._get_monthly_breakdown()
    assert all(e["revenue"] == 0.0 for e in out)
    assert all(e["order_count"] == 0 for e in out)


def test_get_monthly_breakdown_recoverable_error_returns_empty() -> None:
    plugin = FinancialReportPlugin()
    with patch(GET_DB, side_effect=RuntimeError("boom")):
        assert plugin._get_monthly_breakdown() == []


# ---------------------------------------------------------------------------
# FinancialReportPlugin._get_product_profitability  (lines 173-208)
# ---------------------------------------------------------------------------


def test_get_product_profitability_maps_rows() -> None:
    db = MagicMock()
    rows = [
        SimpleNamespace(
            product_name="苹果",
            total_revenue=9999.999,
            total_qty=12.345,
            order_count=3,
            avg_price=83.333,
        ),
        SimpleNamespace(
            product_name="香蕉",
            total_revenue=None,
            total_qty=None,
            order_count=None,
            avg_price=None,
        ),
    ]
    (
        db.query.return_value.filter.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value
    ) = rows
    plugin = FinancialReportPlugin()
    with patch(GET_DB, _db_ctx(db)):
        out = plugin._get_product_profitability()
    assert len(out) == 2
    assert out[0]["product_name"] == "苹果"
    assert out[0]["total_revenue"] == 10000.0
    assert out[0]["total_qty"] == 12.35
    assert out[0]["order_count"] == 3
    assert out[0]["avg_price"] == 83.33
    # null aggregates coerced to 0
    assert out[1]["total_revenue"] == 0.0
    assert out[1]["order_count"] == 0


def test_get_product_profitability_recoverable_error_returns_empty() -> None:
    plugin = FinancialReportPlugin()
    with patch(GET_DB, side_effect=RuntimeError("boom")):
        assert plugin._get_product_profitability() == []


# ---------------------------------------------------------------------------
# FinancialReportPlugin._get_customer_analysis  (lines 210-243)
# ---------------------------------------------------------------------------


def test_get_customer_analysis_maps_rows() -> None:
    db = MagicMock()
    rows = [
        SimpleNamespace(
            purchase_unit="客户A",
            total_amount=5000.005,
            order_count=2,
            avg_order=2500.0,
        ),
        SimpleNamespace(
            purchase_unit=None,
            total_amount=None,
            order_count=None,
            avg_order=None,
        ),
    ]
    (
        db.query.return_value.filter.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value
    ) = rows
    plugin = FinancialReportPlugin()
    with patch(GET_DB, _db_ctx(db)):
        out = plugin._get_customer_analysis()
    assert out[0]["customer"] == "客户A"
    assert out[0]["total_amount"] == 5000.01
    assert out[0]["order_count"] == 2
    assert out[0]["avg_order_value"] == 2500.0
    assert out[1]["total_amount"] == 0.0


def test_get_customer_analysis_recoverable_error_returns_empty() -> None:
    plugin = FinancialReportPlugin()
    with patch(GET_DB, side_effect=RuntimeError("boom")):
        assert plugin._get_customer_analysis() == []


# ---------------------------------------------------------------------------
# FinancialReportPlugin.run end-to-end + error path
# ---------------------------------------------------------------------------


def test_financial_report_run_success_clips_lists_to_ten() -> None:
    plugin = FinancialReportPlugin()
    metrics = FinancialMetrics(
        total_revenue=10000.0,
        total_cost=4000.0,
        gross_profit=6000.0,
        profit_margin=60.0,
        order_count=5,
        avg_order_value=2000.0,
    )
    big_products = [{"product_name": f"p{i}"} for i in range(15)]
    big_customers = [{"customer": f"c{i}"} for i in range(15)]
    with (
        patch.object(plugin, "_calculate_financial_metrics", return_value=metrics),
        patch.object(plugin, "_get_monthly_breakdown", return_value=[{"month": "2026-06"}]),
        patch.object(plugin, "_get_product_profitability", return_value=big_products),
        patch.object(plugin, "_get_customer_analysis", return_value=big_customers),
    ):
        out = plugin.run({})
    assert out.level == "info"
    assert out.details["metrics"]["profit_margin"] == 60.0
    assert len(out.details["product_analysis"]) == 10
    assert len(out.details["customer_analysis"]) == 10
    assert "毛利率 60.0%" in out.summary


def test_financial_report_run_recoverable_error_returns_warn() -> None:
    plugin = FinancialReportPlugin()
    with patch.object(plugin, "_calculate_financial_metrics", side_effect=RuntimeError("kaboom")):
        out = plugin.run({})
    assert out.level == "warn"
    assert "财务分析执行失败" in out.summary
    assert out.details["message"] == "kaboom"


# ---------------------------------------------------------------------------
# InventoryValuationPlugin._get_material_valuation  (lines 285-342)
# ---------------------------------------------------------------------------


def test_get_material_valuation_builds_categories() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.side_effect = [4, 8888.888]
    cat_rows = [
        ("生鲜", 5000.0, 3),
        (None, None, None),
    ]
    db.query.return_value.filter.return_value.group_by.return_value.all.return_value = cat_rows
    plugin = InventoryValuationPlugin()
    with patch(GET_DB, _db_ctx(db)):
        out = plugin._get_material_valuation()
    assert out["total_items"] == 4
    assert out["total_value"] == 8888.89
    assert out["categories"][0] == {"category": "生鲜", "value": 5000.0, "count": 3}
    # None category -> "未分类", None value/count -> 0
    assert out["categories"][1] == {"category": "未分类", "value": 0.0, "count": 0}


def test_get_material_valuation_recoverable_error_returns_default() -> None:
    plugin = InventoryValuationPlugin()
    with patch(GET_DB, side_effect=RuntimeError("boom")):
        out = plugin._get_material_valuation()
    assert out == {"total_items": 0, "total_value": 0.0, "categories": []}


# ---------------------------------------------------------------------------
# InventoryValuationPlugin._get_product_valuation  (lines 344-375)
# ---------------------------------------------------------------------------


def test_get_product_valuation_returns_totals() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.side_effect = [7, 3333.336]
    plugin = InventoryValuationPlugin()
    with patch(GET_DB, _db_ctx(db)):
        out = plugin._get_product_valuation()
    assert out == {"total_items": 7, "total_value": 3333.34}


def test_get_product_valuation_null_total_value() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.side_effect = [0, None]
    plugin = InventoryValuationPlugin()
    with patch(GET_DB, _db_ctx(db)):
        out = plugin._get_product_valuation()
    assert out == {"total_items": 0, "total_value": 0.0}


def test_get_product_valuation_recoverable_error_returns_default() -> None:
    plugin = InventoryValuationPlugin()
    with patch(GET_DB, side_effect=RuntimeError("boom")):
        out = plugin._get_product_valuation()
    assert out == {"total_items": 0, "total_value": 0.0}


# ---------------------------------------------------------------------------
# InventoryValuationPlugin._get_low_stock_items  (lines 377-414)
# ---------------------------------------------------------------------------


def test_get_low_stock_items_maps_rows() -> None:
    db = MagicMock()
    items = [
        SimpleNamespace(
            name="包装盒",
            category="耗材",
            quantity=2.0,
            min_stock=10.0,
            unit_price=1.5,
        ),
        SimpleNamespace(
            name="标签",
            category=None,
            quantity=None,
            min_stock=None,
            unit_price=None,
        ),
    ]
    db.query.return_value.filter.return_value.limit.return_value.all.return_value = items
    plugin = InventoryValuationPlugin()
    with patch(GET_DB, _db_ctx(db)):
        out = plugin._get_low_stock_items()
    assert out["count"] == 2
    assert out["items"][0] == {
        "name": "包装盒",
        "category": "耗材",
        "current": 2.0,
        "min_required": 10.0,
        "unit_price": 1.5,
    }
    # None numerics coerced to 0.0
    assert out["items"][1]["current"] == 0.0
    assert out["items"][1]["min_required"] == 0.0


def test_get_low_stock_items_recoverable_error_returns_default() -> None:
    plugin = InventoryValuationPlugin()
    with patch(GET_DB, side_effect=RuntimeError("boom")):
        out = plugin._get_low_stock_items()
    assert out == {"count": 0, "items": []}


# ---------------------------------------------------------------------------
# InventoryValuationPlugin.run end-to-end (warn level when low stock)
# ---------------------------------------------------------------------------


def test_inventory_valuation_run_warn_when_low_stock() -> None:
    plugin = InventoryValuationPlugin()
    with (
        patch.object(
            plugin,
            "_get_material_valuation",
            return_value={"total_value": 100.0, "total_items": 1, "categories": []},
        ),
        patch.object(
            plugin,
            "_get_product_valuation",
            return_value={"total_value": 200.0, "total_items": 2},
        ),
        patch.object(
            plugin,
            "_get_low_stock_items",
            return_value={"count": 3, "items": [{"name": f"x{i}"} for i in range(15)]},
        ),
    ):
        out = plugin.run({})
    assert out.level == "warn"
    assert out.details["total_inventory_value"] == 300.0
    assert len(out.details["low_stock_alerts"]) == 10
    assert "3 项低于安全库存" in out.summary


def test_inventory_valuation_run_info_when_no_low_stock() -> None:
    plugin = InventoryValuationPlugin()
    with (
        patch.object(
            plugin,
            "_get_material_valuation",
            return_value={"total_value": 50.0, "total_items": 0, "categories": []},
        ),
        patch.object(
            plugin,
            "_get_product_valuation",
            return_value={"total_value": 0.0, "total_items": 0},
        ),
        patch.object(
            plugin,
            "_get_low_stock_items",
            return_value={"count": 0, "items": []},
        ),
    ):
        out = plugin.run({})
    assert out.level == "info"
    assert out.details["total_inventory_value"] == 50.0


def test_inventory_valuation_run_recoverable_error_returns_warn() -> None:
    plugin = InventoryValuationPlugin()
    with patch.object(plugin, "_get_material_valuation", side_effect=RuntimeError("kaboom")):
        out = plugin.run({})
    assert out.level == "warn"
    assert "库存评估失败" in out.summary
    assert out.details["message"] == "kaboom"
