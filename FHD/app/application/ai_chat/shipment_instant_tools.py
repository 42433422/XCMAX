"""Pro/Normal instant tools mixin for AIChatInstantToolsMixin."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

from app.utils.operational_errors import RECOVERABLE_ERRORS

OPERATIONAL_ERRORS = RECOVERABLE_ERRORS

from app.utils.mixin_module_sync import sync_mixin_methods


class AIChatShipmentInstantToolsMixin:
    def _build_shipment_confirmation_preview(
        self,
        response_data: dict[str, Any],
        parsed_params: dict[str, Any],
        ai_result: dict[str, Any],
        *,
        slots: dict[str, Any] | None = None,
        original_message: str = "",
        order_text: str = "",
        parsed_order: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a shipment preview card without generating a document.

        Both the public normal chat and the professional shortcut must stop at
        a preview.  The client later sends this deterministic payload only when
        the user explicitly clicks ``确认执行``.  This keeps model output
        advisory and prevents a chat response from silently writing a shipment
        record or creating a print-ready file.
        """
        try:
            from app.application.ai_chat_helpers import build_shipment_preview_response_dict
            from app.application.facades.tools_facade import _parse_order_text

            safe_slots = slots if isinstance(slots, dict) else {}
            raw_original_message = str(original_message or "").strip()
            parsed_params = parsed_params if isinstance(parsed_params, dict) else {}

            parsed = parsed_order if isinstance(parsed_order, dict) else {"success": False}
            safe_order_text = str(order_text or "").strip()
            if raw_original_message:
                # The user's wording is the source of record.  In particular,
                # do not replace their spec/quantity with a model paraphrase.
                safe_order_text = raw_original_message
                # Pro mode may already have complete deterministic slots.  A
                # conversational original that is not parseable must not erase
                # those slots (for example a terse “好” after slot extraction).
                if not parsed.get("success"):
                    parsed = _parse_order_text(safe_order_text)

            if not parsed.get("success"):
                fallback_order_text = str(
                    parsed_params.get("order_text") or safe_slots.get("order_text") or ""
                ).strip()
                if fallback_order_text and fallback_order_text != safe_order_text:
                    safe_order_text = fallback_order_text
                    parsed = _parse_order_text(safe_order_text)

            structured_products = parsed_params.get("products") or safe_slots.get("products") or []
            if not isinstance(structured_products, list):
                structured_products = []
            structured_unit_name = str(
                parsed_params.get("unit_name") or safe_slots.get("unit_name") or ""
            ).strip()
            if not structured_products:
                slot_model = str(
                    safe_slots.get("model_number")
                    or safe_slots.get("product_model")
                    or parsed_params.get("model_number")
                    or ""
                ).strip()
                slot_name = str(
                    safe_slots.get("name")
                    or safe_slots.get("product_name")
                    or parsed_params.get("name")
                    or parsed_params.get("product_name")
                    or ""
                ).strip()
                slot_spec = safe_slots.get("tin_spec") or parsed_params.get("tin_spec")
                slot_quantity = safe_slots.get("quantity_tins") or parsed_params.get(
                    "quantity_tins"
                )
                if slot_model or slot_name:
                    structured_product: dict[str, Any] = {}
                    if slot_model:
                        structured_product["model_number"] = slot_model
                    if slot_name:
                        structured_product["name"] = slot_name
                    if slot_spec not in (None, ""):
                        structured_product["tin_spec"] = slot_spec
                    if slot_quantity not in (None, ""):
                        structured_product["quantity_tins"] = slot_quantity
                    structured_products = [structured_product]

            unit_name = str(parsed.get("unit_name") or structured_unit_name or "").strip()
            products = parsed.get("products") or structured_products
            if not isinstance(products, list):
                products = []

            if not unit_name or not products:
                response_data["message"] = "订单信息不完整，请补充后再确认"
                response_data["response"] = str(
                    parsed.get("message") or "订单信息不完整，请补充单位、产品、规格和桶数。"
                )
                response_data.setdefault("data", {})["data"] = {
                    "intent": "shipment_preview",
                    "parsed_data": parsed,
                }
                response_data.pop("toolCall", None)
                response_data.pop("task", None)
                return response_data

            if not safe_order_text:
                # Structured slots are already deterministic.  Reconstruct a
                # transparent transport string from those slots rather than
                # sending an unrelated LLM acknowledgement to execution.
                safe_order_text = self._build_order_text_from_products(
                    unit_name,
                    products,
                    "",
                    "",
                    "",
                )

            preview = build_shipment_preview_response_dict(
                unit_name,
                products,
                safe_order_text,
                order_number=parsed.get("order_number"),
                order_number_provenance=(
                    parsed.get("order_number_provenance")
                    if isinstance(parsed.get("order_number_provenance"), dict)
                    else None
                ),
            )
            preview_params = preview["task"]["payload"]["params"]

            # Template preferences are carried to the click payload, but no
            # client-supplied owner id is ever added here.  The server injects
            # the authenticated owner after confirmation.
            optional_params = {
                "template_id": safe_slots.get("template_id") or parsed_params.get("template_id"),
                "template_name": safe_slots.get("template_name")
                or safe_slots.get("template")
                or parsed_params.get("template_name")
                or parsed_params.get("template"),
                "preferred_template": safe_slots.get("preferred_template")
                or safe_slots.get("template")
                or parsed_params.get("preferred_template"),
                "date": parsed_params.get("date") or safe_slots.get("date"),
                "order_number": parsed_params.get("order_number") or safe_slots.get("order_number"),
            }
            for key, value in optional_params.items():
                if value is not None and str(value).strip():
                    preview_params[key] = value

            return preview
        except RECOVERABLE_ERRORS as tool_err:
            logger.error("构建 shipment_generate 预演失败: %s", tool_err, exc_info=True)
            response_data["message"] = "发货单预演失败"
            response_data["response"] = f"发货单预演失败：{str(tool_err)}"

        return response_data

    def _execute_shipment_generate(
        self,
        response_data: dict[str, Any],
        parsed_params: dict[str, Any],
        ai_result: dict[str, Any],
        *,
        slots: dict[str, Any] | None = None,
        original_message: str = "",
    ) -> dict[str, Any]:
        """Execute a shipment only after a caller has obtained confirmation.

        This is a compatibility primitive for the explicit execution layer;
        it is intentionally *not* used by normal or Pro natural-language chat
        entry points.  Those entries call
        :meth:`_build_shipment_confirmation_preview` and the user's button
        reaches ``/api/tools/execute`` instead.
        """

        try:
            from app.application.facades.tools_facade import _parse_order_text
            from app.bootstrap import get_shipment_app_service

            safe_slots = slots if isinstance(slots, dict) else {}
            raw_original_message = str(original_message or "").strip()
            parsed_params = parsed_params if isinstance(parsed_params, dict) else {}

            parsed = {"success": False}
            order_text = ""
            if raw_original_message:
                order_text = raw_original_message
                parsed = _parse_order_text(order_text)

            if not parsed.get("success"):
                fallback_order_text = str(
                    parsed_params.get("order_text")
                    or safe_slots.get("order_text")
                    or ai_result.get("text", "")
                    or ""
                ).strip()
                if fallback_order_text and fallback_order_text != order_text:
                    order_text = fallback_order_text
                    parsed = _parse_order_text(order_text)

            structured_products = parsed_params.get("products") or safe_slots.get("products") or []
            if not isinstance(structured_products, list):
                structured_products = []
            structured_unit_name = str(
                parsed_params.get("unit_name") or safe_slots.get("unit_name") or ""
            ).strip()

            if parsed.get("success") or (structured_unit_name and structured_products):
                app_service = get_shipment_app_service()
                doc_result = app_service.generate_shipment_document(
                    unit_name=parsed.get("unit_name") or structured_unit_name,
                    products=parsed.get("products") or structured_products,
                    template_name=(
                        parsed_params.get("template_name") or parsed_params.get("template")
                    ),
                    template_id=parsed_params.get("template_id"),
                    preferred_template=(
                        parsed_params.get("preferred_template") or parsed_params.get("template")
                    ),
                    date=parsed_params.get("date"),
                    order_number=parsed_params.get("order_number"),
                    intent="shipment_generate",
                    allow_products_from_db=True,
                    raw_text=order_text,
                )
                response_data.setdefault("data", {})["data"] = {"document": doc_result}

                if doc_result.get("success"):
                    doc_name = doc_result.get("doc_name") or ""
                    response_data["response"] = (
                        f"已生成发货单：{doc_name}" if doc_name else "已生成发货单。"
                    )
                else:
                    response_data["response"] = doc_result.get("message", "生成发货单失败")
            else:
                response_data["response"] = parsed.get("message", "订单解析失败")
        except RECOVERABLE_ERRORS as tool_err:
            logger.error("确认后的 shipment_generate 执行失败: %s", tool_err, exc_info=True)
            response_data["response"] = f"生成发货单失败：{str(tool_err)}"

        return response_data

    def _execute_shipments_query(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """执行发货记录查询"""
        try:
            from app.bootstrap import get_shipment_app_service

            app_service = get_shipment_app_service()
            orders = app_service.get_orders(10) or []

            lines = ["最新出货/订单记录（最近 10 条）："]
            if not orders:
                lines.append("暂无订单记录。")
            else:
                for o in orders[:10]:
                    order_no = o.get("order_number") or o.get("order_no") or o.get("id") or ""
                    customer = (
                        o.get("customer_name") or o.get("unit_name") or o.get("purchase_unit") or ""
                    )
                    date = o.get("date") or o.get("created_at") or ""
                    amount = (
                        o.get("total_amount") or o.get("total_amount_yuan") or o.get("amount") or 0
                    )
                    status = o.get("status") or "已完成"
                    lines.append(f"- {order_no} | {customer} | {date} | ¥{amount} | {status}")

            response_data["response"] = "\n".join(lines)
            response_data["data"]["data"] = {"orders": orders}
            response_data.pop("toolCall", None)
        except RECOVERABLE_ERRORS as tool_err:
            logger.error("即时执行 shipments 失败：%s", tool_err, exc_info=True)

        return response_data


sync_mixin_methods(
    AIChatShipmentInstantToolsMixin,
    target=globals(),
    source_module="app.application.ai_chat.instant_tools",
    method_names=(
        "_build_shipment_confirmation_preview",
        "_execute_shipment_generate",
        "_execute_shipments_query",
    ),
)
