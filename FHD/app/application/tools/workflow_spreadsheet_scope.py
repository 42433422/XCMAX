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
    artifact_path,
    read_verified_spreadsheet,
    store_spreadsheet,
)
from app.application.elt.service import get_elt_service
from app.application.office_parse_app_service import EMPLOYEE_BY_SUFFIX
from app.application.shipment_excel_etl_security import open_etl_input_file
from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.infrastructure.auth.agent_mod_scope import _bound_actor
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.path_io.path_utils import get_app_data_dir


def _run_spreadsheet(file_path: str, context: dict[str, Any]) -> tuple[bytes, str] | None:
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
            if isinstance(row, dict)
            and str(row.get("artifact_id", "")).startswith(("xlsx_", "csv_"))
        ]
        for receipt in receipts:
            artifact_id = receipt["artifact_id"]
            path = artifact_path(run_id, artifact_id)
            if file_path in {str(path), f"/api/agent/runs/{run_id}/artifacts/{artifact_id}"} or (
                len(receipts) == 1 and isinstance(data, dict) and data.get("file_path") == file_path
            ):
                return read_verified_spreadsheet(run_id, receipt), path.suffix
    return None


def _staging_root() -> Path:
    root = Path(get_app_data_dir()).resolve() / "temp_excel"
    root.mkdir(exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise PermissionError("员工文件暂存目录无效")
    return root


@contextmanager
def workflow_file_snapshot(file_path: str, context: dict[str, Any]) -> Iterator[Path]:
    actor = _bound_actor(context)
    prior = _run_spreadsheet(file_path, context)
    if prior is not None:
        content, suffix = prior
    else:
        source_id = file_path
        for candidate in (
            context.get("excel_analysis"),
            context.get("last_excel_analysis_context"),
        ):
            if not isinstance(candidate, dict):
                continue
            candidate = candidate.get("result", candidate)
            if (
                isinstance(candidate, dict)
                and candidate.get("file_path") == file_path
                and isinstance(candidate.get("upload_id"), str)
            ):
                source_id = candidate["upload_id"]
                break
        with get_db() as db:
            upload_id = (
                db.query(EltUpload.id)
                .filter(
                    EltUpload.owner_user_id == actor.id,
                    EltUpload.tenant_id == tenant_id_for_write(),
                    or_(EltUpload.id == source_id, EltUpload.storage_path == source_id),
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
    # These workers accept several path aliases and can choose a template or an
    # output path. Supply only server-owned paths, including the output root.
    source = str(
        payload.get("upload_id")
        or payload.get("file_path")
        or payload.get("path")
        or payload.get("excel_path")
        or ""
    ).strip()
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
