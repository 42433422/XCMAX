"""Record extraction and normalization for Excel imports."""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class ExcelImportRecordExtractor:
    def __init__(
        self,
        *,
        context_resolver: Any,
        column_inferer: Any,
        price_resolver: Any,
        resolve_unit_price_column: Callable[..., tuple[str, str | None]],
        is_number_text: Callable[[str], bool],
        row_values_look_like_table_headers: Callable[[list[str]], bool],
    ) -> None:
        self._context = context_resolver
        self._columns = column_inferer
        self._prices = price_resolver
        self._resolve_unit_price_column = resolve_unit_price_column
        self._is_number_text = is_number_text
        self._row_values_look_like_table_headers = row_values_look_like_table_headers

    def _extract_excel_import_records(
        self,
        excel_analysis: dict[str, Any],
        request_context: dict[str, Any] | None = None,
        *,
        user_message: str = "",
    ) -> tuple[list[dict[str, Any]], str | None]:
        preview_data = (
            excel_analysis.get("preview_data")
            if isinstance(excel_analysis.get("preview_data"), dict)
            else {}
        )
        preview_data = preview_data or {}
        records: list[dict[str, Any]] = []

        reloaded = self._context._try_structured_reload_records(
            excel_analysis, preview_data, request_context
        )
        if reloaded:
            records = reloaded
        else:
            sample_rows = preview_data.get("sample_rows") or []
            if isinstance(sample_rows, list):
                for row in sample_rows:
                    if isinstance(row, dict):
                        records.append(dict(row))

            grid_rows = (preview_data.get("grid_preview") or {}).get("rows") or []
            if isinstance(grid_rows, list) and len(grid_rows) >= 2:
                header = grid_rows[0]
                if isinstance(header, list):
                    header_keys = [str(h or "").strip() for h in header]
                    for row in grid_rows[1:]:
                        if not isinstance(row, list):
                            continue
                        item: dict[str, Any] = {}
                        for idx, key in enumerate(header_keys):
                            if not key:
                                continue
                            item[key] = row[idx] if idx < len(row) else None
                        if any(str(v or "").strip() for v in item.values()):
                            records.append(item)

        # 某些表格第一行是“真实表头”，但被解析为数据行（键名为 Unnamed:*）
        if records:
            first = records[0]
            if isinstance(first, dict):
                keys = list(first.keys())
                key_unnamed_ratio = 0.0
                if keys:
                    unnamed_count = sum(1 for k in keys if str(k).startswith("Unnamed:"))
                    key_unnamed_ratio = unnamed_count / len(keys)
                header_values = [str(first.get(k) or "").strip() for k in keys]
                label_like_ratio = sum(
                    1 for v in header_values if v and not self._is_number_text(v)
                ) / float(len(header_values) or 1)
                headerish = self._row_values_look_like_table_headers(header_values)
                should_promote = len(records) >= 2 and (
                    (key_unnamed_ratio >= 0.5 and label_like_ratio >= 0.5)
                    or (key_unnamed_ratio >= 0.35 and headerish)
                )
                if should_promote:
                    rebuilt: list[dict[str, Any]] = []
                    for row in records[1:]:
                        if not isinstance(row, dict):
                            continue
                        mapped: dict[str, Any] = {}
                        for idx, key in enumerate(keys):
                            header = header_values[idx] if idx < len(header_values) else ""
                            if not header:
                                continue
                            mapped[header] = row.get(key)
                        if any(str(v or "").strip() for v in mapped.values()):
                            rebuilt.append(mapped)
                    if rebuilt:
                        records = rebuilt

        records = [
            (
                {k: self._context._sanitize_import_scalar(v) for k, v in r.items()}
                if isinstance(r, dict)
                else r
            )
            for r in records
        ]

        if not records:
            return [], None

        inferred_roles, role_conf = self._columns._infer_excel_column_roles(records)
        if role_conf < 0.55:
            llm_roles = self._columns._infer_excel_column_roles_with_llm(records)
            # 低置信度时优先采用 LLM 非空结果，空值回退特征推断
            for role in ("unit_name", "product_name", "model_number", "unit_price"):
                if llm_roles.get(role):
                    inferred_roles[role] = llm_roles[role]

        header_roles = self._columns._header_hint_column_roles(
            [str(k).strip() for k in records[0].keys()] if records else []
        )
        for role in ("unit_name", "product_name", "model_number", "unit_price"):
            hk = str(header_roles.get(role) or "").strip()
            if hk:
                inferred_roles[role] = hk

        keys = [str(k).strip() for k in records[0].keys() if str(k).strip()]
        merged_intent = self._prices._merge_user_intent_for_price_resolution(
            user_message, request_context
        )
        overrides = (
            request_context.get("excel_import_column_overrides")
            if isinstance(request_context, dict)
            else None
        )
        cur_price = str(inferred_roles.get("unit_price") or "").strip()
        price_col, price_err = self._resolve_unit_price_column(
            keys, cur_price, merged_intent, overrides if isinstance(overrides, dict) else {}
        )
        if price_err:
            return [], price_err
        inferred_roles["unit_price"] = price_col

        unit_key = inferred_roles.get("unit_name", "")
        product_key = inferred_roles.get("product_name", "")
        model_key = inferred_roles.get("model_number", "")
        price_key = inferred_roles.get("unit_price", "")

        default_unit = self._context._default_purchase_unit_for_import(
            excel_analysis, preview_data, request_context
        )
        logger.debug(
            "[导入调试] _default_purchase_unit_for_import 返回: %s (request_context keys: %s)",
            repr(default_unit),
            (
                list(request_context.keys())
                if isinstance(request_context, dict)
                else type(request_context).__name__
            ),
        )
        if unit_key:
            col_vals = [str((row or {}).get(unit_key) or "").strip() for row in records]
            if self._columns._packaging_or_measure_ratio(col_vals) >= 0.45:
                unit_key = ""
        if unit_key and unit_key == product_key:
            unit_key = ""
        if unit_key and product_key and unit_key == model_key:
            unit_key = ""

        reserved_cols = {c for c in (unit_key, product_key, model_key, price_key) if c}
        if not product_key:
            fb_name = self._columns._fallback_excel_product_name_column(records, reserved_cols)
            if fb_name:
                product_key = fb_name
                reserved_cols.add(fb_name)
        if not model_key:
            fb_model = self._columns._fallback_excel_model_number_column(records, reserved_cols)
            if fb_model:
                model_key = fb_model

        dedup: set[tuple[str, str, str]] = set()
        normalized: list[dict[str, Any]] = []
        for row in records:
            unit_name = str((row or {}).get(unit_key) or "").strip() if unit_key else ""
            if (
                not unit_name
                and default_unit
                or (
                    default_unit
                    and unit_name
                    and self._context._excel_cell_looks_like_product_measure_unit(unit_name)
                )
            ):
                unit_name = default_unit.strip()
            product_name = str((row or {}).get(product_key) or "").strip() if product_key else ""
            model_number = (
                str((row or {}).get(model_key) or "").strip().upper() if model_key else ""
            )
            price_text = str((row or {}).get(price_key) or "").strip() if price_key else ""
            try:
                unit_price = float(price_text) if price_text else 0.0
            except RECOVERABLE_ERRORS:
                unit_price = 0.0
            if not unit_name:
                continue
            if not product_name and not model_number:
                continue
            dedup_key = (unit_name, product_name, model_number)
            if dedup_key in dedup:
                continue
            dedup.add(dedup_key)
            normalized.append(
                {
                    "unit_name": unit_name,
                    "product_name": product_name or model_number,
                    "model_number": model_number,
                    "unit_price": unit_price,
                }
            )
        return normalized, None


__all__ = ["ExcelImportRecordExtractor"]
