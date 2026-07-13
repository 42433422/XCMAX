"""Product import preview and execution use case."""

from __future__ import annotations

import json
from typing import Any

from app.application.tools.workflow_import_mapping import (
    _excel_cell_as_clean_str,
    _excel_cell_as_float,
    _infer_product_field_mapping,
    _looks_like_contract_or_footer_line,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _import_products_preview_or_execute(
    df,
    columns,
    unit_name,
    confirm,
    row_count,
    *,
    read_meta: dict[str, Any] | None = None,
    price_column_hint: str | None = None,
):
    field_mapping = _infer_product_field_mapping(columns, price_column_hint=price_column_hint)

    detected_unit = unit_name
    if not detected_unit and "unit" in field_mapping:
        units = df[field_mapping["unit"]].dropna().astype(str).unique()
        if len(units) == 1:
            detected_unit = str(units[0]).strip()

    spec_col = field_mapping.get("specification")
    model_col = field_mapping.get("model_number")
    name_col = field_mapping.get("name")

    records: list[dict[str, Any]] = []
    skipped_clause_like = 0
    for _, row in df.iterrows():
        spec_val = ""
        if spec_col:
            spec_val = _excel_cell_as_clean_str(row.get(spec_col, ""))
        elif model_col:
            spec_val = _excel_cell_as_clean_str(row.get(model_col, ""))
        name_val = _excel_cell_as_clean_str(row.get(name_col, "")) if name_col else ""
        model_val = (
            _excel_cell_as_clean_str(row.get(field_mapping["model_number"], ""))
            if "model_number" in field_mapping
            else ""
        )
        if name_val and _looks_like_contract_or_footer_line(name_val):
            skipped_clause_like += 1
            continue
        qty_raw = row.get(field_mapping["quantity"], 0) if "quantity" in field_mapping else 0
        try:
            qf = _excel_cell_as_float(qty_raw, 0.0)
            qty_i = int(qf)
        except (TypeError, ValueError):
            qty_i = 0
        record = {
            "model_number": ((model_val or None) if "model_number" in field_mapping else None),
            "name": ((name_val or None) if name_col else None),
            "specification": spec_val or None,
            "price": (
                _excel_cell_as_float(row.get(field_mapping.get("price", ""), 0), 0.0)
                if "price" in field_mapping
                else 0.0
            ),
            "unit": detected_unit or unit_name or "件",
            "quantity": qty_i if "quantity" in field_mapping else 0,
            "description": (
                _excel_cell_as_clean_str(row.get(field_mapping["description"], "")) or None
                if "description" in field_mapping
                else None
            ),
            "brand": (
                _excel_cell_as_clean_str(row.get(field_mapping["brand"], "")) or None
                if "brand" in field_mapping
                else None
            ),
            "category": (
                _excel_cell_as_clean_str(row.get(field_mapping["category"], "")) or None
                if "category" in field_mapping
                else None
            ),
        }
        if record["name"]:
            records.append(record)

    if not confirm:
        payload = {
            "success": True,
            "preview": True,
            "import_type": "products",
            "detected_unit": detected_unit,
            "field_mapping": field_mapping,
            "row_count": len(records),
            "skipped_clause_like_rows": skipped_clause_like,
            "sample_data": records[:5],
            "message": (
                f"检测到 {len(records)} 条产品记录，绑定客户: {detected_unit or unit_name or '未指定'}。"
                + (
                    f" 已跳过疑似表尾条款行 {skipped_clause_like} 条。"
                    if skipped_clause_like
                    else ""
                )
                + "当前为预览模式，传 confirm=true 或去掉 preview_only 可直接导入。"
            ),
        }
        if read_meta:
            payload["read_options"] = read_meta
        return json.dumps(payload, ensure_ascii=False)

    try:
        from app.bootstrap import get_customer_app_service, get_products_service
        from app.services.unified_query_service import find_purchase_unit

        if detected_unit or unit_name:
            target_unit = detected_unit or unit_name
            if not find_purchase_unit(unit_name=target_unit):
                customer_service = get_customer_app_service()
                customer_service.create(
                    {
                        "customer_name": target_unit,
                        "contact_person": None,
                        "contact_phone": None,
                        "contact_address": None,
                    }
                )

        products_service = get_products_service()
        for record in records:
            record["unit"] = detected_unit or unit_name or "件"

        result = products_service.batch_add_products(records)

        imported = 0
        failed = 0
        if isinstance(result, dict):
            imported = int(result.get("success_count") or result.get("imported") or 0)
            failed = int(result.get("failed_count") or result.get("failed") or 0)
            if imported == 0 and failed == 0 and isinstance(result.get("data"), dict):
                nested = result["data"]
                imported = int(nested.get("success_count") or 0)
                failed = int(nested.get("failed_count") or 0)
        msg = (
            result.get("message")
            if isinstance(result, dict) and result.get("message")
            else f"成功导入 {imported} 条产品"
        )

        return json.dumps(
            {
                "success": True,
                "preview": False,
                "imported": imported,
                "failed": failed,
                "skipped_clause_like_rows": skipped_clause_like,
                "message": msg
                + (
                    f"（另跳过疑似条款/表尾行 {skipped_clause_like} 条）"
                    if skipped_clause_like
                    else ""
                ),
            },
            ensure_ascii=False,
        )

    except RECOVERABLE_ERRORS as e:
        return json.dumps({"success": False, "error": f"导入失败: {str(e)}"}, ensure_ascii=False)


__all__ = ["_import_products_preview_or_execute"]
