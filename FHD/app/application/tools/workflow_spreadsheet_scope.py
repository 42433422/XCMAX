"""Open workflow files through account-owned uploads and current-run receipts."""

from __future__ import annotations

import copy
import hashlib
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from typing import Any

from sqlalchemy.orm import Session

from app.application import excel_export_limits
from app.application.agent_orchestrator.artifact_files import (
    RUN_FILE_MIME_TYPES,
    artifact_path,
    read_verified_run_file,
    store_run_file,
    store_scoped_run_file,
    store_spreadsheet,
)
from app.application.elt.service import get_elt_service
from app.application.office_parse_app_service import EMPLOYEE_BY_SUFFIX
from app.application.shipment_excel_elt_security import (
    _validated_path_component,
    open_elt_input_file,
    resolve_elt_path,
)
from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.domain.context.session_excel_context import excel_analysis_from_runtime
from app.infrastructure.auth.agent_mod_scope import _bound_actor
from app.infrastructure.chat_stream_lifetime import (
    publish_stream_note as publish_stream_note,
)
from app.infrastructure.chat_stream_lifetime import (
    publish_stream_tool_record as publish_stream_tool_record,
)
from app.infrastructure.tenant_scope import (
    TenantScopeError as TenantScopeError,
)
from app.infrastructure.tenant_scope import (
    tenant_id_for_write,
)
from app.infrastructure.tenant_scope import (
    tenant_scope as tenant_scope,
)
from app.infrastructure.workspace import (
    resolve_existing_file_under_root as resolve_existing_file_under_root,
)
from app.infrastructure.workspace import (
    resolve_existing_workspace_file as resolve_existing_workspace_file,
)
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


def _fresh_upload_cutoff():
    """未绑定的展示名仅在最近上传范围内解析，默认 24 小时内。"""
    try:
        hours = float(os.environ.get("XCAGI_ELT_UPLOAD_FRESH_HOURS", "") or 24)
    except ValueError:
        hours = 24.0
    if not 0 < hours <= 720:
        hours = 24.0
    return utc_now_naive() - timedelta(hours=hours)


def _upload_basename_candidates(value: str) -> list[str]:
    """聊天上传返回的文件路径带随机前缀，这里同时保留原名候选。"""
    name = Path(value).name
    candidates = [name]
    unprefixed = re.fullmatch(r"[0-9a-fA-F]{8,32}-(.+)", name)
    if unprefixed is not None and unprefixed.group(1) != name:
        candidates.append(unprefixed.group(1))
    return candidates


def _unique_upload(rows: list[EltUpload]) -> EltUpload | None:
    if len(rows) > 1:
        raise PermissionError("存在多个同名上传文件，请明确选择 upload_id")
    return rows[0] if rows else None


def _fresh_named_upload(upload: EltUpload) -> EltUpload:
    if (
        not upload.storage_path
        or upload.expires_at is None
        or upload.expires_at.replace(tzinfo=None) <= utc_now_naive()
        or upload.created_at is None
        or upload.created_at.replace(tzinfo=None) <= _fresh_upload_cutoff()
    ):
        raise PermissionError("指定附件已过期或不在文件名引用有效期内，请重新确认附件")
    return upload


def _resolve_owned_upload(
    db: Session, value: str, context: dict[str, Any], owner_user_id: int
) -> EltUpload | None:
    """Resolve one identity inside the original account/tenant boundary."""
    query = db.query(EltUpload).filter(
        EltUpload.owner_user_id == owner_user_id,
        EltUpload.tenant_id == tenant_id_for_write(),
    )
    analysis = excel_analysis_from_runtime(context) or {}
    reference = analysis.get("upload_id")
    previous_path = str(analysis.get("file_path") or "").strip()
    ids = context.get("attachment_upload_ids")
    bound: list[EltUpload] = []
    if ids is not None:
        if (
            not isinstance(ids, list)
            or not 1 <= len(ids) <= 4
            or any(not isinstance(item, str) or not item or len(item) > 80 for item in ids)
            or len(set(ids)) != len(ids)
        ):
            raise PermissionError("附件引用无效，请明确选择 upload_id")
        # Resolve the entire set first; a missing bound attachment must not silently
        # turn into a different upload, even if only one remaining name matches.
        bound = query.filter(EltUpload.id.in_(ids)).all()
        if len(bound) != len(ids):
            raise PermissionError("指定附件不存在或不属于当前账号与租户")
        if any(
            row.expires_at is None or row.expires_at.replace(tzinfo=None) <= utc_now_naive()
            for row in bound
        ):
            raise PermissionError("指定附件已过期，请重新确认附件")
    # Explicit IDs are authoritative only within the existing selected attachment set.
    exact = query.filter(EltUpload.id == value).one_or_none()
    if exact is not None:
        if bound and all(row.id != exact.id for row in bound):
            raise PermissionError("文件与会话附件身份冲突，请明确选择 upload_id")
        return exact
    exact = _unique_upload(query.filter(EltUpload.storage_path == value).limit(2).all())
    if exact is not None:
        if (
            (
                previous_path
                and value == previous_path
                and isinstance(reference, str)
                and reference
                and exact.id != reference
            )
            or (bound and all(row.id != exact.id for row in bound))
            or any(row.id != exact.id and row.file_name == exact.file_name for row in bound)
        ):
            raise PermissionError("文件路径与会话附件身份冲突，请明确选择 upload_id")
        return exact

    candidates = _upload_basename_candidates(value)
    if bound:
        match = _unique_upload([row for row in bound if row.file_name in candidates])
        if match is not None:
            if (
                value == previous_path
                and isinstance(reference, str)
                and reference
                and reference != match.id
                and Path(value).name != value
            ):
                raise PermissionError("原会话引用与当前附件身份冲突，请明确选择 upload_id")
            return _fresh_named_upload(match)
        # Do not search other uploads by name while a current attachment set exists.
        return None

    if isinstance(reference, str) and reference:
        previous = query.filter(EltUpload.id == reference).one_or_none()
        # Compare the ORIGINAL reference, before any basename-to-storage rewrite.
        if previous_path and value == previous_path:
            if previous is None:
                raise PermissionError("原会话附件不可用，请重新确认附件")
            return previous
        if Path(value).name == value and (
            (previous is not None and previous.file_name in candidates)
            or (previous_path and value in _upload_basename_candidates(previous_path))
        ):
            if previous is None:
                raise PermissionError("原会话附件不可用，请重新确认附件")
            return _fresh_named_upload(previous)

    # An unregistered path (including a legacy random-prefixed path) is not an
    # identity. Only a bare display name may fall back to a unique fresh record.
    if bound or Path(value).name != value or "\\" in value:
        return None
    return _unique_upload(
        query.filter(
            EltUpload.file_name.in_(candidates),
            EltUpload.storage_path != "",
            EltUpload.expires_at > utc_now_naive(),
            EltUpload.created_at > _fresh_upload_cutoff(),
        )
        .limit(2)
        .all()
    )


def resolve_owned_upload_path(file_path: str, context: dict[str, Any]) -> str:
    """Resolve a display name without silently replacing a bound upload."""
    value = str(file_path or "").strip()
    if not value:
        return value
    actor = _bound_actor(context)
    with get_db() as db:
        upload = _resolve_owned_upload(db, value, context, actor.id)
        if upload is not None:
            return str(upload.storage_path or upload.id)
    return value


@contextmanager
def workflow_file_snapshot(file_path: str, context: dict[str, Any]) -> Iterator[Path]:
    from app.application.agent_runtime.conversation_attachments import resolve_conversation_upload

    actor = _bound_actor(context)
    file_path = str(file_path or "").strip()
    reference = resolve_conversation_upload(file_path, context)
    prior = _run_file(file_path, context) if reference is None else None
    if prior is None and reference is None:
        from app.infrastructure.xiaox.receipts import read_action_artifact

        prior = read_action_artifact(file_path, context)
    if prior is not None:
        content, suffix = prior
    else:
        with get_db() as db:
            selected = _resolve_owned_upload(
                db, reference.upload_id if reference else file_path, context, actor.id
            )
            if selected is None:
                raise PermissionError("文件不属于当前账号或当前任务，请明确选择 upload_id")
            if reference and (
                (selected.id, selected.sha256) != (reference.upload_id, reference.sha256)
                or selected.expires_at is None
                or selected.expires_at.replace(tzinfo=None) <= utc_now_naive()
            ):
                raise PermissionError("原附件已过期或内容已变化，请重新上传原件")
            upload = get_elt_service()._owned_upload(db, selected.id, actor.id)
            suffix = Path(upload.file_name).suffix.lower()
            with open_elt_input_file(upload.storage_path, owner_user_id=actor.id) as source:
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
    employee_id: str, payload: dict[str, Any], context: dict[str, Any], *, ephemeral: bool = False
) -> Iterator[dict[str, Any]]:
    aliases = ("upload_id", "file_path", "path", "excel_path")
    source = next((str(payload[key]).strip() for key in aliases if payload.get(key)), "")
    with workflow_file_snapshot(source, context) as snapshot:
        if EMPLOYEE_BY_SUFFIX.get(snapshot.suffix) != employee_id:
            raise PermissionError("文件类型与读取员工不匹配")
        factory = TemporaryDirectory if ephemeral else mkdtemp
        directory = factory(prefix="employee-read-", dir=_staging_root())
        options: dict[str, Any] = {
            key: payload[key] for key in ("action", "max_row_cap", "max_col_cap") if key in payload
        }
        with nullcontext(directory) if isinstance(directory, str) else directory as workspace:
            yield {**options, "file_path": str(snapshot), "workspace_root": workspace}


@contextmanager
def workbook_writer_input(payload: dict[str, Any], context: dict[str, Any]) -> Iterator[dict]:
    """A signed worker only sees an owned template and a private output directory."""
    from jsonschema import Draft202012Validator

    from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
    from app.domain.workbook_write_contract import WORKBOOK_WRITE_INPUT, WORKBOOK_WRITE_REVIEW

    original = {
        key: value
        for key, value in payload.items()
        if key not in {"source", "user_message", "task"}
    }
    if not Draft202012Validator(WORKBOOK_WRITE_INPUT).is_valid(original):
        raise PermissionError("模板写入需要明确 template_path 与 plan；不接受工作区或输出路径覆盖")
    with workflow_file_snapshot(original["template_path"], context) as template:
        if context.get("source") == "xiaox_runtime":
            review = context.get(WORKBOOK_WRITE_REVIEW)
            if not isinstance(review, dict) or (
                hashlib.sha256(template.read_bytes()).hexdigest() != review.get("template_sha256")
                or canonical_digest(original["plan"]) != review.get("plan_sha256")
            ):
                raise PermissionError("原工作簿或执行计划与写入预检不一致")
            approval = context.get("_tool_approval_scope") or {}
            if review.get("requires_manual_approval") and (
                approval.get("tool_id"), approval.get("action")
            ) != ("employee", "execute"):
                raise PermissionError("原始数据改动缺少当前操作的人工审批")
        suffix = template.suffix.lower()
        if suffix not in {".xlsx", ".xlsm"}:
            raise PermissionError("模板必须是当前账号的 xlsx/xlsm 工作簿")
        if name := original.get("output_name"):
            try:
                original["output_name"] = _validated_path_component(name)
                if len(name.encode()) > 255 or Path(name).suffix.lower() != suffix:
                    raise ValueError("invalid workbook download name or suffix")
            except ValueError as exc:
                raise PermissionError("下载文件名无效，须使用与模板同类的扩展名") from exc
        with TemporaryDirectory(prefix="workbook-write-", dir=_staging_root()) as directory:
            yield {
                **copy.deepcopy(original),
                "template_path": str(template),
                "workspace_root": directory,
                "output_relpath": "filled" + suffix,
                "strict_protected": True,
            }


def publish_workbook_output(
    employee_id: str, result: dict, context: dict, workspace: str, *, output_name: str | None = None
) -> dict:
    """Publish the real worker output before the private workspace is removed."""
    from app.domain.workbook_write_contract import WORKBOOK_READER
    from app.mod_sdk.employee_tool_registry import office_output_paths

    paths = office_output_paths(employee_id, result)
    if len(paths) != 1:
        raise PermissionError("工作簿员工没有唯一实际产物")
    path = resolve_elt_path(paths[0], workspace_root=workspace)
    suffix = path.suffix.lower()
    reader = employee_id == WORKBOOK_READER
    if (
        not path.is_relative_to(Path(workspace).resolve())
        or suffix not in ({".json"} if reader else {".xlsx", ".xlsm"})
        or (output_name and Path(output_name).suffix.lower() != suffix)
    ):
        raise PermissionError("工作簿员工产物路径或类型无效")
    with open_elt_input_file(path, workspace_root=workspace) as source:
        receipt = store_scoped_run_file(
            source.read(), name=output_name or path.name, context=context
        )
    # Do not expose the private staging paths or claim formula recalculation.
    return {
        **{
            key: result[key]
            for key in ("employee_id", "pack", "duration_ms", "executed_at", "source")
            if key in result
        },
        "success": True,
        "file_path": receipt["uri"],
        "artifacts": [receipt],
        "result": {
            "handlers": ["direct_python"],
            "outputs": [
                {
                    "handler": "direct_python",
                    "ok": True,
                    "output": {
                        "ok": True,
                        "items": [{"output_path": receipt["uri"]}],
                        "summary": "已提取工作簿内容。"
                        if reader
                        else "工作簿已写出，等待独立 QC；公式按文本保存，未进行数值重算。",
                    },
                }
            ],
        },
    }


def export_workflow_spreadsheet(
    payload: dict[str, Any],
    context: dict[str, Any],
    export: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    _bound_actor(context)
    run_id = str(context.get("run_id") or "")
    if not run_id:
        raise PermissionError("导出表格需要当前任务")
    if error := excel_export_limits.export_input_error(payload):
        return error
    with TemporaryDirectory(prefix="workflow-export-", dir=_staging_root()) as directory:
        result = export(payload, workspace_root=directory)
        if result.get("success") is True:
            data = result["data"]
            path = Path(data["file_path"])
            with open_elt_input_file(path, workspace_root=directory) as source:
                content = source.read(excel_export_limits.MAX_EXPORT_FILE_BYTES + 1)
                if len(content) > excel_export_limits.MAX_EXPORT_FILE_BYTES:
                    return excel_export_limits.ExcelExportLimitError(
                        "导出文件超过产物大小预算"
                    ).result()
                receipt = store_spreadsheet(run_id, content, name=path.name)
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

    published = result.get("artifacts")
    if isinstance(published, list) and published:
        for receipt in published:
            if not isinstance(receipt, dict) or receipt.get("artifact_type") != "file":
                raise PermissionError("员工产物缺少原文件回执")
            metadata = receipt.get("metadata") or {}
            if not isinstance(metadata, dict) or receipt.get("uri") != (
                f"/api/agent/runs/{context.get('run_id')}/artifacts/{receipt.get('artifact_id')}"
            ):
                raise PermissionError("员工产物引用不属于当前原调用")
            if any(
                str(metadata.get(key)) != str(value)
                for key, value in {
                    "run_id": context.get("run_id"),
                    "owner_user_id": str(_bound_actor(context).id),
                    "tenant_id": context.get("tenant_id"),
                    "step_id": context.get("step_id"),
                    "call_id": context.get("call_id"),
                    "node_id": context.get("node_id"),
                    "params_sha256": context.get("input_sha256"),
                }.items()
            ):
                raise PermissionError("员工产物不属于当前原调用")
            read_verified_run_file(str(context["run_id"]), receipt)
        return copy.deepcopy(published)

    paths = {
        resolve_elt_path(raw, workspace_root=workspace_root)
        for raw in office_output_paths(employee_id, result)
    }
    for path in paths:
        with open_elt_input_file(path, workspace_root=workspace_root) as source:
            if len(paths) != 1:
                continue
            result["file_path"] = str(path)
            run_id = str(context.get("run_id") or "")
            if run_id and path.suffix.lower() in RUN_FILE_MIME_TYPES:
                return [store_employee_output(run_id, path, source.read(), context)]
    return []
