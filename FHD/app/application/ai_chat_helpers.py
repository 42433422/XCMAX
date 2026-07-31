"""
与归档 ``ai_chat`` 路由共用的纯 Python 辅助函数。

供 ``normal_chat_dispatch``、``/api/ai/chat-unified`` 等原生 FastAPI 路由复用。
"""

from __future__ import annotations

import logging
from typing import Any, cast

from app.utils.ai_helpers import format_money, safe_float
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _fetch_product_meta_by_models(models, unit_name: str = "") -> dict[str, dict[str, Any]]:
    model_list = [m for m in models if m]
    if not model_list:
        return {}

    meta: dict[str, dict[str, Any]] = {}
    try:
        from app.bootstrap import get_products_service

        products_service = get_products_service()

        def _normalize_model_token(v: Any) -> str:
            text = str(v or "").strip().upper()
            return text.replace(" ", "").replace("-", "")

        def _pick_best_record(records: list, model: str) -> dict[str, Any]:
            if not records:
                return {}
            target = _normalize_model_token(model)
            if not target:
                return records[0] or {}

            for r in records:
                rec_model = _normalize_model_token((r or {}).get("model_number"))
                if rec_model and rec_model == target:
                    return cast("dict[str, Any]", r)

            for r in records:
                rec_name = _normalize_model_token((r or {}).get("name"))
                if rec_name and target in rec_name:
                    return cast("dict[str, Any]", r)

            for r in records:
                rec_model = _normalize_model_token((r or {}).get("model_number"))
                if rec_model and target in rec_model:
                    return cast("dict[str, Any]", r)

            return records[0] or {}

        for model in model_list:
            model_raw = str(model or "").strip()
            model_norm = _normalize_model_token(model_raw)
            records = []

            if unit_name:
                result = (
                    products_service.get_products(model_number=model_raw, unit_name=unit_name) or {}
                )
                records = result.get("data") or []

            if not records:
                result = products_service.get_products(model_number=model_raw) or {}
                records = result.get("data") or []

            if not records:
                result = products_service.get_products(keyword=model_raw) or {}
                records = result.get("data") or []

            if records:
                first = _pick_best_record(records, model_raw)
                meta_payload = {
                    "name": first.get("name") or first.get("product_name") or "",
                    "price": safe_float(first.get("price")),
                }
                if model_raw:
                    meta[model_raw] = meta_payload
                if model_norm:
                    meta[model_norm] = meta_payload
    except RECOVERABLE_ERRORS as err:
        logger.warning("补全预览产品信息失败：%s", err, exc_info=True)
    return meta


def _build_number_preview_items(unit_name: str, products) -> dict[str, Any]:
    products = products or []
    models = []
    for p in products:
        model = (p.get("model_number") or p.get("model") or "").strip()
        if model:
            models.append(model)
    product_meta = _fetch_product_meta_by_models(models, unit_name)

    items = []
    grand_total = 0.0
    has_priced_row = False

    for p in products:
        model = (p.get("model_number") or p.get("model") or p.get("name") or "").strip()
        qty_num = safe_float(p.get("quantity_tins"))
        qty = int(qty_num) if qty_num is not None and qty_num.is_integer() else (qty_num or 0)
        spec = p.get("tin_spec") or p.get("spec") or ""
        spec_num = safe_float(spec)

        model_norm = str(model).strip().upper().replace(" ", "").replace("-", "") if model else ""
        meta = {}
        if model:
            meta = product_meta.get(model, {}) or product_meta.get(model_norm, {}) or {}

        product_name_raw = str(p.get("name") or p.get("product_name") or "").strip()
        if product_name_raw in {"-", "--", "—", "－"}:
            product_name_raw = ""
        product_name = product_name_raw or meta.get("name") or "-"

        unit_price = safe_float(p.get("unit_price"))
        if unit_price is None:
            unit_price = safe_float(p.get("price"))
        if unit_price is None:
            unit_price = safe_float(meta.get("price"))

        line_total = None
        parsed_amount = safe_float(p.get("amount"))
        if unit_price is not None:
            quantity_kg = safe_float(p.get("quantity_kg"))
            if quantity_kg is None and qty_num is not None and spec_num is not None:
                quantity_kg = float(qty_num) * float(spec_num)
            if quantity_kg is not None:
                line_total = unit_price * quantity_kg
            elif qty_num is not None:
                line_total = unit_price * float(qty_num)
        if line_total is None:
            line_total = parsed_amount
        if line_total is not None:
            grand_total += line_total
            has_priced_row = True

        items.append(
            {
                "单位": unit_name or "",
                "型号": model,
                "产品名称": product_name,
                "桶数": qty,
                "规格": spec,
                "单价": format_money(unit_price),
                "总价": format_money(line_total),
            }
        )

    return {
        "items": items,
        "grand_total": grand_total if has_priced_row else None,
    }


def _trusted_owner_id(value: Any) -> int | None:
    """Accept only a server-provided positive owner id for ETL preview reads."""

    try:
        owner = int(value)
    except (TypeError, ValueError):
        return None
    return owner if owner > 0 else None


def _enrich_shipment_preview_from_etl(
    unit_name: str,
    products: list[dict[str, Any]],
    *,
    authenticated_owner_user_id: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None, list[str]]:
    """Hydrate only the *display* side of a shipment confirmation card.

    ETL preview rows remain owner-scoped, unexecuted evidence.  The original
    natural-language product payload is deliberately left untouched because
    the confirmed tool re-resolves it using the authenticated request owner.
    This prevents display metadata from becoming a client-controlled write
    parameter or changing strict number-mode behaviour.
    """

    owner = _trusted_owner_id(authenticated_owner_user_id)
    display_products = [dict(product) for product in products if isinstance(product, dict)]
    if owner is None or not display_products:
        return display_products, [], None, []

    try:
        from app.application.etl.shipment_preview_fallback import (
            find_latest_preview_layout_candidate,
            resolve_preview_product_candidate,
        )
    except RECOVERABLE_ERRORS:
        return display_products, [], None, []

    evidence: list[dict[str, Any]] = []
    warnings: list[str] = []
    for display_product in display_products:
        product_name = str(
            display_product.get("name") or display_product.get("product_name") or ""
        ).strip()
        if not product_name:
            continue
        try:
            candidate = resolve_preview_product_candidate(
                owner_user_id=owner,
                unit_name=unit_name,
                product_name=product_name,
            )
        except RECOVERABLE_ERRORS:
            continue
        if not isinstance(candidate, dict):
            continue

        # Show the proven model/price but do not modify `products` sent to the
        # confirm endpoint.  The endpoint owns its own authenticated lookup.
        if not str(
            display_product.get("model_number") or display_product.get("model") or ""
        ).strip():
            model = str(candidate.get("model_number") or "").strip()
            if model:
                display_product["model_number"] = model
        if display_product.get("unit_price") in (None, "") and display_product.get("price") in (
            None,
            "",
        ):
            if candidate.get("price") not in (None, ""):
                display_product["unit_price"] = candidate.get("price")

        source_specification = safe_float(candidate.get("specification"))
        requested_specification = safe_float(
            display_product.get("tin_spec") or display_product.get("specification")
        )
        if (
            source_specification is not None
            and requested_specification is not None
            and abs(source_specification - requested_specification) > 1e-9
        ):
            warning = (
                f"{product_name} 本次规格 {format_money(requested_specification)}kg/桶"
                f"不同于历史记录 {format_money(source_specification)}kg/桶；"
                "将只用于本次发货单，不会改写产品默认规格。"
            )
            if warning not in warnings:
                warnings.append(warning)

        provenance = candidate.get("provenance")
        evidence.append(
            {
                "product_name": str(candidate.get("name") or product_name),
                "model_number": str(candidate.get("model_number") or ""),
                "unit_price": candidate.get("price"),
                "source_date": candidate.get("source_date"),
                "provenance": dict(provenance) if isinstance(provenance, dict) else {},
            }
        )

    try:
        layout = find_latest_preview_layout_candidate(
            owner_user_id=owner,
            unit_name=unit_name,
        )
    except RECOVERABLE_ERRORS:
        layout = None
    return display_products, evidence, layout if isinstance(layout, dict) else None, warnings


def build_shipment_preview_response_dict(
    unit_name: str,
    products,
    order_text: str,
    *,
    order_number: str | None = None,
    order_number_provenance: dict[str, Any] | None = None,
    authenticated_owner_user_id: int | None = None,
) -> dict[str, Any]:
    """Build a confirmation-only shipment task.

    A manually labelled document number is carried as data on the confirmation
    payload, never executed at parse time.  The original natural-language text
    remains present for audit/reparse on the confirmed endpoint.
    """

    manual_order_number = str(order_number or "").strip()
    raw_products = [dict(product) for product in (products or []) if isinstance(product, dict)]
    display_products, etl_product_evidence, etl_layout, etl_warnings = (
        _enrich_shipment_preview_from_etl(
            unit_name,
            raw_products,
            authenticated_owner_user_id=authenticated_owner_user_id,
        )
    )
    # ``find_latest_preview_layout_candidate`` only returns a layout after its
    # tenant + owner scoped lookup matched this requested unit.  Use its
    # evidenced customer spelling on the *card* so an abbreviated chat input
    # (for example ``金汉武``) is transparent to the user.  Keep the original
    # parsed unit in ``params`` below: confirmation must re-resolve all ETL
    # evidence from the authenticated request, never trust display metadata.
    display_unit_name = (
        str(etl_layout.get("customer_name") if isinstance(etl_layout, dict) else "").strip()
        or str(unit_name or "").strip()
    )
    preview = _build_number_preview_items(display_unit_name, display_products)
    total_text = (
        f"，预估总价 ¥{format_money(preview['grand_total'])}"
        if preview.get("grand_total") is not None
        else ""
    )
    order_number_text = f"，单号：{manual_order_number}" if manual_order_number else ""
    items = preview["items"]
    params: dict[str, Any] = {
        "order_text": order_text,
        "unit_name": unit_name,
        # Preserve only the natural-language parse as executable input.  The
        # enriched ETL evidence is display-only and is re-read server-side on
        # confirmation from tenant + owner scoped storage.
        "products": raw_products,
        "number_mode": True,
    }
    if manual_order_number:
        params["order_number"] = manual_order_number
        if isinstance(order_number_provenance, dict):
            params["order_number_provenance"] = dict(order_number_provenance)
    response_data: dict[str, Any] = {
        "routing": "normal_slot_dispatch",
        "intent": "shipment_preview",
    }
    if manual_order_number and isinstance(order_number_provenance, dict):
        response_data["order_number_provenance"] = dict(order_number_provenance)
    if etl_product_evidence or etl_layout:
        response_data["etl_preview"] = {
            "products": etl_product_evidence,
            "layout": dict(etl_layout) if etl_layout else None,
        }
    description_suffix = ""
    if display_unit_name and display_unit_name != str(unit_name or "").strip():
        description_suffix += (
            f" 已按当前用户的 ETL 预演将“{str(unit_name or '').strip()}”"
            f"识别为“{display_unit_name}”，确认时会再次校验。"
        )
    if etl_product_evidence:
        description_suffix += " 已按当前用户的 ETL 预演补全型号和单价，确认时会再次校验。"
    if etl_layout:
        description_suffix += (
            f" 已识别发货单版式“{str(etl_layout.get('name') or '').strip()}”，"
            "仅供本次确认生成使用。"
        )
    if etl_warnings:
        description_suffix += " " + " ".join(etl_warnings)
    return {
        "success": True,
        "message": "已识别订单，请确认执行",
        "response": '已识别订单，请点击"确认执行"生成发货单。',
        "task": {
            "type": "shipment_generate",
            "title": "发货单预览",
            "description": (
                f"单位：{display_unit_name}，共 {len(raw_products)} 项{total_text}{order_number_text}。"
                f"确认后将生成并可继续打印。{description_suffix}"
            ),
            "items": items,
            "api_url": "/api/tools/execute",
            "method": "POST",
            "payload": {
                "tool_id": "shipment_generate",
                "action": "执行",
                "params": params,
            },
            "switch_view": "orders",
        },
        "data": response_data,
    }


def recognize_intents(message: str) -> dict[str, Any]:
    from app.application.intent_recognition_app import recognize_intents as _recognize

    result = _recognize(message)
    return {
        "primary_intent": result.get("primary_intent"),
        "tool_key": result.get("tool_key"),
        "intent_hints": result.get("intent_hints", []),
        "is_negated": result.get("is_negated", False),
        "is_greeting": result.get("is_greeting", False),
        "is_goodbye": result.get("is_goodbye", False),
        "is_help": result.get("is_help", False),
        "confidence": result.get("confidence", 0.5),
        "sources_used": result.get("sources_used", ["rule_engine"]),
    }


def _resolve_mode_scoped_user_id(
    requested_user_id: Any,
    remote_addr: str,
    mode_channel: str,
) -> str:
    raw = str(requested_user_id or "").strip()
    if raw:
        return raw
    ip = str(remote_addr or "unknown")
    channel = str(mode_channel or "default").strip().lower() or "default"
    return f"user_{ip}:{channel}"


def normalize_batch_messages_payload(data: dict[str, Any]) -> list:
    raw = data.get("messages") or data.get("message_list") or []
    if isinstance(raw, str):
        raw = [raw]
    out = []
    for m in raw:
        s = str(m).strip()
        if s:
            out.append(s)
    return out


from app.application.ai_chat_single_payload import (
    unified_chat_single_payload,
)
