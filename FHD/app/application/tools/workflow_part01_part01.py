# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.tools.workflow")


def _read_excel_dataframe(
    p: _facade().Path, *, sheet_name: _facade().Any, header_row_1based: int | None
) -> _facade().pd.DataFrame:
    kw: dict[str, _facade().Any] = {}
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        kw["engine"] = "openpyxl"
    if sheet_name:
        kw["sheet_name"] = sheet_name
    if header_row_1based is not None:
        kw["header"] = header_row_1based - 1
    return _facade().pd.read_excel(p, **kw)


def run_natural_language_pandas(
    df: _facade().pd.DataFrame, natural_language: str, **kwargs
) -> dict[str, _facade().Any]:
    """将自然语言查询转换为 pandas 操作并执行（接 excel_text_to_pandas）。"""
    generated_code = ""
    error_msg: str | None = None
    result_df = df
    try:
        legacy_pandas = _facade().importlib.import_module("app.legacy.excel_text_to_pandas")
        converter = legacy_pandas.ExcelTextToPandas()
        code = converter.translate(natural_language, df)
        if code and code.strip():
            generated_code = code
            result_df = _facade()._safe_exec_pandas(code, df)
    except ValueError as e:
        error_msg = str(e)
    except _facade().RECOVERABLE_ERRORS as e:
        error_msg = str(e)
    records = _facade().json.loads(
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
    args: dict[str, _facade().Any], workspace_root: str | None = None
) -> dict[str, _facade().Any]:
    file_path = str(args.get("file_path") or "")
    action = str(args.get("action") or "read")
    sheet_name = args.get("sheet_name")
    header_1b = _facade()._parse_excel_header_row_1based(args)
    if not file_path:
        return {"success": False, "error": "file_path is required"}
    root = workspace_root or str(_facade().Path.cwd())
    try:
        p = _facade().resolve_safe_excel_path(root, file_path)
    except _facade().RECOVERABLE_ERRORS as e:
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
        df = _facade()._read_excel_dataframe(p, sheet_name=sheet_name, header_row_1based=header_1b)
    except _facade().RECOVERABLE_ERRORS as e:
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
        query_out = _facade().run_natural_language_pandas(df, nl, file_path=file_path)
        query_out["action"] = "excel_query"
        return query_out
    if action == "read":
        max_return = 200
        slice_df = df.head(max_return)
        out: dict[str, _facade().Any] = {
            "success": True,
            "action": action,
            "file_path": file_path,
            "sheet_name": sheet_name,
            "columns": list(df.columns.astype(str)),
            "row_count": int(len(df)),
            "returned_rows": int(len(slice_df)),
            "truncated": len(df) > max_return,
            "records": _facade().json.loads(
                slice_df.replace({float("nan"): None}).to_json(orient="records")
            ),
        }
        try:
            from app.application.template_grid_core import _extract_customer_hint_from_excel

            customer_hint = str(
                _extract_customer_hint_from_excel(str(p), str(sheet_name).strip() or None) or ""
            ).strip()
            if customer_hint:
                out["customer_hint"] = customer_hint
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug("suppressed exception", exc_info=True)
        if header_1b is not None:
            out["header_row"] = header_1b
        return out
    if action == "query":
        expr = str(args.get("query_expression") or "").strip()
        out_df = _facade().safe_filter_dataframe(df, expr)
        return {
            "success": True,
            "action": "query",
            "file_path": file_path,
            "row_count": int(len(out_df)),
            "records": _facade().json.loads(
                out_df.head(200).replace({float("nan"): None}).to_json(orient="records")
            ),
            "columns": list(out_df.columns.astype(str)),
        }
    if action == "aggregate":
        group_by = [str(x) for x in args.get("group_by") or [] if str(x)]
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
                    "_".join([str(c) for c in x if str(c) != ""]).strip("_")
                    if isinstance(x, tuple)
                    else str(x)
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
            "records": _facade().json.loads(
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
            "dtypes": {str(k): str(v) for (k, v) in df.dtypes.items()},
        }
    return {"success": False, "error": f"unsupported_action:{action}"}
