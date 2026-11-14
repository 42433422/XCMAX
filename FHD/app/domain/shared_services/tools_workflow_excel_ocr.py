"""Excel 与 OCR 域工作流路由：Excel 分析/向量索引/OCR/导入。"""

from __future__ import annotations

import logging

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _registered_router_excel_analysis(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    """注册路由适配器；Excel 分析语义统一由 handle_excel_analysis 提供。"""
    payload = dict(params or {})
    payload["action"] = action
    if not str(payload.get("file_path") or "").strip():
        from app.domain.context.session_excel_context import excel_analysis_from_runtime

        excel_ctx = excel_analysis_from_runtime(runtime_context) or {}
        payload["file_path"] = str(excel_ctx.get("file_path") or "").strip()
    if not str(payload.get("file_path") or "").strip():
        return {"success": False, "message": "excel_analysis 缺少 file_path 参数"}
    if action == "query" and not payload.get("query_expression"):
        payload["action"] = "excel_query"
        payload["natural_language"] = str(payload.get("question") or user_message).strip()
    try:
        from app.application.tools.workflow import handle_excel_analysis

        if action == "export" and "_actor_authorization" in runtime_context:
            from app.application.tools.workflow_spreadsheet_scope import export_workflow_spreadsheet

            result = export_workflow_spreadsheet(payload, runtime_context, handle_excel_analysis)
        elif (
            action in {"read", "structure", "query", "statistics"}
            and "_actor_authorization" in runtime_context
        ):
            from app.application.tools.workflow_spreadsheet_scope import (
                workflow_file_snapshot,
            )

            original = str(payload["file_path"])
            with workflow_file_snapshot(original, runtime_context) as snapshot:
                if snapshot.suffix not in {".xlsx", ".xls", ".xlsm", ".csv"}:
                    raise PermissionError("文件类型不支持表格分析")
                result = handle_excel_analysis({**payload, "file_path": str(snapshot)})
            if isinstance(result, dict):
                result["file_path"] = original
                result.pop("resolved_path", None)
        else:
            result = handle_excel_analysis(
                payload, workspace_root=runtime_context.get("workspace_root")
            )
    except PermissionError as err:
        return {"success": False, "error_code": "spreadsheet_access_denied", "message": str(err)}
    except RECOVERABLE_ERRORS as err:
        logger.error("excel_analysis 执行失败: %s", err, exc_info=True)
        return {"success": False, "message": f"Excel 分析失败：{str(err)}"}
    if not isinstance(result, dict):
        return {"success": False, "message": str(result)}
    if (
        result.get("success")
        and action == "statistics"
        and ("expected_row_count" in params or "expected_totals" in params)
    ):
        from math import isclose

        mismatches = []
        if (
            "expected_row_count" in params
            and result.get("row_count") != params["expected_row_count"]
        ):
            mismatches.append("明细行数")
        summary = result.get("numeric_summary") or {}
        for column, expected in (params.get("expected_totals") or {}).items():
            # Sales exports name the money column amount. Plans often say total_amount.
            source = column
            if source not in summary and source == "total_amount" and "amount" in summary:
                source = "amount"
            actual = summary.get(source, {}).get("sum")
            if actual is None or not isclose(
                float(actual), float(expected), rel_tol=1e-9, abs_tol=1e-9
            ):
                mismatches.append(str(column))
        result["verification"] = {"verified": not mismatches, "mismatches": mismatches}
        if mismatches:
            result.update(success=False, message="Excel 核验未通过：" + "、".join(mismatches))
    if not result.get("success") and "error" in result and "message" not in result:
        result["message"] = result["error"]
    if result.get("success") is True and not isinstance(result.get("data"), dict):
        result = {
            **result,
            "data": {
                "records": result.get("records") or [],
                "columns": result.get("columns") or [],
                "row_count": result.get("row_count"),
                "file_path": result.get("file_path"),
            },
        }
    return result


def _registered_router_generate_office_document(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action != "execute":
        return {"success": False, "message": f"未知 generate_office_document action: {action}"}
    payload = dict(params or {})
    payload.setdefault("user_request", user_message)
    try:
        import json

        from app.application.tools.workflow import execute_workflow_tool

        raw = execute_workflow_tool(
            "generate_office_document",
            payload,
            workspace_root=runtime_context.get("workspace_root"),
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, dict) else {"success": False, "message": str(raw)}
    except RECOVERABLE_ERRORS as err:
        logger.error("generate_office_document 执行失败: %s", err, exc_info=True)
        return {"success": False, "message": f"文档生成失败：{str(err)}"}


def _registered_router_excel_vector_index(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    if action == "execute":
        file_path = str(params.get("file_path") or "").strip()
        if not file_path:
            return {"success": False, "message": "缺少 file_path"}
        index_name = str(params.get("index_name") or "").strip() or None
        index_id = str(params.get("index_id") or "").strip() or None
        try:
            from app.fastapi_routes.excel_vector import get_excel_vector_ingest_app_service

            result = get_excel_vector_ingest_app_service().ingest_excel(
                file_path=file_path, index_name=index_name, index_id=index_id
            )
        except RECOVERABLE_ERRORS as err:
            logger.error("excel_vector_index 执行失败: %s", err, exc_info=True)
            return {"success": False, "message": str(err), "error_code": "excel_vector_exception"}
        payload = dict(result or {})
        if payload.get("success") and payload.get("index_id"):
            payload["excel_vector_index_id"] = payload.get("index_id")
            payload["excel_index_id"] = payload.get("index_id")
        return payload
    if action == "query":
        index_id = str(params.get("index_id") or "").strip()
        query_text = str(params.get("query") or params.get("query_text") or "").strip()
        if not index_id:
            return {"success": False, "message": "缺少 index_id"}
        if not query_text:
            return {"success": False, "message": "缺少 query"}
        try:
            top_k = int(params.get("top_k", 5))
        except (TypeError, ValueError):
            top_k = 5
        try:
            from app.fastapi_routes.excel_vector import get_excel_vector_search_app_service

            return dict(
                get_excel_vector_search_app_service().query(
                    index_id=index_id, query_text=query_text, top_k=top_k
                )
                or {}
            )
        except RECOVERABLE_ERRORS as err:
            logger.error("excel_vector_index query 失败: %s", err, exc_info=True)
            return {"success": False, "message": str(err), "error_code": "excel_vector_exception"}
    return {"success": False, "message": f"未知 excel_vector_index action: {action}"}
