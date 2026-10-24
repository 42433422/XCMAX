"""Business-record and employee adapters used by legacy workflow dispatch."""

from __future__ import annotations

import logging
from typing import Any, cast

logger = logging.getLogger(__name__)


def _execute_products_tool(params: dict[str, Any]) -> dict[str, Any]:
    """执行产品查询工具"""
    try:
        from app.bootstrap import get_products_service

        keyword = str(params.get("keyword") or "").strip()
        unit_name = str(params.get("unit_name") or params.get("unit") or "").strip() or None
        model_number = (
            str(params.get("model_number") or params.get("product_code") or "").strip() or None
        )
        page = int(params.get("page", 1))
        per_page = int(params.get("per_page", 20))
        svc = get_products_service()
        if model_number and unit_name:
            result = svc.get_products(
                unit_name=unit_name,
                model_number=model_number,
                keyword=None,
                page=page,
                per_page=per_page,
            )
        elif model_number:
            result = svc.get_products(
                unit_name=None,
                model_number=model_number,
                keyword=None,
                page=page,
                per_page=per_page,
            )
        elif unit_name:
            result = svc.get_products(
                unit_name=unit_name,
                model_number=None,
                keyword=keyword or None,
                page=page,
                per_page=per_page,
            )
        else:
            result = svc.get_products(
                unit_name=None,
                model_number=None,
                keyword=keyword or None,
                page=page,
                per_page=per_page,
            )
        return result
    except ImportError as e:
        logger.error("产品服务导入失败: %s", e)
        return {"success": False, "message": "产品服务不可用", "error_code": "service_unavailable"}
    except (ValueError, TypeError) as e:
        logger.warning("产品查询参数错误: %s", e)
        return {
            "success": False,
            "message": "查询参数错误，请检查输入",
            "error_code": "invalid_parameters",
        }
    except RuntimeError as e:
        logger.error("产品查询运行时错误: %s", e)
        return {"success": False, "message": "查询失败，请稍后重试", "error_code": "query_failed"}


def _execute_customers_tool(params: dict[str, Any]) -> dict[str, Any]:
    """执行客户查询工具"""
    try:
        from app.bootstrap import get_customer_app_service

        keyword = params.get("keyword") or params.get("customer_name") or ""
        page = int(params.get("page", 1))
        per_page = int(params.get("per_page", 20))
        svc = get_customer_app_service()
        return cast(
            "dict[str, Any]",
            svc.get_all(keyword=str(keyword).strip() or None, page=page, per_page=per_page),
        )
    except ImportError as e:
        logger.error("客户服务导入失败: %s", e)
        return {"success": False, "message": "客户服务不可用", "error_code": "service_unavailable"}
    except (ValueError, TypeError) as e:
        logger.warning("客户查询参数错误: %s", e)
        return {
            "success": False,
            "message": "查询参数错误，请检查输入",
            "error_code": "invalid_parameters",
        }
    except RuntimeError as e:
        logger.error("客户查询运行时错误: %s", e)
        return {"success": False, "message": "查询失败，请稍后重试", "error_code": "query_failed"}


def _execute_customers_ensure_exists_tool(
    params: dict[str, Any],
) -> dict[str, Any]:
    """创建客户（单位）如不存在。"""
    try:
        from app.bootstrap import get_customer_app_service

        unit = str(params.get("unit_name") or params.get("customer_name") or "").strip()
        if not unit:
            return {
                "success": False,
                "message": "缺少 unit_name",
                "error_code": "missing_unit_name",
            }
        svc = get_customer_app_service()
        matched = svc.match_purchase_unit(unit)
        if matched:
            return {
                "success": True,
                "created": False,
                "message": f"单位已存在：{unit}",
                "data": {
                    "id": getattr(matched, "id", None),
                    "customer_name": getattr(matched, "unit_name", None) or unit,
                    "unit_name": getattr(matched, "unit_name", None) or unit,
                },
            }
        created = svc.create({"customer_name": unit})
        out = dict(created) if isinstance(created, dict) else {"success": False}
        out["created"] = bool(out.get("success"))
        return out
    except ImportError as e:
        logger.error("客户创建服务导入失败: %s", e)
        return {
            "success": False,
            "message": "客户创建服务不可用",
            "error_code": "service_unavailable",
            "created": False,
        }
    except (ValueError, TypeError) as e:
        logger.warning("客户创建参数错误: %s", e)
        return {
            "success": False,
            "message": "创建参数错误，请检查单位名称",
            "error_code": "invalid_parameters",
            "created": False,
        }
    except RuntimeError as e:
        logger.error("客户创建运行时错误: %s", e)
        return {
            "success": False,
            "message": "创建失败，请稍后重试",
            "error_code": "create_failed",
            "created": False,
        }


def _execute_shipment_records_tool(params: dict[str, Any]) -> dict[str, Any]:
    try:
        from app.bootstrap import get_shipment_app_service

        unit = params.get("unit_name") or params.get("keyword") or params.get("customer_name")
        limit = int(params.get("limit", 50))
        svc = get_shipment_app_service()
        rows = svc.get_shipment_records(unit_name=str(unit).strip() if unit else None, limit=limit)
        return {"success": True, "data": rows, "message": f"共 {len(rows)} 条出货记录"}
    except ImportError as e:
        logger.error("出货记录服务导入失败: %s", e)
        return {
            "success": False,
            "message": "出货记录服务不可用",
            "error_code": "service_unavailable",
        }
    except (ValueError, TypeError) as e:
        logger.warning("出货记录查询参数错误: %s", e)
        return {
            "success": False,
            "message": "查询参数错误，请检查单位名称",
            "error_code": "invalid_parameters",
        }
    except RuntimeError as e:
        logger.error("出货记录查询运行时错误: %s", e)
        return {"success": False, "message": "查询失败，请稍后重试", "error_code": "query_failed"}


def _execute_materials_tool(params: dict[str, Any]) -> dict[str, Any]:
    try:
        from app.bootstrap import get_materials_service

        search = str(params.get("keyword") or params.get("search") or "").strip() or None
        category = str(params.get("category") or "").strip() or None
        page = int(params.get("page", 1))
        per_page = int(params.get("per_page", 20))
        return get_materials_service().get_all_materials(
            search=search, category=category, page=page, per_page=per_page
        )
    except ImportError as e:
        logger.error("原材料服务导入失败: %s", e)
        return {
            "success": False,
            "message": "原材料服务不可用",
            "error_code": "service_unavailable",
        }
    except (ValueError, TypeError) as e:
        logger.warning("原材料查询参数错误: %s", e)
        return {
            "success": False,
            "message": "查询参数错误，请检查输入",
            "error_code": "invalid_parameters",
        }
    except RuntimeError as e:
        logger.error("原材料查询运行时错误: %s", e)
        return {"success": False, "message": "查询失败，请稍后重试", "error_code": "query_failed"}


def _execute_employee_list_tool(params: dict[str, Any]) -> dict[str, Any]:
    from app.application.facades.tools_facade import execute_registered_workflow_tool

    return execute_registered_workflow_tool("employee", "list", params)


def _execute_employee_execute_tool(params: dict[str, Any]) -> dict[str, Any]:
    from app.application.facades.tools_facade import execute_registered_workflow_tool

    return execute_registered_workflow_tool("employee", "execute", params)


def _execute_business_db_read_tool(params: dict[str, Any]) -> dict[str, Any]:
    from app.application.facades.tools_facade import execute_registered_workflow_tool

    return execute_registered_workflow_tool("business_db", "read", params)


def _execute_business_db_write_tool(params: dict[str, Any]) -> dict[str, Any]:
    from app.application.facades.tools_facade import execute_registered_workflow_tool

    return execute_registered_workflow_tool("business_db", "write", params)
