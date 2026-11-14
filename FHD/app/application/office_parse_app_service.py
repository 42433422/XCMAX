"""平台办公文件解析：统一调度 office full-read 员工 Mod。"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

OFFICE_UPLOAD_SUFFIXES = frozenset(
    {".xlsx", ".xlsm", ".xls", ".csv", ".docx", ".doc", ".pdf", ".pptx", ".ppt"}
)

EMPLOYEE_BY_SUFFIX: dict[str, str] = {
    ".xlsx": "excel-full-read-employee",
    ".xlsm": "excel-full-read-employee",
    ".xls": "excel-full-read-employee",
    ".csv": "csv-full-read-employee",
    ".docx": "word-full-read-employee",
    ".doc": "word-full-read-employee",
    ".pdf": "pdf-full-read-employee",
    ".pptx": "ppt-full-read-employee",
    ".ppt": "ppt-full-read-employee",
}


def resolve_office_read_employee(filename: str) -> str:
    suffix = Path(str(filename or "")).suffix.lower()
    return EMPLOYEE_BY_SUFFIX.get(suffix, "")


def is_office_docking_file(filename: str) -> bool:
    return Path(str(filename or "")).suffix.lower() in OFFICE_UPLOAD_SUFFIXES


async def run_office_read_employee(
    employee_id: str,
    *,
    file_path: str,
    workspace_root: str,
    output_relpath: str | None = None,
) -> dict[str, Any]:
    """调用已加载 employee_pack 的 /run 语义（进程内 dispatch）。"""
    from app.mod_sdk.mods_bus import import_mod_backend_py

    mod_id = str(employee_id or "").strip()
    if not mod_id:
        raise ValueError("缺少 employee_id")

    mod_path = ""
    try:
        from app.infrastructure.mods.registry import get_mod_registry

        meta = get_mod_registry().get_mod_metadata(mod_id)
        mod_path = str(getattr(meta, "mod_path", "") or "")
    except RECOVERABLE_ERRORS:
        logger.debug("office parse mod lookup failed", exc_info=True)

    if not mod_path:
        from pathlib import Path as _Path

        guess = _Path(__file__).resolve().parents[2] / "mods" / "_employees" / mod_id
        if guess.is_dir():
            mod_path = str(guess)
    if not mod_path:
        raise RuntimeError(f"办公员工 Mod 未找到: {mod_id}")

    payload: dict[str, Any] = {
        "file_path": file_path,
        "workspace_root": workspace_root,
        "action": "convert",
    }
    if output_relpath:
        payload["output_relpath"] = output_relpath

    stem = mod_id.replace("-", "_")
    blueprints = import_mod_backend_py(mod_path, mod_id, "blueprints")
    dispatch = getattr(blueprints, "_dispatch_run", None) if blueprints else None
    if not callable(dispatch):
        raise RuntimeError(f"员工 Mod 缺少 dispatch: {mod_id}")
    result = await dispatch(mod_id, mod_id, stem, payload)
    if isinstance(result, dict) and result.get("success") is False:
        raise RuntimeError(str(result.get("message") or result.get("error") or "员工执行失败"))
    data = result.get("data") if isinstance(result, dict) else result
    return data if isinstance(data, dict) else {"raw": data}


def read_workspace_output_files(
    workspace_root: str,
    file_paths: list[str],
    *,
    max_bytes: int = 2_097_152,
) -> list[dict[str, Any]]:
    from fastapi import HTTPException

    from app.infrastructure.workspace import (
        resolve_existing_file_under_root,
    )
    from app.infrastructure.workspace import (
        workspace_root as configured_workspace_root,
    )

    base = configured_workspace_root()
    out: list[dict[str, Any]] = []
    for raw in file_paths:
        raw_path = str(raw or "").strip()
        if not raw_path:
            continue
        normalized = raw_path.replace("\\", "/")
        base_text = base.as_posix().rstrip("/")
        if normalized.startswith(f"{base_text}/"):
            rel = normalized[len(base_text) + 1 :]
        elif normalized.startswith("/") or (len(normalized) >= 3 and normalized[1:3] == ":/"):
            out.append({"path": raw_path, "kind": "text", "error": "invalid_path"})
            continue
        else:
            rel = normalized.lstrip("/")
        try:
            path = resolve_existing_file_under_root(base, rel)
        except FileNotFoundError:
            out.append({"path": rel, "kind": "text", "error": "file_not_found"})
            continue
        except (ValueError, OSError, HTTPException):
            out.append({"path": rel, "kind": "text", "error": "invalid_path"})
            continue
        try:
            blob = path.read_bytes()[:max_bytes]
        except OSError:
            out.append({"path": rel, "kind": "text", "error": "read_failed"})
            continue
        suffix = path.suffix.lower()
        if suffix == ".json":
            import json

            try:
                parsed = json.loads(blob.decode("utf-8", errors="replace"))
                out.append(
                    {
                        "path": rel,
                        "kind": "json",
                        "json": parsed if isinstance(parsed, dict) else {"value": parsed},
                    }
                )
                continue
            except json.JSONDecodeError:
                pass
        text = blob.decode("utf-8", errors="replace")
        out.append({"path": rel, "kind": "text", "text": text})
    return out


_OFFICE_ACTION_RE = re.compile(r"导入|入库|解析办公")
_OFFICE_PATH_RE = re.compile(
    r"@?((?:[^\s'\"<>])+?\.(?:xlsx|xlsm|xls|csv|docx|doc|pdf|pptx|ppt))"
    r"(?=$|[\s,，。.!！?？]|导入|入库)",
    re.IGNORECASE,
)
_SHEET_LABEL_RE = re.compile(r"(?:工作表|sheet)\s*[:：]?\s*([^\s,，。]+)", re.IGNORECASE)
_PREVIEW_READY = "preview_ready"
_PREVIEW_FAILED = {"failed", "error", "interrupted"}


def is_office_elt_chat_message(message: str) -> bool:
    text = str(message or "")
    return bool(_OFFICE_ACTION_RE.search(text) and _OFFICE_PATH_RE.search(text))


def _resolve_office_path(file_path: str) -> Path:
    from urllib.parse import unquote

    from app.application.elt.errors import EltError
    from app.infrastructure.workspace import resolve_existing_workspace_file, workspace_root

    raw = unquote(str(file_path or "").strip()).replace("\\", "/")
    if raw.startswith("@"):
        raw = raw[1:]
    root = workspace_root().as_posix().rstrip("/")
    if raw.startswith(f"{root}/"):
        raw = raw[len(root) + 1 :]
    raw = raw.lstrip("/")
    try:
        return resolve_existing_workspace_file(raw)
    except FileNotFoundError as exc:
        raise EltError("ELT_UPLOAD_MISSING", "找不到要入库的办公文件", status_code=404) from exc
    except (ValueError, OSError) as exc:
        raise EltError("ELT_UPLOAD_PATH_INVALID", "办公文件路径无效") from exc


def _elt_parse_path(path: Path) -> tuple[Path, Path | None]:
    if path.suffix.lower() != ".xls":
        return path, None
    from uuid import uuid4

    from app.application.elt.errors import EltError, ReviewedExcelError
    from app.application.reviewed_excel_legacy import ensure_slice_workbook
    from app.utils.path_io.path_utils import get_app_data_dir

    try:
        data, _receipt = ensure_slice_workbook(path.read_bytes())
    except ReviewedExcelError as exc:
        raise EltError("ELT_FILE_TYPE_UNSUPPORTED", str(exc)) from exc
    # 转换后的工作簿必须落在 ELT 受信根内，否则后续 resolve_elt_path 会拒绝系统临时目录。
    staging_root = Path(get_app_data_dir()).resolve() / "temp_excel"
    staging_root.mkdir(parents=True, exist_ok=True)
    converted = staging_root / f"{path.stem}-{uuid4().hex}.xlsx"
    converted.write_bytes(data)
    return converted, converted


def _elt_target(detection: dict[str, Any], suffix: str) -> str:
    from app.application.elt.parsers import KNOWLEDGE_ONLY_SUFFIXES

    target = str(detection.get("target_type") or "")
    if suffix in KNOWLEDGE_ONLY_SUFFIXES:
        return "knowledge"
    if target in {
        "products",
        "customers",
        "customer_products",
        "shipment_records",
        "attendance",
        "purchase_orders",
        "knowledge",
    }:
        return target
    # 未确认的文件（配方单、财务台账等）没有匹配的业务主数据目标：
    # 退回知识库，避免把逐笔流水或工艺记录写进产品/客户表。
    return "knowledge"


def _worksheet_templates(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        return []
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    try:
        templates: list[dict[str, str]] = []
        for worksheet in workbook.worksheets:
            if getattr(worksheet, "sheet_state", "visible") in {"hidden", "veryHidden"}:
                continue
            title = str(worksheet.title)
            templates.append({"id": title, "label": title, "sheet": title})
        return templates
    finally:
        workbook.close()


def _one_sheet(data: bytes, sheet: str) -> bytes:
    from io import BytesIO

    from openpyxl import load_workbook

    workbook = load_workbook(BytesIO(data))
    try:
        if sheet not in workbook.sheetnames:
            return data
        for name in list(workbook.sheetnames):
            if name != sheet:
                del workbook[name]
        out = BytesIO()
        workbook.save(out)
        return out.getvalue()
    finally:
        workbook.close()


def _stage_bytes(path: Path, template: dict[str, Any] | None) -> tuple[bytes, str]:
    data = path.read_bytes()
    name = path.name
    suffix = path.suffix.lower()
    if suffix == ".xls":
        from app.application.elt.errors import EltError, ReviewedExcelError
        from app.application.reviewed_excel_legacy import ensure_slice_workbook

        try:
            data, _receipt = ensure_slice_workbook(data)
        except ReviewedExcelError as exc:
            raise EltError("ELT_FILE_TYPE_UNSUPPORTED", str(exc)) from exc
        name = f"{path.stem}.xlsx"
        suffix = ".xlsx"
    if template and suffix in {".xlsx", ".xlsm"}:
        sheet = str(template.get("sheet") or "")
        data = _one_sheet(data, sheet)
        name = f"{Path(name).stem}-{sheet or 'sheet'}{suffix}"
    return data, name


def parse_office_file_elt(file_path: str) -> dict[str, Any]:
    """Parse one office file with the docking ELT parser. Worksheets stay optional."""
    from app.application.elt.parsers import parse_file
    from app.application.elt.target_detection import detect_elt_target

    path = _resolve_office_path(file_path)
    parse_path, cleanup = _elt_parse_path(path)
    try:
        detection = detect_elt_target(parse_path)
        target = _elt_target(detection, parse_path.suffix.lower())
        dataset = parse_file(parse_path, target_type=target)
        try:
            row_count = len(dataset.rows or [])
            headers = [str(item) for item in (dataset.headers or [])[:12]]
            warnings = [
                str(item.get("message") if isinstance(item, dict) else item)
                for item in (dataset.warnings or [])[:4]
            ]
        finally:
            dataset.close()
        templates = _worksheet_templates(parse_path)
    finally:
        if cleanup is not None:
            cleanup.unlink(missing_ok=True)
    return {
        "pipeline": "elt",
        "file_path": file_path,
        "file_name": path.name,
        "target_type": target,
        "detection": detection,
        "templates": templates,
        "selected_template_index": -1,
        "row_count": row_count,
        "headers": headers,
        "warnings": warnings,
        "template_candidate": str(detection.get("document_type") or "") == "recipe_sheet",
        "summary": f"ELT 已解析 {path.name}，{row_count} 行。工作表模板可选，当前未选用。",
    }


def _preview_ready(run: dict[str, Any] | None) -> bool:
    return (
        run is not None
        and str(run.get("status") or "") == _PREVIEW_READY
        and bool(run.get("preview_revision"))
    )


def _await_office_preview(service: Any, db: Any, run_id: str, owner: int, wait_seconds: float):
    if wait_seconds <= 0 or not run_id:
        return None
    deadline = time.monotonic() + wait_seconds
    last = None
    while time.monotonic() < deadline:
        time.sleep(0.4)
        expire = getattr(db, "expire_all", None)
        if callable(expire):
            expire()
        last = service.get_run(db, run_id=run_id, owner_user_id=owner)
        if _preview_ready(last):
            return last
        if str((last or {}).get("status") or "") in _PREVIEW_FAILED:
            return None
    return last if _preview_ready(last) else None


def _plan_from_preview(
    owned_path: str,
    *,
    file_name: str,
    owner: int,
    upload_id: str,
    run: dict[str, Any],
    detection: dict[str, Any],
    sha: str,
) -> dict[str, Any] | None:
    from app.application.elt.auto_ingest_service import get_auto_ingest_service
    from app.application.elt.errors import EltError
    from app.request_active_mod_ctx import get_request_active_mod_id

    try:
        knowledge = get_auto_ingest_service().knowledge_plan(
            path=Path(owned_path),
            file_name=file_name,
            note="",
            owner_user_id=owner,
            owned_upload_user_id=owner,
            allow_model=False,
        )
    except EltError:
        logger.debug("office elt knowledge plan skipped", exc_info=True)
        return None
    return {
        "run_id": str(run.get("id") or run.get("run_id") or ""),
        "upload_id": upload_id,
        "preview_revision": str(run.get("preview_revision") or ""),
        "target_type": str(run.get("target_type") or detection.get("target_type") or ""),
        "detection": detection,
        "name": file_name,
        "note": "",
        "mod_id": get_request_active_mod_id(),
        "candidate_sha256": sha,
        "knowledge": knowledge,
        "valid_rows_only": True,
    }


def _is_template_candidate(parsed: dict[str, Any]) -> bool:
    detection = parsed.get("detection") if isinstance(parsed.get("detection"), dict) else {}
    return str(detection.get("document_type") or "") == "recipe_sheet"


def _save_template_candidate(
    path: Path, parsed: dict[str, Any], *, tenant_id: int
) -> dict[str, Any]:
    """把生产/配方版式写入模版库，供智能对话生成客户实际生产表。"""
    from app.application.office_template_ingest_app_service import (
        ingest_office_bytes_to_template_library,
    )
    from app.infrastructure.tenant_scope import tenant_scope

    detection = parsed.get("detection") if isinstance(parsed.get("detection"), dict) else {}
    template_name = str(detection.get("sheet_name") or path.stem or "生产模板").strip()
    headers = [str(item).strip() for item in (parsed.get("headers") or []) if str(item).strip()]
    field_override = (
        [{"label": header, "value": "", "type": "dynamic"} for header in headers]
        if headers
        else None
    )
    try:
        with tenant_scope(int(tenant_id)):
            payload, _code = ingest_office_bytes_to_template_library(
                file_body=path.read_bytes(),
                filename=path.name,
                template_name=template_name,
                source="elt_recipe_template",
                field_override=field_override,
            )
    except RECOVERABLE_ERRORS:
        logger.exception("生产模版入库失败")
        payload = {"success": False, "message": "模版库入库失败", "ingested": False}
    ok = bool(payload.get("success"))
    return {
        "pipeline": "template",
        "status": "ingested" if ok else "failed",
        "file_name": path.name,
        "template_name": template_name,
        "template_candidate": True,
        "template_ingest": payload,
        "auto_ingest": {
            "status": "applied" if ok else "failed",
            "business": {"target_type": "template"},
            "knowledge": {},
        },
    }


def save_office_file_elt(
    file_path: str,
    *,
    tenant_id: int,
    owner_user_id: int,
    template_index: int = -1,
    parsed: dict[str, Any] | None = None,
    preview_wait_seconds: float = 180,
    client_disconnected: bool = False,
) -> dict[str, Any]:
    """Stage the file and queue one docking approval. A disconnect does not skip the queue.

    The write stays on ``submit_docking_write``: status ``awaiting_approval``, titled
    ``数据对接入库：{file}``. Approval releases the existing ELT batch. There is no
    immediate ``start_background`` write. A preview that is not ready is omitted, so
    release keeps the existing ``ELT_CANDIDATE_REQUIRED`` gate instead of a side door.
    """
    _ = client_disconnected
    from io import BytesIO

    from app.application.elt.docking_approval import submit_docking_write
    from app.application.elt.optional_template import choose_optional_template
    from app.application.elt.service import get_elt_service
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import tenant_scope

    if parsed is None:
        parsed = parse_office_file_elt(file_path)
    path = _resolve_office_path(str(parsed.get("file_path") or file_path))
    if _is_template_candidate(parsed):
        return _save_template_candidate(path, parsed, tenant_id=int(tenant_id))
    templates = [item for item in (parsed.get("templates") or []) if isinstance(item, dict)]
    chosen = choose_optional_template(templates, template_index)
    template_id = str(chosen.get("id") or "") if isinstance(chosen, dict) else ""
    payload, staged_name = _stage_bytes(path, chosen if isinstance(chosen, dict) else None)
    detection = dict(parsed.get("detection") or {})
    target = str(parsed.get("target_type") or _elt_target(detection, path.suffix.lower()))
    service = get_elt_service()
    plan = None
    owned_path = ""
    with tenant_scope(int(tenant_id)):
        with get_db() as db:
            upload = service.save_upload(
                db,
                owner_user_id=int(owner_user_id),
                file_name=staged_name,
                content_type=None,
                stream=BytesIO(payload),
            )
            owned = service._owned_upload(db, str(upload["upload_id"]), int(owner_user_id))
            owned_path = str(owned.storage_path)
            preview = service.create_preview(
                db,
                owner_user_id=int(owner_user_id),
                upload_id=str(upload["upload_id"]),
                target_type=target,
            )
            run = (
                preview
                if _preview_ready(preview)
                else _await_office_preview(
                    service,
                    db,
                    str(preview.get("id") or ""),
                    int(owner_user_id),
                    preview_wait_seconds,
                )
            )
            if _preview_ready(run):
                plan = _plan_from_preview(
                    owned_path,
                    file_name=staged_name,
                    owner=int(owner_user_id),
                    upload_id=str(upload["upload_id"]),
                    run=run,
                    detection=detection or {"target_type": target},
                    sha=str(getattr(owned, "sha256", "") or run.get("file_sha256") or ""),
                )
    receipt = submit_docking_write(
        owner_user_id=int(owner_user_id),
        tenant_id=int(tenant_id),
        source_path=owned_path,
        file_name=staged_name,
        template_id=template_id,
        prepared_plan=plan,
        owned_upload_user_id=int(owner_user_id),
    )
    return {
        "pipeline": "elt",
        "status": receipt.get("status"),
        "batch_id": receipt.get("batch_id"),
        "approval_request_id": receipt.get("approval_request_id"),
        "template_id": template_id,
        "selected_template_index": template_index if chosen else -1,
        "prepared": plan is not None,
        "auto_ingest": receipt,
        "file_name": staged_name,
    }


def _office_actor(runtime_context: dict[str, Any] | None) -> tuple[int, int] | None:
    ctx = runtime_context or {}
    owner = ctx.get("local_user_id", ctx.get("user_id"))
    tenant = ctx.get("tenant_id")
    if owner is None or tenant is None or isinstance(owner, bool) or isinstance(tenant, bool):
        return None
    try:
        owner_i = int(owner)
        tenant_i = int(tenant)
    except (TypeError, ValueError):
        return None
    if owner_i <= 0 or tenant_i <= 0:
        return None
    return tenant_i, owner_i


def _sheet_index(message: str, templates: list[dict[str, Any]]) -> int:
    match = _SHEET_LABEL_RE.search(message)
    if not match:
        return -1
    label = match.group(1)
    for index, item in enumerate(templates):
        if label in {
            str(item.get("label") or ""),
            str(item.get("sheet") or ""),
            str(item.get("id") or ""),
        }:
            return index
    return -1


def _office_reply(text: str, *, success: bool) -> dict[str, Any]:
    return {
        "success": success,
        "response": text,
        "text": text,
        "thinking_steps": "[调用工具: elt/office_parse]",
        "action": "office_parse_elt",
        "trace_intent": "office_parse_elt",
    }


def office_chat_elt_reply(
    message: str, runtime_context: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Deterministic office import. A miss returns None; a hit never calls the model."""
    if not is_office_elt_chat_message(message):
        return None
    match = _OFFICE_PATH_RE.search(str(message))
    rel = match.group(1) if match else ""
    wants_save = bool(re.search(r"导入|入库", str(message)))
    from app.application.elt.errors import EltError

    try:
        parsed = parse_office_file_elt(rel)
        if not wants_save:
            labels = "、".join(str(item.get("label") or "") for item in parsed["templates"]) or "无"
            return _office_reply(
                f"已用 ELT 解析 {parsed['file_name']}。可选工作表模板：{labels}。未选用模板，保存后才会提交入库审批。",
                success=True,
            )
        actor = _office_actor(runtime_context)
        if actor is None:
            return _office_reply("处理失败：需要登录后再入库。", success=False)
        tenant_id, owner = actor
        saved = save_office_file_elt(
            rel,
            tenant_id=tenant_id,
            owner_user_id=owner,
            template_index=_sheet_index(str(message), parsed["templates"]),
            parsed=parsed,
        )
        return _office_reply(
            f"已提交审批：数据对接入库：{saved.get('file_name') or parsed.get('file_name')}。通过后才会写入，驳回不写入。",
            success=True,
        )
    except EltError as exc:
        return _office_reply(f"处理失败：{exc.message}", success=False)
    except RECOVERABLE_ERRORS:
        logger.exception("office elt chat path failed")
        return _office_reply("处理失败：办公文件入库没有完成。", success=False)


def registered_office_stage(user_message: str, runtime_context: dict) -> dict:
    """Bind the office-stage write to the authenticated actor and tenant."""
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
    from app.infrastructure.tenant_scope import tenant_scope

    try:
        actor = _bound_actor(runtime_context)
        tenant_id = int(runtime_context.get("tenant_id") or 0)
        if tenant_id <= 0 or int(actor.tenant_id or 0) != tenant_id:
            raise AgentModAuthorizationError("企业范围与登录账号不一致")
        context = {**runtime_context, "local_user_id": int(actor.id), "tenant_id": tenant_id}
    except (AgentModAuthorizationError, AttributeError, TypeError, ValueError):
        return {"success": False, "message": "需要有效的企业登录身份"}
    with tenant_scope(tenant_id):
        result = office_chat_elt_reply(user_message, context)
    return result or {"success": False, "message": "原始请求缺少办公文件或导入意图"}
