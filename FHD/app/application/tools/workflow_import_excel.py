"""Excel → database import handlers (split from workflow.py).

Phase 4C structural split. Public/private symbols remain importable from
``app.application.tools.workflow`` via re-export for tests and Mod handlers.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from app.application.tools.workflow_excel_paths import resolve_safe_excel_path
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _parse_excel_header_row_1based(args: dict[str, Any]) -> int | None:
    """Delegate to workflow helpers (lazy) so patches on workflow still apply."""
    from app.application.tools.workflow import _parse_excel_header_row_1based as _impl

    return _impl(args)


def _read_excel_dataframe(
    p: Path,
    *,
    sheet_name: Any,
    header_row_1based: int | None,
) -> pd.DataFrame:
    from app.application.tools.workflow import _read_excel_dataframe as _impl

    return _impl(p, sheet_name=sheet_name, header_row_1based=header_row_1based)


def _handle_import_excel_to_database(
    args: dict[str, Any],
    workspace_root: str | None = None,
    db_write_token: str | None = None,
) -> str:
    """处理 Excel 导入数据库请求。"""
    _ = db_write_token

    try:
        import_type = str(args.get("import_type") or "products")
        file_path = str(args.get("file_path") or "").strip()
        sheet_n = args.get("sheet_name")

        req_ctx = args.get("context")
        if not isinstance(req_ctx, dict):
            req_ctx = {}
        excel_analysis_ctx = args.get("excel_analysis")
        if not isinstance(excel_analysis_ctx, dict):
            excel_analysis_ctx = req_ctx.get("excel_analysis")
        if not isinstance(excel_analysis_ctx, dict):
            excel_analysis_ctx = {}

        if not str(sheet_n or "").strip():
            selected = req_ctx.get("excel_analysis_selected_sheet")
            if isinstance(selected, dict):
                sn = str(selected.get("sheet_name") or "").strip()
                if sn:
                    sheet_n = sn
        if not str(sheet_n or "").strip():
            sn = str(req_ctx.get("preferred_sheet_name") or "").strip()
            if sn:
                sheet_n = sn
        if not str(sheet_n or "").strip():
            pd0 = excel_analysis_ctx.get("preview_data")
            if isinstance(pd0, dict):
                sn = str(pd0.get("sheet_name") or "").strip()
                if sn:
                    sheet_n = sn

        if not file_path:
            return json.dumps(
                {"success": False, "error": "file_path is required"}, ensure_ascii=False
            )

        import os

        required_token = str(os.environ.get("FHD_DB_WRITE_TOKEN") or "").strip()
        provided_token = str(args.get("db_write_token") or db_write_token or "").strip()
        if required_token and workspace_root is None:
            if not provided_token:
                return json.dumps(
                    {
                        "success": False,
                        "requires_token": True,
                        "token_name": "DB_WRITE_TOKEN",
                    },
                    ensure_ascii=False,
                )
            if provided_token != required_token:
                return json.dumps(
                    {"success": False, "error": "invalid_token"},
                    ensure_ascii=False,
                )

        p = resolve_safe_excel_path(workspace_root or str(Path.cwd()), file_path)
        if not p.exists():
            return json.dumps({"success": False, "error": "file not found"}, ensure_ascii=False)

        unit_name = str(args.get("unit_name") or "").strip()

        if not unit_name:
            unit_name = str(args.get("excel_customer_hint") or "").strip()
            if not unit_name:
                if req_ctx:
                    unit_name = str(req_ctx.get("excel_customer_hint") or "").strip()
            if not unit_name:
                if excel_analysis_ctx:
                    unit_name = str(
                        excel_analysis_ctx.get("customer_hint")
                        or (excel_analysis_ctx.get("preview_data") or {}).get("customer_hint")
                        or ""
                    ).strip()
            if not unit_name:
                try:
                    from app.application.template_grid_core import (
                        _extract_inline_customer_hits_from_cell,
                    )

                    linked_items: list[dict[str, Any]] = []
                    one = req_ctx.get("excel_linked_grid_preview")
                    if isinstance(one, dict):
                        linked_items.append(one)
                    many = req_ctx.get("excel_linked_grid_previews")
                    if isinstance(many, list):
                        linked_items.extend([x for x in many if isinstance(x, dict)])

                    for item in linked_items:
                        text = str(item.get("preview_text") or "").strip()
                        if text:
                            hits = _extract_inline_customer_hits_from_cell(text)
                            if hits:
                                unit_name = str(hits[0]).strip()
                                break
                except RECOVERABLE_ERRORS:
                    logger.debug("suppressed exception", exc_info=True)
            if not unit_name:
                try:
                    from app.application.template_grid_core import _extract_customer_hint_from_excel

                    unit_name = str(
                        _extract_customer_hint_from_excel(str(p), sheet_n if sheet_n else None)
                        or ""
                    ).strip()
                except RECOVERABLE_ERRORS:
                    logger.debug("suppressed exception", exc_info=True)

        preview_only = bool(args.get("preview_only", False))
        confirm = bool(args.get("confirm", True))
        if preview_only:
            confirm = False

        header_1b = _parse_excel_header_row_1based(args)
        if header_1b is None and excel_analysis_ctx:
            try:
                from app.domain.context.session_context import detected_excel_header_row_1based

                header_1b = detected_excel_header_row_1based(
                    excel_analysis_ctx,
                    preferred_sheet_name=str(sheet_n or "").strip() or None,
                )
            except RECOVERABLE_ERRORS:
                header_1b = None
        try:
            df = _read_excel_dataframe(p, sheet_name=sheet_n, header_row_1based=header_1b)
        except RECOVERABLE_ERRORS as e:
            return json.dumps(
                {
                    "success": False,
                    "error": f"read_excel_failed: {e}",
                    "sheet_name": sheet_n,
                    "header_row": header_1b,
                },
                ensure_ascii=False,
            )
        if df.empty:
            return json.dumps(
                {"success": False, "error": "Excel file is empty"}, ensure_ascii=False
            )

        price_column_hint = str(args.get("price_column") or "").strip() or None

        last_data = args.get("last_data_row_1based")
        try:
            last_data_i = (
                int(last_data) if last_data is not None and str(last_data).strip() != "" else None
            )
        except (TypeError, ValueError):
            last_data_i = None
        if last_data_i is not None and last_data_i >= 1:
            hdr_eff = header_1b if header_1b is not None else 1
            n_keep = last_data_i - hdr_eff
            if n_keep < 1:
                return json.dumps(
                    {
                        "success": False,
                        "error": "invalid_last_data_row",
                        "message": "last_data_row_1based 必须大于 header_row（或表头在第 1 行时大于 1）",
                        "header_row": hdr_eff,
                        "last_data_row_1based": last_data_i,
                    },
                    ensure_ascii=False,
                )
            df = df.iloc[:n_keep]

        columns = list(df.columns.astype(str))
        row_count = len(df)

        read_meta = {
            "sheet_name": sheet_n,
            "header_row": header_1b,
            "last_data_row_applied": last_data_i,
        }

        if import_type == "products":
            return _import_products_preview_or_execute(
                df,
                columns,
                unit_name,
                confirm,
                row_count,
                read_meta=read_meta,
                price_column_hint=price_column_hint,
            )
        elif import_type == "customers":
            return _import_customers_preview_or_execute(df, columns, confirm, row_count)
        elif import_type == "orders":
            return _import_orders_preview_or_execute(df, columns, unit_name, confirm, row_count)
        else:
            return json.dumps(
                {
                    "success": True,
                    "preview": True,
                    "import_type": import_type,
                    "columns": columns,
                    "row_count": row_count,
                    "sample_data": json.loads(
                        df.head(5).replace({float("nan"): None}).to_json(orient="records")
                    ),
                    "message": "未实现该类型的自动导入，请先导出为模板格式再导入。",
                },
                ensure_ascii=False,
            )

    except RECOVERABLE_ERRORS as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def _infer_product_field_mapping(
    columns: list[str],
    *,
    price_column_hint: str | None = None,
) -> dict[str, str]:
    """按列名推断产品字段映射。"""
    cols = [str(c) for c in columns]
    mapping: dict[str, str] = {}

    def _norm(s: str) -> str:
        return s.replace(" ", "").replace("\u3000", "").strip()

    norm_pairs = [(c, _norm(c)) for c in cols]
    taken: set[str] = set()

    def _take(field: str, col: str) -> None:
        if field not in mapping and col not in taken:
            mapping[field] = col
            taken.add(col)

    for c, cn in norm_pairs:
        cl = c.lower()
        if "规格" in cn and "号" not in cn and "编" not in cn:
            continue
        if ("编" in c and "号" in c) or "编号" in cn or "编码" in cn or "sku" in cl:
            _take("model_number", c)
            break
    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "型号" in c or "model" in cl:
            _take("model_number", c)
            break

    for c, cn in norm_pairs:
        if c in taken:
            continue
        if "规格" in c or "规格" in cn or ("规" in c and "格" in c):
            _take("specification", c)
            break

    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "产品名称" in cn or "品名" in cn or "名称" in c or "name" in cl:
            _take("name", c)
            break

    hint = _norm(price_column_hint) if price_column_hint else ""
    if hint:
        for c, cn in norm_pairs:
            if c in taken:
                continue
            cn_l = cn.lower()
            hl = hint.lower()
            if hint in cn or hl in cn_l or hint in c:
                _take("price", c)
                break

    if "price" not in mapping:
        price_order = [
            ("调价前", "price"),
            ("调价后", "price"),
            ("现价", "price"),
            ("单价", "price"),
            ("价格", "price"),
            ("price", "price"),
        ]
        for key_sub, field in price_order:
            ks = key_sub.lower()
            for c, cn in norm_pairs:
                if c in taken:
                    continue
                cn_l = cn.lower()
                if ks in cn_l or key_sub in c:
                    _take(field, c)
                    break
            if "price" in mapping:
                break

    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "单位" in c or "unit" in cl:
            _take("unit", c)
            break
    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "数量" in c or "quantity" in cl or "qty" in cl:
            _take("quantity", c)
            break
    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "备注" in c or "描述" in c or "description" in cl:
            _take("description", c)
            break
    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "品牌" in c or "brand" in cl:
            _take("brand", c)
            break
    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "类别" in c or "category" in cl or "分类" in c:
            _take("category", c)
            break

    return mapping


def _excel_cell_as_clean_str(val: Any) -> str:
    """pandas/Excel 单元格转展示用字符串；NaN、字面量 'nan' 视为空。"""
    if val is None:
        return ""
    if isinstance(val, bool):
        return ""
    try:
        if pd.isna(val):
            return ""
    except RECOVERABLE_ERRORS:
        pass
    if isinstance(val, float) and val != val:
        return ""
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        s = str(val).strip()
        if s.lower() in ("nan", "inf", "-inf"):
            return ""
        return s
    s = str(val).strip()
    if s.lower() in ("nan", "none", "null", "<na>", "nat"):
        return ""
    return s


def _excel_cell_as_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or (isinstance(val, float) and val != val):
            return default
        if pd.isna(val):
            return default
    except RECOVERABLE_ERRORS:
        pass
    try:
        v = float(val)
        if v != v:
            return default
        return v
    except (TypeError, ValueError):
        return default


# 报价单 / 合同表尾常见语句（命中则不作为产品行导入）
_CLAUSE_SUBSTRINGS = (
    "含税价",
    "含税",
    "月结",
    "数期",
    "担保",
    "付款责任",
    "保质保量",
    "验收签名",
    "所送货物",
    "若贵司",
    "未能按时付款",
    "配套使用",
    "我厂产品",
    "所示比例施工",
    "供应方签名",
    "供应方",
    "采购方",
    "盖章",
    "出资人",
    "签名及盖章",
    "以上价格为",
    "以上各种产品",
    "请严格按",
    "请配套",
)


def _looks_like_contract_or_footer_line(name: str) -> bool:
    t = (name or "").strip()
    if len(t) < 6:
        return False
    if any(s in t for s in _CLAUSE_SUBSTRINGS):
        return True
    # 「1、xxx」「2、xxx」式条款，且去掉序号后仍像说明句
    m = re.match(r"^\s*(\d+)[、．\.]\s*(.+)$", t)
    if m and len(m.group(2)) >= 8:
        rest = m.group(2)
        if any(s in rest for s in _CLAUSE_SUBSTRINGS):
            return True
        if re.search(r"(以上|所送|数期|保质|验收|付款|月结|含税|施工|配套|货物)", rest):
            return True
    return False


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
        return json.dumps(
            {
                "success": True,
                "preview": True,
                "import_type": "customers",
                "row_count": len(records),
                "sample_data": records[:5],
                "message": (
                    f"检测到 {len(records)} 条客户记录。"
                    f"当前为预览模式，传 confirm=true 或去掉 preview_only 可直接导入。"
                ),
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

        return json.dumps(
            {
                "success": True,
                "preview": False,
                "imported": imported,
                "failed": failed,
                "message": f"成功导入 {imported} 条客户，失败 {failed} 条",
            },
            ensure_ascii=False,
        )

    except RECOVERABLE_ERRORS as e:
        return json.dumps({"success": False, "error": f"导入失败: {str(e)}"}, ensure_ascii=False)


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


__all__ = [
    "_excel_cell_as_clean_str",
    "_excel_cell_as_float",
    "_handle_import_excel_to_database",
    "_import_customers_preview_or_execute",
    "_import_orders_preview_or_execute",
    "_import_products_preview_or_execute",
    "_infer_product_field_mapping",
    "_looks_like_contract_or_footer_line",
]
