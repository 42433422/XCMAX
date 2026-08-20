# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.workflow.planner")


def _execute_shipment_generate_tool(params: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    try:
        from app.application.facades.tools_facade import _parse_order_text
        from app.bootstrap import get_shipment_app_service

        order_text = str(params.get("order_text") or "").strip()
        unit_name = str(params.get("unit_name") or "").strip()
        products = params.get("products")
        if order_text:
            parsed = _parse_order_text(order_text)
        elif unit_name and isinstance(products, list) and products:
            parsed = {"success": True, "unit_name": unit_name, "products": products}
        else:
            return {
                "success": False,
                "message": "缺少 order_text，或 unit_name+products",
                "error_code": "missing_order_params",
            }
        if not parsed.get("success"):
            return {
                "success": False,
                "message": parsed.get("message") or parsed.get("error") or "订单解析失败",
            }
        svc = get_shipment_app_service()
        return _facade().cast(
            "dict[str, Any]",
            svc.generate_shipment_document(
                unit_name=str(parsed.get("unit_name") or ""),
                products=list(parsed.get("products") or []),
                template_name=params.get("template_name") or params.get("template"),
                template_id=params.get("template_id"),
                preferred_template=params.get("preferred_template") or params.get("template"),
                date=params.get("date"),
                order_number=params.get("order_number"),
                intent="shipment_generate",
                allow_products_from_db=True,
                raw_text=order_text or str(params.get("raw_text") or ""),
            ),
        )
    except ImportError as e:
        _facade().logger.error("发货单服务导入失败: %s", e)
        return {
            "success": False,
            "message": "发货单服务不可用",
            "error_code": "service_unavailable",
        }
    except (ValueError, TypeError) as e:
        _facade().logger.warning("发货单生成参数错误: %s", e)
        return {
            "success": False,
            "message": "订单参数错误，请检查输入",
            "error_code": "invalid_parameters",
        }
    except OSError as e:
        _facade().logger.error("发货单文件生成失败: %s", e)
        return {
            "success": False,
            "message": "文档生成失败，请检查磁盘空间",
            "error_code": "file_io_error",
        }
    except RuntimeError as e:
        _facade().logger.error("发货单生成运行时错误: %s", e)
        return {
            "success": False,
            "message": "生成失败，请稍后重试",
            "error_code": "generation_failed",
        }
