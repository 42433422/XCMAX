"""Cross-module business chain: client task, agent, workflow, scheduler, employee, ETL, ERP, MOD.

Each step calls an existing module and keeps the business result tied to rows, files,
and hashes. A tool ``success`` flag is not enough to mark the task complete.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.unified_task import (
    UnifiedTaskError,
    UnifiedTaskResult,
    create_unified_task,
)
from app.application.elt.errors import EltError
from app.application.elt.parser_structure import clean_cell_text, detect_table_layout
from app.application.elt.parsers import parse_file
from app.application.elt.service_support import MAX_FILE_BYTES, load_json
from app.application.elt.service_uploads import UploadServiceMixin
from app.application.elt.targets.products import ProductAdapter
from app.application.employee_runtime.executor import execute_employee_task_local
from app.application.employee_runtime.loader import load_employee_pack_from_disk
from app.application.shipment_excel_elt_security import (
    ShipmentEltPathError,
    open_elt_input_file,
    resolve_elt_path,
)
from app.application.workflow.approval_policy import WorkflowApprovalPolicy
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.db.models.elt import EltRun, EltRunRow, EltUpload
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope
from app.utils.logging.audit_logger import audit_log
from app.utils.operational_errors import RECOVERABLE_ERRORS

_DELIVERY_MODULE = "cross_module_import"
_RESPONSE_MODULE = "cross_module_http_response"
_IMPORT_ERRORS: tuple[type[Exception], ...] = (SQLAlchemyError, *RECOVERABLE_ERRORS)
_QUEUE_OWNER = "agent-task-queue"


_HEADER_ALIASES = {
    "购买单位": "unit",
    "单位": "unit",
    "客户": "unit",
    "型号": "model_number",
    "产品型号": "model_number",
    "产品名称": "name",
    "品名": "name",
    "名称": "name",
    "规格": "specification",
    "价格": "price",
    "单价": "price",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _source_bytes(
    file_path: str | Path, *, user_id: int, db: Session | None = None
) -> tuple[Path, bytes]:
    """Read only an owned upload or an operator-configured ETL workspace input."""
    from app.db.session import get_db
    from app.utils.path_io.path_utils import get_app_data_dir

    candidate = Path(file_path).expanduser()
    upload_root = Path(get_app_data_dir()).resolve() / "elt" / "uploads"
    expected_sha = ""
    if candidate.is_relative_to(upload_root) or candidate.resolve().is_relative_to(upload_root):
        if db is None:
            with get_db() as owned_db:
                return _source_bytes(file_path, user_id=user_id, db=owned_db)
        upload = (
            db.query(EltUpload)
            .filter(
                EltUpload.storage_path == str(candidate.resolve()),
                EltUpload.tenant_id == current_tenant_id(),
                EltUpload.owner_user_id == user_id,
            )
            .first()
        )
        if upload is None:
            raise ShipmentEltPathError("上传文件不属于当前账号")
        upload = UploadServiceMixin()._owned_upload(db, upload.id, user_id)
        source = Path(upload.storage_path)
        expected_sha = upload.sha256
        opened = open_elt_input_file(source, owner_user_id=user_id)
    else:
        source = resolve_elt_path(candidate)
        opened = open_elt_input_file(source)
    with opened as stream:
        body = stream.read(MAX_FILE_BYTES + 1)
    if not body or len(body) > MAX_FILE_BYTES:
        raise ValueError("业务文件为空或超过大小限制")
    if expected_sha and hashlib.sha256(body).hexdigest() != expected_sha:
        raise ValueError("上传文件与入库记录不一致")
    return source, body


def _map_row(values: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for key, value in values.items():
        target = _HEADER_ALIASES.get(clean_cell_text(key))
        if not target:
            continue
        text_value = clean_cell_text(value)
        if text_value:
            mapped[target] = text_value
    return mapped


def _sheet_matrix(path: Path) -> dict[str, list[list[Any]]]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        sheets: dict[str, list[list[Any]]] = {}
        for name in workbook.sheetnames:
            sheet = workbook[name]
            sheets[name] = [
                [cell if cell is not None else "" for cell in row]
                for row in sheet.iter_rows(values_only=True)
            ]
        return sheets
    finally:
        workbook.close()


def identify_workbook(path: Path) -> dict[str, Any]:
    sheets = _sheet_matrix(path)
    regions: list[dict[str, Any]] = []
    for name, rows in sheets.items():
        layout = detect_table_layout(rows, header_hints=("购买单位", "产品名称", "型号", "价格"))
        if layout is None:
            regions.append({"sheet": name, "kind": "note", "headers": []})
            continue
        regions.append(
            {
                "sheet": name,
                "kind": "table",
                "header_row": layout.header_end + 1,
                "headers": list(layout.headers),
            }
        )
    parsed = parse_file(path, target_type="products")
    try:
        parsed_rows = [
            {"sheet": row.sheet, "row_number": row.row_number, "values": dict(row.values)}
            for row in parsed.rows
        ]
    finally:
        parsed.close()
    return {
        "success": True,
        "sheets": list(sheets),
        "regions": regions,
        "parsed_rows": parsed_rows,
        "source": "elt.parse_file+parser_structure.detect_table_layout",
    }


def slice_and_clean(identified: dict[str, Any]) -> dict[str, Any]:
    adapter = ProductAdapter()
    qualifying: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    for row in identified.get("parsed_rows") or []:
        mapped = _map_row(row.get("values") or {})
        issues = list(adapter.validate(mapped))
        price_text = str(mapped.get("price") or "")
        try:
            price_value = float(price_text) if price_text else None
        except ValueError:
            price_value = None
            issues.append(
                {"code": "PRICE_NOT_NUMERIC", "field": "price", "message": "价格不是数字"}
            )
        if price_value is not None and price_value < 0:
            issues.append({"code": "PRICE_NEGATIVE", "field": "price", "message": "价格不能为负"})
        record = {
            "sheet": row.get("sheet"),
            "row_number": row.get("row_number"),
            "data": mapped,
        }
        if issues:
            record["issues"] = issues
            anomalies.append(record)
        else:
            qualifying.append(record)
    parsed_count = len(identified.get("parsed_rows") or [])
    return {
        "success": True,
        "parsed_count": parsed_count,
        "qualifying": qualifying,
        "anomalies": anomalies,
        "complete": parsed_count == len(qualifying) + len(anomalies) and parsed_count > 0,
    }


def write_result_workbook(path: Path, cleaned: dict[str, Any]) -> dict[str, Any]:
    workbook = Workbook()
    qualified = workbook.worksheets[0]
    qualified.title = "合格明细"
    qualified.append(["购买单位", "型号", "产品名称", "规格", "价格"])
    for row in cleaned["qualifying"]:
        data = row["data"]
        qualified.append(
            [
                data.get("unit"),
                data.get("model_number"),
                data.get("name"),
                data.get("specification"),
                data.get("price"),
            ]
        )
    anomaly_sheet = workbook.create_sheet("异常清单")
    anomaly_sheet.append(["行号", "代码", "说明", "原始名称", "原始价格"])
    for row in cleaned["anomalies"]:
        data = row["data"]
        codes = ",".join(item["code"] for item in row["issues"])
        messages = ";".join(item["message"] for item in row["issues"])
        anomaly_sheet.append(
            [row["row_number"], codes, messages, data.get("name"), data.get("price")]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()
    anomaly_csv = path.with_name(path.stem + "-anomalies.csv")
    lines = ["row_number,code,message"]
    for row in cleaned["anomalies"]:
        for issue in row["issues"]:
            lines.append(f"{row['row_number']},{issue['code']},{issue['message']}")
    anomaly_csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "success": True,
        "result_path": str(path),
        "anomaly_csv": str(anomaly_csv),
        "sha256": _sha256(path),
        "qualifying_count": len(cleaned["qualifying"]),
        "anomaly_count": len(cleaned["anomalies"]),
    }


def import_products(db: Session, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Stage approved new products; the caller commits them with its delivery receipt."""
    adapter = ProductAdapter()
    written: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row["data"])
        decision = adapter.preview(db, data, allowed_update_fields=set(), context={})
        if decision.action != "new":
            raise ValueError(decision.reason or decision.action)
        result = adapter.execute_row(
            db,
            data,
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context={},
        )
        written.append(result)
    return {
        "success": True,
        "written": written,
        "count": len(written),
    }


def _audit(
    event: str, trace_id: str, task_id: str, user_id: str, tenant_id: str, **details: Any
) -> None:
    audit_log(
        event,
        user_id=user_id,
        details={
            "trace_id": trace_id,
            "task_id": task_id,
            "tenant_id": tenant_id,
            "at": _now(),
            **details,
        },
    )


def _run_employee(
    employee_id: str, task: str, payload: dict[str, Any], workspace: Path, *, user_id: int
) -> dict[str, Any]:
    pack = load_employee_pack_from_disk(employee_id)
    result = execute_employee_task_local(
        employee_id,
        task,
        {**payload, "skip_collaboration": True, "workspace_root": str(workspace)},
        user_id=user_id,
        workspace_root=str(workspace),
        runtime_context={"employee_collaboration_skip": True},
    )
    return {"pack": {"id": pack["pack_id"], "version": pack["version"]}, "result": result}


def verify_against_data(
    *,
    qualifying_count: int,
    anomaly_count: int,
    stored_count: int,
    tool_success: bool,
    result_sha: str,
    result_path: Path,
) -> dict[str, Any]:
    file_ok = result_path.is_file() and _sha256(result_path) == result_sha
    counts_ok = stored_count == qualifying_count
    accepted = bool(file_ok and counts_ok and qualifying_count >= 0)
    if tool_success and not counts_ok:
        accepted = False
    status = "partial" if accepted and anomaly_count else "completed" if accepted else "failed"
    return {
        "accepted": accepted,
        "status": status,
        "tool_success_ignored_when_counts_disagree": bool(tool_success and not counts_ok),
        "qualifying_count": qualifying_count,
        "anomaly_count": anomaly_count,
        "stored_count": stored_count,
        "file_sha256": result_sha
        if file_ok
        else _sha256(result_path)
        if result_path.is_file()
        else "",
        "anomalies_reported": anomaly_count > 0,
    }


def _approval_fingerprint(checkpoint: dict[str, Any], params: dict[str, Any]) -> str:
    return canonical_hash(
        {
            "scope": {
                key: checkpoint[key] for key in ("tenant_id", "user_id", "task_id", "run_id")
            },
            "source_sha256": checkpoint["original_sha256"],
            "params": params,
        }
    )


def _approved_products(
    workflow: dict[str, Any], run: AgentRun, checkpoint: dict[str, Any], request_id: str
) -> list[dict[str, Any]]:
    """Bind the write to the persisted approval, authenticated task and exact input."""
    context = workflow.get("runtime_context") or {}
    stored_context = run.metadata.get("runtime_context") or {}
    plan = workflow.get("plan")
    products = checkpoint.get("qualifying")
    if (
        not isinstance(plan, PlanGraph)
        or len(plan.nodes) != 1
        or not isinstance(products, list)
        or not products
        or any(not isinstance(item, dict) for item in products)
        or checkpoint != stored_context.get("cross_module_checkpoint")
        or str(run.user_id) != str(checkpoint.get("user_id"))
        or run.run_id != checkpoint.get("run_id")
        or run.metadata.get("approval_request_id") != request_id
        or str(current_tenant_id()) != checkpoint.get("tenant_id")
        or any(
            not checkpoint.get(key)
            or str(context.get(key)) != str(checkpoint[key])
            or str(stored_context.get(key)) != str(checkpoint[key])
            for key in ("tenant_id", "user_id", "task_id")
        )
    ):
        raise ValueError("审批与任务身份不一致，已阻止写入")
    node = plan.nodes[0]
    params = checkpoint.get("elt_params")
    if (
        node.tool_id != "elt_import"
        or node.action != "execute"
        or not isinstance(params, dict)
        or node.params != params
        or checkpoint.get("approval_fingerprint") != _approval_fingerprint(checkpoint, params)
    ):
        raise ValueError("审批参数与上传快照不一致，已阻止写入")
    return products


def reject_cross_module_task(run_id: str, reason: str) -> AgentRun | None:
    """Persist rejection on the task and the queue. A rejected task cannot be claimed."""
    from app.application.agent_orchestrator.task_execution_repository import (
        get_task_execution_repository,
    )

    orchestrator = AgentOrchestrator()
    run = orchestrator.get_run(str(run_id or ""))
    if run is None:
        return None
    if run.status not in {"completed", "failed", "cancelled", "rejected"}:
        run.status = "rejected"
        run.error = str(reason or "审批已拒绝")[:500]
        run.add_event("approval.rejected", run.error, {"run_id": run.run_id})
        orchestrator.save_run(run)
    queue = get_task_execution_repository()
    current = queue.get(run.run_id)
    if current is not None and current.state not in {
        "succeeded",
        "failed",
        "rejected",
        "cancelled",
        "timed_out",
    }:
        queue.transition(run.run_id, "rejected", error_code="approval_rejected")
    return orchestrator.get_run(run.run_id) or run


def project_rejected_approval(run: AgentRun) -> AgentRun:
    """Restart reads the approval row. A rejected request cannot stay waiting_user."""
    if str(run.status or "") not in {"waiting_user", "waiting_approval", "queued"}:
        return run
    db_id = run.metadata.get("approval_request_db_id")
    if not db_id:
        return run
    from app.db.models.approval import ApprovalRequest
    from app.db.session import get_db, get_host_db

    context = run.metadata.get("runtime_context") or {}
    session = get_host_db if isinstance(context.get("cross_module_checkpoint"), dict) else get_db
    with session() as db:
        row = db.get(ApprovalRequest, int(db_id))
        status = "" if row is None else str(row.status or "")
        reason = "" if row is None else str(row.rejection_reason or "")
    if status != "rejected":
        return run
    stored = reject_cross_module_task(run.run_id, reason or "审批已拒绝")
    return stored or run


def is_cross_module_client_task(request: dict[str, Any]) -> bool:
    """Only an explicit reviewed ELT execution can select this product transaction."""
    text = str(request.get("message") or "")
    return (request.get("tool_id"), request.get("action")) == ("elt_import", "execute") and all(
        word in text for word in ("Excel", "导入", "产品库")
    )


def _owned_elt_preview(
    db: Session, params: dict[str, Any], context: dict[str, Any]
) -> tuple[EltRun, EltUpload, list[EltRunRow]]:
    """Read the existing ELT authority, preserving its exact preview and actor gates."""
    from fastapi import HTTPException

    from app.application.elt.preview_confirmation import verify_preview
    from app.application.elt.service import get_elt_service
    from app.application.elt.service_execution import _unconfirmed_mappings
    from app.domain.shared_services.tools_workflow_elt import _elt_enabled
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
    from app.infrastructure.auth.business_scope_gate import check_owned_business_permission

    try:
        actor = _bound_actor(context)
        tenant = check_owned_business_permission(actor, "elt.execute")
        check_owned_business_permission(actor, "product.edit")
    except (HTTPException, AgentModAuthorizationError) as exc:
        raise UnifiedTaskError("导入授权不可用，请核对当前账号的企业产品写入权限") from exc
    if (
        not _elt_enabled()
        or str(tenant) != str(context.get("tenant_id"))
        or str(actor.id) != str(context.get("user_id"))
        or tenant != current_tenant_id()
        or set(params) - {"run_id", "preview_revision", "valid_rows_only", "accept_suggested"}
        or not params.get("run_id")
        or not params.get("preview_revision")
    ):
        raise UnifiedTaskError("导入需要当前企业账号的单份 ELT 预演编号和确认版本")
    service = get_elt_service()
    run = service._owned_run(db, str(params["run_id"]), actor.id)
    if (
        run.target_type != "products"
        or run.status != "preview_ready"
        or run.rollback_status
        or (
            run.operation_token
            and run.operation_token != getattr(db.info.get("elt_operation_owner"), "token", None)
        )
        or run.update_rows
        or not run.new_rows
    ):
        raise UnifiedTaskError("此产品导入仅接受已就绪的新建行预演，请核对原 ELT 任务")
    if run.error_rows and params.get("valid_rows_only") is not True:
        raise UnifiedTaskError("预演包含错误行，必须明确确认仅导入正确行")
    if _unconfirmed_mappings(load_json(run.draft_json, {}).get("field_mappings")) and (
        params.get("accept_suggested") is not True
    ):
        raise UnifiedTaskError("预演字段映射尚未确认")
    verify_preview(db, run, str(params["preview_revision"]))
    upload = service._execution_upload(db, run, actor.id)
    rows = (
        db.query(EltRunRow)
        .filter_by(run_id=run.id, tenant_id=tenant, owner_user_id=actor.id)
        .order_by(EltRunRow.id)
        .all()
    )
    if sum(row.final_action == "new" for row in rows) != run.new_rows or any(
        row.execution_status or row.final_action == "update" for row in rows
    ):
        raise UnifiedTaskError("预演行与执行范围不一致，已阻止写入")
    return run, upload, rows


def create_cross_module_task(**request: Any) -> UnifiedTaskResult:
    if is_cross_module_client_task(request):
        with _cross_module_scope(request.get("runtime_context") or {}):
            return _create_cross_module_task(**request)
    return create_unified_task(**request)


def _create_cross_module_task(**request: Any) -> UnifiedTaskResult:
    from app.db.session import get_db

    selected = is_cross_module_client_task(request)
    context = request.get("runtime_context") or {}
    orchestrator = request["orchestrator"]
    existing = orchestrator.get_task(
        user_id=request["user_id"],
        task_id=request["task_id"],
        tenant_id=context.get("tenant_id", ""),
    )
    if selected and existing is None:
        try:
            with get_db() as db:
                _owned_elt_preview(db, request["params"], context)
        except EltError as exc:
            raise UnifiedTaskError("ELT 预演不属于当前账号或内容已经变化，请重新核对") from exc
    result = create_unified_task(**request)
    if selected and not result.deduplicated:
        begin_cross_module_http(
            orchestrator, result.run, params=request["params"], runtime_context=context
        )
        result = UnifiedTaskResult(run=orchestrator.get_run(result.run.run_id) or result.run)
    return result


def _workflow_receipt(
    request_id: str,
    *,
    success: bool,
    loaded_from_storage: bool,
    execution_accepted: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    from app.application.workflow.approval_persistence import (
        WORKFLOW_EXECUTION_FAILED_CODE,
        WORKFLOW_EXECUTION_SUCCESS_CODE,
    )

    if execution_accepted and not success:
        return {
            "workflow_executed": False,
            "approval_request_id": request_id,
            "success": False,
            "execution_accepted": True,
            "code": "queued",
            "message": "审批已通过，执行已交给调度器",
            "nodes_executed": 0,
            "nodes_total": 1,
            "loaded_from_storage": loaded_from_storage,
            **extra,
        }
    return {
        "workflow_executed": True,
        "approval_request_id": request_id,
        "success": success,
        "code": WORKFLOW_EXECUTION_SUCCESS_CODE if success else WORKFLOW_EXECUTION_FAILED_CODE,
        "message": "AI 工作流执行完成" if success else "AI 工作流执行失败",
        "nodes_executed": 1 if success else 0,
        "nodes_total": 1,
        "loaded_from_storage": loaded_from_storage,
        **extra,
    }


def begin_cross_module_http(
    orchestrator: AgentOrchestrator,
    run: AgentRun,
    *,
    params: dict[str, Any],
    runtime_context: dict[str, Any],
) -> None:
    """Parse the uploaded workbook and persist the approval. Do not write ERP yet."""
    from app.application.agent_orchestrator.artifact_files import artifact_path, store_spreadsheet

    context = dict(run.metadata.get("runtime_context") or runtime_context)
    tenant_text = str(context.get("tenant_id") or "")
    user_text = str(context.get("user_id") or run.user_id)
    if (
        not tenant_text.isdigit()
        or int(tenant_text) <= 0
        or str(current_tenant_id()) != tenant_text
        or not user_text.isdigit()
        or int(user_text) <= 0
    ):
        raise UnifiedTaskError("任务缺少有效账号和租户，已停止写入")
    from app.db.session import get_db

    try:
        with get_db() as db:
            _preview, upload, rows = _owned_elt_preview(db, params, context)
            source, source_body = _source_bytes(upload.storage_path, user_id=int(user_text), db=db)
            cleaned: dict[str, Any] = {"qualifying": [], "anomalies": []}
            for row in rows:
                item: dict[str, Any] = {
                    "data": load_json(row.normalized_json, {}),
                    "row_number": row.source_row,
                }
                if row.final_action == "new":
                    cleaned["qualifying"].append(item)
                elif row.final_action == "error":
                    item["issues"] = load_json(row.validation_json, [])
                    cleaned["anomalies"].append(item)
    except (ValueError, OSError, EltError) as exc:
        raise UnifiedTaskError("业务文件不可访问或不属于当前账号，请重新上传") from exc
    original_hash = hashlib.sha256(source_body).hexdigest()
    store_spreadsheet(run.run_id, source_body, name=source.name)
    if not cleaned.get("qualifying"):
        raise RuntimeError("没有可导入的合格行，已停止写入")
    result_path = artifact_path(run.run_id, "cross_module_import")
    files = write_result_workbook(result_path, cleaned)
    checkpoint = {
        "trace_id": uuid.uuid4().hex,
        "task_id": str(context.get("task_id") or ""),
        "run_id": run.run_id,
        "user_id": user_text,
        "tenant_id": tenant_text,
        "session_id": str(context.get("session_id") or context.get("conversation_id") or ""),
        "source_path": str(source),
        "original_sha256": original_hash,
        "result_path": files["result_path"],
        "result_sha256": files["sha256"],
        "anomaly_csv": files["anomaly_csv"],
        "qualifying": [dict(row["data"]) for row in cleaned["qualifying"]],
        "anomaly_count": len(cleaned["anomalies"]),
        "elt_params": dict(params),
    }
    checkpoint["idempotency_key"] = canonical_hash(
        {key: checkpoint[key] for key in ("tenant_id", "user_id", "task_id")}
    )
    node_params = dict(params)
    checkpoint["approval_fingerprint"] = _approval_fingerprint(checkpoint, node_params)
    context["cross_module_http"] = True
    context["cross_module_checkpoint"] = checkpoint
    plan = PlanGraph(
        plan_id="plan-approve-" + checkpoint["task_id"],
        intent=str(run.message or ""),
        nodes=[
            WorkflowNode(
                "write",
                "elt_import",
                "execute",
                params=node_params,
                risk="high",
                idempotent=False,
                description="导入产品",
            )
        ],
        risk_level="high",
    )
    from app.application.workflow.approval_service import get_approval_service

    approval = get_approval_service()
    gate = WorkflowApprovalPolicy(
        approval_service=approval,
        require_persistence=True,
    )
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    # Approval and task ledgers remain in the host authority; business data stays in the Mod.
    approval_scope = set_request_active_mod_id("")
    try:
        with tenant_scope(int(tenant_text)):
            decision = gate.evaluate_plan(plan, runtime_context=context)
            request_id = decision.approval_request_ids[0] if decision.approval_request_ids else ""
            if not request_id:
                created = approval.create_approval_request(
                    plan.plan_id,
                    plan.nodes[0],
                    runtime_context=context,
                    plan=plan,
                    require_persistence=True,
                )
                request_id = created.request_id
            metadata = approval.get_request_metadata(request_id) or {}
    finally:
        reset_request_active_mod_id(approval_scope)
    if not metadata.get("id"):
        raise RuntimeError("审批请求未能持久化，已阻止数据库写入")
    run.metadata["runtime_context"] = context
    run.metadata["trace_id"] = checkpoint["trace_id"]
    run.metadata["approval_request_id"] = request_id
    run.metadata["approval_request_db_id"] = int(metadata["id"])
    run.metadata["approval_loaded_from_storage"] = False
    # waiting_user is the existing person-wait alias of canonical waiting_approval.
    run.status = "waiting_user"
    run.add_event(
        "task.queued",
        "任务已写入持久队列，等待审批后由调度器认领",
        {"priority": 1, "queue": "agent_task_executions"},
    )
    orchestrator.save_run(run)
    from app.application.agent_orchestrator.task_execution_repository import (
        get_task_execution_repository,
    )

    get_task_execution_repository().enqueue_waiting_approval(
        run,
        requested_by=_QUEUE_OWNER,
        priority=1,
        approver=user_text,
    )
    _audit(
        "client.task_started",
        checkpoint["trace_id"],
        checkpoint["task_id"],
        checkpoint["user_id"],
        tenant_text,
        session_id=checkpoint["session_id"],
        file_sha256=original_hash,
        status="waiting_approval",
        queue_state="queued",
        request=run.message,
    )


def cross_module_ready(run: AgentRun | None) -> bool:
    if run is None or run.metadata.get("cross_module_dispatch") != "approved":
        return False
    context = run.metadata.get("runtime_context") or {}
    return isinstance(context.get("cross_module_checkpoint"), dict)


from app.application.agent_orchestrator.cross_module_execution import (
    InjectedTransactionFault,
    _cross_module_scope,
    drive_cross_module_execution,
    execute_claimed_cross_module,
    load_cross_module_http_result,
    raise_if_tx_fault,
    resume_cross_module_http,
)

__all__ = [
    "InjectedTransactionFault",
    "begin_cross_module_http",
    "cross_module_ready",
    "drive_cross_module_execution",
    "execute_claimed_cross_module",
    "identify_workbook",
    "import_products",
    "is_cross_module_client_task",
    "load_cross_module_http_result",
    "project_rejected_approval",
    "raise_if_tx_fault",
    "reject_cross_module_task",
    "resume_cross_module_http",
    "slice_and_clean",
    "verify_against_data",
    "write_result_workbook",
]
