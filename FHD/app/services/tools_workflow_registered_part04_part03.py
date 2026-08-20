# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.tools_workflow_registered")


def _registered_router_excel_analysis(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    file_path = str(params.get("file_path") or "").strip()
    if not file_path:
        excel_ctx = (
            runtime_context.get("excel_analysis")
            if isinstance(runtime_context.get("excel_analysis"), dict)
            else None
        )
        if not excel_ctx:
            last_ctx = runtime_context.get("last_excel_analysis_context")
            if isinstance(last_ctx, dict):
                excel_ctx = (
                    last_ctx.get("result") if isinstance(last_ctx.get("result"), dict) else last_ctx
                )
        if isinstance(excel_ctx, dict):
            file_path = str(excel_ctx.get("file_path") or "").strip()
    if not file_path:
        return {"success": False, "message": "excel_analysis 缺少 file_path 参数"}
    question = str(params.get("question") or "").strip()
    try:
        from app.infrastructure.skills.excel_analyzer.excel_template_analyzer import (
            get_excel_analyzer_skill,
        )
        from app.infrastructure.skills.excel_toolkit.excel_toolkit import get_excel_toolkit_skill
    except ImportError:
        return {"success": False, "message": "Excel Skill 未正确安装"}
    toolkit_skill = get_excel_toolkit_skill()
    analyzer_skill = get_excel_analyzer_skill()
    if action == "read":
        result = toolkit_skill.execute(file_path=file_path, action="view")
        return result
    if action == "structure":
        result = analyzer_skill.execute(file_path=file_path)
        return result
    if action == "statistics":
        view_result = toolkit_skill.execute(file_path=file_path, action="view")
        if not view_result.get("success"):
            return view_result
        content = view_result.get("content") or []
        total_rows = view_result.get("row_count") or 0
        all_values = []
        for row in content:
            for cell in row.get("cells") or []:
                v = cell.get("value")
                if v is not None:
                    try:
                        all_values.append(float(v))
                    except (TypeError, ValueError):
                        pass
        if all_values:
            stats = {
                "count": len(all_values),
                "sum": round(sum(all_values), 4),
                "avg": round(sum(all_values) / len(all_values), 4),
                "min": min(all_values),
                "max": max(all_values),
            }
        else:
            stats = {"count": 0}
        return {
            "success": True,
            "file_path": file_path,
            "total_rows": total_rows,
            "statistics": stats,
        }
    if action == "query":
        view_result = toolkit_skill.execute(file_path=file_path, action="view")
        if not view_result.get("success"):
            return view_result
        content = view_result.get("content") or []
        if not question:
            return {"success": True, "data": content[:20]}
        question_lower = question.lower()
        if any(kw in question_lower for kw in ["多少", "总和", "总计", "total", "sum"]):
            all_vals = []
            for row in content:
                for cell in row.get("cells") or []:
                    try:
                        all_vals.append(float(cell.get("value")))
                    except (TypeError, ValueError):
                        pass
            total = sum(all_vals) if all_vals else 0
            return {"success": True, "answer": f"所有数值总和为 {round(total, 4)}", "total": total}
        if any(kw in question_lower for kw in ["最大", "最高", "max"]):
            all_vals = [
                float(c.get("value"))
                for row in content
                for c in row.get("cells") or []
                if c.get("value") is not None
            ]
            try:
                mx = max(all_vals)
                return {"success": True, "answer": f"最大值为 {mx}", "max": mx}
            except ValueError:
                return {"success": True, "answer": "未找到数值"}
        return {
            "success": True,
            "data": content[:20],
            "message": f"已读取前 {min(20, len(content))} 行数据",
        }
    return {"success": False, "message": f"未知 excel_analysis action: {action}"}


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
    except _facade().RECOVERABLE_ERRORS as err:
        _facade().logger.error("generate_office_document 执行失败: %s", err, exc_info=True)
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
        except _facade().RECOVERABLE_ERRORS as err:
            _facade().logger.error("excel_vector_index 执行失败: %s", err, exc_info=True)
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
        except _facade().RECOVERABLE_ERRORS as err:
            _facade().logger.error("excel_vector_index query 失败: %s", err, exc_info=True)
            return {"success": False, "message": str(err), "error_code": "excel_vector_exception"}
    return {"success": False, "message": f"未知 excel_vector_index action: {action}"}


def _ocr_artifact_payload(
    *,
    text: str,
    file_path: str = "",
    structured_data: dict[str, _facade().Any] | None = None,
    analysis: dict[str, _facade().Any] | None = None,
    confidence: _facade().Any = 0,
) -> dict[str, _facade().Any]:
    return {
        "artifact_type": "ocr_text",
        "name": "ocr_result",
        "source": "ocr.recognize",
        "uri": file_path,
        "mime_type": "image/*",
        "summary": "OCR 解析结果",
        "fields": [
            {"name": key, "value": value}
            for key, value in dict(structured_data or {}).items()
            if value not in (None, "", [], {})
        ][:20],
        "preview": {
            "text": text[:1000],
            "confidence": confidence,
            "structured_data": dict(structured_data or {}),
            "analysis": dict(analysis or {}),
        },
        "metadata": {"parser_used": "ocr", "text": text, "success": True},
    }
