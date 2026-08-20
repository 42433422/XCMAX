# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.tools.workflow")


def _looks_like_contract_or_footer_line(name: str) -> bool:
    t = (name or "").strip()
    if len(t) < 6:
        return False
    if any(s in t for s in _facade()._CLAUSE_SUBSTRINGS):
        return True
    m = _facade().re.match("^\\s*(\\d+)[、．\\.]\\s*(.+)$", t)
    if m and len(m.group(2)) >= 8:
        rest = m.group(2)
        if any(s in rest for s in _facade()._CLAUSE_SUBSTRINGS):
            return True
        if _facade().re.search("(以上|所送|数期|保质|验收|付款|月结|含税|施工|配套|货物)", rest):
            return True
    return False


def _import_products_preview_or_execute(
    df,
    columns,
    unit_name,
    confirm,
    row_count,
    *,
    read_meta: dict[str, _facade().Any] | None = None,
    price_column_hint: str | None = None,
):
    field_mapping = _facade()._infer_product_field_mapping(
        columns, price_column_hint=price_column_hint
    )
    detected_unit = unit_name
    if not detected_unit and "unit" in field_mapping:
        units = df[field_mapping["unit"]].dropna().astype(str).unique()
        if len(units) == 1:
            detected_unit = str(units[0]).strip()
    spec_col = field_mapping.get("specification")
    model_col = field_mapping.get("model_number")
    name_col = field_mapping.get("name")
    records: list[dict[str, _facade().Any]] = []
    skipped_clause_like = 0
    for _, row in df.iterrows():
        spec_val = ""
        if spec_col:
            spec_val = _facade()._excel_cell_as_clean_str(row.get(spec_col, ""))
        elif model_col:
            spec_val = _facade()._excel_cell_as_clean_str(row.get(model_col, ""))
        name_val = _facade()._excel_cell_as_clean_str(row.get(name_col, "")) if name_col else ""
        model_val = (
            _facade()._excel_cell_as_clean_str(row.get(field_mapping["model_number"], ""))
            if "model_number" in field_mapping
            else ""
        )
        if name_val and _facade()._looks_like_contract_or_footer_line(name_val):
            skipped_clause_like += 1
            continue
        qty_raw = row.get(field_mapping["quantity"], 0) if "quantity" in field_mapping else 0
        try:
            qf = _facade()._excel_cell_as_float(qty_raw, 0.0)
            qty_i = int(qf)
        except (TypeError, ValueError):
            qty_i = 0
        record = {
            "model_number": model_val or None if "model_number" in field_mapping else None,
            "name": name_val or None if name_col else None,
            "specification": spec_val or None,
            "price": _facade()._excel_cell_as_float(row.get(field_mapping.get("price", ""), 0), 0.0)
            if "price" in field_mapping
            else 0.0,
            "unit": detected_unit or unit_name or "件",
            "quantity": qty_i if "quantity" in field_mapping else 0,
            "description": _facade()._excel_cell_as_clean_str(
                row.get(field_mapping["description"], "")
            )
            or None
            if "description" in field_mapping
            else None,
            "brand": _facade()._excel_cell_as_clean_str(row.get(field_mapping["brand"], "")) or None
            if "brand" in field_mapping
            else None,
            "category": _facade()._excel_cell_as_clean_str(row.get(field_mapping["category"], ""))
            or None
            if "category" in field_mapping
            else None,
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
            "message": f"检测到 {len(records)} 条产品记录，绑定客户: {detected_unit or unit_name or '未指定'}。"
            + (f" 已跳过疑似表尾条款行 {skipped_clause_like} 条。" if skipped_clause_like else "")
            + "当前为预览模式，传 confirm=true 或去掉 preview_only 可直接导入。",
        }
        if read_meta:
            payload["read_options"] = read_meta
        return _facade().json.dumps(payload, ensure_ascii=False)
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
        msg = str(
            result.get("message")
            if isinstance(result, dict) and result.get("message")
            else f"成功导入 {imported} 条产品"
        )
        return _facade().json.dumps(
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
    except _facade().RECOVERABLE_ERRORS:
        return _facade().json.dumps(
            {"success": False, "error": "产品导入失败，请检查文件后重试"},
            ensure_ascii=False,
        )


def _import_customers_preview_or_execute(df, columns, confirm, row_count):
    records = []
    for _, row in df.iterrows():
        record = {}
        for col in columns:
            col_l = col.lower()
            val = str(row.get(col, "")).strip()
            if "名称" in col or "name" in col_l or "客户" in col:
                record["customer_name"] = val
            elif "联系人" in col or "contact" in col_l or "person" in col_l:
                record["contact_person"] = val
            elif "电话" in col or "phone" in col_l or "mobile" in col_l:
                record["contact_phone"] = val
            elif "地址" in col or "address" in col_l:
                record["contact_address"] = val
        if record.get("customer_name"):
            records.append(record)
    if not confirm:
        return _facade().json.dumps(
            {
                "success": True,
                "preview": True,
                "import_type": "customers",
                "row_count": len(records),
                "sample_data": records[:5],
                "message": f"检测到 {len(records)} 条客户记录。当前为预览模式，传 confirm=true 或去掉 preview_only 可直接导入。",
            },
            ensure_ascii=False,
        )
    try:
        from app.bootstrap import get_customer_app_service

        customer_service = get_customer_app_service()
        imported = 0
        failed = 0
        for record in records:
            result = customer_service.create(record)
            if result.get("success"):
                imported += 1
            else:
                failed += 1
        return _facade().json.dumps(
            {
                "success": True,
                "preview": False,
                "imported": imported,
                "failed": failed,
                "message": f"成功导入 {imported} 条客户，失败 {failed} 条",
            },
            ensure_ascii=False,
        )
    except _facade().RECOVERABLE_ERRORS:
        return _facade().json.dumps(
            {"success": False, "error": "客户导入失败，请检查文件后重试"},
            ensure_ascii=False,
        )


def _import_orders_preview_or_execute(df, columns, unit_name, confirm, row_count):
    """从 Excel 导入出货记录（订单）。"""
    sample_data = _facade().json.loads(
        df.head(5).replace({float("nan"): None}).to_json(orient="records")
    )
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
        return _facade().json.dumps(
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
                        row.get(next((c for (c, f) in col_map.items() if f == "unit_name"), ""), "")
                        or ""
                    ).strip()
                )
                if not effective_unit:
                    failed += 1
                    continue
                product_name = str(
                    row.get(next((c for (c, f) in col_map.items() if f == "product_name"), ""), "")
                    or ""
                ).strip()
                model_number = str(
                    row.get(next((c for (c, f) in col_map.items() if f == "model_number"), ""), "")
                    or ""
                ).strip()
                qty_raw = row.get(next((c for (c, f) in col_map.items() if f == "quantity"), ""), 1)
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
            except _facade().RECOVERABLE_ERRORS:
                failed += 1
        return _facade().json.dumps(
            {
                "success": True,
                "preview": False,
                "imported": imported,
                "failed": failed,
                "message": f"成功导入 {imported} 条出货记录，失败 {failed} 条",
            },
            ensure_ascii=False,
        )
    except _facade().RECOVERABLE_ERRORS:
        return _facade().json.dumps(
            {"success": False, "error": "订单导入失败，请检查文件后重试"},
            ensure_ascii=False,
        )
