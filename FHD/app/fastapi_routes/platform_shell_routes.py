"""GET /api/platform-shell/capabilities - host capability inventory (phase 4)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from app.infrastructure.auth.dependencies import require_identified_user
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
async def platform_shell_deliverable_status(request: Request):
    """Deliverable acceptance: edition pack, mod routes, recommended next step."""
    from app.mod_sdk.deliverable_status import build_deliverable_status

    return {"success": True, "data": build_deliverable_status(app=request.app)}


@router.get("/industry-baseline")
async def platform_shell_industry_baseline(request: Request, industry_id: str = "general"):
    """Suggested baseline mods for an industry (chat + industry pack + account)."""
    from app.mod_sdk.industry_baseline import build_industry_baseline_plan_for_request

    return {
        "success": True,
        "data": await build_industry_baseline_plan_for_request(request, industry_id),
    }


@router.get("/onboarding-industries")
async def platform_shell_onboarding_industries(request: Request):
    """Onboarding industry picker; enterprise filters by entitlement."""
    from app.mod_sdk.industry_baseline import build_onboarding_industry_catalog_for_request

    return {"success": True, "data": await build_onboarding_industry_catalog_for_request(request)}


@router.get("/employee-planner-status")
async def platform_shell_employee_planner_status():
    """Office employee_pack install state vs Planner tool registry."""
    from app.mod_sdk.employee_tool_registry import build_employee_tools_status

    return {"success": True, "data": build_employee_tools_status()}


@router.get("/employee-tools")
async def platform_shell_employee_tools():
    """Loaded employee_pack tool summary + runtime missing warnings."""
    from app.mod_sdk.employee_tool_registry import build_employee_tools_status

    return {"success": True, "data": build_employee_tools_status()}


def _employee_directory_for_request(request: Request) -> tuple[list[dict], bool]:
    from app.fastapi_routes.system_routes import _is_platform_admin
    from app.infrastructure.auth.dependencies import get_logged_in_user
    from app.mod_sdk.employee_directory import visible_employee_directory

    user = get_logged_in_user(request)
    include_admin = _is_platform_admin(user)
    return visible_employee_directory(request, include_admin=include_admin), include_admin


@router.get("/employee-directory", dependencies=[Depends(require_identified_user)])
async def platform_shell_employee_directory(request: Request, response: Response):
    """统一员工目录：智能对话 / 员工工作台 / 信息形象 共用同一份可用员工名单。

    展示口径包含 prompt-only 员工（对话型专家），执行类接口仍只取 runtime_ok。
    """
    employees, include_admin = _employee_directory_for_request(request)
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "success": True,
        "data": {
            "employees": employees,
            "count": len(employees),
            "scope": "platform" if include_admin else "tenant",
        },
    }


@router.get("/employee-ssot", dependencies=[Depends(require_identified_user)])
async def platform_shell_employee_ssot(request: Request, response: Response):
    """Employee & department SSOT derived views.

    Source ``config/duty_roster.json`` derives:
    * ``admin`` - admin 6 depts + on-duty employees.
    * ``enterprise`` - enterprise 4 layers + listed/unlisted employees.
    """
    from app.mod_sdk.employee_directory import scope_employee_ssot
    from app.mod_sdk.employee_ssot import derive_employee_ssot

    employees, include_admin = _employee_directory_for_request(request)
    response.headers["Cache-Control"] = "private, no-store"
    payload = derive_employee_ssot(installed_ids={row["pack_id"] for row in employees})
    return {
        "success": True,
        "data": scope_employee_ssot(payload, employees, include_admin=include_admin),
    }


class OfficeSampleCleanupBody(BaseModel):
    file_paths: list[str] = Field(default_factory=list)


class WorkspaceReadFilesBody(BaseModel):
    workspace_root: str = ""
    file_paths: list[str] = Field(default_factory=list)


class OfficeConfirmBody(BaseModel):
    intent: str = Field(
        ..., description="attendance | erp_products | knowledge_only | elt_parse | elt_save"
    )
    file_path: str = ""
    workspace_root: str = ""
    source_name: str = ""
    knowledge_text: str = ""
    field_mapping: dict[str, str] = Field(default_factory=dict)
    template_index: int = -1


def _office_upload_suffixes() -> set[str]:
    from app.application.office_parse_app_service import OFFICE_UPLOAD_SUFFIXES

    return set(OFFICE_UPLOAD_SUFFIXES)


async def _save_workspace_upload(file: UploadFile, *, subdir: str, user) -> dict[str, str]:
    import os
    import uuid
    from pathlib import Path

    from fastapi import HTTPException

    from app.utils.security.secure_filename import secure_filename

    name = (file.filename or "").strip()
    suffix = Path(name).suffix.lower()
    from app.application.elt.parsers import OCR_SUFFIXES

    allowed = _office_upload_suffixes() | (OCR_SUFFIXES if subdir == "chat" else set())
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported office file type: {suffix or '(no extension)'}",
        )

    workspace_root = Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).resolve()
    upload_dir = workspace_root / "uploads" / subdir
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe = secure_filename(name) or f"upload{suffix}"
    if not safe.lower().endswith(suffix):
        safe = f"{safe}{suffix}"
    dest = upload_dir / f"{uuid.uuid4().hex[:12]}-{safe}"
    from io import BytesIO

    from app.application.elt.errors import EltError
    from app.application.elt.parsers import SUPPORTED_SUFFIXES
    from app.application.elt.service_uploads import register_chat_upload

    raw = await file.read()
    attachment = {
        "attachment_warning": "此格式未取得可信附件凭证，请另存为 .xlsx 后重新上传用于智能对话。"
    }
    if suffix in SUPPORTED_SUFFIXES:
        try:
            receipt = register_chat_upload(user, name, file.content_type, BytesIO(raw))
            attachment = {"upload_id": receipt["upload_id"]}
        except EltError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    dest.write_bytes(raw)
    try:
        rel = dest.relative_to(workspace_root).as_posix()
    except ValueError:
        rel = str(dest)
    return {
        "file_path": rel,
        "filename": name,
        "workspace_root": str(workspace_root),
        **attachment,
    }


@router.post("/workspace-read-files", response_model=dict[str, object])
async def platform_shell_workspace_read_files(body: WorkspaceReadFilesBody):
    """Read approved output files located under the selected workspace."""
    from app.application.office_parse_app_service import read_workspace_output_files

    files = read_workspace_output_files(body.workspace_root, body.file_paths or [])
    return {"success": True, "data": {"files": files}}


@router.post("/office/confirm", response_model=dict[str, object])
async def platform_shell_office_confirm(body: OfficeConfirmBody, request: Request):
    """Office confirm ingest: knowledge / business intent."""
    from fastapi import HTTPException

    intent = str(body.intent or "").strip().lower()
    if intent in {"elt_parse", "elt_save"}:
        import asyncio

        from app.application.elt.errors import EltError
        from app.application.office_parse_app_service import (
            parse_office_file_elt,
            save_office_file_elt,
        )
        from app.application.session_account_meta import enrich_session_meta_with_tenant
        from app.infrastructure.auth.dependencies import (
            resolve_session_user,
            session_id_from_request,
        )

        if not body.file_path:
            raise HTTPException(status_code=400, detail="file_path 不能为空")
        user = resolve_session_user(request)
        if user is None or getattr(user, "id", None) is None:
            raise HTTPException(status_code=401, detail="请先登录")
        tenant_id = getattr(user, "tenant_id", None)
        if not tenant_id:
            sid = session_id_from_request(request)
            meta = enrich_session_meta_with_tenant(sid, user) if sid else {}
            tenant_id = meta.get("tenant_id")
        if not tenant_id:
            raise HTTPException(status_code=400, detail="缺少 tenant_id，无法入库")
        # ELT 的模型协助按登录账号取市场模型；不绑定 owner 时会被判为「无可用模型」。
        from app.application.elt.llm_session_provider import (
            bind_elt_llm_owner,
            reset_elt_llm_owner,
        )

        llm_owner_token = bind_elt_llm_owner(int(user.id))
        try:
            if intent == "elt_parse":
                result = await asyncio.to_thread(parse_office_file_elt, body.file_path)
            else:
                result = await asyncio.to_thread(
                    save_office_file_elt,
                    body.file_path,
                    tenant_id=int(tenant_id),
                    owner_user_id=int(user.id),
                    template_index=int(body.template_index),
                )
        except EltError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
        finally:
            reset_elt_llm_owner(llm_owner_token)
        return {"success": True, "data": result}
    if intent == "knowledge_only":
        text = str(body.knowledge_text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="knowledge_text must not be empty")
        from app.application.dataset_rag_app_service import get_dataset_rag_app_service

        doc = get_dataset_rag_app_service().ingest_document(
            dataset_id="office-docking",
            source=body.source_name or "office-upload",
            text=text,
        )
        return {"success": True, "data": {"intent": intent, "document": doc}}
    if intent == "attendance":
        if not body.file_path:
            raise HTTPException(status_code=400, detail="file_path 不能为空")
        from pathlib import Path

        from app.application.attendance_import_app_service import import_attendance_workbook
        from app.mod_sdk.workspace import resolve_existing_workspace_file
        from app.utils.path_io.path_utils import get_app_data_dir

        excel_path = resolve_existing_workspace_file(body.file_path)
        db_path = Path(get_app_data_dir()) / "data" / "mod_dbs" / "taiyangniao-pro.db"
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
                "note": "仅识别为 ERP 产品表；正式导入使用 execute_erp_capability 的 elt_import.preview 核对预演，再以原 run_id 和 preview_revision 请求 elt_import.execute 并完成审批",
                "file_path": body.file_path,
            },
        }
    raise HTTPException(status_code=400, detail=f"不支持的 intent: {intent}")


class OnboardingSeedBody(BaseModel):
    industry_id: str = "general"


@router.post("/onboarding/seed-demo", response_model=dict[str, object])
async def platform_shell_onboarding_seed_demo(body: OnboardingSeedBody, request: Request):
    """Create tenant-scoped demonstration data for the selected onboarding industry."""
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


@router.get("/auth/permission-matrix", response_model=dict[str, object])
async def platform_shell_permission_matrix(request: Request):
    """Resolve the signed-in account's effective platform-shell permissions."""
    from app.application.session_account_meta import enrich_session_meta_with_tenant
    from app.domain.app_pure.auth_permission_resolver import resolve_permissions
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
async def platform_shell_office_sample_upload(
    request: Request,
    file: UploadFile = File(...),
):
    """教程 / 新手引导示例文件：保存到 workspace/uploads/tutorial。"""
    from app.infrastructure.auth.dependencies import resolve_session_user

    user = resolve_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    data = await _save_workspace_upload(file, subdir="tutorial", user=user)
    return {"success": True, "data": data}


@router.get("/workspace-root")
async def platform_shell_workspace_root():
    import os
    from pathlib import Path

    root = Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).resolve()
    return {"success": True, "data": {"workspace_root": str(root)}}


@router.post("/chat-office-file-upload")
async def platform_shell_chat_office_file_upload(
    request: Request,
    file: UploadFile = File(...),
    attachment_only: bool = False,
):
    """对话「解析办公文件」：保存到 workspace/uploads/chat，返回相对 workspace_root 的路径。"""
    from app.infrastructure.auth.dependencies import resolve_session_user

    user = resolve_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if attachment_only:
        from io import BytesIO
        from pathlib import Path

        from app.application.agent_orchestrator.attachment_inputs import MAX_ATTACHMENT_BYTES
        from app.application.elt.errors import EltError
        from app.application.elt.service_uploads import register_chat_upload

        name = (file.filename or "").strip()
        if Path(name).suffix.lower() != ".docx":
            raise HTTPException(status_code=400, detail="此入口仅接收 .docx 对话附件")
        raw = await file.read(MAX_ATTACHMENT_BYTES + 1)
        if len(raw) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail="附件过大，请上传较小的 Word 文件")
        try:
            receipt = register_chat_upload(user, name, file.content_type, BytesIO(raw))
        except EltError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        return {
            "success": True,
            "data": {"upload_id": receipt["upload_id"], "filename": receipt["file_name"]},
        }
    data = await _save_workspace_upload(file, subdir="chat", user=user)
    return {"success": True, "data": data}


@router.post("/office-sample-cleanup")
async def platform_shell_office_sample_cleanup(
    body: OfficeSampleCleanupBody | None = Body(default=None),
):
    """清理教程示例上传文件（仅限 uploads/tutorial 目录内）。"""
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
