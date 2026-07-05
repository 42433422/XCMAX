"""GET /api/platform-shell/capabilities — 通用化宿主能力清单（阶段 4）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, File, Request, UploadFile
from pydantic import BaseModel, Field

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/platform-shell", tags=["platform-shell"])


@router.get("/capabilities")
async def platform_shell_capabilities():
    installed: list[str] = []
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        for m in get_mod_manager().list_all_mods():
            mid = str(m.get("id") or "").strip()
            if mid:
                installed.append(mid)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("platform_shell: list mods failed: %s", exc)

    from app.mod_sdk.platform_shell import build_platform_shell_payload

    return {"success": True, "data": build_platform_shell_payload(installed)}


@router.get("/decoupling-progress")
async def decoupling_progress():
    installed: list[str] = []
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        for m in get_mod_manager().list_all_mods():
            mid = str(m.get("id") or "").strip()
            if mid:
                installed.append(mid)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("decoupling-progress: list mods failed: %s", exc)

    from app.mod_sdk.decoupling_progress import build_decoupling_progress_payload

    return {"success": True, "data": build_decoupling_progress_payload(installed)}


@router.get("/deliverable-status")
async def platform_shell_deliverable_status():
    """可交付验收：edition 包是否装齐、Mod 路由是否挂载、建议下一步操作。"""
    from app.mod_sdk.deliverable_status import build_deliverable_status

    return {"success": True, "data": build_deliverable_status()}


@router.get("/industry-baseline")
async def platform_shell_industry_baseline(request: Request, industry_id: str = "通用"):
    """按行业返回建议补装的基础 Mod 清单（对话底座 + 行业基础线 + 行业包 + 账号定制）。"""
    from app.mod_sdk.industry_baseline import build_industry_baseline_plan_for_request

    return {
        "success": True,
        "data": await build_industry_baseline_plan_for_request(request, industry_id),
    }


@router.get("/onboarding-industries")
async def platform_shell_onboarding_industries(request: Request):
    """引导「行业定型」：开放可选行业及中性化行业包名；企业版按 entitlement 二级筛选。"""
    from app.mod_sdk.industry_baseline import build_onboarding_industry_catalog_for_request

    return {"success": True, "data": await build_onboarding_industry_catalog_for_request(request)}


@router.get("/employee-planner-status")
async def platform_shell_employee_planner_status():
    """办公 employee_pack 安装态 vs Planner 工具注册表（教程验收 / 设置诊断）。"""
    from app.mod_sdk.employee_tool_registry import build_employee_tools_status

    return {"success": True, "data": build_employee_tools_status()}


@router.get("/employee-tools")
async def platform_shell_employee_tools():
    """已加载 employee_pack 工具摘要 + runtime 缺失警告。"""
    from app.mod_sdk.employee_tool_registry import build_employee_tools_status

    return {"success": True, "data": build_employee_tools_status()}


@router.get("/employee-ssot")
async def platform_shell_employee_ssot():
    """员工 & 部门系统单一真相源派生视图。

    一份数据源 ``config/duty_roster.json`` 自动派生：
    * ``admin``      —— 管理端 6 部门 + 上岗员工(编制 ∩ 已安装)。
    * ``enterprise`` —— 企业端 4 部门(层) + 上架(商店)/未上架(宿主入门定制)员工。
    """
    from app.application.ops_closure_status import _installed_employee_pack_ids
    from app.mod_sdk.employee_ssot import derive_employee_ssot

    installed: set[str] = set()
    try:
        installed = _installed_employee_pack_ids()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("employee-ssot: 读取已安装 employee_pack 失败: %s", exc)

    return {"success": True, "data": derive_employee_ssot(installed_ids=installed)}


class OfficeSampleCleanupBody(BaseModel):
    file_paths: list[str] = Field(default_factory=list)


class WorkspaceReadFilesBody(BaseModel):
    workspace_root: str = ""
    file_paths: list[str] = Field(default_factory=list)


class OfficeConfirmBody(BaseModel):
    intent: str = Field(..., description="attendance | erp_products | knowledge_only")
    file_path: str = ""
    workspace_root: str = ""
    source_name: str = ""
    knowledge_text: str = ""
    field_mapping: dict[str, str] = Field(default_factory=dict)


def _office_upload_suffixes() -> set[str]:
    from app.application.office_parse_app_service import OFFICE_UPLOAD_SUFFIXES

    return set(OFFICE_UPLOAD_SUFFIXES)


async def _save_workspace_upload(file: UploadFile, *, subdir: str) -> dict[str, str]:
    import os
    import uuid
    from pathlib import Path

    from fastapi import HTTPException

    from app.utils.secure_filename import secure_filename

    name = (file.filename or "").strip()
    suffix = Path(name).suffix.lower()
    if suffix not in _office_upload_suffixes():
        raise HTTPException(
            status_code=400,
            detail=f"不支持的办公文件类型: {suffix or '(无扩展名)'}",
        )

    workspace_root = Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).resolve()
    upload_dir = workspace_root / "uploads" / subdir
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe = secure_filename(name) or f"upload{suffix}"
    if not safe.lower().endswith(suffix):
        safe = f"{safe}{suffix}"
    dest = upload_dir / f"{uuid.uuid4().hex[:12]}-{safe}"
    dest.write_bytes(await file.read())
    try:
        rel = dest.relative_to(workspace_root).as_posix()
    except ValueError:
        rel = str(dest)
    return {"file_path": rel, "filename": name, "workspace_root": str(workspace_root)}


@router.post("/workspace-read-files")
async def platform_shell_workspace_read_files(body: WorkspaceReadFilesBody):
    from app.application.office_parse_app_service import read_workspace_output_files

    files = read_workspace_output_files(body.workspace_root, body.file_paths or [])
    return {"success": True, "data": {"files": files}}


@router.post("/office/confirm")
async def platform_shell_office_confirm(body: OfficeConfirmBody, request: Request):
    """平台办公确认入库：知识库 / 业务库 intent。"""
    from fastapi import HTTPException

    intent = str(body.intent or "").strip().lower()
    if intent == "knowledge_only":
        text = str(body.knowledge_text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="knowledge_text 不能为空")
        from app.application.dataset_rag_app_service import get_dataset_rag_app_service

        doc = get_dataset_rag_app_service().ingest_document(
            dataset_id="office-docking",
            source=body.source_name or "office-upload",
            text=text,
        )
        return {"success": True, "data": {"intent": intent, "document": doc}}
    if intent == "attendance":
        if not body.file_path:
            raise HTTPException(status_code=400, detail="file_path 必填")
        from pathlib import Path

        from app.application.attendance_import_app_service import import_attendance_workbook
        from app.mod_sdk.workspace import resolve_safe_workspace_relpath

        excel_path = resolve_safe_workspace_relpath(body.file_path)
        db_path = Path(body.workspace_root or ".") / "data" / "mod_dbs" / "taiyangniao-pro.db"
        result = import_attendance_workbook(
            excel_path,
            db_path,
            source_file_key=body.source_name or body.file_path,
            sync_ui_tables=True,
        )
        return {"success": True, "data": result}
    if intent == "erp_products":
        return {
            "success": True,
            "data": {
                "intent": intent,
                "note": "请通过智能对话 import_excel_to_database 完成 ERP 产品入库",
                "file_path": body.file_path,
            },
        }
    raise HTTPException(status_code=400, detail=f"未知 intent: {intent}")


class OnboardingSeedBody(BaseModel):
    industry_id: str = "通用"


@router.post("/onboarding/seed-demo")
async def platform_shell_onboarding_seed_demo(body: OnboardingSeedBody, request: Request):
    from app.application.onboarding_seed_app_service import seed_onboarding_demo_data
    from app.infrastructure.auth.dependencies import resolve_session_user

    user = resolve_session_user(request)
    if user is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="请先登录")
    tenant_id = getattr(user, "tenant_id", None)
    if not tenant_id:
        from app.application.session_account_meta import enrich_session_meta_with_tenant
        from app.infrastructure.auth.dependencies import session_id_from_request

        sid = session_id_from_request(request)
        meta = enrich_session_meta_with_tenant(sid, user) if sid else {}
        tenant_id = meta.get("tenant_id")
    if not tenant_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="缺少 tenant_id，无法写入演示数据")
    data = seed_onboarding_demo_data(tenant_id=int(tenant_id), industry_id=body.industry_id)
    return {"success": True, "data": data}


@router.get("/auth/permission-matrix")
async def platform_shell_permission_matrix(request: Request):
    from app.application.auth_permission_resolver import resolve_permissions
    from app.application.session_account_meta import enrich_session_meta_with_tenant
    from app.infrastructure.auth.dependencies import resolve_session_user, session_id_from_request

    user = resolve_session_user(request)
    if user is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="请先登录")
    sid = session_id_from_request(request)
    meta = enrich_session_meta_with_tenant(sid, user) if sid else {}
    account_kind = str(meta.get("account_kind") or getattr(user, "tier", "") or "personal")
    return {
        "success": True,
        "data": resolve_permissions(user=user, account_kind=account_kind, session_meta=meta),
    }


@router.post("/office-sample-upload")
async def platform_shell_office_sample_upload(file: UploadFile = File(...)):
    """教程 / 办公包演示：把样本存到 workspace/uploads/tutorial。"""
    data = await _save_workspace_upload(file, subdir="tutorial")
    return {"success": True, "data": data}


@router.get("/workspace-root")
async def platform_shell_workspace_root():
    import os
    from pathlib import Path

    root = Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).resolve()
    return {"success": True, "data": {"workspace_root": str(root)}}


@router.post("/chat-office-file-upload")
async def platform_shell_chat_office_file_upload(file: UploadFile = File(...)):
    """智能对话上传：存到 workspace/uploads/chat，并返回 workspace_root 供办公员工读取。"""
    data = await _save_workspace_upload(file, subdir="chat")
    return {"success": True, "data": data}


@router.post("/office-sample-cleanup")
async def platform_shell_office_sample_cleanup(
    body: OfficeSampleCleanupBody | None = Body(default=None),
):
    """删除教程上传的临时办公样本（仅 uploads/tutorial 下路径）。"""
    import os
    from pathlib import Path

    workspace_root = Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).resolve()
    tutorial_root = (workspace_root / "uploads" / "tutorial").resolve()
    removed: list[str] = []
    for raw in (body.file_paths if body else []) or []:
        rel = str(raw or "").strip().lstrip("/").replace("\\", "/")
        if not rel:
            continue
        candidate = (workspace_root / rel).resolve()
        if (
            not str(candidate).startswith(str(tutorial_root) + os.sep)
            and candidate != tutorial_root
        ):
            continue
        if candidate.is_file():
            try:
                candidate.unlink()
                removed.append(rel)
            except OSError:
                pass
    return {"success": True, "data": {"removed": removed}}
