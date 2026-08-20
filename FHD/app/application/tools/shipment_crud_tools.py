"""订单（出货记录）CRUD 工具执行器。

为 Function Calling 提供 delete / update / list / clear_all 四个高危与只读操作。
所有调用均直连 ``ShipmentApplicationService``（service 层），不经过 HTTP。

执行器风格与 ``app/application/tools/workflow.py`` 现有 handler 对齐：
- 入参为 ``dict[str, Any]``
- 返回 ``dict[str, Any]``（由 dispatcher ``json.dumps`` 序列化）
- 高危操作必须显式 ``confirm=True``，否则返回预览/拒绝
"""

from __future__ import annotations

import logging
from typing import Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _get_service():
    """获取 ShipmentApplicationService 单例（与 fastapi_routes/shipment_orders.py 同源）。"""
    from app.bootstrap import get_shipment_application_service_core

    return get_shipment_application_service_core()


def delete_order(args: dict[str, Any]) -> dict[str, Any]:
    """删除单条出货记录。

    Required args:
        order_number: 订单 ID（与 /api/shipment/orders/{order_number} 同语义，即 record_id）

    Optional args:
        confirm: 必须为 True 才执行删除（高危二次确认）
    """
    order_number = str(args.get("order_number") or "").strip()
    confirm = bool(args.get("confirm", False))

    if not order_number:
        return {"success": False, "error": "order_number is required"}

    if not confirm:
        return {
            "success": False,
            "needs_confirm": True,
            "message": f"删除订单 {order_number} 为高危操作，请显式传 confirm=true 再调用",
            "order_number": order_number,
        }

    try:
        record_id = int(order_number)
    except (TypeError, ValueError):
        return {
            "success": False,
            "error": "invalid_order_number",
            "message": f"无效的订单编号格式：{order_number}",
        }

    try:
        svc = _get_service()
        result = svc.delete_shipment_record(record_id)
        if isinstance(result, dict) and result.get("success"):
            result["order_number"] = order_number
            result["message"] = result.get("message") or f"订单 {order_number} 已删除"
        return cast("dict[str, Any]", result)
    except RECOVERABLE_ERRORS as e:
        logger.exception("delete_order 失败: %s", e)
        return {"success": False, "error": str(e), "order_number": order_number}


def update_order(args: dict[str, Any]) -> dict[str, Any]:
    """更新出货记录字段。

    Required args:
        order_number: 订单 ID（record_id）
        fields: 待更新字段 dict，可包含 unit_name / product_name / model_number /
                quantity_kg / quantity_tins / tin_spec / unit_price / amount / status 等

    Optional args:
        confirm: 高危操作二次确认（默认 False；未确认时返回预览）
    """
    order_number = str(args.get("order_number") or "").strip()
    fields = args.get("fields") or {}
    confirm = bool(args.get("confirm", False))

    if not order_number:
        return {"success": False, "error": "order_number is required"}
    if not isinstance(fields, dict) or not fields:
        return {"success": False, "error": "fields must be a non-empty dict"}

    try:
        record_id = int(order_number)
    except (TypeError, ValueError):
        return {
            "success": False,
            "error": "invalid_order_number",
            "message": f"无效的订单编号格式：{order_number}",
        }

    # status 字段白名单校验（与 fastapi_routes/shipment_orders.py PATCH 端点一致）
    requested_status = fields.get("status")
    if requested_status is not None and str(requested_status) not in {
        "pending",
        "printed",
        "completed",
        "cancelled",
    }:
        return {"success": False, "error": "invalid_status", "message": "无效的订单状态"}

    if not confirm:
        return {
            "success": False,
            "needs_confirm": True,
            "message": f"更新订单 {order_number} 为写操作，请显式传 confirm=true 再调用",
            "order_number": order_number,
            "preview_fields": fields,
        }

    try:
        svc = _get_service()
        # update_shipment_record 接受 unit_name/products/date 命名参数 + 其余字段走 **kwargs -> fields
        update_kwargs: dict[str, Any] = {}
        for key in (
            "unit_name",
            "product_name",
            "model_number",
            "quantity_kg",
            "quantity_tins",
            "tin_spec",
            "unit_price",
            "amount",
            "status",
            "date",
        ):
            if key in fields and fields[key] is not None:
                update_kwargs[key] = fields[key]

        result = svc.update_shipment_record(record_id, **update_kwargs)
        if isinstance(result, dict) and result.get("success"):
            result["order_number"] = order_number
        return cast("dict[str, Any]", result)
    except RECOVERABLE_ERRORS as e:
        logger.exception("update_order 失败: %s", e)
        return {"success": False, "error": str(e), "order_number": order_number}


def list_orders(args: dict[str, Any]) -> dict[str, Any]:
    """查询订单（出货记录）列表。

    Optional args:
        filters: 过滤条件 dict，可包含 unit_name / keyword / start_date / end_date
        limit: 返回条数上限，默认 20，最大 200
    """
    filters = args.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}
    try:
        limit = int(args.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 200))

    unit_name = str(filters.get("unit_name") or filters.get("purchase_unit") or "").strip() or None
    keyword = str(filters.get("keyword") or filters.get("q") or "").strip()

    try:
        svc = _get_service()
        # 走 search_orders（关键字）或 get_orders（最新列表）/ get_shipment_records（按 unit）
        if keyword:
            rows = svc.search_orders(keyword)
            rows = rows[:limit]
        elif unit_name:
            rows = svc.get_shipment_records(unit_name, limit=limit)
        else:
            rows = svc.get_orders(limit=limit)

        return {
            "success": True,
            "data": rows,
            "count": len(rows) if isinstance(rows, list) else 0,
            "filters": filters,
            "limit": limit,
        }
    except RECOVERABLE_ERRORS as e:
        logger.exception("list_orders 失败: %s", e)
        return {"success": False, "error": str(e), "data": []}


def clear_all_orders(args: dict[str, Any]) -> dict[str, Any]:
    """清空所有出货记录（极高危）。

    Required args:
        confirm: 必须为 True 才执行（强制二次确认）
    """
    confirm = bool(args.get("confirm", False))
    if not confirm:
        return {
            "success": False,
            "needs_confirm": True,
            "message": "清空所有订单为极高危操作，请显式传 confirm=true 再调用",
        }

    try:
        svc = _get_service()
        result = svc.clear_all_orders()
        return cast("dict[str, Any]", result)
    except RECOVERABLE_ERRORS as e:
        logger.exception("clear_all_orders 失败: %s", e)
        return {"success": False, "error": str(e)}


__all__ = [
    "delete_order",
    "update_order",
    "list_orders",
    "clear_all_orders",
]
