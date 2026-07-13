"""Read-only Excel analysis use cases used by workflow tools."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from app.application.tools.workflow_excel_paths import resolve_safe_excel_path
from app.infrastructure.excel.text_to_pandas import _safe_exec_pandas
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _parse_excel_header_row_1based(args: dict[str, Any]) -> int | None:
    raw = args.get("header_row")
    if raw is None or raw == "":
        raw = args.get("header_row_index")
    if raw is None or raw == "":
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


def _read_excel_dataframe(
    p: Path,
    *,
    sheet_name: Any = None,
    header_row_1based: int | None = None,
) -> pd.DataFrame:
    kw: dict[str, Any] = {}
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        kw["engine"] = "openpyxl"
    if sheet_name:
        kw["sheet_name"] = sheet_name
    if header_row_1based is not None:
        kw["header"] = header_row_1based - 1
    return pd.read_excel(p, **kw)


def run_natural_language_pandas(
    df: pd.DataFrame, natural_language: str, **kwargs
) -> dict[str, Any]:
    """将自然语言查询转换为 pandas 操作并执行（接 excel_text_to_pandas）。"""
    generated_code = ""
    error_msg: str | None = None
    result_df = df

    try:
        from app.legacy.excel_text_to_pandas import ExcelTextToPandas

        converter = ExcelTextToPandas()
        code = converter.translate(natural_language, df)
        if code and code.strip():
            generated_code = code
            result_df = _safe_exec_pandas(code, df)
    except ValueError as e:
        error_msg = str(e)
    except RECOVERABLE_ERRORS as e:
        error_msg = str(e)

    records = json.loads(
        result_df.head(200).replace({float("nan"): None}).to_json(orient="records")
    )
    return {
        "generated_code": generated_code,
        "result_kind": "dataframe",
        "row_count": len(result_df),
        "truncated": len(result_df) > 200,
        "returned_rows": min(len(result_df), 200),
        "columns": list(result_df.columns.astype(str)),
        "records": records,
        **({"error": error_msg} if error_msg else {}),
    }


def handle_excel_analysis(
    args: dict[str, Any],
    workspace_root: str | None = None,
    *,
    resolve_path: Callable[[str, str], Path] = resolve_safe_excel_path,
    read_dataframe: Callable[..., pd.DataFrame] = _read_excel_dataframe,
    query_runner: Callable[..., dict[str, Any]] = run_natural_language_pandas,
) -> dict[str, Any]:
    file_path = str(args.get("file_path") or "")
    action = str(args.get("action") or "read")
    sheet_name = args.get("sheet_name")
    header_1b = _parse_excel_header_row_1based(args)
    if not file_path:
        return {"success": False, "error": "file_path is required"}
    root = workspace_root or str(Path.cwd())
    try:
        p = resolve_path(root, file_path)
    except RECOVERABLE_ERRORS as e:
        return {"success": False, "error": str(e), "workspace_root": root, "file_path": file_path}
    if not p.exists():
        return {
            "success": False,
            "error": "file not found",
            "file_path": file_path,
            "workspace_root": root,
            "resolved_path": str(p),
        }
    try:
        df = read_dataframe(p, sheet_name=sheet_name, header_row_1based=header_1b)
    except RECOVERABLE_ERRORS as e:
        return {
            "success": False,
            "error": f"read failed: {e}",
            "file_path": file_path,
            "resolved_path": str(p),
            "sheet_name": sheet_name,
            "header_row": header_1b,
        }
    if action == "excel_query":
        nl = str(args.get("natural_language") or "").strip()
        out = query_runner(df, nl, file_path=file_path)
        out["action"] = "excel_query"
        return out
    if action == "read":
        max_return = 200
        slice_df = df.head(max_return)
        out: dict[str, Any] = {
            "success": True,
            "action": action,
            "file_path": file_path,
            "sheet_name": sheet_name,
            "columns": list(df.columns.astype(str)),
            "row_count": int(len(df)),
            "returned_rows": int(len(slice_df)),
            "truncated": len(df) > max_return,
            "records": json.loads(slice_df.replace({float("nan"): None}).to_json(orient="records")),
        }
        try:
            from app.application.template_grid_core import _extract_customer_hint_from_excel

            customer_hint = str(
                _extract_customer_hint_from_excel(str(p), str(sheet_name).strip() or None) or ""
            ).strip()
            if customer_hint:
                out["customer_hint"] = customer_hint
        except RECOVERABLE_ERRORS:
            logger.debug("suppressed exception", exc_info=True)
        if header_1b is not None:
            out["header_row"] = header_1b
        return out
    if action == "query":
        expr = str(args.get("query_expression") or "").strip()
        out_df = df.query(expr) if expr else df
        return {
            "success": True,
            "action": "query",
            "file_path": file_path,
            "row_count": int(len(out_df)),
            "records": json.loads(
                out_df.head(200).replace({float("nan"): None}).to_json(orient="records")
            ),
            "columns": list(out_df.columns.astype(str)),
        }
    if action == "aggregate":
        group_by = [str(x) for x in (args.get("group_by") or []) if str(x)]
        metrics = args.get("metrics") or []
        if group_by and isinstance(metrics, list):
            agg_map: dict[str, list[str]] = {}
            for m in metrics:
                if not isinstance(m, dict):
                    continue
                col = str(m.get("column") or "").strip()
                op = str(m.get("op") or "").strip()
                if col and op:
                    agg_map.setdefault(col, []).append(op)
            if agg_map:
                out_df = df.groupby(group_by, dropna=False).agg(agg_map).reset_index()
                out_df.columns = [
                    (
                        "_".join([str(c) for c in x if str(c) != ""]).strip("_")
                        if isinstance(x, tuple)
                        else str(x)
                    )
                    for x in out_df.columns
                ]
            else:
                out_df = df
        else:
            out_df = df
        return {
            "success": True,
            "action": "aggregate",
            "file_path": file_path,
            "row_count": int(len(out_df)),
            "records": json.loads(
                out_df.head(200).replace({float("nan"): None}).to_json(orient="records")
            ),
            "columns": list(out_df.columns.astype(str)),
        }
    if action == "statistics":
        return {
            "success": True,
            "action": "statistics",
            "file_path": file_path,
            "row_count": int(len(df)),
            "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
        }
    return {"success": False, "error": f"unsupported_action:{action}"}


__all__ = [
    "_parse_excel_header_row_1based",
    "_read_excel_dataframe",
    "run_natural_language_pandas",
    "handle_excel_analysis",
]
