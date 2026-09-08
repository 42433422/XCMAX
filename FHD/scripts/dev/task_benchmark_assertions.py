"""Business outcome assertions independent of planner action labels."""

from __future__ import annotations

from typing import Any


def check_returned_records(execution: dict[str, Any], assertions: list[dict]) -> tuple[bool, str]:
    for assertion in assertions:
        matching = [
            step
            for step in execution.get("steps", [])
            if step.get("status") == "completed"
            and step.get("tool_id") == assertion["tool_id"]
            and step.get("action") == assertion["action"]
        ]
        accepted = False
        for step in matching:
            value = step.get("output")
            for key in assertion.get("path", ["data"]):
                value = value.get(key) if isinstance(value, dict) else None
            if "equals" in assertion:
                expected_value = assertion["equals"]
                if value == expected_value and isinstance(value, bool) == isinstance(
                    expected_value, bool
                ):
                    accepted = True
                    break
                continue
            if not isinstance(value, list):
                continue
            if "count" in assertion and len(value) != assertion["count"]:
                continue
            expected = assertion.get("includes") or []
            if not expected:
                raise ValueError("returned-record assertions need expected record contents")
            if all(
                any(
                    isinstance(row, dict)
                    and all(row.get(key) == field for key, field in item.items())
                    for row in value
                )
                for item in expected
            ):
                accepted = True
                break
        if not accepted:
            return False, f"returned records differ: {assertion['tool_id']}.{assertion['action']}"
    return True, ""


def seed_records(fixtures: list[dict]) -> None:
    from app.application.business_db_write_verification import _model_config
    from app.db import SessionLocal
    from app.infrastructure.tenant_scope import current_tenant_id

    with SessionLocal() as db:
        for fixture in fixtures:
            model, fields, _ = _model_config(fixture["entity"])
            values = {fields.get(key, key): value for key, value in fixture["values"].items()}
            if "tenant_id" in values:
                raise ValueError("fixture may not override the isolated trial tenant")
            db.add(model(tenant_id=current_tenant_id(), **values))
        db.commit()


def seed_sales_period_orders(rows: list[dict]) -> None:
    """Seed explicit month-boundary amounts in the trial's already-isolated DB."""
    from calendar import monthrange
    from datetime import datetime, timedelta
    from decimal import Decimal

    from app.db import SessionLocal
    from app.db.models.sales import SalesOrder, SalesOrderItem
    from app.infrastructure.tenant_scope import current_tenant_id

    now = datetime.now()
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last = first.replace(
        day=monthrange(first.year, first.month)[1],
        hour=23,
        minute=59,
        second=59,
        microsecond=999999,
    )
    instants = {
        "month_start": first,
        "month_end": last,
        "previous_month_end": first - timedelta(microseconds=1),
    }
    with SessionLocal() as db:
        for index, row in enumerate(rows):
            instant = instants[row["at"]]
            amount = Decimal(str(row["amount"]))
            order = SalesOrder(
                tenant_id=current_tenant_id(),
                order_no=f"BENCH-PERIOD-{index}",
                customer_name="月报测试客户",
                created_at=instant,
                total_amount=amount,
            )
            db.add(order)
            db.flush()
            db.add(
                SalesOrderItem(
                    tenant_id=current_tenant_id(),
                    order_id=order.id,
                    product_name="月报测试产品",
                    quantity=1,
                    unit_price=amount,
                    amount=amount,
                )
            )
        db.commit()
