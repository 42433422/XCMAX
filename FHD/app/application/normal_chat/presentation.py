"""Pure presentation of business results; no service lookup or request state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.utils.ai_helpers import format_money, safe_float

from .query_execution import JsonObject, slot_reply


def _page(
    result: JsonObject,
    *,
    intent: str,
    key: str,
    empty: str,
    heading: Callable[[int], str],
    row: Callable[[JsonObject], str],
    more: Callable[[int], str] | None = None,
    include_total: bool = True,
    count_total: bool = True,
) -> JsonObject:
    items = result.get("data") or []
    total = int(result.get("total") or len(items)) if count_total else len(items)
    response = empty
    if items:
        response = heading(total) + "\n" + "\n".join(row(item) for item in items[:10])
        if total > 10 and more is not None:
            response += "\n" + more(total - 10)
    data = {key: items[:20]}
    if include_total:
        data["total"] = total
    return slot_reply(intent, response, data=data)


def inventory_alert(result: JsonObject) -> JsonObject:
    return _page(
        result,
        intent="inventory_alert",
        key="low_stock_items",
        empty="当前没有低库存原材料，库存状态正常。",
        heading=lambda n: f"⚠️ 发现 {n} 种低库存原材料：",
        row=lambda m: f"- {m.get('name', '')} 当前库存 {m.get('quantity', 0)} {m.get('unit', '')}",
        include_total=False,
        count_total=False,
    )


def manufacturing(result: JsonObject) -> JsonObject:
    return _page(
        result,
        intent="mrp_production",
        key="orders",
        empty="当前没有生产工单。",
        heading=lambda n: f"共 {n} 条生产工单：",
        row=lambda o: (
            f"- {o.get('order_no', '')} {o.get('product_name', '')} ×{o.get('quantity', 0)}（{o.get('status', '')}）"
        ),
        more=lambda n: f"…其余 {n} 条请到「生产制造」查看",
    )


def materials(result: JsonObject, keyword: str) -> JsonObject:
    return _page(
        result,
        intent="materials_query",
        key="materials",
        empty="当前物料库暂无数据。" if not keyword else f"没有查到与「{keyword}」匹配的物料。",
        heading=lambda n: f"当前共有 {n} 种物料：",
        row=lambda m: (
            f"- {m.get('name', '')} 库存 {m.get('quantity', 0)} {m.get('unit', '')}（{m.get('material_code', '')}）"
        ),
        more=lambda n: f"…其余 {n} 种请到「物料管理」查看",
    )


def _shipment_row(record: JsonObject) -> str:
    unit = str(record.get("unit_name") or record.get("purchase_unit") or "") or "-"
    date = str(record.get("date") or record.get("created_at") or "")[:10]
    return f"- {date} {unit}"


def shipments(records: list[JsonObject], keyword: str) -> JsonObject:
    return _page(
        {"data": records},
        intent="shipment_records_query",
        key="records",
        empty="当前没有出货记录。" if not keyword else f"没有查到与「{keyword}」相关的出货记录。",
        heading=lambda n: f"共 {n} 条出货记录：",
        row=_shipment_row,
        more=lambda n: f"…其余 {n} 条请到「出货记录」查看",
        include_total=False,
        count_total=False,
    )


def suppliers(result: JsonObject, keyword: str) -> JsonObject:
    return _page(
        result,
        intent="purchase_query",
        key="suppliers",
        empty="当前没有供应商数据。" if not keyword else f"没有查到与「{keyword}」匹配的供应商。",
        heading=lambda n: f"共 {n} 家供应商：",
        row=lambda s: f"- {s.get('name', '')} {s.get('contact_person', '')}".rstrip(),
        include_total=False,
        count_total=False,
    )


def purchase_orders(result: JsonObject) -> JsonObject:
    return _page(
        result,
        intent="purchase_query",
        key="orders",
        empty="当前没有采购订单。",
        heading=lambda n: f"共 {n} 条采购订单：",
        row=lambda o: (
            f"- {o.get('order_no', '')} {o.get('supplier_name', '')} ￥{format_money(safe_float(o.get('total_amount')))}"
        ),
        more=lambda n: f"…其余 {n} 条请到「采购管理」查看",
    )


def _transaction_row(transaction: JsonObject) -> str:
    kind = str(transaction.get("transaction_type") or "")
    direction = "收入" if "in" in kind.lower() or "收款" in kind else "支出"
    return (
        f"- {str(transaction.get('transaction_date') or '')[:10]} {direction} "
        f"￥{format_money(safe_float(transaction.get('amount')))} {transaction.get('counterparty_name', '')}"
    )


def finance(result: JsonObject) -> JsonObject:
    return _page(
        result,
        intent="finance_query",
        key="transactions",
        empty="当前没有财务收支记录。",
        heading=lambda n: f"共 {n} 条收支记录：",
        row=_transaction_row,
        more=lambda n: f"…其余 {n} 条请到「财务」查看",
    )


def sales(result: JsonObject, keyword: str) -> JsonObject:
    return _page(
        result,
        intent="sales_query",
        key="orders",
        empty="当前没有销售订单。" if not keyword else f"没有查到与「{keyword}」匹配的销售订单。",
        heading=lambda n: f"共 {n} 条销售订单：",
        row=lambda o: (
            f"- {o.get('order_no', '')} {o.get('customer_name', '')} ￥{format_money(safe_float(o.get('total_amount')))}（{str(o.get('status') or '')}）"
        ),
        more=lambda n: f"…其余 {n} 条请到「销售订单」查看",
    )


def aging(result: JsonObject, account_type: str) -> JsonObject:
    lines = [
        f"- {b.get('bucket', '')}：￥{format_money(safe_float(b.get('amount')))}"
        for b in result.get("data") or []
    ]
    response = (
        f"{account_type}账龄（截至 {result.get('as_of_date', '')}）：\n"
        + "\n".join(lines)
        + f"\n未结合计 ￥{format_money(safe_float(result.get('total_outstanding')))}"
    )
    return slot_reply("aging_report", response, data=result)


def reports(result: JsonObject, label: str) -> JsonObject:
    rows = result.get("data") or []
    summary = result.get("summary") or {}
    if not rows:
        response = f"当前{label}报表暂无数据。"
    else:
        response = f"{label}报表共 {len(rows)} 条：\n" + "\n".join(f"- {r}" for r in rows[:5])
        if summary:
            bits = [f"{k}={v}" for k, v in summary.items()][:4]
            response += f"\n汇总：{'，'.join(bits)}"
    return slot_reply(
        "reports_query",
        response,
        data={"report_type": label, "rows": rows[:20], "summary": summary},
    )


def replenishment(result: JsonObject) -> JsonObject:
    suggestions = result.get("data") or []
    summary = result.get("summary") or {}
    if not suggestions:
        response = "当前没有需要补货的物料，库存状态正常。"
    else:
        lines = [
            f"- {s.get('name', '')} 当前 {s.get('current_quantity', 0)} {s.get('unit', '')}，建议补 {s.get('suggest_quantity', 0)}"
            for s in suggestions[:10]
        ]
        response = (
            f"发现 {len(suggestions)} 种物料需要补货：\n"
            + "\n".join(lines)
            + f"\n合计建议采购金额 ￥{format_money(safe_float(summary.get('total_suggest_amount')))}"
        )
    return slot_reply(
        "replenishment_suggest",
        response,
        data={"suggestions": suggestions[:20], "summary": summary},
    )


def customer_reply(
    response: str,
    *,
    keyword: str,
    output: JsonObject,
    success: bool,
    customers: list[Any] | None = None,
) -> JsonObject:
    params: JsonObject = {"page": 1, "per_page": 50}
    if keyword:
        params["keyword"] = keyword
    record = {
        "tool_id": "customers",
        "action": "query",
        "params": params,
        "output": output,
        "tool_call_id": "tc-customers-query",
    }
    data: JsonObject = {"legacy_tool_records": [record]}
    if customers is not None:
        data["customers"] = customers
    return slot_reply(
        "customers_query",
        response,
        data=data,
        success=success,
        legacy_tool_records=[record],
        agent_tool_dispatch=True,
    )


def customers(result: object, keyword: str) -> JsonObject:
    items = result.get("data", []) if isinstance(result, dict) else []
    if not isinstance(items, list):
        items = []
    total = int(result.get("total") or len(items)) if isinstance(result, dict) else len(items)
    if not items:
        response = f"没有查到与「{keyword}」匹配的客户。" if keyword else "当前客户库暂无数据。"
    else:
        lines = [
            f"- {c.get('customer_name', '')} {c.get('contact_person', '')}".rstrip()
            for c in items[:10]
        ]
        response = f"当前共有 {total} 位客户：\n" + "\n".join(lines)
        if total > 10:
            response += f"\n…其余 {total - 10} 位请到「客户管理」查看"
    return customer_reply(
        response,
        keyword=keyword,
        success=True,
        customers=items[:20],
        output={"success": True, "data": items[:20], "total": total, "page": 1, "per_page": 50},
    )


def rejected_customers(result: JsonObject, keyword: str) -> JsonObject:
    return customer_reply(
        str(result.get("message") or result.get("response") or "客户查询工具执行失败"),
        keyword=keyword,
        output=result,
        success=False,
    )
