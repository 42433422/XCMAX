"""Shipment-order import preview and execution use case."""

from __future__ import annotations

import json

from app.utils.operational_errors import RECOVERABLE_ERRORS


def _import_orders_preview_or_execute(df, columns, unit_name, confirm, row_count):
    """从 Excel 导入出货记录（订单）。"""
    sample_data = json.loads(df.head(5).replace({float("nan"): None}).to_json(orient="records"))
    # 推断列映射
    col_map: dict[str, str] = {}
    name_hints = {
        "产品名称": "product_name",
        "product_name": "product_name",
        "名称": "product_name",
    }
    model_hints = {
        "型号": "model_number",
        "model_number": "model_number",
        "产品型号": "model_number",
    }
    qty_hints = {
        "数量": "quantity",
        "quantity": "quantity",
        "qty": "quantity",
        "数量(桶)": "quantity",
    }
    unit_name_hints = {"购买单位": "unit_name", "客户": "unit_name", "purchase_unit": "unit_name"}
    for col in columns:
        col_lower = str(col).strip().lower()
        if col in name_hints or col_lower in {k.lower() for k in name_hints}:
            col_map[col] = "product_name"
        elif col in model_hints or col_lower in {k.lower() for k in model_hints}:
            col_map[col] = "model_number"
        elif col in qty_hints or col_lower in {k.lower() for k in qty_hints}:
            col_map[col] = "quantity"
        elif col in unit_name_hints or col_lower in {k.lower() for k in unit_name_hints}:
            col_map[col] = "unit_name"

    if not confirm:
        return json.dumps(
            {
                "success": True,
                "preview": True,
                "import_type": "orders",
                "columns": columns,
                "column_mapping": col_map,
                "row_count": row_count,
                "sample_data": sample_data,
                "message": f"检测到 {row_count} 条出货记录，确认导入请设置 confirm=true。",
            },
            ensure_ascii=False,
        )

    try:
        from app.bootstrap import get_shipment_app_service

        svc = get_shipment_app_service()
        imported = 0
        failed = 0
        for _, row in df.iterrows():
            try:
                effective_unit = (
                    unit_name
                    or str(
                        row.get(next((c for c, f in col_map.items() if f == "unit_name"), ""), "")
                        or ""
                    ).strip()
                )
                if not effective_unit:
                    failed += 1
                    continue
                product_name = str(
                    row.get(next((c for c, f in col_map.items() if f == "product_name"), ""), "")
                    or ""
                ).strip()
                model_number = str(
                    row.get(next((c for c, f in col_map.items() if f == "model_number"), ""), "")
                    or ""
                ).strip()
                qty_raw = row.get(next((c for c, f in col_map.items() if f == "quantity"), ""), 1)
                qty = max(1, int(float(qty_raw))) if qty_raw else 1
                items = [
                    {
                        "product_name": product_name or model_number,
                        "model_number": model_number,
                        "quantity": qty,
                    }
                ]
                result = svc.create_shipment(unit_name=effective_unit, items_data=items)
                if result.get("success"):
                    imported += 1
                else:
                    failed += 1
            except RECOVERABLE_ERRORS:
                failed += 1

        return json.dumps(
            {
                "success": True,
                "preview": False,
                "imported": imported,
                "failed": failed,
                "message": f"成功导入 {imported} 条出货记录，失败 {failed} 条",
            },
            ensure_ascii=False,
        )
    except RECOVERABLE_ERRORS as e:
        return json.dumps(
            {"success": False, "error": f"订单导入失败: {str(e)}"}, ensure_ascii=False
        )


__all__ = ["_import_orders_preview_or_execute"]
