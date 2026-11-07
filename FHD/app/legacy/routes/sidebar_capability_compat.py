"""保留旧侧栏兼容路径，并将探测调用引向真实能力接口。"""

from __future__ import annotations

from typing import Any, TypeVar, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.infrastructure.auth.business_scope_gate import require_scoped_business_permission

router = APIRouter(tags=["sidebar-capability-compat"])
_T = TypeVar("_T")
_PROBE_REPLACEMENTS = {
    "/api/knowledge/base": "/api/knowledge/v1/health",
    "/api/workflow-employee-space/overview": "/api/system/workflow-employee-catalog",
    "/api/workflow/employees": "/api/system/workflow-employee-catalog",
    "/api/core-workflow/employees": "/api/system/workflow-employee-catalog",
    "/api/datasources": "/api/private-db-assistant/sources",
    "/api/erp/data-sources": "/api/private-db-assistant/sources",
    "/api/print/templates": "/api/templates",
    "/api/label/templates": "/api/templates",
    "/api/print/jobs": "/api/print/label-jobs/{job_id}",
}


def _legacy_probe_result(result: _T, request: Request, response: Response) -> _T:
    replacement = _PROBE_REPLACEMENTS.get(request.url.path)
    if replacement:
        target = result if isinstance(result, Response) else response
        target.headers["Deprecation"] = "@1794009600"  # 2026-11-07 UTC
        target.headers["Link"] = f'<{replacement}>; rel="successor-version"'
    return result


@router.get("/api/knowledge")
@router.get("/api/knowledge/")
@router.get("/api/knowledge/base", deprecated=True)
def knowledge_root_alias(request: Request, response: Response) -> dict[str, Any]:
    from app.fastapi_routes.knowledge_v1 import health

    return _legacy_probe_result(
        {"success": True, "alias_of": "/api/knowledge/v1/health", "data": health(request)},
        request,
        response,
    )


@router.get("/api/persy/knowledge")
@router.get("/api/persy/knowledge/")
def persy_knowledge_alias(request: Request) -> dict[str, Any]:
    from app.fastapi_routes.knowledge_v1 import dataset_status

    return cast(
        "dict[str, Any]",
        dataset_status("persy-knowledge", request, include_documents=False),
    )


@router.get("/api/workflow-employee-space/overview", deprecated=True)
@router.get("/api/workflow/employees", deprecated=True)
@router.get("/api/employees")
@router.get("/api/core-workflow/employees", deprecated=True)
async def workflow_employees_alias(request: Request, response: Response) -> dict[str, Any]:
    from app.fastapi_routes.system_routes import get_workflow_employee_catalog

    return _legacy_probe_result(
        cast("dict[str, Any]", await get_workflow_employee_catalog()), request, response
    )


@router.get("/api/data-sources")
@router.get("/api/datasources", deprecated=True)
@router.get("/api/erp/data-sources", deprecated=True)
def data_sources_alias(request: Request, response: Response) -> dict[str, Any]:
    """数据来源页实际走微信/私有库适配器；此处返回可发现的来源目录。"""
    sources = [
        {
            "id": "private_db_assistant",
            "name": "私有库助手",
            "kind": "private_db",
            "apis": ["/api/private-db-assistant/sources"],
        }
    ]
    return _legacy_probe_result(
        {"success": True, "data": sources, "total": len(sources)}, request, response
    )


@router.get(
    "/api/print/templates",
    deprecated=True,
    dependencies=[Depends(require_scoped_business_permission("print.label"))],
)
@router.get(
    "/api/label/templates",
    deprecated=True,
    dependencies=[Depends(require_scoped_business_permission("print.label"))],
)
def print_templates_alias(request: Request, response: Response) -> Any:
    """保留旧模板响应形状，并提示迁移到 /api/templates。"""
    from app.fastapi_routes.template_api import templates_list_compat

    return _legacy_probe_result(templates_list_compat(request), request, response)


@router.get(
    "/api/print/jobs",
    deprecated=True,
    status_code=501,
    dependencies=[Depends(require_scoped_business_permission("print.label"))],
)
def print_jobs_alias(request: Request, response: Response) -> JSONResponse:
    message = "旧打印探测接口不提供任务列表，请使用创建任务返回的 job_id 查询进度。"
    return _legacy_probe_result(
        JSONResponse(
            {
                "success": False,
                "message": message,
                "error": {"code": "PRINT_JOBS_UNSUPPORTED", "message": message},
                "replacement": _PROBE_REPLACEMENTS["/api/print/jobs"],
            },
            status_code=501,
        ),
        request,
        response,
    )
