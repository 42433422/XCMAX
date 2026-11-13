from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from app.neuro_bus.event_publisher_mixin import NeuroEventPublisherMixin
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 出货表没有采购成本字段，利润按行业演示口径估算；页面必须明示这是估算值。
COST_ESTIMATE_RATIO = 0.30


def _month_starts(months: int) -> list[datetime]:
    """返回最近 N 个月的月初（含当月），按时间升序。"""
    now = datetime.now()
    starts: list[datetime] = []
    for offset in range(months - 1, -1, -1):
        year, month = now.year, now.month - offset
        while month <= 0:
            month += 12
            year -= 1
        starts.append(datetime(year, month, 1))
    return starts


def _next_month(start: datetime) -> datetime:
    if start.month == 12:
        return datetime(start.year + 1, 1, 1)
    return datetime(start.year, start.month + 1, 1)


class ChartDataService(NeuroEventPublisherMixin):
    def __init__(self):
        pass

    def get_financial_dashboard(self, months: int = 6) -> dict[str, Any]:
        """经营/财报可视化看板：KPI、图表序列与明细表一次取数。"""
        months = max(1, min(int(months or 6), 24))
        try:
            from sqlalchemy import Float as SAFloat
            from sqlalchemy import and_, case, cast
            from sqlalchemy import func as sa_func

            from app.db.models.shipment import ShipmentRecord
            from app.db.session import get_db

            starts = _month_starts(months)
            labels = [start.strftime("%Y-%m") for start in starts]
            revenue: list[float] = []
            orders: list[int] = []
            current_start = starts[-1]

            with get_db() as db:
                for idx, start in enumerate(starts):
                    end = starts[idx + 1] if idx + 1 < len(starts) else _next_month(start)
                    row = (
                        db.query(
                            sa_func.coalesce(sa_func.sum(ShipmentRecord.amount), 0),
                            sa_func.count(ShipmentRecord.id),
                        )
                        .filter(
                            ShipmentRecord.created_at >= start,
                            ShipmentRecord.created_at < end,
                        )
                        .first()
                    )
                    revenue.append(round(float((row or (0, 0))[0] or 0), 2))
                    orders.append(int((row or (0, 0))[1] or 0))

                product_rows = (
                    db.query(
                        ShipmentRecord.product_name,
                        sa_func.coalesce(sa_func.sum(ShipmentRecord.amount), 0).label("revenue"),
                        sa_func.coalesce(sa_func.sum(ShipmentRecord.quantity_kg), 0).label("kg"),
                        sa_func.coalesce(sa_func.sum(ShipmentRecord.quantity_tins), 0).label(
                            "tins"
                        ),
                        sa_func.count(ShipmentRecord.id).label("orders"),
                    )
                    .filter(
                        ShipmentRecord.created_at >= current_start,
                        ShipmentRecord.created_at < _next_month(current_start),
                    )
                    .group_by(ShipmentRecord.product_name)
                    .order_by(sa_func.sum(ShipmentRecord.amount).desc())
                    .limit(20)
                    .all()
                )
                customer_rows = (
                    db.query(
                        ShipmentRecord.purchase_unit,
                        sa_func.coalesce(sa_func.sum(ShipmentRecord.amount), 0).label("total"),
                        sa_func.count(ShipmentRecord.id).label("orders"),
                    )
                    .filter(
                        ShipmentRecord.created_at >= current_start,
                        ShipmentRecord.created_at < _next_month(current_start),
                    )
                    .group_by(ShipmentRecord.purchase_unit)
                    .order_by(sa_func.sum(ShipmentRecord.amount).desc())
                    .limit(20)
                    .all()
                )

            cost = [round(value * COST_ESTIMATE_RATIO, 2) for value in revenue]
            profit = [round(value - item, 2) for value, item in zip(revenue, cost)]

            month_total = revenue[-1]
            product_table = [
                {
                    "rank": idx + 1,
                    "product_name": row.product_name,
                    "revenue": round(float(row.revenue or 0), 2),
                    "quantity_kg": round(float(row.kg or 0), 2),
                    "quantity_tins": int(row.tins or 0),
                    "orders": int(row.orders or 0),
                    "share_pct": round(float(row.revenue or 0) / month_total * 100, 1)
                    if month_total
                    else 0,
                }
                for idx, row in enumerate(product_rows)
            ]
            customer_table = [
                {
                    "rank": idx + 1,
                    "customer": row.purchase_unit,
                    "revenue": round(float(row.total or 0), 2),
                    "orders": int(row.orders or 0),
                    "avg_order": round(float(row.total or 0) / int(row.orders or 1), 2),
                    "share_pct": round(float(row.total or 0) / month_total * 100, 1)
                    if month_total
                    else 0,
                }
                for idx, row in enumerate(customer_rows)
            ]

            inventory_table: list[dict[str, Any]] = []
            try:
                from app.db.models.material import Material

                with get_db() as db:
                    rows = (
                        db.query(
                            Material.category,
                            sa_func.coalesce(
                                sa_func.sum(
                                    cast(Material.quantity, SAFloat)
                                    * cast(Material.unit_price, SAFloat)
                                ),
                                0.0,
                            ).label("value"),
                            sa_func.count(Material.id).label("items"),
                            sa_func.coalesce(
                                sa_func.sum(
                                    case(
                                        (
                                            and_(
                                                Material.min_stock > 0,
                                                Material.quantity < Material.min_stock,
                                            ),
                                            1,
                                        ),
                                        else_=0,
                                    )
                                ),
                                0,
                            ).label("low_stock"),
                        )
                        .filter(Material.is_active == 1)
                        .group_by(Material.category)
                        .all()
                    )
                inventory_table = [
                    {
                        "category": row.category or "未分类",
                        "value": round(float(row.value or 0), 2),
                        "items": int(row.items or 0),
                        "low_stock": int(row.low_stock or 0),
                    }
                    for row in rows
                ]
            except RECOVERABLE_ERRORS:
                logger.exception("financial dashboard inventory failed")

            monthly_table = [
                {
                    "month": labels[idx],
                    "revenue": revenue[idx],
                    "orders": orders[idx],
                    "estimated_cost": cost[idx],
                    "profit": profit[idx],
                    "margin_pct": round(profit[idx] / revenue[idx] * 100, 1) if revenue[idx] else 0,
                }
                for idx in range(months)
            ]

            total_revenue = round(sum(revenue), 2)
            total_orders = sum(orders)
            inventory_value = round(sum(item["value"] for item in inventory_table), 2)
            low_stock_total = sum(item["low_stock"] for item in inventory_table)
            current_revenue = revenue[-1]
            previous_revenue = revenue[-2] if len(revenue) > 1 else 0
            delta_pct = (
                round((current_revenue - previous_revenue) / previous_revenue * 100, 1)
                if previous_revenue
                else None
            )

            return {
                "success": True,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "months": months,
                "cost_estimate_ratio": COST_ESTIMATE_RATIO,
                "kpis": [
                    {
                        "key": "month_revenue",
                        "label": "本月营收",
                        "value": current_revenue,
                        "unit": "元",
                        "delta_pct": delta_pct,
                    },
                    {
                        "key": "period_revenue",
                        "label": f"近{months}月营收",
                        "value": total_revenue,
                        "unit": "元",
                    },
                    {
                        "key": "orders",
                        "label": f"近{months}月出货单",
                        "value": total_orders,
                        "unit": "单",
                    },
                    {
                        "key": "gross_profit",
                        "label": "估算毛利",
                        "value": round(total_revenue * (1 - COST_ESTIMATE_RATIO), 2),
                        "unit": "元",
                    },
                    {
                        "key": "inventory_value",
                        "label": "原料库存货值",
                        "value": inventory_value,
                        "unit": "元",
                        "hint": f"{low_stock_total} 项低于安全库存" if low_stock_total else "",
                    },
                ],
                "charts": {
                    "revenue_trend": {
                        "labels": labels,
                        "revenue": revenue,
                        "orders": orders,
                        "cost": cost,
                        "profit": profit,
                    },
                    "product_mix": {
                        "labels": [item["product_name"] for item in product_table],
                        "values": [item["revenue"] for item in product_table],
                    },
                    "customer_ranking": {
                        "labels": [item["customer"] for item in customer_table],
                        "amounts": [item["revenue"] for item in customer_table],
                        "orders": [item["orders"] for item in customer_table],
                    },
                    "inventory_mix": {
                        "labels": [item["category"] for item in inventory_table],
                        "values": [item["value"] for item in inventory_table],
                    },
                },
                "tables": {
                    "monthly": monthly_table,
                    "products": product_table,
                    "customers": customer_table,
                    "inventory": inventory_table,
                },
                "notes": [
                    "数据来源：系统业务库的出货记录、原材料与产品库存，按当前账号可见数据实时聚合。",
                    f"利润为演示口径：按营收的 {int(COST_ESTIMATE_RATIO * 100)}% 估算成本，正式财报请以财务账套为准。",
                    "产品与客户明细取本月数据；趋势与 KPI 覆盖所选月份区间。",
                ],
            }
        except RECOVERABLE_ERRORS:
            logger.exception("get_financial_dashboard failed")
            return {"success": False, "message": "经营看板数据暂不可用，请稍后重试"}

    def get_revenue_chart_data(self, months: int = 6) -> dict[str, Any]:
        try:
            from sqlalchemy import func as sa_func

            from app.db.models.shipment import ShipmentRecord
            from app.db.session import get_db

            chart_data: dict[str, list[Any]] = {"labels": [], "revenue": [], "orders": []}

            with get_db() as db:
                for i in range(months):
                    date = datetime.now() - timedelta(days=30 * i)
                    month_start = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

                    if i == months - 1:
                        month_end = month_start
                    else:
                        next_month = month_start + timedelta(days=32)
                        month_end = next_month.replace(day=1)

                    result = (
                        db.query(
                            sa_func.coalesce(sa_func.sum(ShipmentRecord.amount), 0),
                            sa_func.count(ShipmentRecord.id),
                        )
                        .filter(
                            ShipmentRecord.created_at >= month_start,
                            ShipmentRecord.created_at < month_end,
                        )
                        .first()
                    )

                    chart_data["labels"].insert(0, month_start.strftime("%Y-%m"))
                    chart_data["revenue"].insert(0, round(float(result[0] or 0), 2))
                    chart_data["orders"].insert(0, int(result[1] or 0))

            return {
                "success": True,
                "type": "line",
                "data": chart_data,
                "title": "月度营收趋势",
            }
        except RECOVERABLE_ERRORS:
            logger.exception("get_revenue_chart_data failed")
            return {"success": False, "message": "营收图表暂不可用"}

    def get_product_pie_chart_data(self) -> dict[str, Any]:
        try:
            from sqlalchemy import func as sa_func

            from app.db.models.shipment import ShipmentRecord
            from app.db.session import get_db

            now = datetime.now()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            with get_db() as db:
                results = (
                    db.query(
                        ShipmentRecord.product_name,
                        sa_func.coalesce(sa_func.sum(ShipmentRecord.amount), 0).label("total"),
                    )
                    .filter(ShipmentRecord.created_at >= month_start)
                    .group_by(ShipmentRecord.product_name)
                    .order_by(sa_func.sum(ShipmentRecord.amount).desc())
                    .limit(10)
                    .all()
                )

                labels = [r.product_name for r in results]
                values = [round(float(r.total or 0), 2) for r in results]

            return {
                "success": True,
                "type": "pie",
                "data": {
                    "labels": labels,
                    "values": values,
                },
                "title": "产品销售占比（本月）",
            }
        except RECOVERABLE_ERRORS:
            logger.exception("get_product_pie_chart_data failed")
            return {"success": False, "message": "产品图表暂不可用"}

    def get_customer_bar_chart_data(self) -> dict[str, Any]:
        try:
            from sqlalchemy import func as sa_func

            from app.db.models.shipment import ShipmentRecord
            from app.db.session import get_db

            now = datetime.now()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            with get_db() as db:
                results = (
                    db.query(
                        ShipmentRecord.purchase_unit,
                        sa_func.coalesce(sa_func.sum(ShipmentRecord.amount), 0).label("total"),
                        sa_func.count(ShipmentRecord.id).label("count"),
                    )
                    .filter(ShipmentRecord.created_at >= month_start)
                    .group_by(ShipmentRecord.purchase_unit)
                    .order_by(sa_func.sum(ShipmentRecord.amount).desc())
                    .limit(8)
                    .all()
                )

                data = {
                    "labels": [
                        (
                            r.purchase_unit[:10] + "..."
                            if len(r.purchase_unit) > 10
                            else r.purchase_unit
                        )
                        for r in results
                    ],
                    "amounts": [round(float(r.total or 0), 2) for r in results],
                    "orders": [int(r.count or 0) for r in results],
                }

            return {
                "success": True,
                "type": "bar",
                "data": data,
                "title": "客户销售额排行（本月）",
            }
        except RECOVERABLE_ERRORS:
            logger.exception("get_customer_bar_chart_data failed")
            return {"success": False, "message": "客户图表暂不可用"}

    def get_profit_trend_chart_data(self, months: int = 6) -> dict[str, Any]:
        try:
            from sqlalchemy import func as sa_func

            from app.db.models.shipment import ShipmentRecord
            from app.db.session import get_db

            chart_data: dict[str, list[Any]] = {
                "labels": [],
                "revenue": [],
                "estimated_cost": [],
                "profit": [],
            }

            with get_db() as db:
                for i in range(months):
                    date = datetime.now() - timedelta(days=30 * i)
                    month_start = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

                    if i == months - 1:
                        month_end = month_start
                    else:
                        next_month = month_start + timedelta(days=32)
                        month_end = next_month.replace(day=1)

                    revenue_result = (
                        db.query(sa_func.coalesce(sa_func.sum(ShipmentRecord.amount), 0))
                        .filter(
                            ShipmentRecord.created_at >= month_start,
                            ShipmentRecord.created_at < month_end,
                        )
                        .scalar()
                    )

                    revenue = float(revenue_result or 0)
                    estimated_cost = revenue * 0.3
                    profit = revenue - estimated_cost

                    chart_data["labels"].insert(0, month_start.strftime("%Y-%m"))
                    chart_data["revenue"].insert(0, round(revenue, 2))
                    chart_data["estimated_cost"].insert(0, round(estimated_cost, 2))
                    chart_data["profit"].insert(0, round(profit, 2))

            return {
                "success": True,
                "type": "mixed",
                "data": chart_data,
                "title": "营收成本利润趋势",
            }
        except RECOVERABLE_ERRORS:
            logger.exception("get_profit_trend_chart_data failed")
            return {"success": False, "message": "利润图表暂不可用"}

    def get_inventory_chart_data(self) -> dict[str, Any]:
        try:
            from sqlalchemy import Float as SAFloat
            from sqlalchemy import cast
            from sqlalchemy import func as sa_func

            from app.db.models.material import Material
            from app.db.session import get_db

            with get_db() as db:
                category_results = (
                    db.query(
                        Material.category,
                        sa_func.coalesce(
                            sa_func.sum(
                                cast(Material.quantity, SAFloat)
                                * cast(Material.unit_price, SAFloat)
                            ),
                            0.0,
                        ).label("value"),
                    )
                    .filter(Material.is_active == 1)
                    .group_by(Material.category)
                    .all()
                )

                categories = []
                values = []

                for cat, val in category_results:
                    if val and val > 0:
                        categories.append(cat or "未分类")
                        values.append(round(float(val), 2))

            return {
                "success": True,
                "type": "doughnut",
                "data": {
                    "labels": categories,
                    "values": values,
                },
                "title": "原材料库存价值分布",
            }
        except RECOVERABLE_ERRORS as e:
            from sqlalchemy.exc import ProgrammingError

            if (
                isinstance(e, ProgrammingError)
                and getattr(getattr(e, "orig", None), "pgcode", None) == "42P01"
            ):
                return {
                    "success": True,
                    "type": "doughnut",
                    "data": {"labels": [], "values": []},
                    "title": "原材料库存价值分布",
                }
            logger.exception("get_inventory_chart_data failed")
            return {"success": False, "message": "库存图表暂不可用"}

    def get_all_charts_data(self) -> dict[str, Any]:
        return {
            "revenue_trend": self.get_revenue_chart_data(),
            "product_distribution": self.get_product_pie_chart_data(),
            "customer_ranking": self.get_customer_bar_chart_data(),
            "profit_analysis": self.get_profit_trend_chart_data(),
            "inventory_breakdown": self.get_inventory_chart_data(),
        }


chart_service = ChartDataService()


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(
    ChartDataService, "app.domain.shared_services.kitten_report.chart_data_service"
)
