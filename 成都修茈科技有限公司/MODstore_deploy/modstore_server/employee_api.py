# mypy: disable-error-code="arg-type"
"""员工API模块，提供员工相关的API端点。"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from modstore_server.api.deps import _get_current_user, require_admin
from modstore_server.duty_roster import (
    employee_partition_meta,
)
from modstore_server.employee_api_support import (
    _annotate_employee_list_row as _annotate_employee_list_row,
)
from modstore_server.employee_api_support import (
    _assert_employee_scope_visible_to_user as _assert_employee_scope_visible_to_user,
)
from modstore_server.employee_api_support import (
    _candidate_employee_pack_ids as _candidate_employee_pack_ids,
)
from modstore_server.employee_api_support import (
    _collect_llm_context_text as _collect_llm_context_text,
)
from modstore_server.employee_api_support import (
    _employee_download_jobs_root as _employee_download_jobs_root,
)
from modstore_server.employee_api_support import (
    _employee_id_from_list_row as _employee_id_from_list_row,
)
from modstore_server.employee_api_support import (
    _list_duty_employee_rows as _list_duty_employee_rows,
)
from modstore_server.employee_api_support import (
    _load_employee_pack_with_aliases as _load_employee_pack_with_aliases,
)
from modstore_server.employee_api_support import (
    _persist_employee_outputs_for_download as _persist_employee_outputs_for_download,
)
from modstore_server.employee_api_support import (
    _reraise_employee_pack_not_found as _reraise_employee_pack_not_found,
)
from modstore_server.employee_api_support import (
    _resolve_taiyangniao_backend as _resolve_taiyangniao_backend,
)
from modstore_server.employee_api_support import _runtime_dir as _runtime_dir
from modstore_server.employee_api_support import (
    _user_may_execute_employee_pack as _user_may_execute_employee_pack,
)
from modstore_server.employee_api_support import (
    sync_triggers_after_registration as sync_triggers_after_registration,
)
from modstore_server.employee_api_uploads import (
    _employee_upload_max_bytes as _employee_upload_max_bytes,
)
from modstore_server.employee_api_uploads import (
    _employee_upload_suffix_mismatch_message as _employee_upload_suffix_mismatch_message,
)
from modstore_server.employee_api_uploads import (
    _safe_employee_upload_basename as _safe_employee_upload_basename,
)
from modstore_server.employee_api_uploads import (
    _suffix_allowed_for_employee as _suffix_allowed_for_employee,
)
from modstore_server.employee_executor import (
    get_employee_status,
)
from modstore_server.employee_executor import list_employees as list_employees_exec
from modstore_server.employee_runtime import (
    library_manifest_fallback_enabled,
)
from modstore_server.infrastructure.db import get_db
from modstore_server.models import CatalogItem, User
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.services.employee import get_default_employee_client

router = APIRouter(prefix="/api/employees", tags=["employees"])


@router.get("/", summary="获取员工列表")
async def list_employees(
    response: Response,
    scope: str = Query(
        "auto",
        description="auto|all|duty|store；duty=管理端上岗员工，store=商店员工",
    ),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """获取所有可用的 AI 员工（数据库 ``catalog_items`` 与本地 ``packages.json`` 已合并去重）。"""
    try:
        raw_scope = str(scope or "auto").strip().lower()
        if raw_scope not in ("auto", "all", "duty", "store"):
            raise HTTPException(400, "scope 必须是 auto/all/duty/store")
        is_admin = bool(getattr(user, "is_admin", False))
        if raw_scope == "duty" and not is_admin:
            raise HTTPException(403, "上岗员工仅管理端可见")
        effective_scope = ("all" if is_admin else "store") if raw_scope == "auto" else raw_scope
        employees = [_annotate_employee_list_row(e) for e in list_employees_exec()]
        duty_rows = _list_duty_employee_rows()
        if effective_scope == "duty":
            employees = duty_rows
        elif effective_scope == "store":
            employees = [e for e in employees if e.get("is_store_employee")]
        elif effective_scope == "all" and not is_admin:
            employees = [e for e in employees if not e.get("is_duty_employee")]
        elif effective_scope == "all" and is_admin:
            by_id = {
                str(e.get("employee_id") or e.get("pack_id") or e.get("pkg_id") or e.get("id")): e
                for e in employees
                if not e.get("is_duty_employee")
            }
            for e in duty_rows:
                by_id[str(e.get("employee_id") or e.get("id"))] = e
            employees = list(by_id.values())
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Employee-Scope"] = effective_scope
        return employees
    except RECOVERABLE_ERRORS as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(500, f"获取员工列表失败: {e}")


@router.get(
    "/catalog-manifest-diagnostics",
    summary="运维：员工目录与 manifest 解析路径（仅管理员）",
)
async def employee_catalog_manifest_diagnostics(
    pack_id: Optional[str] = Query(None, description="可选：检查该包 id 是否在目录或 Mod 库可解析"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """供部署排查「manifest 404」：``MODSTORE_CATALOG_DIR``、``packages.json`` 员工包行数、库目录、可选 pack 命中。"""
    from modstore_server import catalog_store

    catalog_dir = catalog_store.default_catalog_dir()
    pkg_path = catalog_store.packages_path()
    files_root = catalog_store.files_dir()
    ep_rows = 0
    try:
        for r in catalog_store.load_store().get("packages") or []:
            if (
                isinstance(r, dict)
                and str(r.get("artifact") or "").strip().lower() == "employee_pack"
            ):
                ep_rows += 1
    except RECOVERABLE_ERRORS:
        pass

    lib_root = ""
    lib_has_dir = False
    lib_manifest_ok = False
    try:
        from modman.repo_config import load_config, resolved_library

        lib = resolved_library(load_config())
        lib_root = str(lib.resolve())
        if pack_id and pack_id.strip():
            from modman.manifest_util import read_manifest
            from modman.store import find_mod_dir_by_manifest_id

            try:
                d = find_mod_dir_by_manifest_id(lib, pack_id.strip())
                lib_has_dir = d.is_dir()
                data, err = read_manifest(d)
                lib_manifest_ok = bool(not err and isinstance(data, dict))
            except (OSError, ValueError, FileNotFoundError):
                pass
    except RECOVERABLE_ERRORS as exc:
        lib_root = f"(error: {exc})"

    in_json = False
    in_db = False
    pid = (pack_id or "").strip()
    if pid:
        try:
            recs = catalog_store.employee_pack_records_from_store()
            in_json = pid in recs or any(
                catalog_store.norm_pkg_id(k) == catalog_store.norm_pkg_id(pid) for k in recs
            )
        except RECOVERABLE_ERRORS:
            pass
        try:
            in_db = (
                db.query(CatalogItem.id)
                .filter(CatalogItem.pkg_id == pid, CatalogItem.artifact == "employee_pack")
                .first()
                is not None
            )
        except RECOVERABLE_ERRORS:
            pass

    return {
        "catalog_dir": str(catalog_dir),
        "packages_json": str(pkg_path),
        "packages_json_exists": pkg_path.is_file(),
        "employee_pack_rows_in_packages_json": ep_rows,
        "files_dir": str(files_root),
        "library_manifest_fallback": library_manifest_fallback_enabled(),
        "asset_scaffold_publish_catalog_env": (
            os.environ.get("MODSTORE_EMPLOYEE_ASSET_PUBLISH_CATALOG") or ""
        ).strip(),
        "mod_library_root": lib_root,
        "probe_pack_id": pid or None,
        "probe_in_packages_json_employee_packs": in_json,
        "probe_in_catalog_items": in_db,
        "probe_library_dir_found": lib_has_dir,
        "probe_library_manifest_readable": lib_manifest_ok,
        "common_503_paths_hint": [
            "/api/llm/status",
            "/api/llm/catalog",
            "/api/employees/{id}/manifest",
        ],
    }


@router.get("/{employee_id}/status", summary="获取员工状态")
async def get_employee_status_endpoint(
    employee_id: str,
    user: User = Depends(_get_current_user),
):
    """获取员工的状态信息"""
    _assert_employee_scope_visible_to_user(employee_id, user)
    try:
        status = get_employee_status(employee_id)
        if isinstance(status, dict):
            status.update(employee_partition_meta(employee_id, "employee_pack"))
        return status
    except RECOVERABLE_ERRORS as e:
        raise HTTPException(500, f"获取员工状态失败: {e}")


@router.get("/{employee_id}/manifest", summary="获取员工包完整 manifest")
async def get_employee_manifest_endpoint(
    employee_id: str,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """读取员工包磁盘 ``.xcemp/.zip`` 的 ``manifest.json`` 全文。

    用于工作台编辑器（``WorkbenchShell.loadTarget``）回填 ``employee_config_v2``、
    ``workflow_employees[0].workflow_id/panel_summary`` 等字段；``list_employees``
    返回的轻量列表里没有这些。
    """
    _assert_employee_scope_visible_to_user(employee_id, user)
    try:
        pack = _load_employee_pack_with_aliases(db, employee_id.strip())
        response.headers["Cache-Control"] = "private, no-store"
        return pack
    except ValueError as e:
        raise HTTPException(404, str(e))
    except RECOVERABLE_ERRORS as e:
        raise HTTPException(500, f"获取员工包 manifest 失败: {e}")


@router.post("/{employee_id}/execute", summary="执行员工任务")
async def execute_employee_task_endpoint(
    employee_id: str,
    task: str,
    input_data: Optional[Dict] = None,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """执行员工任务"""
    if not _user_may_execute_employee_pack(db, user.id, employee_id):
        raise HTTPException(403, "您无权执行该员工，请先购买或订阅套餐")

    failure: str | None = None
    try:
        result = await run_in_threadpool(
            get_default_employee_client().execute_task,
            employee_id=employee_id,
            task=task,
            input_data=input_data or {},
            user_id=user.id,
        )
    except RECOVERABLE_ERRORS as e:
        _reraise_employee_pack_not_found(e)
        failure = str(e)
        result = None
    try:
        from modstore_server import webhook_dispatcher
        from modstore_server.eventing.contracts import EMPLOYEE_EXECUTION_COMPLETED

        webhook_dispatcher.publish_event(
            EMPLOYEE_EXECUTION_COMPLETED,
            aggregate_id=str(employee_id),
            data={
                "employee_id": employee_id,
                "user_id": int(user.id),
                "task": (task or "")[:256],
                "status": "failure" if failure else "success",
                "error": failure or "",
                "result_summary": (
                    (str(result)[:512] if isinstance(result, str) else "")
                    if not isinstance(result, dict)
                    else {
                        k: result.get(k)
                        for k in ("status", "ok", "duration_ms", "tokens_used")
                        if k in result
                    }
                ),
            },
            source="modstore-employee-api",
        )
    except RECOVERABLE_ERRORS:
        # 投递失败不阻塞业务回包
        pass

    if failure is not None:
        raise HTTPException(500, f"执行员工任务失败: {failure}")
    return result


@router.get(
    "/downloads/{job_id}/{filename}",
    summary="下载员工任务产出文件（execute-file 成功后返回的 job_id）",
)
async def download_employee_output_file(
    job_id: str,
    filename: str,
    user: User = Depends(_get_current_user),
):
    safe_job = "".join(c for c in job_id if c in "0123456789abcdefABCDEF")
    if safe_job != job_id or len(safe_job) < 16:
        raise HTTPException(400, "无效的 job_id")
    fn = Path(filename).name
    if not fn or fn != filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "无效的文件名")
    root = (_employee_download_jobs_root() / str(user.id) / safe_job).resolve()
    path = (root / fn).resolve()
    if path.parent != root:
        raise HTTPException(404, "文件不存在")
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    media = "application/octet-stream"
    if fn.lower().endswith(".xlsx"):
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fn.lower().endswith(".xls"):
        media = "application/vnd.ms-excel"
    elif fn.lower().endswith(".json"):
        media = "application/json"
    elif fn.lower().endswith(".html"):
        media = "text/html; charset=utf-8"
    return FileResponse(path, filename=fn, media_type=media)


@router.post("/{employee_id}/execute-file", summary="执行员工任务（上传原始附件）")
async def execute_employee_task_file_endpoint(
    employee_id: str,
    task: str = Form(""),
    input_data_json: str = Form("{}"),
    file: UploadFile = File(...),
    template_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """multipart：``file`` + ``task`` + ``input_data_json``（对象 JSON）。

    将文件保存到受控临时目录后注入 ``input_data.file_path`` / ``workspace_root``，
    再调用与 ``POST .../execute`` 相同的运行时。请求结束后删除临时目录。
    """
    if not _user_may_execute_employee_pack(db, user.id, employee_id):
        raise HTTPException(403, "您无权执行该员工，请先购买或订阅套餐")

    max_bytes = _employee_upload_max_bytes()
    payload = await file.read()
    if len(payload) > max_bytes:
        mb = max(1, max_bytes // (1024 * 1024))
        raise HTTPException(
            413,
            f"文件过大（超过 {mb}MB）。可调高 MODSTORE_EMPLOYEE_FILE_MAX_BYTES 与网关 client_max_body_size。",
        )

    safe_name = _safe_employee_upload_basename(file.filename or "")
    suffix = Path(safe_name).suffix.lower()
    if not _suffix_allowed_for_employee(employee_id, suffix):
        raise HTTPException(
            400,
            _employee_upload_suffix_mismatch_message(employee_id, suffix),
        )

    try:
        extra = json.loads(input_data_json or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "input_data_json 不是合法 JSON")
    if not isinstance(extra, dict):
        extra = {}

    repo_root = Path(__file__).resolve().parents[1]
    session_dir = repo_root / "var" / "employee_uploads" / str(user.id) / uuid.uuid4().hex
    session_dir.mkdir(parents=True, exist_ok=True)
    dest = session_dir / safe_name

    template_dest: Path | None = None
    if template_file is not None and template_file.filename:
        tpl_payload = await template_file.read()
        if len(tpl_payload) > max_bytes:
            mb = max(1, max_bytes // (1024 * 1024))
            raise HTTPException(
                413,
                f"模板文件过大（超过 {mb}MB）。",
            )
        tpl_name = _safe_employee_upload_basename(template_file.filename or "")
        template_dest = session_dir / tpl_name
        template_dest.write_bytes(tpl_payload)

    failure: str | None = None
    result: Dict | None = None
    try:
        dest.write_bytes(payload)
        input_data: Dict = {**extra}
        input_data.setdefault("action", "convert")
        input_data["file_path"] = str(dest.resolve())
        input_data["workspace_root"] = str(session_dir.resolve())
        input_data.setdefault("original_filename", safe_name)
        if template_dest is not None and template_dest.is_file():
            input_data["template_relpath"] = template_dest.name
        _resolve_taiyangniao_backend(input_data)

        result = await run_in_threadpool(
            get_default_employee_client().execute_task,
            employee_id=employee_id,
            task=task or "执行附件任务",
            input_data=input_data,
            user_id=user.id,
        )
        if isinstance(result, dict):
            llm_text = _collect_llm_context_text(session_dir, result)
            downloads = _persist_employee_outputs_for_download(
                int(user.id), session_dir, dest, result
            )
            result = dict(result)
            if llm_text:
                result["llm_context_text"] = llm_text
            if downloads:
                result["output_downloads"] = downloads
    except RECOVERABLE_ERRORS as e:
        _reraise_employee_pack_not_found(e)
        failure = str(e)
        result = None
    finally:
        try:
            if session_dir.is_dir():
                shutil.rmtree(session_dir, ignore_errors=True)
        except RECOVERABLE_ERRORS:
            pass

    try:
        from modstore_server import webhook_dispatcher
        from modstore_server.eventing.contracts import EMPLOYEE_EXECUTION_COMPLETED

        webhook_dispatcher.publish_event(
            EMPLOYEE_EXECUTION_COMPLETED,
            aggregate_id=str(employee_id),
            data={
                "employee_id": employee_id,
                "user_id": int(user.id),
                "task": (task or "")[:256],
                "status": "failure" if failure else "success",
                "error": failure or "",
                "result_summary": (
                    (str(result)[:512] if isinstance(result, str) else "")
                    if not isinstance(result, dict)
                    else {
                        k: result.get(k)
                        for k in ("status", "ok", "duration_ms", "tokens_used")
                        if k in result
                    }
                ),
            },
            source="modstore-employee-api",
        )
    except RECOVERABLE_ERRORS:
        pass

    if failure is not None:
        raise HTTPException(500, f"执行员工任务失败: {failure}")
    return result
