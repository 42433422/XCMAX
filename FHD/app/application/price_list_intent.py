"""价格表意图响应构造工具。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def build_price_list_chat_reply(rr: dict[str, Any]) -> dict[str, Any]:
    slots = dict(rr.get("slots") or {})
    customer_name = str(slots.get("customer_name") or "").strip()
    keyword = str(slots.get("keyword") or "").strip() or None

    if not customer_name:
        return {
            "success": False,
            "message": "缺少客户名称",
            "response": "请告诉我您要生成哪家客户的价格表？例如：「打印某某公司的价格表」",
        }

    try:
        from app.application.tools import handle_price_list_export

        result = handle_price_list_export(
            {
                "customer_name": customer_name,
                "keyword": keyword,
                "export_date": None,
            }
        )

        logger.info("价格表生成结果: %s", result)

        if result.get("success"):
            product_count = int(result.get("product_count") or 0)
            file_path = str(result.get("file_path") or "")
            filename = str(
                result.get("doc_name")
                or result.get("filename")
                or (Path((file_path or "").replace("\\", "/")).name or "价格表.docx")
            )
            download_url = str(result.get("download_url") or "")
            if not download_url and filename:
                download_url = f"/api/shipment/download/{filename}"
            desc = f"客户：{customer_name}，共 {product_count} 个产品。可下载 Word 或点击「开始打印」。"
            return {
                "success": True,
                "message": result.get("message", "价格表已生成"),
                "response": (
                    f"好的，价格表已生成成功！\n\n{result.get('message', '')}\n\n"
                    f"📄 文件名：{filename}\n💡 已在右侧任务面板中添加下载和打印按钮。"
                ),
                "task": {
                    "type": "price_list_export",
                    "title": "价格表已生成",
                    "description": desc,
                    "completed": True,
                    "downloadUrl": download_url,
                    "file_path": file_path,
                    "doc_name": filename,
                },
                "data": {
                    "file_path": file_path,
                    "download_url": download_url,
                    "filename": filename,
                    "doc_name": filename,
                    "product_count": product_count,
                    "customer_name": customer_name,
                    "intent": "price_list",
                    "action": "price_list_export",
                    "tool_key": "price_list",
                },
            }

        return {
            "success": False,
            "message": result.get("message") or result.get("error") or "价格表生成失败",
            "response": (
                f"抱歉，价格表生成失败："
                f"{result.get('message') or result.get('error') or '未知错误'}"
            ),
        }
    except RECOVERABLE_ERRORS as e:
        logger.error("价格表生成异常：%s", e, exc_info=True)
        return {
            "success": False,
            "message": f"价格表生成异常：{str(e)}",
            "response": f"抱歉，价格表生成时出现错误：{str(e)}",
        }
