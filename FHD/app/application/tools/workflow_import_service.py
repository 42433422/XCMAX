"""Application service coordinating Excel-to-database imports."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def handle_import_excel_to_database(
    args: dict[str, Any],
    workspace_root: str | None = None,
    db_write_token: str | None = None,
    *,
    resolve_path: Callable[[str, str], Path],
    read_dataframe: Callable[..., pd.DataFrame],
    parse_header_row: Callable[[dict[str, Any]], int | None],
    import_products: Callable[..., str],
    import_customers: Callable[..., str],
    import_orders: Callable[..., str],
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

        p = resolve_path(workspace_root or str(Path.cwd()), file_path)
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

        header_1b = parse_header_row(args)
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
            df = read_dataframe(p, sheet_name=sheet_n, header_row_1based=header_1b)
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
            return import_products(
                df,
                columns,
                unit_name,
                confirm,
                row_count,
                read_meta=read_meta,
                price_column_hint=price_column_hint,
            )
        elif import_type == "customers":
            return import_customers(df, columns, confirm, row_count)
        elif import_type == "orders":
            return import_orders(df, columns, unit_name, confirm, row_count)
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


__all__ = ["handle_import_excel_to_database"]
