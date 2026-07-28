from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Mapping
from typing import Any

from app.bootstrap import get_shipment_app_service
from app.db.models import Product
from app.db.session import get_db
from app.infrastructure.tenant_scope import apply_tenant_filter
from app.utils.operational_errors import RECOVERABLE_ERRORS


class ShipmentNumberModeService:
    """
    XCAGI 内部编号模式编排服务。
    - 统一使用 XCAGI DB（purchase_units/products/customer_products）
    - 不依赖外部 98k 或 unit_databases/*.db
    - 失败时按严格策略返回错误，不走预览兜底
    """

    MODIFY_VERB_PATTERN = re.compile(
        r"(再加|还要|继续加|再补|加上|增加|减少|减去|删掉|删除|去掉|移除|改成|改为|改)"
    )

    @staticmethod
    def _normalize_unit_name(value: str) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        text = re.sub(r"(有限责任公司|有限公司|公司|家私|家具|商贸|贸易|建材|装饰)", "", text)
        text = re.sub(r"[\s\-_()（）【】\[\]·,，.。/\\]+", "", text)
        return text

    @staticmethod
    def _normalize_product_name(value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        return re.sub(r"[\s\-_()（）【】\[\]·,，.。/\\]+", "", text)

    @staticmethod
    def _product_row_value(
        row: Any,
        field: str,
        *,
        tuple_index: int | None = None,
    ) -> Any:
        """Read a Product ORM row, mapping, or compact legacy test tuple."""

        if isinstance(row, Mapping):
            return row.get(field)
        if hasattr(row, field):
            return getattr(row, field)
        if tuple_index is not None and isinstance(row, (tuple, list)) and len(row) > tuple_index:
            return row[tuple_index]
        return None

    def _load_active_product_catalog(self) -> list[dict[str, Any]]:
        """Load only the current tenant's active product rows.

        Name-based order requests must never inspect products from a different
        tenant.  We retain tuple decoding solely for existing compatibility tests
        and old compact query callers; production uses full Product ORM rows so
        unit and price are available for deterministic customer-product matching.
        """

        with get_db() as db:
            rows = (
                apply_tenant_filter(db.query(Product), Product)
                .filter(
                    (Product.is_active == 1)
                    | (Product.is_active == True)
                    | (Product.is_active.is_(None))
                )
                .all()
            )

        catalog: list[dict[str, Any]] = []
        for row in rows or []:
            catalog.append(
                {
                    "model_number": str(
                        self._product_row_value(row, "model_number", tuple_index=0) or ""
                    ).strip(),
                    "name": str(self._product_row_value(row, "name", tuple_index=1) or "").strip(),
                    "unit": str(self._product_row_value(row, "unit", tuple_index=2) or "").strip(),
                    "price": self._product_row_value(row, "price", tuple_index=3),
                }
            )
        return catalog

    def _resolve_scoped_product_name(
        self,
        *,
        product_name: str,
        unit_name: str,
        product_catalog: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, str | None, list[dict[str, Any]]]:
        """Resolve a literal product name within one canonical purchase unit.

        The caller intentionally receives ambiguity instead of a fuzzy best guess.
        A later preview/user confirmation may repair the record, but automatic
        document generation must stop when the relationship is not unique.
        """

        normalized_unit = self._normalize_unit_name(unit_name)
        normalized_name = self._normalize_product_name(product_name)
        if not normalized_unit or not normalized_name:
            return None, "NUMBER_MODE_PRODUCT_NAME_NOT_FOUND", []

        scoped_rows = [
            row
            for row in product_catalog
            if self._normalize_unit_name(row.get("unit") or "") == normalized_unit
        ]
        exact_rows = [
            row
            for row in scoped_rows
            if self._normalize_product_name(row.get("name") or "") == normalized_name
        ]
        if len(exact_rows) == 1:
            return exact_rows[0], None, exact_rows
        if len(exact_rows) > 1:
            return None, "NUMBER_MODE_PRODUCT_NAME_AMBIGUOUS", exact_rows
        return None, "NUMBER_MODE_PRODUCT_NAME_NOT_FOUND", scoped_rows

    def _resolve_scoped_product_model(
        self,
        *,
        model_number: str,
        unit_name: str,
        product_catalog: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, str | None, list[dict[str, Any]]]:
        """Resolve a model number inside the canonical purchase unit.

        Full Product rows always carry a customer/unit relationship in the current
        product model.  Compact legacy query tuples do not, so only that legacy
        shape retains model-only compatibility; real tenant data is never allowed
        to fall back from ``(unit, model)`` to another customer's model.
        """

        normalized_unit = self._normalize_unit_name(unit_name)
        normalized_model = str(model_number or "").strip().upper()
        if not normalized_unit or not normalized_model:
            return None, "NUMBER_MODE_PRODUCT_MODEL_NOT_FOUND", []

        has_unit_relationship = any(
            self._normalize_unit_name(row.get("unit") or "") for row in product_catalog
        )
        candidate_rows = product_catalog
        if has_unit_relationship:
            candidate_rows = [
                row
                for row in product_catalog
                if self._normalize_unit_name(row.get("unit") or "") == normalized_unit
            ]

        exact_rows = [
            row
            for row in candidate_rows
            if str(row.get("model_number") or "").strip().upper() == normalized_model
        ]
        if len(exact_rows) == 1:
            return exact_rows[0], None, exact_rows
        if len(exact_rows) > 1:
            return None, "NUMBER_MODE_PRODUCT_MODEL_AMBIGUOUS", exact_rows
        return None, "NUMBER_MODE_PRODUCT_MODEL_NOT_FOUND", candidate_rows

    def _query_active_purchase_unit_names(self) -> list[str]:
        from app.db.models.purchase_unit import PurchaseUnit
        from app.db.session import get_db

        with get_db() as db:
            rows = (
                apply_tenant_filter(db.query(PurchaseUnit.unit_name), PurchaseUnit)
                .filter(PurchaseUnit.is_active == True)
                .order_by(PurchaseUnit.unit_name.asc())
                .all()
            )
            return [str(r[0]).strip() for r in rows if r and str(r[0]).strip()]

    def _resolve_unit_alias(self, typed_unit: str, unit_pool: list[str]) -> str:
        typed = (typed_unit or "").strip()
        if not typed or not unit_pool:
            return ""

        candidate_typed_list = [typed]
        stripped_qty_tail = re.sub(r"(?:\d+|[一二两三四五六七八九十零〇]+)\s*$", "", typed).strip()
        if stripped_qty_tail and stripped_qty_tail not in candidate_typed_list:
            candidate_typed_list.append(stripped_qty_tail)

        normalized_candidates = []
        for item in candidate_typed_list:
            normalized_item = self._normalize_unit_name(item)
            if normalized_item and normalized_item not in normalized_candidates:
                normalized_candidates.append(normalized_item)
        if not normalized_candidates:
            return ""

        def _tail_digits(value: str) -> str:
            match = re.search(r"(\d+)$", str(value or ""))
            return match.group(1) if match else ""

        for normalized_typed in normalized_candidates:
            normalized_exact = [
                unit for unit in unit_pool if self._normalize_unit_name(unit) == normalized_typed
            ]
            if len(normalized_exact) == 1:
                return normalized_exact[0]

            contains = [
                unit
                for unit in unit_pool
                if normalized_typed in self._normalize_unit_name(unit)
                or self._normalize_unit_name(unit) in normalized_typed
            ]
            if len(contains) == 1:
                return contains[0]
            if len(contains) > 1:
                typed_digits = _tail_digits(normalized_typed)
                if typed_digits:
                    digit_matched = [
                        unit
                        for unit in contains
                        if _tail_digits(self._normalize_unit_name(unit)) == typed_digits
                    ]
                    if len(digit_matched) == 1:
                        return digit_matched[0]
                    if len(digit_matched) > 1:
                        contains = digit_matched

            scored = []
            for unit in contains or unit_pool:
                normalized_unit = self._normalize_unit_name(unit)
                if not normalized_unit:
                    continue
                score = difflib.SequenceMatcher(None, normalized_typed, normalized_unit).ratio()
                scored.append((score, unit))
            scored.sort(key=lambda item: item[0], reverse=True)
            if not scored:
                continue

            top_score, top_name = scored[0]
            second_score = scored[1][0] if len(scored) > 1 else 0.0
            if top_score >= 0.86 and (top_score - second_score) >= 0.08:
                return top_name
        return ""

    def _extract_existing_unit_from_modify_text(self, text: str, all_units: list[str]) -> str:
        source_text = (text or "").strip()
        if not source_text or not all_units:
            return ""
        action_match = self.MODIFY_VERB_PATTERN.search(source_text)
        if not action_match:
            return ""
        prefix = source_text[: action_match.start()]
        matches = [unit for unit in all_units if unit and unit in prefix]
        if not matches:
            return ""
        matches.sort(key=len, reverse=True)
        return matches[0]

    def _parse_by_db_terms(
        self,
        *,
        text: str,
        unit_pool: list[str],
        model_pool: list[str],
    ) -> dict[str, Any]:
        """
        基于 XCAGI 实际词条做轻量解析：
        - 单位：最长子串命中 purchase_units
        - 型号：优先命中 products.model_number
        - 规格/桶数：从“规格X”“X桶”抽取
        """
        raw = str(text or "").strip()
        if not raw:
            return {"success": False, "message": "订单文本为空", "unit_name": "", "products": []}

        def _pick_unit_name(source: str) -> str:
            hits = [u for u in unit_pool if u and u in source]
            if not hits:
                return ""
            hits.sort(key=len, reverse=True)
            return hits[0]

        def _pick_model_number(source: str) -> str:
            upper_source = source.upper()
            hits = [m for m in model_pool if m and m in upper_source]
            if not hits:
                return ""
            # 避免短型号误命中（如 980 命中 9803）
            hits.sort(key=len, reverse=True)
            return hits[0]

        unit_name = _pick_unit_name(raw)
        model_number = _pick_model_number(raw)

        m_spec = re.search(r"(?:规格|规)\s*[:：]?\s*(\d+(?:\.\d+)?)", raw)
        m_qty = re.search(r"(\d+(?:\.\d+)?)\s*桶", raw)
        if not m_qty:
            m_qty = re.search(r"(?:要|来|拿|共|一共|总共)\s*(\d+(?:\.\d+)?)", raw)

        tin_spec = float(m_spec.group(1)) if m_spec else None
        quantity_tins = int(float(m_qty.group(1))) if m_qty else None

        # 允许“9803 24 1桶”这类无“规格”关键词的口语输入。
        if tin_spec is None and model_number:
            number_tokens = re.findall(r"\d+(?:\.\d+)?", raw)
            filtered_tokens = []
            for token in number_tokens:
                if token.upper() == model_number:
                    continue
                if quantity_tins is not None and float(token) == float(quantity_tins):
                    continue
                filtered_tokens.append(token)
            if filtered_tokens:
                try:
                    tin_spec = float(filtered_tokens[0])
                except RECOVERABLE_ERRORS:
                    tin_spec = None

        if not (unit_name and model_number and tin_spec and quantity_tins):
            missing = []
            if not unit_name:
                missing.append("单位")
            if not model_number:
                missing.append("型号")
            if not tin_spec:
                missing.append("规格")
            if not quantity_tins:
                missing.append("桶数")
            return {
                "success": False,
                "message": f"DB词条解析未完整命中，缺少：{'、'.join(missing)}",
                "unit_name": unit_name,
                "products": [],
            }

        return {
            "success": True,
            "unit_name": unit_name,
            "products": [
                {
                    "product_name": model_number,
                    "model_number": model_number,
                    "quantity_tins": quantity_tins,
                    "tin_spec": tin_spec,
                }
            ],
            "message": "ok",
        }

    def _build_unit_not_found_payload(
        self, typed_unit: str, all_units: list[str]
    ) -> dict[str, Any]:
        typed = str(typed_unit or "").strip()
        if any(unit == typed for unit in all_units):
            return {}

        contains = [unit for unit in all_units if typed and (typed in unit or unit in typed)]
        fuzzy = difflib.get_close_matches(typed, all_units, n=5, cutoff=0.35) if typed else []
        suggestions: list[str] = []
        for unit in contains + fuzzy:
            if unit and unit not in suggestions:
                suggestions.append(unit)
            if len(suggestions) >= 5:
                break

        if suggestions:
            suggestion_text = "；".join(f"{idx + 1}){name}" for idx, name in enumerate(suggestions))
            message = (
                f"未找到购买单位：{typed}。"
                f"请确认单位名称后重试，或从候选中选择：{suggestion_text}。"
            )
        else:
            message = (
                f"未找到购买单位：{typed}。请先创建该购买单位，或输入已存在的单位名称后再生成。"
            )

        return {
            "success": False,
            "message": message,
            "error_code": "purchase_unit_not_found",
            "data": {
                "input_unit_name": typed,
                "candidate_units": suggestions,
                "need_confirm_unit": True,
            },
        }

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

        # 严格策略：所有主库匹配都限定在当前租户；名称模式还必须唯一地
        # 落在当前购买单位下，不能用全局/模糊产品结果替代。
        if not product_catalog:
            product_catalog = self._load_active_product_catalog()

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

            if not model_number:
                matched_product, resolution_error, related_rows = self._resolve_scoped_product_name(
                    product_name=product_name,
                    unit_name=unit_to_use,
                    product_catalog=product_catalog,
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

            if model_number:
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

        try:
            trusted_owner_user_id = int(owner_user_id) if owner_user_id is not None else 0
        except (TypeError, ValueError):
            trusted_owner_user_id = 0

        generate_kwargs: dict[str, Any] = {
            "unit_name": unit_to_use,
            "products": products,
            "template_name": (str(template_name or "").strip() or None),
            "template_id": (str(template_id or "").strip() or None),
            "preferred_template": (str(preferred_template or "").strip() or None),
            "order_number": (str(custom_order_number or "").strip() or None),
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
