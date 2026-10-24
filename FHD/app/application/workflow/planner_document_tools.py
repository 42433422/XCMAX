"""Document generation adapters with explicit workspace resolution."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)


def _execute_price_list_tool(
    params: dict[str, Any], *, ensure_repo: Callable[[], Path | None]
) -> dict[str, Any]:
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
        fhd_root = ensure_repo()
        from app.application.tools import handle_price_list_export

        result = handle_price_list_export(
            {"customer_name": customer_name, "keyword": keyword, "export_date": date},
            workspace_root=str(fhd_root) if fhd_root else None,
        )
        return result
    except ImportError as e:
        logger.error("价格表导出服务导入失败: %s", e)
        return {
            "success": False,
            "message": "价格表导出服务不可用",
            "error_code": "service_unavailable",
        }
    except (ValueError, TypeError) as e:
        logger.warning("价格表导出参数错误: %s", e)
        return {
            "success": False,
            "message": "参数错误：请检查客户名称和价格参数",
            "error_code": "invalid_parameters",
        }
    except OSError as e:
        logger.error("价格表导出文件操作失败: %s", e)
        return {
            "success": False,
            "message": "文件导出失败，请检查磁盘空间",
            "error_code": "file_io_error",
        }
    except RuntimeError as e:
        logger.error("价格表导出运行时错误: %s", e)
        return {
            "success": False,
            "message": "导出处理失败，请稍后重试",
            "error_code": "export_failed",
        }


def _execute_shipment_generate_tool(params: dict[str, Any]) -> dict[str, Any]:
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
        return cast(
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
        logger.error("发货单服务导入失败: %s", e)
        return {
            "success": False,
            "message": "发货单服务不可用",
            "error_code": "service_unavailable",
        }
    except (ValueError, TypeError) as e:
        logger.warning("发货单生成参数错误: %s", e)
        return {
            "success": False,
            "message": "订单参数错误，请检查输入",
            "error_code": "invalid_parameters",
        }
    except OSError as e:
        logger.error("发货单文件生成失败: %s", e)
        return {
            "success": False,
            "message": "文档生成失败，请检查磁盘空间",
            "error_code": "file_io_error",
        }
    except RuntimeError as e:
        logger.error("发货单生成运行时错误: %s", e)
        return {
            "success": False,
            "message": "生成失败，请稍后重试",
            "error_code": "generation_failed",
        }


def _execute_print_label_tool(params: dict[str, Any]) -> dict[str, Any]:
    try:
        import os

        from app.infrastructure.documents.shipment_document_generator_impl import (
            SimpleLabelGenerator,
        )
        from app.utils.path_io.path_utils import get_resource_path

        products = params.get("products")
        if not isinstance(products, list) or not products:
            return {
                "success": False,
                "message": "缺少 products 数组",
                "error_code": "missing_products",
            }
        labels_dir = get_resource_path("ai_assistant", "商标导出")
        os.makedirs(labels_dir, exist_ok=True)
        order_number = str(params.get("order_number") or params.get("doc_name") or "LABEL").strip()
        gen = SimpleLabelGenerator(labels_dir)
        labels = gen.generate_labels_for_order(order_number=order_number, products=products)
        return {"success": True, "data": labels, "message": f"已生成 {len(labels)} 张标签"}
    except ImportError as e:
        logger.error("标签生成服务导入失败: %s", e)
        return {
            "success": False,
            "message": "标签生成服务不可用",
            "error_code": "service_unavailable",
        }
    except (ValueError, TypeError) as e:
        logger.warning("标签生成参数错误: %s", e)
        return {
            "success": False,
            "message": "标签参数错误，请检查产品数据",
            "error_code": "invalid_parameters",
        }
    except OSError as e:
        logger.error("标签文件生成失败: %s", e)
        return {
            "success": False,
            "message": "标签导出失败，请检查磁盘空间",
            "error_code": "file_io_error",
        }
    except RuntimeError as e:
        logger.error("标签生成运行时错误: %s", e)
        return {
            "success": False,
            "message": "生成失败，请稍后重试",
            "error_code": "generation_failed",
        }
