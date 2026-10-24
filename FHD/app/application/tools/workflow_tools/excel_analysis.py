"""Read and summarize workbooks through bounded, safe DataFrame operations."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd

from app.application.tools.workflow_tools.contracts import ExcelIO, NaturalQuery, Payload
from app.utils.operational_errors import RECOVERABLE_ERRORS


def read_excel_dataframe(
    p: Path, *, sheet_name: Any, header_row_1based: int | None
) -> pd.DataFrame:
    options: Payload = {}
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        options["engine"] = "openpyxl"
    if sheet_name:
        options["sheet_name"] = sheet_name
    if header_row_1based is not None:
        options["header"] = header_row_1based - 1
    return cast(pd.DataFrame, pd.read_excel(p, **options))


def frame_records(df: pd.DataFrame, limit: int = 200) -> list[Payload]:
    return cast(
        list[Payload],
        json.loads(df.head(limit).replace({float("nan"): None}).to_json(orient="records")),
    )


def table_result(df: pd.DataFrame) -> Payload:
    return {
        "row_count": len(df),
        "columns": list(df.columns.astype(str)),
        "records": frame_records(df),
    }


def natural_language_query(
    df: pd.DataFrame,
    natural_language: str,
    translate: Callable[[str, pd.DataFrame], str | None],
    execute: Callable[[str, pd.DataFrame], pd.DataFrame],
) -> Payload:
    generated_code = ""
    error: str | None = None
    result = df
    try:
        code = translate(natural_language, df)
        if code and code.strip():
            generated_code = code
            result = execute(code, df)
    except ValueError:
        error = "invalid_pandas_query"
    except RECOVERABLE_ERRORS:
        error = "excel_query_failed"
    return {
        "generated_code": generated_code,
        "result_kind": "dataframe",
        **table_result(result),
        "truncated": len(result) > 200,
        "returned_rows": min(len(result), 200),
        **({"error": error} if error else {}),
    }


def aggregate_frame(df: pd.DataFrame, args: Payload) -> pd.DataFrame:
    group_by = [str(value) for value in args.get("group_by") or [] if str(value)]
    metrics = args.get("metrics") or []
    if not group_by or not isinstance(metrics, list):
        return df
    operations: dict[str, list[str]] = {}
    for metric in metrics:
        if isinstance(metric, dict):
            column, op = (
                str(metric.get("column") or "").strip(),
                str(metric.get("op") or "").strip(),
            )
            if column and op:
                operations.setdefault(column, []).append(op)
    if not operations:
        return df
    result = df.groupby(group_by, dropna=False).agg(operations).reset_index()
    result.columns = [
        "_".join(str(part) for part in column if str(part) != "").strip("_")
        if isinstance(column, tuple)
        else str(column)
        for column in result.columns
    ]
    return result


@dataclass(frozen=True)
class ExcelAnalysis:
    io: ExcelIO
    query: NaturalQuery
    filter_frame: Callable[[pd.DataFrame, str], pd.DataFrame]
    customer_hint: Callable[[str, str | None], str]
    logger: logging.Logger

    def analyze(self, args: Payload, workspace_root: str | None = None) -> Payload:
        file_path = str(args.get("file_path") or "")
        action = str(args.get("action") or "read")
        sheet = args.get("sheet_name")
        header = self.io.header(args)
        if not file_path:
            return {"success": False, "error": "file_path is required"}
        root = workspace_root or str(Path.cwd())
        try:
            path = self.io.resolve(root, file_path)
        except RECOVERABLE_ERRORS:
            return {
                "success": False,
                "error": "invalid_excel_path",
                "workspace_root": root,
                "file_path": file_path,
            }
        if not path.exists():
            return {
                "success": False,
                "error": "file not found",
                "file_path": file_path,
                "workspace_root": root,
                "resolved_path": str(path),
            }
        try:
            df = self.io.read(path, sheet_name=sheet, header_row_1based=header)
        except RECOVERABLE_ERRORS:
            return {
                "success": False,
                "error": "read_excel_failed",
                "file_path": file_path,
                "resolved_path": str(path),
                "sheet_name": sheet,
                "header_row": header,
            }
        if action == "excel_query":
            out = self.query(
                df, str(args.get("natural_language") or "").strip(), file_path=file_path
            )
            out["action"] = "excel_query"
            return out
        base = {"success": True, "action": action, "file_path": file_path}
        if action == "read":
            out = {
                **base,
                "sheet_name": sheet,
                **table_result(df),
                "returned_rows": min(len(df), 200),
                "truncated": len(df) > 200,
            }
            try:
                hint = str(self.customer_hint(str(path), str(sheet).strip() or None) or "").strip()
                if hint:
                    out["customer_hint"] = hint
            except RECOVERABLE_ERRORS:
                self.logger.debug("suppressed exception", exc_info=True)
            if header is not None:
                out["header_row"] = header
            return out
        if action == "query":
            result = self.filter_frame(df, str(args.get("query_expression") or "").strip())
            return {**base, **table_result(result)}
        if action == "aggregate":
            return {**base, **table_result(aggregate_frame(df, args))}
        if action == "statistics":
            return {
                **base,
                "row_count": len(df),
                "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
            }
        return {"success": False, "error": f"unsupported_action:{action}"}
