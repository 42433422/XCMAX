# -*- coding: utf-8 -*-
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


class OfficeSampleCleanupBody(BaseModel):
    file_paths: list[str] = Field(default_factory=list)


@router.post("/office-sample-upload")
async def platform_shell_office_sample_upload(file: UploadFile = File(...)):
    """教程 / 办公包演示：把样本存到 workspace/uploads/tutorial，供 Word 读取员使用。"""
    import os
    import uuid
    from pathlib import Path

    from fastapi import HTTPException

    from app.utils.secure_filename import secure_filename

    name = (file.filename or "").strip()
    suffix = Path(name).suffix.lower()
    if suffix not in {".xlsx", ".xlsm", ".docx", ".doc"}:
        raise HTTPException(status_code=400, detail="仅支持 .xlsx/.xlsm/.docx/.doc")

    workspace_root = Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).resolve()
    upload_dir = workspace_root / "uploads" / "tutorial"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe = secure_filename(name) or f"tutorial{suffix}"
    if not safe.lower().startswith("xcagi-quickstart") and "教程" not in safe:
        safe = f"xcagi-quickstart-{uuid.uuid4().hex[:8]}{suffix}"
    dest = upload_dir / safe
    dest.write_bytes(await file.read())
    try:
        rel = dest.relative_to(workspace_root).as_posix()
    except ValueError:
        rel = str(dest)
    return {
        "success": True,
        "data": {"file_path": rel, "filename": name, "workspace_root": str(workspace_root)},
    }


@router.get("/workspace-root")
async def platform_shell_workspace_root():
    import os
    from pathlib import Path

    root = Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).resolve()
    return {"success": True, "data": {"workspace_root": str(root)}}


@router.post("/chat-office-file-upload")
async def platform_shell_chat_office_file_upload(file: UploadFile = File(...)):
    """智能对话上传：存到 workspace/uploads/chat，并返回 workspace_root 供办公员工读取。"""
    import os
    import uuid
    from pathlib import Path

    from fastapi import HTTPException

    from app.utils.secure_filename import secure_filename

    name = (file.filename or "").strip()
    suffix = Path(name).suffix.lower()
    if suffix not in {".xlsx", ".xlsm", ".docx", ".doc"}:
        raise HTTPException(status_code=400, detail="仅支持 .xlsx/.xlsm/.docx/.doc")

    workspace_root = Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).resolve()
    upload_dir = workspace_root / "uploads" / "chat"
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
    return {
        "success": True,
        "data": {"file_path": rel, "filename": name, "workspace_root": str(workspace_root)},
    }


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
