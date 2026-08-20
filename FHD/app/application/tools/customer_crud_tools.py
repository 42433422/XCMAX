"""客户（购买单位）CRUD 工具执行器。

直连 ``CustomerApplicationService``，覆盖 update / delete / list 三个操作。
与 ``app/application/tools/shipment_crud_tools.py`` 风格一致。
"""

from __future__ import annotations

import logging
from typing import Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _get_service():
    """获取 CustomerApplicationService 单例。"""
    from app.bootstrap import get_customer_app_service

    return get_customer_app_service()


def _normalize_customer_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """把 LLM 传入的字段名归一化到 CustomerApplicationService.update 接受的形态。

    兼容 user 传入的 name / customer_name / contact_address 等别名。
    """
    out: dict[str, Any] = {}
    if not isinstance(fields, dict):
        return out

    if "customer_name" in fields:
        out["customer_name"] = fields["customer_name"]
    elif "name" in fields:
        out["customer_name"] = fields["name"]

    if "contact_person" in fields:
        out["contact_person"] = fields["contact_person"]
    elif "person" in fields:
        out["contact_person"] = fields["person"]

    if "contact_phone" in fields:
        out["contact_phone"] = fields["contact_phone"]
    elif "phone" in fields:
        out["contact_phone"] = fields["phone"]

    if "contact_address" in fields:
        out["contact_address"] = fields["contact_address"]
    elif "address" in fields:
        out["contact_address"] = fields["address"]

    # 丢弃 None 值，避免覆盖 service 层 None 校验
    return {k: v for k, v in out.items() if v is not None}


def update_customer(args: dict[str, Any]) -> dict[str, Any]:
    """更新客户（购买单位）字段。

    Required args:
        customer_id: 客户 ID
        fields: 待更新字段 dict（customer_name / contact_person / contact_phone / contact_address）

    Optional args:
        confirm: 写操作二次确认（默认 False）
    """
    try:
        customer_id = int(args.get("customer_id") or 0)
    except (TypeError, ValueError):
        return {"success": False, "error": "customer_id is required and must be int"}

    fields = args.get("fields") or {}
    if not isinstance(fields, dict) or not fields:
        return {"success": False, "error": "fields must be a non-empty dict"}

    confirm = bool(args.get("confirm", False))
    if not confirm:
        return {
            "success": False,
            "needs_confirm": True,
            "message": f"更新客户 {customer_id} 为写操作，请显式传 confirm=true 再调用",
            "customer_id": customer_id,
            "preview_fields": fields,
        }

    normalized = _normalize_customer_fields(fields)
    if not normalized:
        return {"success": False, "error": "no supported fields in fields dict"}

    try:
        svc = _get_service()
        result = svc.update(customer_id, normalized)
        if isinstance(result, dict):
            result.setdefault("customer_id", customer_id)
        return cast("dict[str, Any]", result)
    except RECOVERABLE_ERRORS as e:
        logger.exception("update_customer 失败: %s", e)
        return {"success": False, "error": str(e), "customer_id": customer_id}


def delete_customer(args: dict[str, Any]) -> dict[str, Any]:
    """删除客户（购买单位）。

    Required args:
        customer_id: 客户 ID

    Optional args:
        confirm: 高危操作二次确认（默认 False）
        force: 是否强制删除（忽略关联检查，传给 service 层）。默认 False
    """
    try:
        customer_id = int(args.get("customer_id") or 0)
    except (TypeError, ValueError):
        return {"success": False, "error": "customer_id is required and must be int"}

    confirm = bool(args.get("confirm", False))
    force = bool(args.get("force", False))

    if not confirm:
        return {
            "success": False,
            "needs_confirm": True,
            "message": f"删除客户 {customer_id} 为高危操作，请显式传 confirm=true 再调用",
            "customer_id": customer_id,
            "force": force,
        }

    try:
        svc = _get_service()
        result = svc.delete(customer_id, force=force)
        if isinstance(result, dict):
            result.setdefault("customer_id", customer_id)
        return cast("dict[str, Any]", result)
    except RECOVERABLE_ERRORS as e:
        logger.exception("delete_customer 失败: %s", e)
        return {"success": False, "error": str(e), "customer_id": customer_id}


def list_customers(args: dict[str, Any]) -> dict[str, Any]:
    """查询客户（购买单位）列表。

    Optional args:
        filters: dict，可包含 keyword / page / per_page
        limit: 同 per_page；若未提供 per_page 则用 limit（默认 20，最大 200）
    """
    filters = args.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}

    keyword = str(filters.get("keyword") or "").strip() or None
    try:
        page = int(filters.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    page = max(1, page)

    try:
        per_page = int(filters.get("per_page") or args.get("limit") or 20)
    except (TypeError, ValueError):
        per_page = 20
    per_page = max(1, min(per_page, 200))

    try:
        svc = _get_service()
        result = svc.get_all(keyword=keyword, page=page, per_page=per_page)
        # service 返回 {success, data, total, page, per_page}，直接透传
        if isinstance(result, dict):
            result.setdefault("filters", filters)
        return cast("dict[str, Any]", result)
    except RECOVERABLE_ERRORS as e:
        logger.exception("list_customers 失败: %s", e)
        return {"success": False, "error": str(e), "data": [], "total": 0}


__all__ = [
    "update_customer",
    "delete_customer",
    "list_customers",
]
