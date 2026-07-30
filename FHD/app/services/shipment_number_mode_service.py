from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Mapping
from typing import Any

from app.bootstrap import get_shipment_app_service
from app.db.models import Product
from app.db.session import get_db
from app.infrastructure.shipment_number_resolution import ShipmentNumberResolutionMixin
from app.infrastructure.tenant_scope import apply_tenant_filter
from app.utils.operational_errors import RECOVERABLE_ERRORS


class ShipmentNumberModeService(ShipmentNumberResolutionMixin):
    """
    XCAGI 内部编号模式编排服务。
    - 统一使用 XCAGI DB（purchase_units/products/customer_products）
    - 不依赖外部 98k 或 unit_databases/*.db
    - 失败时按严格策略返回错误，不走预览兜底
    """

    MODIFY_VERB_PATTERN = re.compile(
        r"(再加|还要|继续加|再补|加上|增加|减少|减去|删掉|删除|去掉|移除|改成|改为|改)"
    )
    # Customer ledgers often use a parenthetical trading/shop alias while the
    # delivery note records the legal/customer-facing name.  Keep this in
    # lockstep with ``customer_alias_key`` used by the ETL parser, so a known
    # value such as ``金汉武（宾驰）`` can still reach the canonical customer.
    _PARENTHETICAL_UNIT_ALIAS_RE = re.compile(r"[（(][^）)]*[）)]")

    @staticmethod
    def _normalize_success_payload(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return payload

        doc_name = str(payload.get("doc_name") or payload.get("filename") or "").strip()
        file_path = str(payload.get("file_path") or payload.get("filepath") or "").strip()
        final_order_number = str(payload.get("order_number") or "").strip()
        record_id = payload.get("record_id")
        order_id = payload.get("order_id")
        final_record_id = record_id if record_id is not None else order_id
        document = payload.get("document") if isinstance(payload.get("document"), dict) else {}

        if doc_name and not document.get("filename"):
            document["filename"] = doc_name
        if file_path and not document.get("filepath"):
            document["filepath"] = file_path
        if final_order_number and not document.get("order_number"):
            document["order_number"] = final_order_number
        if final_record_id is not None:
            document["record_id"] = final_record_id
            document["order_id"] = final_record_id

        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if doc_name:
            data["doc_name"] = doc_name
        if file_path:
            data["file_path"] = file_path
        if final_order_number:
            data["order_number"] = final_order_number
            payload["order_number"] = final_order_number
        if final_record_id is not None:
            payload["record_id"] = final_record_id
            payload["order_id"] = final_record_id
            data["record_id"] = final_record_id
            data["order_id"] = final_record_id
        if document:
            payload["document"] = document
            data["document"] = document

        payload["data"] = data
        return payload

    def execute(
        self,
        *,
        order_text: str,
        custom_order_number: str,
        direct_unit_name: str,
        direct_products: list[dict[str, Any]],
        parse_order_text: Callable[[str], dict[str, Any]],
        template_name: str | None = None,
        template_id: str | None = None,
        preferred_template: str | None = None,
        owner_user_id: int | None = None,
    ) -> tuple[dict[str, Any], int]:
        text = str(order_text or "").strip()
        if not text and not (direct_unit_name and direct_products):
            return {
                "success": False,
                "message": "缺少订单文本参数，请提供订单信息",
                "error_code": "missing_order_text",
            }, 400

        unit_pool = self._query_active_purchase_unit_names()
        unit_to_use = str(direct_unit_name or "").strip()
        parsed = {"success": False, "unit_name": "", "products": []}

        product_catalog: list[dict[str, Any]] = []
        model_pool: list[str] = []
        if text:
            parsed = parse_order_text(text) or {}

            # 解析失败时，补一层“XCAGI DB 词条解析”。
            if not parsed.get("success"):
                product_catalog = self._load_active_product_catalog()
                model_pool = [
                    str(row.get("model_number") or "").strip().upper()
                    for row in product_catalog
                    if str(row.get("model_number") or "").strip()
                ]
                parsed_by_db = self._parse_by_db_terms(
                    text=text,
                    unit_pool=unit_pool,
                    model_pool=model_pool,
                )
                if parsed_by_db.get("success"):
                    parsed = parsed_by_db

            if not unit_to_use and parsed.get("success"):
                unit_to_use = str(parsed.get("unit_name") or "").strip()

        is_modify_request = bool(self.MODIFY_VERB_PATTERN.search(text))
        if is_modify_request:
            recovered = self._extract_existing_unit_from_modify_text(text, unit_pool)
            if recovered:
                unit_to_use = recovered

        if not unit_to_use and is_modify_request:
            return {
                "success": False,
                "message": "检测到增删改请求，但未识别到购买单位。请先明确单位，例如：七彩乐园再加1桶9803规格28。",
                "error_code": "purchase_unit_required_for_modify",
                "data": {"need_confirm_unit": True},
            }, 400

        if unit_to_use:
            resolved_alias = self._resolve_unit_alias(unit_to_use, unit_pool)
            if resolved_alias:
                unit_to_use = resolved_alias
            unit_not_found = self._build_unit_not_found_payload(unit_to_use, unit_pool)
            if unit_not_found:
                return unit_not_found, 400

        products = list(direct_products or [])
        if not products:
            if not parsed.get("success"):
                return {
                    "success": False,
                    "message": (
                        "编号模式解析失败，已按严格策略停止生成（未启用预览兜底）。"
                        f" 失败原因：{parsed.get('message', '无法解析订单信息')}"
                    ),
                    "error_code": "NUMBER_MODE_STRICT_FAILED",
                    "data": {"parsed_data": parsed},
                }, 400
            products = list(parsed.get("products") or [])

        if not products or not unit_to_use:
            return {
                "success": False,
                "message": "编号模式解析失败，已按严格策略停止生成（未启用预览兜底）。 失败原因：无法解析订单信息",
                "error_code": "NUMBER_MODE_STRICT_FAILED",
                "data": {"parsed_data": parsed},
            }, 400

        try:
            trusted_owner_user_id = int(owner_user_id) if owner_user_id is not None else 0
        except (TypeError, ValueError):
            trusted_owner_user_id = 0

        # 严格策略：所有主库匹配都限定在当前租户；名称模式还必须唯一地
        # 落在当前购买单位下，不能用全局/模糊产品结果替代。
        if not product_catalog:
            product_catalog = self._load_active_product_catalog()

        preview_product_provenance: list[dict[str, Any]] = []
        for idx, product in enumerate(products, start=1):
            model_number = str(product.get("model_number") or "").strip().upper()
            product_name = str(product.get("product_name") or product.get("name") or "").strip()
            tin_spec = str(product.get("tin_spec") or product.get("specification") or "").strip()
            quantity = (
                product.get("quantity_tins")
                if "quantity_tins" in product
                else product.get("quantity")
            )

            try:
                quantity_value = float(quantity)
            except RECOVERABLE_ERRORS:
                quantity_value = 0.0

            if not tin_spec:
                return {
                    "success": False,
                    "message": f"编号模式解析失败，已按严格策略停止生成（未启用预览兜底）。 失败原因：第{idx}项规格缺失。",
                    "error_code": "NUMBER_MODE_STRICT_FAILED",
                    "data": {"parsed_data": parsed},
                }, 400
            if quantity_value <= 0:
                return {
                    "success": False,
                    "message": f"编号模式解析失败，已按严格策略停止生成（未启用预览兜底）。 失败原因：第{idx}项数量缺失或无效。",
                    "error_code": "NUMBER_MODE_STRICT_FAILED",
                    "data": {"parsed_data": parsed},
                }, 400

            preview_status, preview_candidate = self._resolve_owner_preview_product_candidate(
                owner_user_id=trusted_owner_user_id,
                unit_name=unit_to_use,
                product_name=product_name,
            )
            if preview_status == "conflict":
                return self._preview_product_conflict_payload(
                    parsed=parsed,
                    unit_name=unit_to_use,
                    product_name=product_name,
                ), 400

            product_from_preview: dict[str, Any] | None = None
            matched_product: dict[str, Any] | None = None
            preview_model = (
                str(preview_candidate.get("model_number") if preview_candidate else "")
                .strip()
                .upper()
            )

            if not model_number:
                # An exact, validated owner-scoped preview is newer business
                # evidence than the master catalogue, which may still carry a
                # historic model or price.  A preview without a usable model
                # cannot satisfy strict number mode, so master matching remains
                # available for that incomplete case.
                if preview_candidate is not None and preview_model:
                    matched_product = {
                        "name": preview_candidate.get("name"),
                        "model_number": preview_model,
                        "price": preview_candidate.get("price"),
                    }
                    product_from_preview = preview_candidate
                else:
                    matched_product, resolution_error, related_rows = (
                        self._resolve_scoped_product_name(
                            product_name=product_name,
                            unit_name=unit_to_use,
                            product_catalog=product_catalog,
                        )
                    )
                    if matched_product is None:
                        if resolution_error == "NUMBER_MODE_PRODUCT_NAME_AMBIGUOUS":
                            candidates = [
                                {
                                    "name": str(row.get("name") or ""),
                                    "model_number": str(row.get("model_number") or ""),
                                }
                                for row in related_rows
                            ]
                            return {
                                "success": False,
                                "message": (
                                    "编号模式解析失败，已按严格策略停止生成（未启用预览兜底）。 "
                                    f"失败原因：购买单位“{unit_to_use}”下的产品名称“{product_name}”匹配到多个产品。"
                                ),
                                "error_code": "NUMBER_MODE_PRODUCT_NAME_AMBIGUOUS",
                                "data": {
                                    "parsed_data": parsed,
                                    "unit_name": unit_to_use,
                                    "product_name": product_name,
                                    "candidates": candidates,
                                },
                            }, 400
                        return {
                            "success": False,
                            "message": (
                                "编号模式解析失败，已按严格策略停止生成（未启用预览兜底）。 "
                                f"失败原因：第{idx}项型号缺失，且未找到购买单位“{unit_to_use}”下的产品名称“{product_name}”。"
                            ),
                            "error_code": "NUMBER_MODE_PRODUCT_NAME_NOT_FOUND",
                            "data": {
                                "parsed_data": parsed,
                                "unit_name": unit_to_use,
                                "product_name": product_name,
                            },
                        }, 400

                canonical_name = str(matched_product.get("name") or product_name).strip()
                canonical_model = str(matched_product.get("model_number") or "").strip().upper()
                product["name"] = canonical_name
                product["product_name"] = canonical_name
                if canonical_model:
                    product["model_number"] = canonical_model
                    model_number = canonical_model
                if product.get("unit_price") in (None, ""):
                    product["unit_price"] = matched_product.get("price")

            if model_number and product_from_preview is None:
                # A caller-supplied model remains authoritative.  When the
                # private preview agrees, it can still provide the fresher
                # price; disagreement is an explicit business-fact conflict.
                if preview_candidate is not None and preview_model:
                    if preview_model != model_number:
                        return self._preview_product_conflict_payload(
                            parsed=parsed,
                            unit_name=unit_to_use,
                            product_name=product_name,
                        ), 400
                    matched_product = {
                        "name": preview_candidate.get("name"),
                        "model_number": preview_model,
                        "price": preview_candidate.get("price"),
                    }
                    product_from_preview = preview_candidate
                else:
                    matched_product, resolution_error, related_rows = (
                        self._resolve_scoped_product_model(
                            model_number=model_number,
                            unit_name=unit_to_use,
                            product_catalog=product_catalog,
                        )
                    )
                    if matched_product is None:
                        if resolution_error == "NUMBER_MODE_PRODUCT_MODEL_AMBIGUOUS":
                            candidates = [
                                {
                                    "name": str(row.get("name") or ""),
                                    "model_number": str(row.get("model_number") or ""),
                                }
                                for row in related_rows
                            ]
                            return {
                                "success": False,
                                "message": (
                                    "编号模式解析失败，已按严格策略停止生成（未启用预览兜底）。 "
                                    f"失败原因：购买单位“{unit_to_use}”下的型号“{model_number}”匹配到多个产品。"
                                ),
                                "error_code": "NUMBER_MODE_PRODUCT_MODEL_AMBIGUOUS",
                                "data": {
                                    "parsed_data": parsed,
                                    "unit_name": unit_to_use,
                                    "model_number": model_number,
                                    "candidates": candidates,
                                },
                            }, 400
                        return {
                            "success": False,
                            "message": (
                                "编号模式解析失败，已按严格策略停止生成（未启用预览兜底）。 "
                                f"失败原因：型号不存在或不属于购买单位“{unit_to_use}”（{model_number}）。"
                            ),
                            "error_code": "NUMBER_MODE_STRICT_FAILED",
                            "data": {
                                "parsed_data": parsed,
                                "missing_model_number": model_number,
                                "match_error_code": "NUMBER_MODE_PRODUCT_MODEL_NOT_FOUND",
                            },
                        }, 400

                canonical_name = str(matched_product.get("name") or product_name).strip()
                canonical_model = (
                    str(matched_product.get("model_number") or model_number).strip().upper()
                )
                if canonical_name:
                    product["name"] = canonical_name
                    product["product_name"] = canonical_name
                product["model_number"] = canonical_model
                if product.get("unit_price") in (None, ""):
                    product["unit_price"] = matched_product.get("price")

            if product_from_preview is not None:
                provenance = product_from_preview.get("provenance")
                if isinstance(provenance, dict):
                    preview_product_provenance.append(dict(provenance))

        parsed_order_number = str(parsed.get("order_number") or "").strip()
        requested_order_number = str(custom_order_number or "").strip()
        effective_order_number = requested_order_number or parsed_order_number
        parsed_order_number_provenance = (
            parsed.get("order_number_provenance")
            if parsed_order_number
            and parsed_order_number == effective_order_number
            and isinstance(parsed.get("order_number_provenance"), dict)
            else None
        )

        generate_kwargs: dict[str, Any] = {
            "unit_name": unit_to_use,
            "products": products,
            "template_name": (str(template_name or "").strip() or None),
            "template_id": (str(template_id or "").strip() or None),
            "preferred_template": (str(preferred_template or "").strip() or None),
            "order_number": effective_order_number or None,
            "intent": "shipment_generate",
            "raw_text": text,
        }
        # Private ETL templates are owner-scoped.  This value is supplied by
        # the authenticated route, never by params parsed from the request.
        if trusted_owner_user_id > 0:
            generate_kwargs["owner_user_id"] = trusted_owner_user_id

        app_service = get_shipment_app_service()
        result = app_service.generate_shipment_document(
            **generate_kwargs,
        )
        result = self._normalize_success_payload(result)

        if result.get("success"):
            if parsed_order_number_provenance is not None:
                result["order_number_provenance"] = dict(parsed_order_number_provenance)
            if preview_product_provenance:
                warning = (
                    "本次产品信息来自尚未执行的 ETL 预演候选，仅用于本次已确认的发货单；"
                    "未写入产品库。"
                )
                existing_warnings = result.get("warnings")
                warnings = list(existing_warnings) if isinstance(existing_warnings, list) else []
                warnings.append(
                    {
                        "code": "ETL_PREVIEW_PRODUCT_CANDIDATE_USED",
                        "message": warning,
                    }
                )
                result["warnings"] = warnings
                result["etl_preview_provenance"] = {
                    "products": preview_product_provenance,
                }
            return result, 200

        return {
            "success": False,
            "message": (
                "编号模式解析失败，已按严格策略停止生成（未启用预览兜底）。"
                f" 失败原因：{result.get('message', '生成失败')}"
            ),
            "error_code": "NUMBER_MODE_STRICT_FAILED",
            "data": {
                "parsed_data": parsed,
                "detail": result,
            },
        }, 400


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(
    ShipmentNumberModeService, "app.services.shipment_number_mode_service"
)
