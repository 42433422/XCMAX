# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.tools.workflow")


def _resolve_new_tool_dispatch(name: str) -> _facade().Any:
    """惰性解析新工具执行器；首次调用时统一 import 全部新工具模块并缓存映射。"""
    global _NEW_TOOL_DISPATCH_CACHE
    if _facade()._NEW_TOOL_DISPATCH_CACHE is None:
        try:
            from app.application.tools.customer_crud_tools import (
                delete_customer,
                list_customers,
                update_customer,
            )
            from app.application.tools.rbac_tools import (
                assign_role,
                create_role,
                delete_role,
                list_roles,
                update_role,
            )
            from app.application.tools.report_config_tools import (
                configure_report,
                list_report_configs,
            )
            from app.application.tools.shipment_crud_tools import (
                delete_order,
                list_orders,
                update_order,
            )

            _facade()._NEW_TOOL_DISPATCH_CACHE = {
                "delete_order": delete_order,
                "update_order": update_order,
                "list_orders": list_orders,
                "update_customer": update_customer,
                "delete_customer": delete_customer,
                "list_customers": list_customers,
                "configure_report": configure_report,
                "list_report_configs": list_report_configs,
                "create_role": create_role,
                "update_role": update_role,
                "delete_role": delete_role,
                "assign_role": assign_role,
                "list_roles": list_roles,
            }
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug("new tool dispatch init failed", exc_info=True)
            _facade()._NEW_TOOL_DISPATCH_CACHE = {}
    return (
        _facade()._NEW_TOOL_DISPATCH_CACHE.get(name) if _facade()._NEW_TOOL_DISPATCH_CACHE else None
    )


def _handle_import_excel_to_database(
    args: dict[str, _facade().Any],
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
            return _facade().json.dumps(
                {"success": False, "error": "file_path is required"}, ensure_ascii=False
            )
        import os

        required_token = str(os.environ.get("FHD_DB_WRITE_TOKEN") or "").strip()
        provided_token = str(args.get("db_write_token") or db_write_token or "").strip()
        if required_token and workspace_root is None:
            if not provided_token:
                return _facade().json.dumps(
                    {"success": False, "requires_token": True, "token_name": "DB_WRITE_TOKEN"},
                    ensure_ascii=False,
                )
            if provided_token != required_token:
                return _facade().json.dumps(
                    {"success": False, "error": "invalid_token"}, ensure_ascii=False
                )
        p = _facade().resolve_safe_excel_path(
            workspace_root or str(_facade().Path.cwd()), file_path
        )
        if not p.exists():
            return _facade().json.dumps(
                {"success": False, "error": "file not found"}, ensure_ascii=False
            )
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

                    linked_items: list[dict[str, _facade().Any]] = []
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
                except _facade().RECOVERABLE_ERRORS:
                    _facade().logger.debug("suppressed exception", exc_info=True)
            if not unit_name:
                try:
                    from app.application.template_grid_core import _extract_customer_hint_from_excel

                    unit_name = str(
                        _extract_customer_hint_from_excel(str(p), sheet_n if sheet_n else None)
                        or ""
                    ).strip()
                except _facade().RECOVERABLE_ERRORS:
                    _facade().logger.debug("suppressed exception", exc_info=True)
        preview_only = bool(args.get("preview_only", False))
        confirm = bool(args.get("confirm", True))
        if preview_only:
            confirm = False
        header_1b = _facade()._parse_excel_header_row_1based(args)
        if header_1b is None and excel_analysis_ctx:
            try:
                from app.domain.context.session_context import detected_excel_header_row_1based

                header_1b = detected_excel_header_row_1based(
                    excel_analysis_ctx, preferred_sheet_name=str(sheet_n or "").strip() or None
                )
            except _facade().RECOVERABLE_ERRORS:
                header_1b = None
        try:
            df = _facade()._read_excel_dataframe(p, sheet_name=sheet_n, header_row_1based=header_1b)
        except _facade().RECOVERABLE_ERRORS as e:
            return _facade().json.dumps(
                {
                    "success": False,
                    "error": f"read_excel_failed: {e}",
                    "sheet_name": sheet_n,
                    "header_row": header_1b,
                },
                ensure_ascii=False,
            )
        if df.empty:
            return _facade().json.dumps(
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
                return _facade().json.dumps(
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
            return _facade().cast(
                "str",
                _facade()._import_products_preview_or_execute(
                    df,
                    columns,
                    unit_name,
                    confirm,
                    row_count,
                    read_meta=read_meta,
                    price_column_hint=price_column_hint,
                ),
            )
        elif import_type == "customers":
            return _facade().cast(
                "str",
                _facade()._import_customers_preview_or_execute(df, columns, confirm, row_count),
            )
        elif import_type == "orders":
            return _facade().cast(
                "str",
                _facade()._import_orders_preview_or_execute(
                    df, columns, unit_name, confirm, row_count
                ),
            )
        else:
            return _facade().json.dumps(
                {
                    "success": True,
                    "preview": True,
                    "import_type": import_type,
                    "columns": columns,
                    "row_count": row_count,
                    "sample_data": _facade().json.loads(
                        df.head(5).replace({float("nan"): None}).to_json(orient="records")
                    ),
                    "message": "未实现该类型的自动导入，请先导出为模板格式再导入。",
                },
                ensure_ascii=False,
            )
    except _facade().RECOVERABLE_ERRORS as e:
        return _facade().json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def _infer_product_field_mapping(
    columns: list[str], *, price_column_hint: str | None = None
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
        if "规格" in cn and "号" not in cn and ("编" not in cn):
            continue
        if "编" in c and "号" in c or "编号" in cn or "编码" in cn or ("sku" in cl):
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
        if "产品名称" in cn or "品名" in cn or "名称" in c or ("name" in cl):
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


def _excel_cell_as_clean_str(val: _facade().Any) -> str:
    """pandas/Excel 单元格转展示用字符串；NaN、字面量 'nan' 视为空。"""
    if val is None:
        return ""
    if isinstance(val, bool):
        return ""
    try:
        if _facade().pd.isna(val):
            return ""
    except _facade().RECOVERABLE_ERRORS:
        pass
    if isinstance(val, float) and val != val:
        return ""
    if isinstance(val, (int, float)) and (not isinstance(val, bool)):
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


def _excel_cell_as_float(val: _facade().Any, default: float = 0.0) -> float:
    try:
        if val is None or (isinstance(val, float) and val != val):
            return default
        if _facade().pd.isna(val):
            return default
    except _facade().RECOVERABLE_ERRORS:
        pass
    try:
        v = float(val)
        if v != v:
            return default
        return v
    except (TypeError, ValueError):
        return default
