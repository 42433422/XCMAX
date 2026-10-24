"""Normalize import context, validate the workbook slice, and select a typed importer."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from app.application.tools.workflow_tools.contracts import ExcelIO, Payload
from app.application.tools.workflow_tools.excel_analysis import frame_records
from app.utils.operational_errors import RECOVERABLE_ERRORS


class ProductsImport(Protocol):
    def __call__(
        self,
        df: pd.DataFrame,
        columns: list[str],
        unit_name: str,
        confirm: bool,
        row_count: int,
        *,
        read_meta: Payload | None = None,
        price_column_hint: str | None = None,
    ) -> str: ...


@dataclass(frozen=True)
class ImportHandlers:
    products: ProductsImport
    customers: Callable[[pd.DataFrame, list[str], bool, int], str]
    orders: Callable[[pd.DataFrame, list[str], str, bool, int], str]


@dataclass(frozen=True)
class ImportHints:
    from_excel: Callable[[str, str | None], str]
    from_text: Callable[[str], list[str]]
    header: Callable[[Payload, str | None], int | None]


@dataclass(frozen=True)
class PreparedImport:
    kind: str
    frame: pd.DataFrame
    unit_name: str
    confirm: bool
    read_meta: Payload
    price_column: str | None


def import_context(args: Payload) -> tuple[Payload, Payload, Any]:
    context = args.get("context")
    if not isinstance(context, dict):
        context = {}
    analysis = args.get("excel_analysis")
    if not isinstance(analysis, dict):
        analysis = context.get("excel_analysis")
    if not isinstance(analysis, dict):
        analysis = {}
    sheet = args.get("sheet_name")
    selected = context.get("excel_analysis_selected_sheet")
    preview = analysis.get("preview_data")
    candidates = (
        selected.get("sheet_name") if isinstance(selected, dict) else None,
        context.get("preferred_sheet_name"),
        preview.get("sheet_name") if isinstance(preview, dict) else None,
    )
    for candidate in candidates:
        if not str(sheet or "").strip():
            value = str(candidate or "").strip()
            if value:
                sheet = value
    return context, analysis, sheet


@dataclass(frozen=True)
class ExcelImport:
    io: ExcelIO
    hints: ImportHints
    handlers: ImportHandlers
    required_token: Callable[[], str]
    logger: logging.Logger

    def execute(self, args: Payload, workspace_root: str | None, db_write_token: str | None) -> str:
        try:
            prepared = self.prepare(args, workspace_root, db_write_token)
            if isinstance(prepared, dict):
                return json.dumps(prepared, ensure_ascii=False)
            df = prepared.frame
            columns = list(df.columns.astype(str))
            if prepared.kind == "products":
                return self.handlers.products(
                    df,
                    columns,
                    prepared.unit_name,
                    prepared.confirm,
                    len(df),
                    read_meta=prepared.read_meta,
                    price_column_hint=prepared.price_column,
                )
            if prepared.kind == "customers":
                return self.handlers.customers(df, columns, prepared.confirm, len(df))
            if prepared.kind == "orders":
                return self.handlers.orders(
                    df, columns, prepared.unit_name, prepared.confirm, len(df)
                )
            return json.dumps(
                {
                    "success": True,
                    "preview": True,
                    "import_type": prepared.kind,
                    "columns": columns,
                    "row_count": len(df),
                    "sample_data": frame_records(df, 5),
                    "message": "未实现该类型的自动导入，请先导出为模板格式再导入。",
                },
                ensure_ascii=False,
            )
        except RECOVERABLE_ERRORS:
            return json.dumps(
                {"success": False, "error": "excel_import_failed"}, ensure_ascii=False
            )

    def prepare(
        self, args: Payload, workspace_root: str | None, db_write_token: str | None
    ) -> PreparedImport | Payload:
        kind = str(args.get("import_type") or "products")
        file_path = str(args.get("file_path") or "").strip()
        context, analysis, sheet = import_context(args)
        if not file_path:
            return {"success": False, "error": "file_path is required"}
        required = self.required_token()
        provided = str(args.get("db_write_token") or db_write_token or "").strip()
        if required and workspace_root is None:
            if not provided:
                return {"success": False, "requires_token": True, "token_name": "DB_WRITE_TOKEN"}
            if provided != required:
                return {"success": False, "error": "invalid_token"}
        path = self.io.resolve(workspace_root or str(Path.cwd()), file_path)
        if not path.exists():
            return {"success": False, "error": "file not found"}
        unit = self.unit_name(args, context, analysis, path, sheet)
        confirm = bool(args.get("confirm", True)) and not bool(args.get("preview_only", False))
        header = self.io.header(args)
        if header is None and analysis:
            try:
                header = self.hints.header(analysis, str(sheet or "").strip() or None)
            except RECOVERABLE_ERRORS:
                header = None
        try:
            df = self.io.read(path, sheet_name=sheet, header_row_1based=header)
        except RECOVERABLE_ERRORS:
            return {
                "success": False,
                "error": "read_excel_failed",
                "sheet_name": sheet,
                "header_row": header,
            }
        if df.empty:
            return {"success": False, "error": "Excel file is empty"}
        raw_last = args.get("last_data_row_1based")
        try:
            last = int(raw_last) if raw_last is not None and str(raw_last).strip() != "" else None
        except (TypeError, ValueError):
            last = None
        if last is not None and last >= 1:
            effective_header = header if header is not None else 1
            keep = last - effective_header
            if keep < 1:
                return {
                    "success": False,
                    "error": "invalid_last_data_row",
                    "message": "last_data_row_1based 必须大于 header_row（或表头在第 1 行时大于 1）",
                    "header_row": effective_header,
                    "last_data_row_1based": last,
                }
            df = df.iloc[:keep]
        return PreparedImport(
            kind,
            df,
            unit,
            confirm,
            {"sheet_name": sheet, "header_row": header, "last_data_row_applied": last},
            str(args.get("price_column") or "").strip() or None,
        )

    def unit_name(
        self, args: Payload, context: Payload, analysis: Payload, path: Path, sheet: Any
    ) -> str:
        unit = str(args.get("unit_name") or "").strip()
        if not unit:
            unit = str(args.get("excel_customer_hint") or "").strip()
        if not unit:
            unit = str(context.get("excel_customer_hint") or "").strip()
        if not unit and analysis:
            unit = str(
                analysis.get("customer_hint")
                or (analysis.get("preview_data") or {}).get("customer_hint")
                or ""
            ).strip()
        if not unit:
            try:
                linked: list[Payload] = []
                one, many = (
                    context.get("excel_linked_grid_preview"),
                    context.get("excel_linked_grid_previews"),
                )
                if isinstance(one, dict):
                    linked.append(one)
                if isinstance(many, list):
                    linked.extend(item for item in many if isinstance(item, dict))
                for item in linked:
                    text = str(item.get("preview_text") or "").strip()
                    if text:
                        hits = self.hints.from_text(text)
                        if hits:
                            unit = str(hits[0]).strip()
                            break
            except RECOVERABLE_ERRORS:
                self.logger.debug("suppressed exception", exc_info=True)
        if not unit:
            try:
                unit = str(self.hints.from_excel(str(path), sheet if sheet else None) or "").strip()
            except RECOVERABLE_ERRORS:
                self.logger.debug("suppressed exception", exc_info=True)
        return unit
