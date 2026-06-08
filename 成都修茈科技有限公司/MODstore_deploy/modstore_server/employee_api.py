"""员工API模块，提供员工相关的API端点。"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user, require_admin
from modstore_server.employee_executor import (
    get_employee_status,
)
from modstore_server.employee_executor import list_employees as list_employees_exec
from modstore_server.employee_runtime import (
    library_manifest_fallback_enabled,
    load_employee_pack,
    try_load_employee_pack_from_library,
)
from modstore_server.infrastructure.db import get_db
from modstore_server.models import CatalogItem, Entitlement, User, UserPlan
from modstore_server.services.employee import get_default_employee_client

router = APIRouter(prefix="/api/employees", tags=["employees"])


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or "/tmp/modstore_runtime").expanduser()


def _employee_download_jobs_root() -> Path:
    d = _runtime_dir() / "employee_output_downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_taiyangniao_backend(input_data: Dict[str, Any]) -> None:
    """注入太阳鸟 pro 的 backend 路径（Linux 部署常用 MODSTORE_REPO_ROOT/mods/taiyangniao-pro/backend）。"""
    if input_data.get("taiyangniao_backend_path") or input_data.get("source_backend_path"):
        return
    tb = (os.environ.get("TAIYANGNIAO_BACKEND_PATH") or "").strip()
    if not tb:
        rr = (os.environ.get("MODSTORE_REPO_ROOT") or "").strip()
        if rr:
            cand = Path(rr).expanduser() / "mods" / "taiyangniao-pro" / "backend"
            if cand.is_dir():
                tb = str(cand)
    if not tb:
        here = Path(__file__).resolve().parent
        deploy_root = here.parent
        for cand in (
            deploy_root.parent / "mods" / "taiyangniao-pro" / "backend",
            deploy_root / "mods" / "taiyangniao-pro" / "backend",
        ):
            if cand.is_dir():
                tb = str(cand)
                break
    if tb:
        input_data["taiyangniao_backend_path"] = tb


_ARTIFACT_OUTPUT_SUFFIXES = (
    ".xlsx",
    ".xlsm",
    ".xls",
    ".json",
    ".csv",
    ".txt",
    ".md",
    ".pdf",
    ".pptx",
    ".docx",
    ".html",
)


def _gather_artifact_paths(obj: Any, acc: List[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in (
                "output",
                "input",
                "file_path",
                "filepath",
                "path",
                "json_file",
                "text_file",
            ) and isinstance(v, str):
                s = v.strip()
                if s.lower().endswith(_ARTIFACT_OUTPUT_SUFFIXES):
                    acc.append(s)
            else:
                _gather_artifact_paths(v, acc)
    elif isinstance(obj, list):
        for it in obj:
            _gather_artifact_paths(it, acc)


def _gather_spreadsheet_paths(obj: Any, acc: List[str]) -> None:
    _gather_artifact_paths(obj, acc)


def _list_session_output_files(session_dir: Path) -> List[Path]:
    out_dir = session_dir / "outputs"
    if not out_dir.is_dir():
        return []
    found: List[Path] = []
    for p in sorted(out_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in _ARTIFACT_OUTPUT_SUFFIXES:
            found.append(p)
    return found


def _collect_llm_context_text(
    session_dir: Path, exec_result: Dict[str, Any], *, max_chars: int = 120_000
) -> str:
    """在删除临时目录前，把读取员工 outputs 中的文本/JSON 汇总给工作台 LLM。"""
    parts: List[str] = []
    seen: set[str] = set()
    for rel in _list_session_output_files(session_dir):
        key = str(rel.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            if rel.suffix.lower() == ".json":
                data = json.loads(rel.read_text(encoding="utf-8"))
                body = json.dumps(data, ensure_ascii=False, indent=2)
            else:
                body = rel.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        body = (body or "").strip()
        if not body:
            continue
        label = str(rel.relative_to(session_dir)).replace("\\", "/")
        parts.append(f"### {label}\n{body}")

    if not parts:
        try:
            blob = json.dumps(exec_result, ensure_ascii=False, indent=2)
            if blob and blob not in ("{}", "null"):
                parts.append(f"### execute_result\n{blob}")
        except Exception:
            pass

    text = "\n\n".join(parts).strip()
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n…（已截断，原文约 {len(text)} 字符）"
    return text


def _is_reasonable_output_file(candidate: Path, upload_input: Path) -> bool:
    try:
        cr = candidate.resolve()
        ir = upload_input.resolve()
    except OSError:
        return False
    if cr == ir:
        return False
    name = candidate.name
    low = name.lower()
    if "模板" in name or "template" in low:
        return False
    if "考勤统计表" in name and "输出" not in name:
        return False
    if "输出" in name or "output" in low:
        return True
    return "424" in candidate.parts


def _persist_employee_outputs_for_download(
    user_id: int,
    session_dir: Path,
    upload_dest: Path,
    exec_result: Dict[str, Any],
) -> List[Dict[str, str]]:
    raw_paths: List[str] = []
    _gather_artifact_paths(exec_result, raw_paths)
    seen: set[str] = set()
    unique: List[Path] = []
    session_resolved = session_dir.resolve()
    for p in _list_session_output_files(session_dir):
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    for p_raw in raw_paths:
        try:
            p = Path(p_raw).expanduser()
            if not p.is_file():
                continue
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            low = p.suffix.lower()
            under_outputs = False
            try:
                p.resolve().relative_to(session_resolved / "outputs")
                under_outputs = True
            except ValueError:
                pass
            if not under_outputs and low not in (".json", ".csv", ".txt", ".md"):
                if not _is_reasonable_output_file(p, upload_dest):
                    continue
            try:
                p.resolve().relative_to(session_resolved)
            except ValueError:
                continue
            unique.append(p)
        except OSError:
            continue
    if not unique:
        return []
    job_id = uuid.uuid4().hex
    job_dir = (_employee_download_jobs_root() / str(user_id) / job_id).resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    meta: List[Dict[str, str]] = []
    for i, src in enumerate(unique):
        dest_name = src.name
        dest = job_dir / dest_name
        if dest.exists():
            stem = dest.stem
            suf = dest.suffix
            dest = job_dir / f"{stem}_{i}{suf}"
        shutil.copy2(src, dest)
        label = (
            "下载转换结果" if ("输出" in dest.name or "output" in dest.name.lower()) else dest.name
        )
        meta.append({"job_id": job_id, "filename": dest.name, "label": label})
    return meta


def sync_triggers_after_registration(manifest: Dict) -> None:
    """员工包注册/更新后，同步其 triggers 到 DB（后台静默执行）。"""
    try:
        from modstore_server.sync_employee_triggers import sync_triggers_for_manifest

        sync_triggers_for_manifest(manifest)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("sync_triggers_after_registration failed")


def _user_may_execute_employee_pack(db: Session, user_id: int, pack_id: str) -> bool:
    """路径参数 ``employee_id`` 与 ``CatalogItem.pkg_id`` 一致（见 employee_runtime.load_employee_pack）。"""
    u = db.query(User).filter(User.id == user_id).first()
    if u and getattr(u, "is_admin", False):
        return True

    row = (
        db.query(CatalogItem)
        .filter(CatalogItem.pkg_id == pack_id.strip(), CatalogItem.artifact == "employee_pack")
        .first()
    )
    if not row:
        return False
    if row.author_id is not None and int(row.author_id) == int(user_id):
        return True

    ent = (
        db.query(Entitlement)
        .filter(
            Entitlement.user_id == user_id,
            Entitlement.catalog_id == row.id,
            Entitlement.is_active == True,
        )
        .first()
    )
    if ent:
        return True

    if bool(getattr(row, "is_public", False)) and float(row.price or 0) <= 0:
        return True

    now = datetime.now(timezone.utc)
    plan = (
        db.query(UserPlan)
        .filter(UserPlan.user_id == user_id, UserPlan.is_active == True)
        .order_by(UserPlan.id.desc())
        .first()
    )
    if not plan:
        return False
    exp = plan.expires_at
    if exp is None:
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > now


def _candidate_employee_pack_ids(employee_id: str) -> List[str]:
    raw = (employee_id or "").strip()
    if not raw:
        return []
    candidates = [raw]
    dashed = raw.replace("_", "-")
    underscored = raw.replace("-", "_")
    for item in (dashed, underscored, f"{dashed}-employee", f"{underscored}_employee"):
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def _load_employee_pack_with_aliases(db: Session, employee_id: str) -> Dict[str, Any]:
    """目录（DB + ``packages.json``）优先；未命中时可选从 Mod 库目录读取。"""
    from modstore_server.employee_runtime import load_employee_pack_resolved

    return load_employee_pack_resolved(db, employee_id)


@router.get("/", summary="获取员工列表")
async def list_employees(
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """获取所有可用的 AI 员工（数据库 ``catalog_items`` 与本地 ``packages.json`` 已合并去重）。"""
    try:
        employees = list_employees_exec()
        response.headers["Cache-Control"] = "private, no-store"
        return employees
    except Exception as e:
        raise HTTPException(500, f"获取员工列表失败: {e}")


@router.get(
    "/catalog-manifest-diagnostics", summary="运维：员工目录与 manifest 解析路径（仅管理员）"
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
    except Exception:
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
    except Exception as exc:
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
        except Exception:
            pass
        try:
            in_db = (
                db.query(CatalogItem.id)
                .filter(CatalogItem.pkg_id == pid, CatalogItem.artifact == "employee_pack")
                .first()
                is not None
            )
        except Exception:
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
    try:
        status = get_employee_status(employee_id)
        return status
    except Exception as e:
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
    try:
        pack = _load_employee_pack_with_aliases(db, employee_id.strip())
        response.headers["Cache-Control"] = "private, no-store"
        return pack
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
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
        result = get_default_employee_client().execute_task(
            employee_id=employee_id,
            task=task,
            input_data=input_data or {},
            user_id=user.id,
        )
    except Exception as e:
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
    except Exception:
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


_EMPLOYEE_UPLOAD_MAX_DEFAULT = 100 * 1024 * 1024
_EMPLOYEE_UPLOAD_ALLOWED_SUFFIX = frozenset(
    {
        ".xlsx",
        ".xlsm",
        ".xls",
        ".csv",
        ".pdf",
        ".pptx",
        ".ppt",
        ".docx",
        ".doc",
        ".docm",
        ".dotx",
        ".dotm",
        ".rtf",
        ".json",
        ".txt",
    }
)
_READ_EMPLOYEE_SUFFIX: Dict[str, frozenset] = {
    "excel-full-read-employee": frozenset({".xlsx", ".xlsm", ".xls"}),
    "csv-full-read-employee": frozenset({".csv"}),
    "pdf-full-read-employee": frozenset({".pdf"}),
    "ppt-full-read-employee": frozenset({".pptx", ".ppt"}),
    "word-full-read-employee": frozenset({".docx", ".doc", ".docm", ".dotx", ".dotm", ".rtf"}),
    "json-report-employee": frozenset({".json"}),
}


def _suffix_allowed_for_employee(employee_id: str, suffix: str) -> bool:
    if suffix not in _EMPLOYEE_UPLOAD_ALLOWED_SUFFIX:
        return False
    from modstore_server.office_plaintext_generate import (
        GENERATE_EMPLOYEE_IDS,
        suffix_allowed_for_generate_employee,
    )

    for pid in _candidate_employee_pack_ids(employee_id):
        if pid in GENERATE_EMPLOYEE_IDS:
            return suffix_allowed_for_generate_employee(pid, suffix)
        allowed = _READ_EMPLOYEE_SUFFIX.get(pid)
        if allowed is not None:
            return suffix in allowed
    read_hint = {
        ".pptx": "ppt-full-read-employee",
        ".ppt": "ppt-full-read-employee",
        ".docx": "word-full-read-employee",
        ".doc": "word-full-read-employee",
        ".xlsx": "excel-full-read-employee",
        ".csv": "csv-full-read-employee",
        ".pdf": "pdf-full-read-employee",
    }.get(suffix)
    if read_hint:
        return False
    return True


def _employee_upload_suffix_mismatch_message(employee_id: str, suffix: str) -> str:
    """Human-readable hint when execute-file suffix does not match selected employee."""
    from modstore_server.office_plaintext_generate import GENERATE_EMPLOYEE_IDS

    ext = suffix.lstrip(".").lower() or "未知"
    read_for_suffix = {
        ".pptx": ("ppt-full-read-employee", "PPT 全量读取员"),
        ".ppt": ("ppt-full-read-employee", "PPT 全量读取员"),
        ".docx": ("word-full-read-employee", "Word 全量读取员"),
        ".doc": ("word-full-read-employee", "Word 全量读取员"),
        ".docm": ("word-full-read-employee", "Word 全量读取员"),
        ".dotx": ("word-full-read-employee", "Word 全量读取员"),
        ".dotm": ("word-full-read-employee", "Word 全量读取员"),
        ".rtf": ("word-full-read-employee", "Word 全量读取员"),
        ".xlsx": ("excel-full-read-employee", "Excel 全量读取员"),
        ".xlsm": ("excel-full-read-employee", "Excel 全量读取员"),
        ".xls": ("excel-full-read-employee", "Excel 全量读取员"),
        ".csv": ("csv-full-read-employee", "CSV 全量读取员"),
        ".pdf": ("pdf-full-read-employee", "PDF 全量读取员"),
    }
    generate_for_suffix = {
        ".pptx": ("ppt-generate-employee", "PPT 生成员"),
        ".ppt": ("ppt-generate-employee", "PPT 生成员"),
        ".docx": ("word-generate-employee", "Word 生成员"),
        ".xlsx": ("excel-generate-employee", "Excel 生成员"),
        ".csv": ("csv-generate-employee", "CSV 生成员"),
        ".pdf": ("pdf-generate-employee", "PDF 生成员"),
    }

    pack_ids = _candidate_employee_pack_ids(employee_id)
    is_generate = any(pid in GENERATE_EMPLOYEE_IDS for pid in pack_ids)

    if suffix not in _EMPLOYEE_UPLOAD_ALLOWED_SUFFIX:
        return f"不支持 .{ext} 上传；读取类支持 Office/PDF，生成员支持 .json/.txt（Word 生成员可选 .docx 模板）"

    read_hint = read_for_suffix.get(suffix)
    if read_hint and is_generate:
        rid, rlabel = read_hint
        gid, glabel = generate_for_suffix.get(suffix, ("", ""))
        gen_part = (
            f"；若要从 JSON 生成 PPT，请先由「{rlabel}」（{rid}）导出 presentation_full.json，再选「{glabel}」（{gid}）"
            if suffix in {".pptx", ".ppt"} and gid
            else f"；请改选「{rlabel}」（{rid}）全量解析该文件"
        )
        return (
            f"生成员「{employee_id}」不接受 .{ext} 原稿{gen_part}。"
            f"生成员仅支持 .json/.txt（Word 生成员可选 .docx 模板）"
        )

    if read_hint:
        rid, rlabel = read_hint
        return f"当前员工不接受 .{ext}；请改选「{rlabel}」（{rid}）"

    if suffix == ".json":
        return (
            "JSON 文件请使用 json-report-employee（量化报告）或对应格式的 *-generate-employee（生成 Office）；"
            "生成员不接受 .pptx/.docx 等原稿"
        )

    return (
        "文件类型与所选员工不匹配；生成员支持 .json/.txt（Word 生成员可选 .docx 模板），"
        "读取类支持 Office/PDF（含 .pptx/.docx/.xlsx/.pdf 等）"
    )


def _employee_upload_max_bytes() -> int:
    raw = (os.environ.get("MODSTORE_EMPLOYEE_FILE_MAX_BYTES") or "").strip()
    if not raw:
        return _EMPLOYEE_UPLOAD_MAX_DEFAULT
    try:
        return max(1, int(raw, 10))
    except ValueError:
        return _EMPLOYEE_UPLOAD_MAX_DEFAULT


def _safe_employee_upload_basename(name: str, fallback: str = "upload.xlsx") -> str:
    base = Path(name or "").name
    if not base or base in {".", ".."}:
        return fallback
    if ".." in base or "/" in base or "\\" in base:
        return fallback
    return base[:200] if len(base) > 200 else base


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

        result = get_default_employee_client().execute_task(
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
    except Exception as e:
        failure = str(e)
        result = None
    finally:
        try:
            if session_dir.is_dir():
                shutil.rmtree(session_dir, ignore_errors=True)
        except Exception:
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
    except Exception:
        pass

    if failure is not None:
        raise HTTPException(500, f"执行员工任务失败: {failure}")
    return result
