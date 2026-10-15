"""
XCAGI 前端使用的 Excel 模板列表等（GET /api/templates）。

FHD compact 栈（backend.http_app）不加载完整 XCAGI 时，至少避免 404；
若同进程可导入 ``app.application.template_app_service``，则返回真实列表，否则空列表。
"""

from __future__ import annotations

import logging
import time
from typing import Any, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from app.fastapi_routes.template_create import router as template_create_router
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.infrastructure.tenant_scope import tenant_scope
from app.neuro_bus.application_neuro_bridge import publish_neuro_event
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["templates-compat"])
router.include_router(template_create_router)


def _templates_payload() -> dict:
    try:
        from app.application.template_app_service import get_template_app_service

        data = get_template_app_service().get_templates()
        return {"success": True, "templates": data.get("templates") or []}
    except RECOVERABLE_ERRORS as e:
        logger.warning("template_api: 模板服务加载失败: %s", e)
        # 返回 503-compatible 错误结构；GET /api/templates 自身不抛异常，
        # 但调用方（前端）可通过 service_unavailable 字段判断需要告警。
        return {
            "success": False,
            "templates": [],
            "service_unavailable": True,
            "message": "模板服务暂时不可用，请刷新或联系管理员",
        }


def _find_template_row(template_id: str) -> dict[str, Any] | None:
    """按前端常用的 id / db_id / db:<n> 在列表结果中解析单条模板。"""
    raw = str(template_id or "").strip()
    if not raw:
        return None
    templates = _templates_payload().get("templates") or []
    if raw.startswith("db:"):
        for t in templates:
            if str((t or {}).get("id") or "") == raw:
                return cast("dict[str, Any] | None", t)
        try:
            n = int(raw.split(":", 1)[1])
        except (ValueError, IndexError):
            n = None
        if n is not None:
            for t in templates:
                if (t or {}).get("db_id") == n:
                    return cast("dict[str, Any] | None", t)
    if raw.isdigit():
        n = int(raw)
        for t in templates:
            if (t or {}).get("db_id") == n or str((t or {}).get("id") or "") == raw:
                return cast("dict[str, Any] | None", t)
    for t in templates:
        if str((t or {}).get("id") or "") == raw:
            return cast("dict[str, Any] | None", t)
    return None


def _publish_template_event(event_type: str, payload: dict[str, Any]) -> None:
    """发布模板相关事件到 NeuroBus"""
    try:
        publish_neuro_event(
            event_type,
            payload,
            domain="template",
        )
    except RECOVERABLE_ERRORS:
        pass  # 静默失败，不影响主流程


@router.get("/api/templates/list", summary="模板列表（兼容旧路径 /api/templates/list）")
def templates_list_legacy_alias(request: Request):
    """与 GET /api/templates 相同，供仍使用 /list 后缀的前端使用。"""
    return templates_list_compat(request)


@router.get("/api/templates", summary="模板列表（兼容 XCAGI 前端）")
@router.get("/api/templates/", summary="模板列表（兼容 XCAGI 前端）", include_in_schema=False)
def templates_list_compat(request: Request):
    t0 = time.perf_counter()
    rid = str(getattr(request.state, "trace_id", None) or id(request))

    # 发布请求开始事件
    _publish_template_event(
        "template.request.started",
        {
            "request_id": rid,
            "path": str(request.url.path),
            "method": request.method,
            "client": request.client.host if request.client else None,
        },
    )

    try:
        result = _templates_payload()
        latency_ms = (time.perf_counter() - t0) * 1000.0

        # 发布请求完成事件
        _publish_template_event(
            "template.request.completed",
            {
                "request_id": rid,
                "path": str(request.url.path),
                "latency_ms": round(latency_ms, 3),
                "template_count": len(result.get("templates", [])),
                "success": result.get("success", False),
            },
        )
        from fastapi.responses import JSONResponse

        if result.get("service_unavailable"):
            return JSONResponse(result, status_code=503)
        return result
    except RECOVERABLE_ERRORS as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0

        # 发布请求失败事件
        _publish_template_event(
            "template.request.failed",
            {
                "request_id": rid,
                "path": str(request.url.path),
                "latency_ms": round(latency_ms, 3),
                "error": str(e)[:300],
            },
        )
        raise


@router.get(
    "/api/templates/detail/{template_id}",
    summary="模板详情（兼容 /api/templates/detail/{id}）",
)
def templates_detail_compat(template_id: str):
    row = _find_template_row(template_id)
    if not row:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"success": True, "template": row}


@router.get("/api/templates/{template_id}", summary="模板详情（XCAGI：/api/templates/{id}）")
def templates_get_one(template_id: str):
    if template_id in {"list", "detail"}:
        raise HTTPException(status_code=404, detail="Not Found")
    row = _find_template_row(template_id)
    if not row:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"success": True, "template": row}


def _tenant_scope_or_403(user: Any):
    """与 template_create 一致：账号是唯一身份来源，缺租户上下文直接 403。"""
    tenant_id = getattr(user, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="缺少租户上下文，无法操作模板")
    return tenant_scope(int(tenant_id))


@router.post("/api/templates/upload", summary="上传办公文件解析并入库模板库（analyze → create）")
async def templates_upload(
    request: Request,
    file: UploadFile = File(...),
    template_name: str = Form(default=""),
    name: str = Form(default=""),
    template_scope: str = Form(default=""),
    type: str = Form(default=""),
    source: str = Form(default="office_upload"),
    user: Any = Depends(get_logged_in_user),
) -> JSONResponse:
    """办公文件入口：解析并自动入库模版库。

    前端 templatePreview 默认上传端点。此前仅存在于 env 门禁的 legacy_gap
    路由（XCAGI_REGISTER_LEGACY_ROUTES=1），默认应用从未挂载 → 一律 405，
    客户无法导入模板（G7 断链根因）。本路由为默认挂载的 SSOT 实现。
    """
    from app.application.office_template_ingest_app_service import (
        ingest_office_bytes_to_template_library,
    )

    raw = await file.read()
    display_name = str(template_name or name or "").strip()
    scope = str(template_scope or type or "").strip()
    # 文档历史参数 type=excel|word|logo 不是 business_scope，避免误触发词条校验
    if scope.lower() in {"excel", "word", "logo", "label", "image"}:
        scope = ""
    with _tenant_scope_or_403(user):
        data, code = ingest_office_bytes_to_template_library(
            file_body=raw,
            filename=str(file.filename or "upload.bin"),
            template_name=display_name,
            template_scope=scope,
            source=str(source or "office_upload").strip() or "office_upload",
        )
    return JSONResponse(data, status_code=code)


@router.post("/api/templates/analyze", summary="解析办公模板（auto_save=1 时等同 upload）")
async def templates_analyze(
    request: Request,
    file: UploadFile = File(...),
    template_name: str = Form(default=""),
    template_scope: str = Form(default=""),
    auto_save: str = Form(default="0"),
    user: Any = Depends(get_logged_in_user),
) -> JSONResponse:
    """解析办公模板；``auto_save=1`` 时直接写入模版库（等同 upload）。"""
    raw = await file.read()
    with _tenant_scope_or_403(user):
        if str(auto_save or "").strip().lower() in {"1", "true", "yes", "on"}:
            from app.application.office_template_ingest_app_service import (
                ingest_office_bytes_to_template_library,
            )

            data, code = ingest_office_bytes_to_template_library(
                file_body=raw,
                filename=str(file.filename or "upload.bin"),
                template_name=template_name,
                template_scope=template_scope,
                source="templates_analyze_auto_save",
            )
        else:
            from app.legacy.routes.document_templates_compat import (
                run_archive_template_analyze,
            )

            data, code = run_archive_template_analyze(
                file_body=raw,
                filename=str(file.filename or "upload.bin"),
                template_name=template_name,
                template_scope=template_scope,
            )
    return JSONResponse(data, status_code=code)


@router.get(
    "/api/templates/progress/{task_id}",
    summary="模板解析进度查询（上传/分析流程轮询）",
)
def templates_progress(task_id: str):
    from app.template_analysis_progress import get_template_analysis_progress

    return get_template_analysis_progress(task_id)
