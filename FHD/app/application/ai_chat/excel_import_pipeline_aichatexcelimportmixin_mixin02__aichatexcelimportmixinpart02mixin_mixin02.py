# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_chat.excel_import_pipeline")


class __AIChatExcelImportMixinPart02MixinPart02Mixin:
    def _extract_excel_import_records(
        self,
        excel_analysis: dict[str, _facade().Any],
        request_context: dict[str, _facade().Any] | None = None,
        *,
        user_message: str = "",
    ) -> tuple[list[dict[str, _facade().Any]], str | None]:
        preview_data = (
            excel_analysis.get("preview_data")
            if isinstance(excel_analysis.get("preview_data"), dict)
            else {}
        )
        preview_data = preview_data or {}
        records: list[dict[str, _facade().Any]] = []
        reloaded = self._try_structured_reload_records(
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
                        item: dict[str, _facade().Any] = {}
                        for idx, key in enumerate(header_keys):
                            if not key:
                                continue
                            item[key] = row[idx] if idx < len(row) else None
                        if any(str(v or "").strip() for v in item.values()):
                            records.append(item)
        if records:
            first = records[0]
            if isinstance(first, dict):
                keys = list(first.keys())
                key_unnamed_ratio = 0.0
                if keys:
                    unnamed_count = sum(1 for k in keys if str(k).startswith("Unnamed:"))
                    key_unnamed_ratio = unnamed_count / len(keys)
                header_values = [str(first.get(k) or "").strip() for k in keys]
                label_like_ratio = len(
                    [v for v in header_values if v and (not self._is_number_text(v))]
                ) / float(len(header_values) or 1)
                headerish = self._row_values_look_like_table_headers(header_values)
                should_promote = len(records) >= 2 and (
                    key_unnamed_ratio >= 0.5
                    and label_like_ratio >= 0.5
                    or (key_unnamed_ratio >= 0.35 and headerish)
                )
                if should_promote:
                    rebuilt: list[dict[str, _facade().Any]] = []
                    for row in records[1:]:
                        if not isinstance(row, dict):
                            continue
                        mapped: dict[str, _facade().Any] = {}
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
            {k: self._sanitize_import_scalar(v) for k, v in r.items()} if isinstance(r, dict) else r
            for r in records
        ]
        if not records:
            return ([], None)
        inferred_roles, role_conf = self._infer_excel_column_roles(records)
        if role_conf < 0.55:
            llm_roles = self._infer_excel_column_roles_with_llm(records)
            for role in ("unit_name", "product_name", "model_number", "unit_price"):
                if llm_roles.get(role):
                    inferred_roles[role] = llm_roles[role]
        header_roles = self._header_hint_column_roles(
            [str(k).strip() for k in records[0].keys()] if records else []
        )
        for role in ("unit_name", "product_name", "model_number", "unit_price"):
            hk = str(header_roles.get(role) or "").strip()
            if hk:
                inferred_roles[role] = hk
        keys = [str(k).strip() for k in records[0].keys() if str(k).strip()]
        merged_intent = self._merge_user_intent_for_price_resolution(user_message, request_context)
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
            return ([], price_err)
        inferred_roles["unit_price"] = price_col
        unit_key = inferred_roles.get("unit_name", "")
        product_key = inferred_roles.get("product_name", "")
        model_key = inferred_roles.get("model_number", "")
        price_key = inferred_roles.get("unit_price", "")
        default_unit = self._default_purchase_unit_for_import(
            excel_analysis, preview_data, request_context
        )
        _facade().logger.debug(
            "[导入调试] _default_purchase_unit_for_import 返回: %s (request_context keys: %s)",
            repr(default_unit),
            list(request_context.keys())
            if isinstance(request_context, dict)
            else type(request_context).__name__,
        )
        if unit_key:
            col_vals = [str((row or {}).get(unit_key) or "").strip() for row in records]
            if self._packaging_or_measure_ratio(col_vals) >= 0.45:
                unit_key = ""
        if unit_key and unit_key == product_key:
            unit_key = ""
        if unit_key and product_key and (unit_key == model_key):
            unit_key = ""
        reserved_cols = {c for c in (unit_key, product_key, model_key, price_key) if c}
        if not product_key:
            fb_name = self._fallback_excel_product_name_column(records, reserved_cols)
            if fb_name:
                product_key = fb_name
                reserved_cols.add(fb_name)
        if not model_key:
            fb_model = self._fallback_excel_model_number_column(records, reserved_cols)
            if fb_model:
                model_key = fb_model
        dedup: set[tuple[str, str, str]] = set()
        normalized: list[dict[str, _facade().Any]] = []
        for row in records:
            unit_name = str((row or {}).get(unit_key) or "").strip() if unit_key else ""
            if (
                not unit_name
                and default_unit
                or (
                    default_unit
                    and unit_name
                    and self._excel_cell_looks_like_product_measure_unit(unit_name)
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
            except _facade().RECOVERABLE_ERRORS:
                unit_price = 0.0
            if not unit_name:
                continue
            if not product_name and (not model_number):
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
        return (normalized, None)

    @staticmethod
    def _excel_analysis_payload_present(context: dict[str, _facade().Any] | None) -> bool:
        """请求里是否带有可用的 excel_analysis（与 extract-grid 结构一致）。"""
        ea = (context or {}).get("excel_analysis") if isinstance(context, dict) else None
        if not isinstance(ea, dict) or not ea:
            return False
        if str(ea.get("summary") or "").strip():
            return True
        fields = ea.get("fields")
        if isinstance(fields, list) and len(fields) > 0:
            return True
        pd = ea.get("preview_data") if isinstance(ea.get("preview_data"), dict) else {}
        if not isinstance(pd, dict):
            pd = {}
        if isinstance(pd.get("sample_rows"), list) and len(pd.get("sample_rows") or []) > 0:
            return True
        grid = (pd.get("grid_preview") or {}).get("rows") if isinstance(pd, dict) else None
        return isinstance(grid, list) and len(grid) >= 2

    @staticmethod
    def _looks_like_short_excel_import_command(text: str) -> bool:
        """
        用户常用短指令（如「加入数据库」）。无 excel_analysis 时若落入 DeepSeek / planner 会长时间无响应。
        """
        t = str(text or "").strip()
        if not t:
            return False
        exact = {"加入数据库", "加入库", "入库", "添加到库", "写入数据库", "导入数据库"}
        if t in exact:
            return True
        if len(t) > 40:
            return False
        return any(k in t for k in ("加入数据库", "导入数据库", "添加到库", "写入数据库"))

    @staticmethod
    def _looks_like_explicit_workflow_tool_intent(text: str) -> bool:
        return _facade().looks_like_explicit_workflow_tool_intent(text)

    @staticmethod
    def _looks_like_smart_workflow_intent(
        text: str, context: dict[str, _facade().Any] | None = None
    ) -> bool:
        """Whether a non-pro chat turn should be allowed into executable planning.

        This keeps casual chat on the lightweight path, but lets ordinary
        desktop/mobile chat use the same agentic tool routing as pro mode for
        concrete tool/data/employee/file requests.
        """
        t = str(text or "").strip()
        if not t:
            return False
        if _facade().AIChatExcelImportMixin._looks_like_explicit_workflow_tool_intent(t):
            return True
        ctx = context if isinstance(context, dict) else {}
        for key in (
            "excel_analysis",
            "file_analysis",
            "file_context",
            "multimodal_attachments",
            "attachments",
            "files",
            "artifacts",
            "ocr",
            "ocr_result",
            "excel_index_id",
            "excel_vector_index_id",
        ):
            if ctx.get(key):
                return True
        lower = t.lower()
        controlled_db = any(
            k in t
            for k in (
                "数据库",
                "查库",
                "读库",
                "写库",
                "业务库",
                "产品库",
                "客户库",
                "物料库",
                "原材料",
                "发货记录",
                "出货记录",
            )
        ) or any(k in lower for k in ("database", " db ", "business_db", "products table"))
        controlled_action = any(
            k in t
            for k in (
                "查",
                "查询",
                "读取",
                "统计",
                "多少",
                "几条",
                "列出",
                "新增",
                "添加",
                "写入",
                "更新",
                "删除",
                "导入",
                "入库",
            )
        ) or any(k in lower for k in ("read", "query", "count", "list", "write", "update"))
        if controlled_db and controlled_action:
            return True
        employee_request = any(k in t for k in ("员工", "超级员工", "调用", "交给", "执行")) or any(
            k in lower for k in ("employee", "agent", "run", "execute")
        )
        if employee_request and any(k in t for k in ("员工", "超级员工", "调用", "交给")):
            return True
        return False
