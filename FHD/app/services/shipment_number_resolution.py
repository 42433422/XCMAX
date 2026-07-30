from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Mapping
from typing import Any

from app.bootstrap import get_shipment_app_service
from app.db.models import Product
from app.db.session import get_db
from app.infrastructure.tenant_scope import apply_tenant_filter
from app.utils.mixin_module_sync import sync_mixin_methods
from app.utils.operational_errors import RECOVERABLE_ERRORS


class ShipmentNumberResolutionMixin:
    _PARENTHETICAL_UNIT_ALIAS_RE = re.compile(r"[（(][^）)]*[）)]")

    @staticmethod
    def _normalize_unit_name(value: str) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        text = ShipmentNumberResolutionMixin._PARENTHETICAL_UNIT_ALIAS_RE.sub("", text)
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

    @staticmethod
    def _resolve_owner_preview_product_candidate(
        *,
        owner_user_id: int,
        unit_name: str,
        product_name: str,
    ) -> tuple[str, dict[str, Any] | None]:
        """Read one authenticated user's ETL preview without weakening scope.

        The outcome deliberately separates ``not_found`` from ``conflict``.
        A missing private preview may use the tenant-local master catalogue;
        conflicting private preview facts must stop the confirmed shipment
        instead of silently accepting possibly stale master model/price data.
        """

        if owner_user_id <= 0 or not str(product_name or "").strip():
            return "not_requested", None
        try:
            from app.application.etl.shipment_preview_fallback import (
                resolve_preview_product_candidate_outcome,
            )

            outcome = resolve_preview_product_candidate_outcome(
                owner_user_id=owner_user_id,
                unit_name=unit_name,
                product_name=product_name,
            )
        except RECOVERABLE_ERRORS:
            return "unavailable", None

        if not isinstance(outcome, Mapping):
            return "unavailable", None
        status = str(outcome.get("status") or "").strip().lower()
        candidate = outcome.get("candidate")
        if status == "resolved" and isinstance(candidate, Mapping):
            return status, dict(candidate)
        if status in {"not_found", "conflict", "unavailable"}:
            return status, None
        return "unavailable", None

    @staticmethod
    def _preview_product_conflict_payload(
        *,
        parsed: dict[str, Any],
        unit_name: str,
        product_name: str,
    ) -> dict[str, Any]:
        """Return a stable, non-leaking failure for conflicting ETL facts."""

        return {
            "success": False,
            "message": (
                "编号模式解析失败，已按严格策略停止生成（未启用预览兜底）。 "
                f"失败原因：购买单位“{unit_name}”下的产品“{product_name}”存在冲突的 ETL 预演信息，"
                "请先在数据对接中心确认或修正后重试。"
            ),
            "error_code": "NUMBER_MODE_ETL_PREVIEW_CONFLICT",
            "data": {
                "parsed_data": parsed,
                "unit_name": unit_name,
                "product_name": product_name,
                "match_error_code": "NUMBER_MODE_ETL_PREVIEW_CONFLICT",
            },
        }

    def _load_active_product_catalog(self) -> list[dict[str, Any]]:
        """Load only the current tenant's active product rows."""

        # ``get_db`` commits when its context exits.  SQLAlchemy's default
        # session policy then expires ORM instances, so copying the catalogue
        # *after* this block would attempt a lazy refresh on detached Product
        # rows during a normal chat shipment confirmation.  Make a plain data
        # snapshot while the session is alive instead.
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
                        "name": str(
                            self._product_row_value(row, "name", tuple_index=1) or ""
                        ).strip(),
                        "unit": str(
                            self._product_row_value(row, "unit", tuple_index=2) or ""
                        ).strip(),
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

            # A shorter, user-facing customer name may safely point at one
            # longer canonical tenant name (for example ``七彩乐园`` ->
            # ``成都七彩乐园家具有限公司``).  The reverse is not safe: a
            # longer input that merely contains a canonical name can carry a
            # meaningful business qualifier (``金汉武三江源`` is not
            # automatically ``金汉武家私``).  Known parenthetical aliases are
            # normalized above before this comparison.
            short_alias_matches = [
                unit
                for unit in unit_pool
                if (
                    (normalized_unit := self._normalize_unit_name(unit))
                    and normalized_typed != normalized_unit
                    and normalized_typed in normalized_unit
                )
            ]
            if len(short_alias_matches) == 1:
                return short_alias_matches[0]
            if len(short_alias_matches) > 1:
                typed_digits = _tail_digits(normalized_typed)
                if typed_digits:
                    digit_matched = [
                        unit
                        for unit in short_alias_matches
                        if _tail_digits(self._normalize_unit_name(unit)) == typed_digits
                    ]
                    if len(digit_matched) == 1:
                        return digit_matched[0]
                    if len(digit_matched) > 1:
                        short_alias_matches = digit_matched

            # Do not allow fuzzy matching to re-introduce the rejected
            # canonical-substring direction above.  The remaining candidates
            # preserve the historical typo-tolerance without swallowing a
            # longer, qualified customer name.
            score_pool = short_alias_matches or [
                unit
                for unit in unit_pool
                if (
                    (normalized_unit := self._normalize_unit_name(unit))
                    and not (
                        normalized_unit != normalized_typed and normalized_unit in normalized_typed
                    )
                )
            ]
            scored = []
            for unit in score_pool:
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


sync_mixin_methods(
    ShipmentNumberResolutionMixin,
    target=globals(),
    source_module="app.services.shipment_number_mode_service",
    method_names=(
        "_normalize_unit_name",
        "_normalize_product_name",
        "_product_row_value",
        "_resolve_owner_preview_product_candidate",
        "_preview_product_conflict_payload",
        "_load_active_product_catalog",
        "_resolve_scoped_product_name",
        "_resolve_scoped_product_model",
        "_query_active_purchase_unit_names",
        "_resolve_unit_alias",
        "_extract_existing_unit_from_modify_text",
        "_parse_by_db_terms",
        "_build_unit_not_found_payload",
    ),
)
