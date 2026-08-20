# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.workflow.planner")


def _extract_business_db_read_keyword(message: str, entity: str) -> str:
    quoted = _facade().re.search("[「“\\\"']([^」”\\\"']+)[」”\\\"']", message)
    if quoted:
        return _facade()._clean_db_slot_value(quoted.group(1))
    if entity == "products":
        slot = _facade()._extract_named_slot(
            message,
            (
                "(?:产品|商品|型号|model)\\s*[:：的]?\\s*([A-Za-z0-9._-]+|[^\\s，,。；;]+)",
                "(?:查|查询|读取|读)\\s*(?:数据库|db|database)?\\s*(?:产品|商品)?\\s*([A-Za-z0-9._-]+)",
            ),
        )
        if slot:
            return slot
        model = _facade().re.search("\\b[A-Za-z0-9][A-Za-z0-9._-]{1,}\\b", message)
        if model:
            return model.group(0).strip()
    if entity == "customers":
        slot = _facade()._extract_named_slot(
            message,
            (
                "(?:客户|单位|购买单位)\\s*[:：的]?\\s*([^\\s，,。；;]+)",
                "(?:查|查询|读取|读)\\s*(?:数据库|db|database)?\\s*(?:客户|单位)?\\s*([^\\s，,。；;]+)",
            ),
        )
        if slot:
            return slot
    if entity == "materials":
        slot = _facade()._extract_named_slot(
            message,
            (
                "(?:原材料|物料|材料)\\s*[:：的]?\\s*([^\\s，,。；;]+)",
                "(?:查|查询|读取|读)\\s*(?:数据库|db|database)?\\s*(?:原材料|物料|材料)?\\s*([^\\s，,。；;]+)",
            ),
        )
        if slot:
            return slot
    cleaned = str(message or "").strip()
    for token in (
        "查询数据库",
        "读取数据库",
        "查数据库",
        "读数据库",
        "数据库",
        "database",
        "查库",
        "读库",
        "查询",
        "读取",
        "查",
        "读",
        "产品",
        "商品",
        "客户",
        "单位",
        "购买单位",
        "原材料",
        "物料",
        "材料",
    ):
        cleaned = cleaned.replace(token, " ")
    cleaned = _facade().re.sub("\\s+", " ", cleaned).strip(" \t\r\n，,。；;：:")
    return cleaned or str(message or "").strip()


def get_tool_registry() -> dict[str, _facade().Any]:
    """
    返回工作流工具注册表，供 ai_chat_app_service 使用。
    覆盖报价、主数据、出货、模板与微信辅助等能力，与意图层 tool_key 对齐。
    """
    from app.services.tools_execution.registry import get_workflow_tool_registry

    return get_workflow_tool_registry()


def execute_tool(tool_name: str, params: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """
    执行指定工具（支持 execute_registered_workflow_tool 注入的 _action）。

    与 get_tool_registry 中的工具 id 一致。
    """
    _facade().logger.info("execute_tool called: tool_name=%s, params=%s", tool_name, params)
    merged = dict(params or {})
    merged.pop("_runtime_context", None)
    action = str(merged.pop("_action", "") or "").strip().lower()
    if not action:
        action_defaults: dict[str, str] = {
            "price_list": "export",
            "products": "query",
            "customers": "query",
            "shipment_generate": "generate",
            "shipment_records": "query",
            "shipments": "query",
            "materials": "query",
            "print_label": "generate",
            "excel_decompose": "decompose",
            "template_extract": "extract",
            "excel_schema": "analyze",
            "excel_analysis": "analyze",
            "import_excel": "import",
            "employee": "list",
            "business_db": "read",
        }
        action = action_defaults.get(tool_name, "query")
    handler = _facade()._WORKFLOW_TOOL_HANDLERS.get((tool_name, action))
    if handler is not None:
        return handler(merged)
    result = _facade().execute_registered_workflow_tool(tool_name, action, merged)
    if not result.get("success") and str(result.get("message", "")).startswith("未注册"):
        return {
            "success": False,
            "message": f"未知工具动作: {tool_name}.{action}",
            "error_code": "unknown_tool_action",
        }
    return result


def _execute_price_list_tool(params: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """执行价格表导出工具"""
    try:
        customer_name = params.get("customer_name") or params.get("unit")
        keyword = params.get("keyword")
        date = params.get("date")
        if not customer_name:
            return {
                "success": False,
                "message": "缺少 customer_name 参数",
                "error_code": "missing_customer_name",
            }
        fhd_root = _facade().ensure_fhd_repo_on_syspath()
        from app.application.tools import handle_price_list_export

        result = handle_price_list_export(
            {"customer_name": customer_name, "keyword": keyword, "export_date": date},
            workspace_root=str(fhd_root) if fhd_root else None,
        )
        return result
    except ImportError as e:
        _facade().logger.error("价格表导出服务导入失败: %s", e)
        return {
            "success": False,
            "message": "价格表导出服务不可用",
            "error_code": "service_unavailable",
        }
    except (ValueError, TypeError) as e:
        _facade().logger.warning("价格表导出参数错误: %s", e)
        return {
            "success": False,
            "message": "参数错误：请检查客户名称和价格参数",
            "error_code": "invalid_parameters",
        }
    except OSError as e:
        _facade().logger.error("价格表导出文件操作失败: %s", e)
        return {
            "success": False,
            "message": "文件导出失败，请检查磁盘空间",
            "error_code": "file_io_error",
        }
    except RuntimeError as e:
        _facade().logger.error("价格表导出运行时错误: %s", e)
        return {
            "success": False,
            "message": "导出处理失败，请稍后重试",
            "error_code": "export_failed",
        }


def _execute_products_tool(params: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
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
        _facade().logger.error("产品服务导入失败: %s", e)
        return {"success": False, "message": "产品服务不可用", "error_code": "service_unavailable"}
    except (ValueError, TypeError) as e:
        _facade().logger.warning("产品查询参数错误: %s", e)
        return {
            "success": False,
            "message": "查询参数错误，请检查输入",
            "error_code": "invalid_parameters",
        }
    except RuntimeError as e:
        _facade().logger.error("产品查询运行时错误: %s", e)
        return {"success": False, "message": "查询失败，请稍后重试", "error_code": "query_failed"}


def _execute_customers_tool(params: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """执行客户查询工具"""
    try:
        from app.bootstrap import get_customer_app_service

        keyword = params.get("keyword") or params.get("customer_name") or ""
        page = int(params.get("page", 1))
        per_page = int(params.get("per_page", 20))
        svc = get_customer_app_service()
        return _facade().cast(
            "dict[str, Any]",
            svc.get_all(keyword=str(keyword).strip() or None, page=page, per_page=per_page),
        )
    except ImportError as e:
        _facade().logger.error("客户服务导入失败: %s", e)
        return {"success": False, "message": "客户服务不可用", "error_code": "service_unavailable"}
    except (ValueError, TypeError) as e:
        _facade().logger.warning("客户查询参数错误: %s", e)
        return {
            "success": False,
            "message": "查询参数错误，请检查输入",
            "error_code": "invalid_parameters",
        }
    except RuntimeError as e:
        _facade().logger.error("客户查询运行时错误: %s", e)
        return {"success": False, "message": "查询失败，请稍后重试", "error_code": "query_failed"}


def _execute_customers_ensure_exists_tool(
    params: dict[str, _facade().Any],
) -> dict[str, _facade().Any]:
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
        _facade().logger.error("客户创建服务导入失败: %s", e)
        return {
            "success": False,
            "message": "客户创建服务不可用",
            "error_code": "service_unavailable",
            "created": False,
        }
    except (ValueError, TypeError) as e:
        _facade().logger.warning("客户创建参数错误: %s", e)
        return {
            "success": False,
            "message": "创建参数错误，请检查单位名称",
            "error_code": "invalid_parameters",
            "created": False,
        }
    except RuntimeError as e:
        _facade().logger.error("客户创建运行时错误: %s", e)
        return {
            "success": False,
            "message": "创建失败，请稍后重试",
            "error_code": "create_failed",
            "created": False,
        }
