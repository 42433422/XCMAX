"""侧栏能力探测/旧路径兼容门面。

前端真实路径以 knowledge/v1、workflow-employee-catalog、excel/templates 等为准；
本模块补齐易被误探测的短路径，避免 404 假阴性。
"""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sidebar-capability-compat"])


@router.get("/api/knowledge")
@router.get("/api/knowledge/")
@router.get("/api/knowledge/base")
def knowledge_root_alias(request: Request) -> dict[str, Any]:
    from app.fastapi_routes.knowledge_v1 import health

    snap = health(request)
    return {
        "success": True,
        "alias_of": "/api/knowledge/v1/health",
        "data": snap,
    }


@router.get("/api/persy/knowledge")
@router.get("/api/persy/knowledge/")
def persy_knowledge_alias(request: Request) -> dict[str, Any]:
    from app.fastapi_routes.knowledge_v1 import dataset_status

    return cast(
        "dict[str, Any]",
        dataset_status("persy-knowledge", request, include_documents=False),
    )


@router.get("/api/workflow-employee-space/overview")
@router.get("/api/workflow/employees")
@router.get("/api/employees")
@router.get("/api/core-workflow/employees")
async def workflow_employees_alias() -> dict[str, Any]:
    from app.fastapi_routes.system_routes import get_workflow_employee_catalog

    return cast("dict[str, Any]", await get_workflow_employee_catalog())


@router.get("/api/data-sources")
@router.get("/api/datasources")
@router.get("/api/erp/data-sources")
def data_sources_alias() -> dict[str, Any]:
    """数据来源页实际走微信/私有库适配器；此处返回可发现的来源目录。"""
    sources = [
        {
            "id": "private_db_assistant",
            "name": "私有库助手",
            "kind": "private_db",
            "apis": ["/api/private-db-assistant/sources"],
        },
    ]
    return {"success": True, "data": sources, "total": len(sources)}


@router.get("/api/print/templates")
@router.get("/api/label/templates")
def print_templates_alias(request: Request) -> Any:
    """模板列表：对齐 /api/templates。"""
    from app.fastapi_routes.template_api import templates_list_compat

    return templates_list_compat(request)


@router.get("/api/print/jobs")
def print_jobs_alias() -> dict[str, Any]:
    return {"success": True, "data": [], "jobs": [], "total": 0}
