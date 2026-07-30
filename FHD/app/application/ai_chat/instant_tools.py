"""Pro/Normal instant tools mixin for AIChatInstantToolsMixin."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

from app.utils.operational_errors import RECOVERABLE_ERRORS

OPERATIONAL_ERRORS = RECOVERABLE_ERRORS


class AIChatInstantToolsMixin:
    def _execute_pro_mode_tools(
        self,
        response_data: dict[str, Any],
        tool_key: str,
        slots: dict[str, Any],
        parsed_params: dict[str, Any],
        ai_result: dict[str, Any],
        original_message: str = "",
    ) -> dict[str, Any]:
        """执行专业模式工具"""
        if tool_key == "products":
            return self._execute_products_query(response_data, slots, parsed_params)
        elif tool_key == "customers":
            return self._execute_customers_intent(
                response_data=response_data,
                slots=slots,
                parsed_params=parsed_params,
                original_message=original_message,
            )
        elif tool_key == "shipment_generate":
            unit_name = slots.get("unit_name") or parsed_params.get("unit_name", "")
            quantity_tins = slots.get("quantity_tins") or parsed_params.get("quantity_tins", "")
            model_number = (
                slots.get("model_number")
                or slots.get("product_model")
                or parsed_params.get("model_number", "")
            )
            tin_spec = slots.get("tin_spec") or parsed_params.get("tin_spec", "")
            products_list = slots.get("products") or []
            parsed_products = []
            parsed_unit_name = ""

            # pro 模式优先从原消息解析整单，保留完整 products[]。
            try:
                from app.application.facades.tools_facade import _parse_order_text

                parsed_order = _parse_order_text(original_message or "")
                if parsed_order.get("success"):
                    parsed_products = parsed_order.get("products") or []
                    parsed_unit_name = parsed_order.get("unit_name") or ""
            except RECOVERABLE_ERRORS as parse_err:
                logger.debug("pro shipment_generate 解析原句失败，回退旧逻辑: %s", parse_err)

            if original_message and len(original_message) > 5:
                order_text = original_message
            elif unit_name and quantity_tins and model_number and tin_spec:
                order_text = (
                    f"{unit_name}{int(quantity_tins)} 桶 {model_number} 规格 {int(float(tin_spec))}"
                )
            elif unit_name and products_list:
                order_text = self._build_order_text_from_products(
                    unit_name, products_list, original_message, quantity_tins, tin_spec
                )
            else:
                order_text = ai_result.get("text", "")

            effective_products = parsed_products or products_list
            effective_unit_name = parsed_unit_name or unit_name
            if not effective_products and (model_number or slots.get("product_name")):
                product_slot: dict[str, Any] = {}
                if model_number:
                    product_slot["model_number"] = model_number
                product_name = str(slots.get("product_name") or "").strip()
                if product_name:
                    product_slot["name"] = product_name
                if tin_spec not in (None, ""):
                    product_slot["tin_spec"] = tin_spec
                if quantity_tins not in (None, ""):
                    product_slot["quantity_tins"] = quantity_tins
                effective_products = [product_slot]
            # A pro-mode shortcut is still a natural-language request, not an
            # already-authorized document write.  Return the same explicit
            # confirmation card as normal chat; only its button may call the
            # legacy shipment execution endpoint.
            return self._build_shipment_confirmation_preview(
                response_data,
                parsed_params,
                ai_result,
                slots=slots,
                original_message=original_message,
                order_text=order_text,
                parsed_order={
                    "success": bool(effective_unit_name and effective_products),
                    "unit_name": effective_unit_name,
                    "products": effective_products,
                },
            )
        else:
            response_data["toolCall"] = {
                "tool_id": tool_key,
                "action": "执行",
                "params": {
                    "order_text": ai_result.get("text", ""),
                    **parsed_params,
                    **ai_result.get("data", {}),
                },
            }
            response_data["response"] = ai_result.get("text", "")
            return response_data

    def _execute_normal_mode_tools(
        self,
        response_data: dict[str, Any],
        tool_key: str,
        parsed_params: dict[str, Any],
        ai_result: dict[str, Any],
        result_data: dict[str, Any],
        slots: dict[str, Any] | None = None,
        original_message: str = "",
    ) -> dict[str, Any]:
        """执行普通模式工具"""
        if tool_key == "shipment_generate":
            # Public chat is preview-first.  Do not call the compatibility
            # execution primitive here: only the task card's explicit click
            # reaches the document-generation endpoint.
            return self._build_shipment_confirmation_preview(
                response_data,
                parsed_params,
                ai_result,
                slots=slots,
                original_message=original_message,
            )
        elif tool_key == "shipments":
            return self._execute_shipments_query(response_data)
        else:
            response_data["toolCall"] = {
                "tool_id": tool_key,
                "action": "执行",
                "params": {"order_text": ai_result.get("text", ""), **parsed_params, **result_data},
            }
            response_data["response"] = ai_result.get("text", "")
            return response_data

    def _execute_products_query(
        self, response_data: dict[str, Any], slots: dict[str, Any], parsed_params: dict[str, Any]
    ) -> dict[str, Any]:
        """执行产品查询"""
        try:
            from app.bootstrap import get_products_service
            from app.infrastructure.lookups.purchase_unit_resolver import resolve_purchase_unit

            unit_name = slots.get("unit_name") or parsed_params.get("unit_name", "")
            model_number = slots.get("model_number") or parsed_params.get("model_number", "")
            keyword = slots.get("keyword") or parsed_params.get("keyword", "")

            if not unit_name and not model_number and keyword and "的" in keyword:
                match = re.search(r"([\u4e00-\u9fa5]{2,6})的(\d+[A-Z]?)", keyword)
                if match:
                    potential_unit = match.group(1)
                    model_candidate = match.group(2)
                    resolved = resolve_purchase_unit(potential_unit)
                    if resolved:
                        unit_name = resolved.unit_name
                    else:
                        unit_name = potential_unit
                    model_number = model_candidate
                    keyword = None

            app_service = get_products_service()

            if model_number and unit_name:
                products_result = app_service.get_products(
                    model_number=model_number, unit_name=unit_name
                )
            elif model_number:
                products_result = app_service.get_products(model_number=model_number)
            elif unit_name:
                products_result = app_service.get_products(unit_name=unit_name)
            elif keyword:
                products_result = app_service.get_products(keyword=keyword)
            else:
                products_result = app_service.get_products()

            products_list = products_result.get("data", []) if products_result else []

            response_data["data"]["unit_name"] = unit_name
            response_data["data"]["model_number"] = model_number
            response_data["data"]["data"] = {"products": products_list}
            response_data["response"] = (
                f"查询到 {len(products_list)} 个产品" if products_list else "未找到产品"
            )
            response_data["toolCall"] = {
                "tool_id": "products",
                "action": "执行",
                "params": {
                    "unit_name": unit_name,
                    "model_number": model_number,
                    "keyword": keyword,
                },
            }
            response_data["autoAction"] = {
                "type": "tool_call",
                "tool_key": "products",
                "params": {
                    "unit_name": unit_name,
                    "model_number": model_number,
                    "keyword": keyword,
                },
                "products": products_list,
                "unit_name": unit_name,
                "query": model_number or keyword or "",
            }
        except RECOVERABLE_ERRORS as prod_err:
            logger.error("即时执行 products 查询失败: %s", prod_err, exc_info=True)
            response_data["response"] = f"查询产品失败：{str(prod_err)}"

        return response_data

    def _execute_customers_query(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """执行客户查询"""
        try:
            from app.bootstrap import get_customer_app_service

            app_service = get_customer_app_service()
            customers_result = app_service.get_all()
            customers = customers_result.get("data", []) if customers_result else []

            response_data["data"]["data"] = {"customers": customers}
            response_data["response"] = (
                f"查询到 {len(customers)} 个客户" if customers else "未找到客户"
            )
        except RECOVERABLE_ERRORS as cust_err:
            logger.error("即时执行 customers 查询失败: %s", cust_err, exc_info=True)
            response_data["response"] = f"查询客户失败：{str(cust_err)}"

        return response_data

    def _execute_customers_intent(
        self,
        response_data: dict[str, Any],
        slots: dict[str, Any],
        parsed_params: dict[str, Any],
        original_message: str = "",
    ) -> dict[str, Any]:
        text = str(original_message or "").strip()
        lower = text.lower()
        unit_name = str(
            slots.get("unit_name")
            or parsed_params.get("unit_name")
            or parsed_params.get("customer_name")
            or parsed_params.get("name")
            or ""
        ).strip()

        is_add_intent = any(k in text for k in ("添加", "新增", "新建", "创建")) or any(
            k in lower for k in ("add", "create", "new")
        )
        is_query_intent = any(k in text for k in ("查询", "查", "列表", "全部")) or any(
            k in lower for k in ("query", "search", "list")
        )

        if is_add_intent and not unit_name:
            response_data["response"] = (
                "你要添加哪个单位？请告诉我单位名称，例如：添加单位 七彩乐园。"
            )
            response_data["data"]["data"] = {
                "intent": "customer_create",
                "missing_fields": ["unit_name"],
            }
            return response_data

        if is_add_intent and unit_name:
            try:
                from app.application.facades.tools_facade import execute_registered_workflow_tool

                created = execute_registered_workflow_tool(
                    tool_id="customers",
                    action="ensure_exists",
                    params={"unit_name": unit_name},
                )
                if created.get("success"):
                    if created.get("created"):
                        response_data["response"] = f"单位已创建：{unit_name}"
                    else:
                        response_data["response"] = f"单位已存在：{unit_name}"
                    response_data["data"]["data"] = created
                    return response_data
                response_data["response"] = created.get("message", "处理单位失败")
                return response_data
            except RECOVERABLE_ERRORS as err:
                logger.error("customers 添加意图执行失败: %s", err, exc_info=True)
                response_data["response"] = f"处理单位失败：{str(err)}"
                return response_data

        if is_query_intent:
            return self._execute_customers_query(response_data)

        # 未明确意图时，不再默认查全表，避免“添加单位”误触发列表查询
        response_data["response"] = (
            "我可以帮你处理单位管理。你可以说：“添加单位 七彩乐园”或“查询客户列表”。"
        )
        response_data["data"]["data"] = {"intent": "customers_followup"}
        return response_data

    def _build_order_text_from_products(
        self,
        unit_name: str,
        products: list,
        original_message: str = "",
        default_qty: int = None,
        default_spec: int = None,
    ) -> str:
        """根据产品列表构建订单文本"""
        import re

        if not products:
            return ""
        if not unit_name:
            return ""

        if original_message and len(products) >= 1:
            normalized_msg = "".join(original_message.replace("，", ",").replace("。", "").split())
            order_pattern = re.compile(
                r"帮?打([^,，]{1,80}?)的?货单?[,，]?(\d{1,6})桶"
                r"(\d{1,8}[A-Z]?(?:-\d{1,8}[A-Z]?)?)规格(\d{1,6})[,，]?"
                r"(\d{1,6})桶(\d{1,8}[A-Z]?(?:-\d{1,8}[A-Z]?)?)规格(\d{1,6})"
            )
            matches = list(order_pattern.finditer(normalized_msg))

            if len(matches) >= 1:
                m = matches[0]
                found_unit = m.group(1)
                if len(m.groups()) >= 7:
                    order_parts = []
                    for i in range(1, len(m.groups()), 4):
                        if i + 3 <= len(m.groups()):
                            qty = int(m.group(i + 1))
                            model = m.group(i + 2)
                            spec = int(m.group(i + 3))
                            order_parts.append(f"{qty}桶{model}规格{spec}")
                    if order_parts and found_unit:
                        return found_unit + "，" + "，".join(order_parts)
                else:
                    order_parts = []
                    for m in matches:
                        qty = int(m.group(2))
                        model = m.group(3)
                        spec = int(m.group(4))
                        order_parts.append(f"{qty}桶{model}规格{spec}")
                    if order_parts and found_unit:
                        return found_unit + "，" + "，".join(order_parts)

        parts = []
        for p in products:
            model = p.get("model") or p.get("model_number") or p.get("name") or ""
            qty = p.get("quantity_tins") or p.get("quantity") or p.get("qty") or 1
            spec = p.get("spec") or p.get("tin_spec") or p.get("规格") or default_spec or 25
            if model:
                parts.append(f"{int(qty)}桶{model}规格{int(float(spec))}")
            else:
                parts.append(f"{int(qty)}桶规格{int(float(spec))}")
        return unit_name + "，" + "，".join(parts)

    def _try_merge_split_model(self, text: str, product_template: dict) -> str:
        """尝试合并被拆分的型号（如 5003-2737B 被拆成 5003 和 2737B）"""
        import re

        qty = product_template.get("quantity_tins") or 1
        product_template.get("spec") or product_template.get("tin_spec") or 25

        number_pattern = r"(\d+)([A-Z]?)\s*规格\s*(\d+)"
        m = re.search(number_pattern, text)
        if m:
            model = m.group(1) + m.group(2)
            spec_val = int(m.group(3))
            return f"{int(qty)}桶{model}规格{spec_val}"

        number_pattern2 = r"(\d+)\s*桶\s*(\d+)([A-Z]?)\s*规格\s*(\d+)"
        m2 = re.search(number_pattern2, text)
        if m2:
            qty_val = int(m2.group(1))
            model = m2.group(2) + m2.group(3)
            spec_val = int(m2.group(4))
            return f"{qty_val}桶{model}规格{spec_val}"

        return ""

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
