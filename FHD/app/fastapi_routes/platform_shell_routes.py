"""GET /api/platform-shell/capabilities - host capability inventory (phase 4)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
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


@router.get("/employee-ssot")
async def platform_shell_employee_ssot():
    """Employee & department SSOT derived views.

    Source ``config/duty_roster.json`` derives:
    * ``admin`` - admin 6 depts + on-duty employees.
    * ``enterprise`` - enterprise 4 layers + listed/unlisted employees.
    """
    from app.application.ops_closure_status import _installed_employee_pack_ids
    from app.mod_sdk.employee_ssot import derive_employee_ssot

    installed: set[str] = set()
    try:
        installed = _installed_employee_pack_ids()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("employee-ssot: failed to read installed employee_pack: %s", exc)

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
            detail=f"unsupported office file type: {suffix or '(no extension)'}",
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
            raise HTTPException(status_code=400, detail="file_path ??")
        from pathlib import Path

        from app.application.attendance_import_app_service import import_attendance_workbook
        from app.mod_sdk.workspace import resolve_existing_workspace_file

        excel_path = resolve_existing_workspace_file(body.file_path)
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
                "note": "??????? import_excel_to_database ?? ERP ????",
                "file_path": body.file_path,
            },
        }
    raise HTTPException(status_code=400, detail=f"?? intent: {intent}")


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

        raise HTTPException(status_code=401, detail="????")
    tenant_id = getattr(user, "tenant_id", None)
    if not tenant_id:
        from app.application.session_account_meta import enrich_session_meta_with_tenant
        from app.infrastructure.auth.dependencies import session_id_from_request

        sid = session_id_from_request(request)
        meta = enrich_session_meta_with_tenant(sid, user) if sid else {}
        tenant_id = meta.get("tenant_id")
    if not tenant_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="?? tenant_id,????????")
    try:
        data = seed_onboarding_demo_data(tenant_id=int(tenant_id), industry_id=body.industry_id)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("onboarding seed failed for tenant=%s: %s", tenant_id, exc)
        raise HTTPException(status_code=503, detail="onboarding seed temporarily unavailable") from None
    except Exception:
        logger.exception("onboarding seed failed for tenant=%s", tenant_id)
        raise HTTPException(status_code=500, detail="onboarding seed failed") from None
    return {"success": True, "data": data}


@router.get("/auth/permission-matrix", response_model=dict[str, object])
async def platform_shell_permission_matrix(request: Request):
    """Resolve the signed-in account's effective platform-shell permissions."""
    from app.application.auth_permission_resolver import resolve_permissions
    from app.application.session_account_meta import enrich_session_meta_with_tenant
    from app.infrastructure.auth.dependencies import resolve_session_user, session_id_from_request

    user = resolve_session_user(request)
    if user is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="????")
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
    """?? / ?????:????? workspace/uploads/tutorial."""
    from app.infrastructure.auth.dependencies import resolve_session_user

    user = resolve_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="????")
    data = await _save_workspace_upload(file, subdir="tutorial")
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
):
    """??????:?? workspace/uploads/chat,??? workspace_root ???????."""
    from app.infrastructure.auth.dependencies import resolve_session_user

    user = resolve_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="????")
    data = await _save_workspace_upload(file, subdir="chat")
    return {"success": True, "data": data}


@router.post("/office-sample-cleanup")
async def platform_shell_office_sample_cleanup(
    body: OfficeSampleCleanupBody | None = Body(default=None),
):
    """?????????????(? uploads/tutorial ???)."""
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
