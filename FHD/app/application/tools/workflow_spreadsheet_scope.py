"""Open workflow files through account-owned uploads and current-run receipts."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from typing import Any

from sqlalchemy import or_

from app.application.agent_orchestrator.artifact_files import (
    RUN_FILE_MIME_TYPES,
    artifact_path,
    read_verified_run_file,
    store_run_file,
    store_spreadsheet,
)
from app.application.elt.service import get_elt_service
from app.application.office_parse_app_service import EMPLOYEE_BY_SUFFIX
from app.application.shipment_excel_etl_security import open_etl_input_file, resolve_etl_path
from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.domain.context.session_excel_context import excel_analysis_from_runtime
from app.infrastructure.auth.agent_mod_scope import _bound_actor
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.path_io.path_utils import get_app_data_dir
from app.utils.time import utc_now_naive


def _run_file(file_path: str, context: dict[str, Any]) -> tuple[bytes, str] | None:
    run_id = context.get("run_id")
    outputs = context.get("node_outputs")
    if not isinstance(run_id, str) or not isinstance(outputs, dict):
        return None
    for output in outputs.values():
        if not isinstance(output, dict) or output.get("success") is not True:
            continue
        data = output.get("data")
        receipts = [
            row
            for row in output.get("artifacts") or []
            if isinstance(row, dict) and row.get("artifact_type") == "file"
        ]
        for receipt in receipts:
            artifact_id = receipt["artifact_id"]
            path = artifact_path(run_id, artifact_id)
            if file_path in {str(path), f"/api/agent/runs/{run_id}/artifacts/{artifact_id}"} or (
                len(receipts) == 1 and isinstance(data, dict) and data.get("file_path") == file_path
            ):
                if path.suffix in {".pdf", ".docx", ".pptx"}:
                    actor = _bound_actor(context)
                    metadata = receipt.get("metadata") or {}
                    if (
                        metadata.get("owner_user_id") != str(actor.id)
                        or metadata.get("tenant_id") != str(tenant_id_for_write())
                        or metadata.get("tenant_id") != str(context.get("tenant_id"))
                    ):
                        raise PermissionError("文件回执不属于当前账号与租户")
                return read_verified_run_file(run_id, receipt), path.suffix
    return None


def _staging_root() -> Path:
    root = Path(get_app_data_dir()).resolve() / "temp_excel"
    root.mkdir(exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise PermissionError("员工文件暂存目录无效")
    return root


def resolve_owned_upload_path(file_path: str, context: dict[str, Any]) -> str:
    """把用户可见的文件名换成当前账号自己的上传存储路径。

    后续轮次只说「导入」时，模型只能看到「宗南.xlsx」这类展示名；
    直接按展示名查库会命中不到归属记录，这里仅在当前账号与租户范围内解析。
    """
    value = str(file_path or "").strip()
    if not value:
        return value
    try:
        actor = _bound_actor(context)
        with get_db() as db:
            query = db.query(EltUpload).filter(
                EltUpload.owner_user_id == actor.id,
                EltUpload.tenant_id == tenant_id_for_write(),
            )
            exact = query.filter(
                or_(EltUpload.id == value, EltUpload.storage_path == value)
            ).first()
            if exact is not None:
                return str(exact.storage_path or exact.id)
            by_name = (
                query.filter(
                    EltUpload.file_name == Path(value).name,
                    EltUpload.storage_path != "",
                    EltUpload.expires_at > utc_now_naive(),
                )
                .order_by(EltUpload.id.desc())
                .first()
            )
            if by_name is not None:
                return str(by_name.storage_path)
    except (PermissionError, ValueError):
        return value
    return value


@contextmanager
def workflow_file_snapshot(file_path: str, context: dict[str, Any]) -> Iterator[Path]:
    actor = _bound_actor(context)
    prior = _run_file(file_path, context)
    if prior is not None:
        content, suffix = prior
    else:
        file_path = resolve_owned_upload_path(file_path, context)
        analysis = excel_analysis_from_runtime(context) or {}
        reference = analysis.get("upload_id")
        if isinstance(reference, str) and reference and file_path == analysis.get("file_path"):
            file_path = reference
        with get_db() as db:
            upload_id = (
                db.query(EltUpload.id)
                .filter(
                    EltUpload.owner_user_id == actor.id,
                    EltUpload.tenant_id == tenant_id_for_write(),
                    or_(EltUpload.id == file_path, EltUpload.storage_path == file_path),
                )
                .scalar()
            )
            if upload_id is None:
                raise PermissionError("文件不属于当前账号或当前任务")
            upload = get_elt_service()._owned_upload(db, upload_id, actor.id)
            suffix = Path(upload.file_name).suffix.lower()
            with open_etl_input_file(upload.storage_path, owner_user_id=actor.id) as source:
                content = source.read(upload.size_bytes + 1)
            if (
                len(content) != upload.size_bytes
                or hashlib.sha256(content).hexdigest() != upload.sha256
            ):
                raise PermissionError("上传文件与保存回执不一致")
    with TemporaryDirectory(prefix="workflow-input-", dir=_staging_root()) as directory:
        path = Path(directory) / ("input" + suffix)
        path.write_bytes(content)
        yield path


@contextmanager
def office_reader_input(
    employee_id: str, payload: dict[str, Any], context: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    aliases = ("upload_id", "file_path", "path", "excel_path")
    source = next((str(payload[key]).strip() for key in aliases if payload.get(key)), "")
    with workflow_file_snapshot(source, context) as snapshot:
        if EMPLOYEE_BY_SUFFIX.get(snapshot.suffix) != employee_id:
            raise PermissionError("文件类型与读取员工不匹配")
        workspace = mkdtemp(prefix="employee-read-", dir=_staging_root())
        options: dict[str, Any] = {
            key: payload[key] for key in ("action", "max_row_cap", "max_col_cap") if key in payload
        }
        yield {**options, "file_path": str(snapshot), "workspace_root": workspace}


def export_workflow_spreadsheet(
    payload: dict[str, Any],
    context: dict[str, Any],
    export: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    _bound_actor(context)
    run_id = str(context.get("run_id") or "")
    if not run_id:
        raise PermissionError("导出表格需要当前任务")
    with TemporaryDirectory(prefix="workflow-export-", dir=_staging_root()) as directory:
        result = export(payload, workspace_root=directory)
        if result.get("success") is True:
            data = result["data"]
            path = Path(data["file_path"])
            with open_etl_input_file(path, workspace_root=directory) as source:
                receipt = store_spreadsheet(run_id, source.read(), name=path.name)
            result["artifacts"] = [receipt]
            data["file_path"] = receipt["uri"]
    return result


def store_employee_output(
    run_id: str, path: Path, content: bytes, context: dict[str, Any]
) -> dict[str, Any]:
    owner = _bound_actor(context).id if path.suffix.lower() in {".pdf", ".docx", ".pptx"} else None
    return store_run_file(
        run_id,
        content,
        name=path.name,
        owner_user_id=owner,
        tenant_id=str(context.get("tenant_id") or ""),
    )


def employee_output_receipts(
    employee_id: str,
    result: dict[str, Any],
    context: dict[str, Any],
    workspace_root: str | None = None,
) -> list[dict[str, Any]]:
    """Publish the same verified handoff for both employee dispatch paths."""
    from app.mod_sdk.employee_tool_registry import office_output_paths

    paths = {
        resolve_etl_path(raw, workspace_root=workspace_root)
        for raw in office_output_paths(employee_id, result)
    }
    for path in paths:
        with open_etl_input_file(path, workspace_root=workspace_root) as source:
            if len(paths) != 1:
                continue
            result["file_path"] = str(path)
            run_id = str(context.get("run_id") or "")
            if run_id and path.suffix.lower() in RUN_FILE_MIME_TYPES:
                return [store_employee_output(run_id, path, source.read(), context)]
    return []
