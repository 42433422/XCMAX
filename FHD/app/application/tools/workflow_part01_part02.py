# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib
from typing import Literal


def _facade():
    return importlib.import_module("app.application.tools.workflow")


def invalidate_workflow_tool_registry() -> None:
    """装包/卸载 employee_pack 后使进程内工具注册表缓存失效。"""
    global _WORKFLOW_REG_VER, _workflow_tool_registry_cache
    _facade()._WORKFLOW_REG_VER += 1
    _facade()._workflow_tool_registry_cache = None
    try:
        from app.mod_sdk.employee_tool_registry import invalidate_employee_tool_cache

        invalidate_employee_tool_cache()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("employee tool cache invalidate skipped", exc_info=True)


def get_workflow_tool_registry() -> list[dict[str, _facade().Any]]:
    global \
        _workflow_tool_registry_cache, \
        _workflow_tool_registry_bulk_token_present, \
        _workflow_registry_cache_ver
    bulk_on = True
    if (
        _facade()._workflow_tool_registry_cache is not None
        and _facade()._workflow_tool_registry_bulk_token_present == bulk_on
        and (_facade()._workflow_registry_cache_ver == _facade()._WORKFLOW_REG_VER)
    ):
        return _facade()._workflow_tool_registry_cache
    reg = _facade().extend_workflow_tool_registry(_facade()._base_registry())
    try:
        from app.mod_sdk.employee_tool_registry import build_employee_pack_tool_definitions

        emp_tools = build_employee_pack_tool_definitions()
        if emp_tools:
            reg = reg + emp_tools
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("employee pack tools merge skipped", exc_info=True)
    if bulk_on:
        reg.append(
            {
                "type": "function",
                "function": {
                    "name": "products_bulk_import",
                    "description": "批量导入产品数据到数据库。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Excel 文件路径"},
                            "sheet_name": {"type": "string", "description": "工作表名称"},
                            "mapping": {"type": "object", "description": "列名映射配置"},
                        },
                        "required": ["file_path"],
                    },
                },
            }
        )
    _facade()._workflow_tool_registry_cache = reg
    _facade()._workflow_tool_registry_bulk_token_present = bulk_on
    _facade()._workflow_registry_cache_ver = _facade()._WORKFLOW_REG_VER
    return reg


def execute_workflow_tool(
    name: str,
    args: dict[str, _facade().Any] | str,
    workspace_root: str | None = None,
    *,
    db_write_token: str | None = None,
) -> str:
    if isinstance(args, str):
        try:
            args = _facade().json.loads(args or "{}")
        except _facade().RECOVERABLE_ERRORS:
            args = {}
    if not isinstance(args, dict):
        args = {}
    if name == _facade().ERP_CAPABILITY_TOOL_NAME:
        return _facade().execute_registered_capability(args, workspace_root=workspace_root)
    try:
        from app.mod_sdk.employee_tool_registry import execute_employee_tool, is_employee_tool

        if is_employee_tool(name):
            return execute_employee_tool(name, args, workspace_root)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("employee tool dispatch skipped", exc_info=True)
    try:
        from app.mod_sdk.planner_native_tools import try_execute_native_planner_tool

        (native_raw, _mod) = try_execute_native_planner_tool(
            name, args, workspace_root, db_write_token=db_write_token
        )
        if native_raw is not None:
            return native_raw
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("planner native tool dispatch skipped", exc_info=True)
    if name == "template_preview":
        from app.services.tools_workflow_registered import execute_registered_workflow_tool

        action = str(args.get("action") or "view").strip() or "view"
        return _facade().json.dumps(
            execute_registered_workflow_tool(name, action, args), ensure_ascii=False
        )
    try:
        from app.application.employee_pack_runner import try_execute_employee_planner_tool

        emp_raw = try_execute_employee_planner_tool(
            name, args, workspace_root, db_write_token=db_write_token
        )
        if emp_raw is not None:
            return emp_raw
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("legacy employee planner tool dispatch skipped", exc_info=True)
    if name == "excel_analysis":
        return _facade().json.dumps(
            _facade().handle_excel_analysis(args, workspace_root=workspace_root), ensure_ascii=False
        )
    if name == "excel_chart_recommend":
        return _facade().json.dumps(
            {
                "suggestions": [
                    {"chart_type": "bar", "title": "分类对比"},
                    {"chart_type": "line", "title": "趋势分析"},
                ]
            },
            ensure_ascii=False,
        )
    if name == "excel_join_compare":
        try:
            action = str(args.get("action") or "join")
            if action == "join":
                (f1, f2) = (args.get("file_paths") or [None, None])[:2]
                p1 = _facade().resolve_safe_excel_path(
                    workspace_root or str(_facade().Path.cwd()), str(f1)
                )
                p2 = _facade().resolve_safe_excel_path(
                    workspace_root or str(_facade().Path.cwd()), str(f2)
                )
                if not p1.exists():
                    return _facade().json.dumps(
                        {"success": False, "error": f"file not found: {f1}"}, ensure_ascii=False
                    )
                if not p2.exists():
                    return _facade().json.dumps(
                        {"success": False, "error": f"file not found: {f2}"}, ensure_ascii=False
                    )
                d1 = _facade().pd.read_excel(p1)
                d2 = _facade().pd.read_excel(p2)
                keys = [str(x) for x in args.get("join_keys") or [] if str(x)]
                how = str(args.get("how") or "inner")
                out = d1.merge(d2, on=keys, how=how) if keys else d1
                return _facade().json.dumps(
                    {
                        "action": "join",
                        "row_count": int(len(out)),
                        "columns": list(out.columns.astype(str)),
                    },
                    ensure_ascii=False,
                )
            elif action == "diff":
                pa = _facade().resolve_safe_excel_path(
                    workspace_root or str(_facade().Path.cwd()), str(args.get("file_path_a") or "")
                )
                pb = _facade().resolve_safe_excel_path(
                    workspace_root or str(_facade().Path.cwd()), str(args.get("file_path_b") or "")
                )
                if not pa.exists():
                    return _facade().json.dumps(
                        {"success": False, "error": f"file not found: {args.get('file_path_a')}"},
                        ensure_ascii=False,
                    )
                if not pb.exists():
                    return _facade().json.dumps(
                        {"success": False, "error": f"file not found: {args.get('file_path_b')}"},
                        ensure_ascii=False,
                    )
                a = _facade().pd.read_excel(pa)
                b = _facade().pd.read_excel(pb)
                keys = [str(x) for x in args.get("key_columns") or [] if str(x)]
                if keys:
                    la = a.set_index(keys)
                    lb = b.set_index(keys)
                    only_l = [idx for idx in la.index if idx not in lb.index]
                    only_r = [idx for idx in lb.index if idx not in la.index]
                    common = [idx for idx in la.index if idx in lb.index]
                    changed = 0
                    for idx in common:
                        if not la.loc[idx].equals(lb.loc[idx]):
                            changed += 1
                    return _facade().json.dumps(
                        {
                            "action": "diff",
                            "only_in_left": {"count": len(only_l)},
                            "only_in_right": {"count": len(only_r)},
                            "rows_with_value_changes": {"count": changed},
                        },
                        ensure_ascii=False,
                    )
                else:
                    return _facade().json.dumps(
                        {"action": "diff", "row_count": int(len(a))}, ensure_ascii=False
                    )
            else:
                return _facade().json.dumps(
                    {"success": False, "error": f"unknown action: {action}"}, ensure_ascii=False
                )
        except _facade().RECOVERABLE_ERRORS:
            return _facade().json.dumps(
                {"success": False, "error": "excel_tool_failed"}, ensure_ascii=False
            )
    if name == "excel_prophet":
        try:
            file_path = str(args.get("file_path") or "")
            value_col = str(args.get("value_column") or args.get("y") or "").strip()
            str(args.get("date_column") or args.get("ds") or "").strip()
            periods = max(1, min(30, int(args.get("periods") or 6)))
            root = workspace_root or str(_facade().Path.cwd())
            if file_path:
                p = _facade().resolve_safe_excel_path(root, file_path)
                df = _facade()._read_excel_dataframe(p, sheet_name=None, header_row_1based=None)
                if not value_col or value_col not in df.columns:
                    num_cols = [
                        c
                        for c in df.columns
                        if _facade().pd.to_numeric(df[c], errors="coerce").notna().sum() > 2
                    ]
                    value_col = num_cols[0] if num_cols else ""
                y = (
                    _facade().pd.to_numeric(df[value_col], errors="coerce").dropna()
                    if value_col
                    else _facade().pd.Series([], dtype=float)
                )
            else:
                y = _facade().pd.Series([], dtype=float)
            if len(y) < 2:
                return _facade().json.dumps(
                    {
                        "action": "forecast",
                        "future_forecast": [{"yhat": 0.0}] * periods,
                        "note": "数据不足，使用零预测",
                    },
                    ensure_ascii=False,
                )
            x = list(range(len(y)))
            n = len(x)
            sx = sum(x)
            sy = float(y.sum())
            sxy = sum(xi * yi for (xi, yi) in zip(x, y))
            sxx = sum(xi**2 for xi in x)
            denom = n * sxx - sx * sx
            slope = (n * sxy - sx * sy) / denom if denom else 0
            intercept = (sy - slope * sx) / n
            future = [
                {"period": i + 1, "yhat": round(intercept + slope * (len(y) + i), 4)}
                for i in range(periods)
            ]
            return _facade().json.dumps(
                {
                    "action": "forecast",
                    "future_forecast": future,
                    "model": "linear_regression",
                    "periods": periods,
                },
                ensure_ascii=False,
            )
        except _facade().RECOVERABLE_ERRORS:
            return _facade().json.dumps(
                {"action": "forecast", "future_forecast": [], "error": "forecast_failed"},
                ensure_ascii=False,
            )
    if name == "excel_schema_understand":
        try:
            file_path = str(args.get("file_path") or "")
            sheet_n = args.get("sheet_name")
            header_1b = _facade()._parse_excel_header_row_1based(args)
            root = workspace_root or str(_facade().Path.cwd())
            p = _facade().resolve_safe_excel_path(root, file_path)
            if not p.exists():
                return _facade().json.dumps(
                    {
                        "success": False,
                        "error": "file_not_found",
                        "message": f"找不到文件: {file_path}",
                        "hint": "请确认文件已正确上传，或重新上传文件。",
                        "workspace_root": root,
                        "resolved_path": str(p),
                    },
                    ensure_ascii=False,
                )
            df = _facade()._read_excel_dataframe(p, sheet_name=sheet_n, header_row_1based=header_1b)
            svc = _facade().ExcelSchemaUnderstandingService()
            out = svc.understand_dataframe(df, file_path=file_path)
            return _facade().json.dumps(out, ensure_ascii=False)
        except _facade().RECOVERABLE_ERRORS:
            return _facade().json.dumps(
                {
                    "success": False,
                    "error": "read_excel_failed",
                    "message": "读取 Excel 文件失败，请检查文件后重试",
                },
                ensure_ascii=False,
            )
    if name == "products_bulk_import":
        from app.application.excel_imports import run_bulk_import

        out = run_bulk_import(args)
        return _facade().json.dumps(out, ensure_ascii=False)
    if name == "excel_vector_index":
        file_path = str(args.get("file_path") or "").strip()
        if not file_path:
            return _facade().json.dumps(
                {"success": False, "error": "file_path is required"}, ensure_ascii=False
            )
        root = workspace_root or str(_facade().Path.cwd())
        p = _facade().resolve_safe_excel_path(root, file_path)
        if not p.exists():
            return _facade().json.dumps(
                {
                    "success": False,
                    "error": "file_not_found",
                    "file_path": file_path,
                    "resolved_path": str(p),
                },
                ensure_ascii=False,
            )
        from app.application import get_excel_vector_ingest_app_service

        index_name = str(args.get("index_name") or "").strip() or None
        index_id = str(args.get("index_id") or "").strip() or None
        result = get_excel_vector_ingest_app_service().ingest_excel(
            file_path=str(p), index_name=index_name, index_id=index_id
        )
        if isinstance(result, dict) and result.get("success") and result.get("index_id"):
            result["excel_vector_index_id"] = result.get("index_id")
            result["excel_index_id"] = result.get("index_id")
        return _facade().json.dumps(result, ensure_ascii=False)
    if name == "import_excel_to_database":
        return _facade()._handle_import_excel_to_database(
            args, workspace_root=workspace_root, db_write_token=db_write_token
        )
    if name == "generate_office_document":
        try:
            req = str(
                args.get("user_request")
                or args.get("prompt")
                or args.get("request")
                or args.get("message")
                or ""
            ).strip()
            raw_fmt = str(args.get("output_format") or "docx").lower().strip()
            fmt: Literal["docx", "xlsx"] = "xlsx" if raw_fmt == "xlsx" else "docx"
            if not req:
                return _facade().json.dumps(
                    {"success": False, "error": "missing_user_request"}, ensure_ascii=False
                )
            from app.services.kitten_ai_document.generate import generate_office_file
            from app.services.kitten_ai_document.pickup import store_document_pickup

            (content, fname) = generate_office_file(req, fmt)
            mime = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                if fmt == "xlsx"
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            token = store_document_pickup(content, fname, mime)
            download_url = f"/api/ai/kitten/document/pickup/{token}"
            return _facade().json.dumps(
                {
                    "success": True,
                    "message": f"已生成《{fname}》。请让用户在浏览器打开以下路径下载（一次性有效，勿泄露 token）：",
                    "pickup_token": token,
                    "file_name": fname,
                    "download_url": download_url,
                    "artifacts": [
                        {
                            "artifact_type": "office_document",
                            "name": fname,
                            "source": "generate_office_document",
                            "uri": download_url,
                            "mime_type": mime,
                            "summary": req[:500],
                            "preview": {
                                "file_name": fname,
                                "download_url": download_url,
                                "output_format": fmt,
                            },
                            "metadata": {
                                "pickup_token": token,
                                "generator": "generate_office_document",
                            },
                        }
                    ],
                    "assistant_hint": "将 download_url 原样写入回复（可做成 Markdown 链接）；不要再次调用 generate_office_document，除非用户明确要求重新生成。",
                },
                ensure_ascii=False,
            )
        except _facade().RECOVERABLE_ERRORS:
            return _facade().json.dumps(
                {"success": False, "error": "office_document_generation_failed"},
                ensure_ascii=False,
            )
    business_db_result = _facade().try_execute_business_db_tool(name, args)
    if business_db_result is not None:
        return _facade().json.dumps(business_db_result, ensure_ascii=False)
    new_tool_dispatch = _facade()._resolve_new_tool_dispatch(name)
    if new_tool_dispatch is not None:
        try:
            result = new_tool_dispatch(args)
            return _facade().json.dumps(result, ensure_ascii=False)
        except _facade().RECOVERABLE_ERRORS:
            return _facade().json.dumps(
                {"success": False, "error": "tool_dispatch_failed"}, ensure_ascii=False
            )
    return _facade().json.dumps(
        {"success": False, "error": "unknown_tool", "tool": name}, ensure_ascii=False
    )
