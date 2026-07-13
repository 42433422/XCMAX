"""Workflow tool dispatcher.

The dispatcher owns protocol routing only. Excel parsing, database imports,
registry schemas, and document generation remain separate use cases.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from app.infrastructure.excel.schema_service import ExcelSchemaUnderstandingService
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def execute_workflow_tool_impl(
    name: str,
    args: dict[str, Any] | str,
    workspace_root: str | None = None,
    *,
    db_write_token: str | None = None,
    resolve_path: Callable[[str, str], Path],
    read_dataframe: Callable[..., pd.DataFrame],
    parse_header_row: Callable[[dict[str, Any]], int | None],
    analyze_excel: Callable[..., dict[str, Any]],
    import_excel: Callable[..., str],
    pandas_module=pd,
) -> str:
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except RECOVERABLE_ERRORS:
            args = {}
    try:
        from app.mod_sdk.employee_tool_registry import execute_employee_tool, is_employee_tool

        if is_employee_tool(name):
            return execute_employee_tool(name, args, workspace_root)
    except RECOVERABLE_ERRORS:
        logger.debug("employee tool dispatch skipped", exc_info=True)
    try:
        from app.mod_sdk.planner_native_tools import try_execute_native_planner_tool

        native_raw, _mod = try_execute_native_planner_tool(
            name, args, workspace_root, db_write_token=db_write_token
        )
        if native_raw is not None:
            return native_raw
    except RECOVERABLE_ERRORS:
        logger.debug("planner native tool dispatch skipped", exc_info=True)
    if name == "template_preview":
        from app.services.tools_workflow_registered import execute_registered_workflow_tool

        action = str(args.get("action") or "view").strip() or "view"
        return json.dumps(
            execute_registered_workflow_tool(name, action, args),
            ensure_ascii=False,
        )
    try:
        from app.application.employee_pack_runner import try_execute_employee_planner_tool

        emp_raw = try_execute_employee_planner_tool(
            name, args, workspace_root, db_write_token=db_write_token
        )
        if emp_raw is not None:
            return emp_raw
    except RECOVERABLE_ERRORS:
        logger.debug("legacy employee planner tool dispatch skipped", exc_info=True)
    if name == "excel_analysis":
        return json.dumps(analyze_excel(args, workspace_root=workspace_root), ensure_ascii=False)
    if name == "excel_chart_recommend":
        return json.dumps(
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
                f1, f2 = (args.get("file_paths") or [None, None])[:2]
                p1 = resolve_path(workspace_root or str(Path.cwd()), str(f1))
                p2 = resolve_path(workspace_root or str(Path.cwd()), str(f2))
                if not p1.exists():
                    return json.dumps(
                        {"success": False, "error": f"file not found: {f1}"}, ensure_ascii=False
                    )
                if not p2.exists():
                    return json.dumps(
                        {"success": False, "error": f"file not found: {f2}"}, ensure_ascii=False
                    )
                d1 = pandas_module.read_excel(p1)
                d2 = pandas_module.read_excel(p2)
                keys = [str(x) for x in (args.get("join_keys") or []) if str(x)]
                how = str(args.get("how") or "inner")
                out = d1.merge(d2, on=keys, how=how) if keys else d1
                return json.dumps(
                    {
                        "action": "join",
                        "row_count": int(len(out)),
                        "columns": list(out.columns.astype(str)),
                    },
                    ensure_ascii=False,
                )
            elif action == "diff":
                pa = resolve_path(
                    workspace_root or str(Path.cwd()), str(args.get("file_path_a") or "")
                )
                pb = resolve_path(
                    workspace_root or str(Path.cwd()), str(args.get("file_path_b") or "")
                )
                if not pa.exists():
                    return json.dumps(
                        {"success": False, "error": f"file not found: {args.get('file_path_a')}"},
                        ensure_ascii=False,
                    )
                if not pb.exists():
                    return json.dumps(
                        {"success": False, "error": f"file not found: {args.get('file_path_b')}"},
                        ensure_ascii=False,
                    )
                a = pandas_module.read_excel(pa)
                b = pandas_module.read_excel(pb)
                keys = [str(x) for x in (args.get("key_columns") or []) if str(x)]
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
                    return json.dumps(
                        {
                            "action": "diff",
                            "only_in_left": {"count": len(only_l)},
                            "only_in_right": {"count": len(only_r)},
                            "rows_with_value_changes": {"count": changed},
                        },
                        ensure_ascii=False,
                    )
                else:
                    return json.dumps(
                        {"action": "diff", "row_count": int(len(a))}, ensure_ascii=False
                    )
            else:
                return json.dumps(
                    {"success": False, "error": f"unknown action: {action}"}, ensure_ascii=False
                )
        except RECOVERABLE_ERRORS as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    if name == "excel_prophet":
        try:
            file_path = str(args.get("file_path") or "")
            value_col = str(args.get("value_column") or args.get("y") or "").strip()
            str(args.get("date_column") or args.get("ds") or "").strip()
            periods = max(1, min(30, int(args.get("periods") or 6)))
            root = workspace_root or str(Path.cwd())
            if file_path:
                p = resolve_path(root, file_path)
                df = read_dataframe(p)
                if not value_col or value_col not in df.columns:
                    num_cols = [
                        c
                        for c in df.columns
                        if pandas_module.to_numeric(df[c], errors="coerce").notna().sum() > 2
                    ]
                    value_col = num_cols[0] if num_cols else ""
                y = (
                    pandas_module.to_numeric(df[value_col], errors="coerce").dropna()
                    if value_col
                    else pandas_module.Series([], dtype=float)
                )
            else:
                y = pandas_module.Series([], dtype=float)
            if len(y) < 2:
                return json.dumps(
                    {
                        "action": "forecast",
                        "future_forecast": [{"yhat": 0.0}] * periods,
                        "note": "数据不足，使用零预测",
                    },
                    ensure_ascii=False,
                )
            x = list(range(len(y)))
            # 简单线性回归预测
            n = len(x)
            sx = sum(x)
            sy = float(y.sum())
            sxy = sum(xi * yi for xi, yi in zip(x, y))
            sxx = sum(xi**2 for xi in x)
            denom = n * sxx - sx * sx
            slope = (n * sxy - sx * sy) / denom if denom else 0
            intercept = (sy - slope * sx) / n
            future = [
                {"period": i + 1, "yhat": round(intercept + slope * (len(y) + i), 4)}
                for i in range(periods)
            ]
            return json.dumps(
                {
                    "action": "forecast",
                    "future_forecast": future,
                    "model": "linear_regression",
                    "periods": periods,
                },
                ensure_ascii=False,
            )
        except RECOVERABLE_ERRORS as e:
            return json.dumps(
                {"action": "forecast", "future_forecast": [], "error": str(e)}, ensure_ascii=False
            )
    if name == "excel_schema_understand":
        try:
            file_path = str(args.get("file_path") or "")
            sheet_n = args.get("sheet_name")
            header_1b = parse_header_row(args)
            root = workspace_root or str(Path.cwd())
            p = resolve_path(root, file_path)
            if not p.exists():
                return json.dumps(
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
            df = read_dataframe(p, sheet_name=sheet_n, header_row_1based=header_1b)
            svc = ExcelSchemaUnderstandingService()
            out = svc.understand_dataframe(df, file_path=file_path)
            return json.dumps(out, ensure_ascii=False)
        except RECOVERABLE_ERRORS as e:
            return json.dumps(
                {"success": False, "error": str(e), "message": f"读取 Excel 文件失败: {e}"},
                ensure_ascii=False,
            )
    if name == "products_bulk_import":
        from app.application.excel_imports import run_bulk_import

        out = run_bulk_import(args)
        return json.dumps(out, ensure_ascii=False)
    if name == "excel_vector_index":
        file_path = str(args.get("file_path") or "").strip()
        if not file_path:
            return json.dumps(
                {"success": False, "error": "file_path is required"}, ensure_ascii=False
            )
        root = workspace_root or str(Path.cwd())
        p = resolve_path(root, file_path)
        if not p.exists():
            return json.dumps(
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
            file_path=str(p),
            index_name=index_name,
            index_id=index_id,
        )
        if isinstance(result, dict) and result.get("success") and result.get("index_id"):
            result["excel_vector_index_id"] = result.get("index_id")
            result["excel_index_id"] = result.get("index_id")
        return json.dumps(result, ensure_ascii=False)
    if name == "import_excel_to_database":
        return import_excel(args, workspace_root=workspace_root, db_write_token=db_write_token)
    if name == "generate_office_document":
        try:
            req = str(
                args.get("user_request")
                or args.get("prompt")
                or args.get("request")
                or args.get("message")
                or ""
            ).strip()
            fmt = str(args.get("output_format") or "docx").lower().strip()
            if fmt not in ("docx", "xlsx"):
                fmt = "docx"
            if not req:
                return json.dumps(
                    {"success": False, "error": "missing_user_request"}, ensure_ascii=False
                )
            from app.services.kitten_ai_document.generate import generate_office_file
            from app.services.kitten_ai_document.pickup import store_document_pickup

            content, fname = generate_office_file(req, fmt)
            mime = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                if fmt == "xlsx"
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            token = store_document_pickup(content, fname, mime)
            download_url = f"/api/ai/kitten/document/pickup/{token}"
            return json.dumps(
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
                    "assistant_hint": (
                        "将 download_url 原样写入回复（可做成 Markdown 链接）；"
                        "不要再次调用 generate_office_document，除非用户明确要求重新生成。"
                    ),
                },
                ensure_ascii=False,
            )
        except RECOVERABLE_ERRORS as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    return json.dumps({"success": False, "error": "unknown_tool", "tool": name}, ensure_ascii=False)


__all__ = ["execute_workflow_tool_impl"]
