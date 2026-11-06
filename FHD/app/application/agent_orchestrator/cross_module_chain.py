"""Cross-module business chain: client task, agent, workflow, scheduler, employee, ETL, ERP, MOD.

Each step calls an existing module and keeps the business result tied to rows, files,
and hashes. A tool ``success`` flag is not enough to mark the task complete.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.business_harness import BUSINESS_HARNESS_PROTOCOL
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.unified_task import UnifiedTaskError
from app.application.elt.errors import EltError
from app.application.elt.parser_structure import clean_cell_text, detect_table_layout
from app.application.elt.parsers import parse_file
from app.application.elt.service_support import MAX_FILE_BYTES
from app.application.elt.service_uploads import UploadServiceMixin
from app.application.elt.targets.helpers import assert_created_row_unchanged
from app.application.elt.targets.products import ProductAdapter
from app.application.employee_runtime.executor import execute_employee_task_local
from app.application.employee_runtime.loader import load_employee_pack_from_disk
from app.application.shipment_excel_etl_security import (
    ShipmentEtlPathError,
    open_etl_input_file,
    resolve_etl_path,
)
from app.application.workflow.approval_gated_engine import ApprovalGatedEngine
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.db.models.elt import EltUpload
from app.db.models.product import Product
from app.domain.task_lifecycle.control import SessionBook
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope
from app.utils.logging.audit_logger import audit_log
from app.utils.operational_errors import RECOVERABLE_ERRORS

_DELIVERY_MODULE = "cross_module_import"
_IMPORT_ERRORS: tuple[type[Exception], ...] = (SQLAlchemyError, *RECOVERABLE_ERRORS)

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
    upload_root = Path(get_app_data_dir()).resolve() / "etl" / "uploads"
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
            raise ShipmentEtlPathError("上传文件不属于当前账号")
        upload = UploadServiceMixin()._owned_upload(db, upload.id, user_id)
        source = Path(upload.storage_path)
        expected_sha = upload.sha256
        opened = open_etl_input_file(source, owner_user_id=user_id)
    else:
        source = resolve_etl_path(candidate)
        opened = open_etl_input_file(source)
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
    params = {"products": products, "file_path": checkpoint["source_path"]}
    if (
        node.tool_id != "products"
        or node.action != "batch_create"
        or node.params != params
        or checkpoint.get("approval_fingerprint") != _approval_fingerprint(checkpoint, params)
    ):
        raise ValueError("审批参数与上传快照不一致，已阻止写入")
    return products


def _import_approved_products(
    db: Session, checkpoint: dict[str, Any], products: list[dict[str, Any]]
) -> tuple[dict[str, Any], int]:
    """Keep the key, products and receipt in the caller's single transaction."""
    tenant = str(checkpoint["tenant_id"])
    run_id = str(checkpoint["run_id"])
    fingerprint = str(checkpoint["approval_fingerprint"])
    if str(current_tenant_id()) != tenant or products != checkpoint.get("qualifying"):
        raise ValueError("写入范围与审批快照不一致")
    book = SessionBook(db)
    prior = book.claim_key(
        _DELIVERY_MODULE, tenant, str(checkpoint["idempotency_key"]), fingerprint, run_id
    )
    if prior and prior != run_id:
        raise ValueError("幂等键属于其他任务，已阻止写入")
    record = book.get(_DELIVERY_MODULE, tenant, run_id)
    receipt = record.get("delivery")
    replayed = receipt is not None
    binding = {key: checkpoint[key] for key in ("tenant_id", "user_id", "task_id", "run_id")}
    if receipt is None:
        imported = import_products(db, [{"data": product} for product in products])
        receipt = {
            "binding": binding,
            "fingerprint": fingerprint,
            "written": imported["written"],
        }
        record["delivery"] = receipt
        book.put(_DELIVERY_MODULE, tenant, run_id, record)
    if (
        not isinstance(receipt, dict)
        or receipt.get("binding") != binding
        or receipt.get("fingerprint") != fingerprint
        or not isinstance(receipt.get("written"), list)
        or len(receipt["written"]) != len(products)
    ):
        raise ValueError("导入回执与审批内容不一致")
    seen: set[int] = set()
    for item in receipt["written"]:
        product_id = int(item["match_ref"])
        if product_id in seen:
            raise ValueError("导入回执含重复产品")
        seen.add(product_id)
        stored = (
            db.query(Product)
            .filter(Product.id == product_id, Product.tenant_id == int(tenant))
            .populate_existing()
            .one_or_none()
        )
        if stored is None:
            raise ValueError("导入产品不存在或不属于该租户")
        assert_created_row_unchanged(stored, item["after"], ProductAdapter.fields, "产品")
    return {"count": len(seen), "replayed": replayed}, len(seen)


def is_cross_module_client_task(message: str, params: dict[str, Any] | None) -> bool:
    """The desktop task API already accepts this business request; no second route."""
    text = str(message or "")
    file_path = str((params or {}).get("file_path") or "").strip()
    return "Excel" in text and "导入" in text and "产品库" in text and bool(file_path)


def _workflow_receipt(
    request_id: str, *, success: bool, loaded_from_storage: bool, **extra: Any
) -> dict[str, Any]:
    from app.application.workflow.approval_persistence import (
        WORKFLOW_EXECUTION_FAILED_CODE,
        WORKFLOW_EXECUTION_SUCCESS_CODE,
    )

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
    try:
        source, source_body = _source_bytes(
            str(params.get("file_path") or ""), user_id=int(user_text)
        )
    except (ValueError, OSError, EltError) as exc:
        raise UnifiedTaskError("业务文件不可访问或不属于当前账号，请重新上传") from exc
    original_hash = hashlib.sha256(source_body).hexdigest()
    snapshot = store_spreadsheet(run.run_id, source_body, name=source.name)
    identified = identify_workbook(artifact_path(run.run_id, snapshot["artifact_id"]))
    cleaned = slice_and_clean(identified)
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
    }
    checkpoint["idempotency_key"] = canonical_hash(
        {key: checkpoint[key] for key in ("tenant_id", "user_id", "task_id")}
    )
    node_params = {
        "products": checkpoint["qualifying"],
        "file_path": str(source),
    }
    checkpoint["approval_fingerprint"] = _approval_fingerprint(checkpoint, node_params)
    context["cross_module_http"] = True
    context["cross_module_checkpoint"] = checkpoint
    plan = PlanGraph(
        plan_id="plan-approve-" + checkpoint["task_id"],
        intent=str(run.message or ""),
        nodes=[
            WorkflowNode(
                "write",
                "products",
                "batch_create",
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
    gate = ApprovalGatedEngine(
        WorkflowEngine(lambda **_kwargs: {"success": False}),
        approval_service=approval,
        require_persistence=True,
    )
    with tenant_scope(int(tenant_text)):
        decision = gate.evaluate_plan(plan, runtime_context=context, strategy="interactive")
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
    if not metadata.get("id"):
        raise RuntimeError("审批请求未能持久化，已阻止数据库写入")
    run.metadata["runtime_context"] = context
    run.metadata["trace_id"] = checkpoint["trace_id"]
    run.metadata["approval_request_id"] = request_id
    run.metadata["approval_request_db_id"] = int(metadata["id"])
    run.metadata["approval_loaded_from_storage"] = False
    run.status = "waiting_user"
    orchestrator.save_run(run)
    _audit(
        "client.task_started",
        checkpoint["trace_id"],
        checkpoint["task_id"],
        checkpoint["user_id"],
        tenant_text,
        session_id=checkpoint["session_id"],
        file_sha256=original_hash,
        status="waiting_approval",
        request=run.message,
    )


def resume_cross_module_http(
    workflow: dict[str, Any], *, request_id: str, loaded_from_storage: bool
) -> dict[str, Any]:
    """Continue the same task from the stored approval snapshot."""
    try:
        return _resume_cross_module_http(
            workflow, request_id=request_id, loaded_from_storage=loaded_from_storage
        )
    except _IMPORT_ERRORS as exc:
        logging.getLogger(__name__).warning(
            "cross-module resume failed type=%s", type(exc).__name__
        )
        return _workflow_receipt(request_id, success=False, loaded_from_storage=loaded_from_storage)


def _resume_cross_module_http(
    workflow: dict[str, Any], *, request_id: str, loaded_from_storage: bool
) -> dict[str, Any]:
    from app.application.agent_orchestrator.artifact_files import store_spreadsheet
    from app.application.agent_orchestrator.run_models import artifact_from_dict
    from app.application.agent_orchestrator.task_execution_repository import (
        get_task_execution_repository,
    )
    from app.db.session import get_db

    context = workflow.get("runtime_context") if isinstance(workflow, dict) else None
    checkpoint = context.get("cross_module_checkpoint") if isinstance(context, dict) else None
    if not loaded_from_storage or not isinstance(checkpoint, dict):
        return _workflow_receipt(request_id, success=False, loaded_from_storage=False)
    orchestrator = AgentOrchestrator()
    run = orchestrator.get_run(str(checkpoint.get("run_id") or ""))
    if run is None:
        return _workflow_receipt(request_id, success=False, loaded_from_storage=True)
    products = _approved_products(workflow, run, checkpoint, request_id)
    source = Path(checkpoint["source_path"])
    result_path = Path(checkpoint["result_path"])
    original_hash = str(checkpoint["original_sha256"])
    user_id = int(checkpoint["user_id"])
    _, source_body = _source_bytes(source, user_id=user_id)
    if (
        hashlib.sha256(source_body).hexdigest() != original_hash
        or not result_path.is_file()
        or _sha256(result_path) != checkpoint["result_sha256"]
    ):
        return _workflow_receipt(
            request_id, success=False, loaded_from_storage=True, source_unchanged=False
        )
    queue = get_task_execution_repository()
    queue.enqueue(run, requested_by="cross-module-http", priority=1)
    owner = "cross-module-http-" + uuid.uuid4().hex
    claimed = queue.claim(owner, lease_seconds=60, run_id=run.run_id)
    if claimed is None or claimed.run_id != run.run_id:
        return _workflow_receipt(request_id, success=False, loaded_from_storage=True)
    tenant_text = str(checkpoint["tenant_id"])
    try:
        with get_db() as db, tenant_scope(int(tenant_text)):
            imported, stored_count = _import_approved_products(db, checkpoint, products)
            _, source_body = _source_bytes(source, user_id=user_id, db=db)
            if hashlib.sha256(source_body).hexdigest() != original_hash:
                raise ValueError("上传文件已变化，已回滚导入")
        with tenant_scope(int(tenant_text)):
            employee = _run_employee(
                "excel-full-read-employee",
                "读取导入结果",
                {"file_path": str(result_path)},
                result_path.parent,
                user_id=user_id,
            )
        employee_ok = bool(employee["result"].get("success"))
        anomaly_count = int(checkpoint.get("anomaly_count") or 0)
        verification = verify_against_data(
            qualifying_count=len(products),
            anomaly_count=anomaly_count,
            stored_count=stored_count,
            tool_success=True,
            result_sha=str(checkpoint["result_sha256"]),
            result_path=result_path,
        )
        _, source_body = _source_bytes(source, user_id=user_id)
        source_unchanged = hashlib.sha256(source_body).hexdigest() == original_hash
        content = result_path.read_bytes() if result_path.is_file() else b""
        download_sha = hashlib.sha256(content).hexdigest() if content else ""
        artifact = store_spreadsheet(run.run_id, content, name="result.xlsx") if content else None
        if artifact is not None and not any(
            item.artifact_id == artifact["artifact_id"] for item in run.artifacts
        ):
            run.artifacts.append(artifact_from_dict(artifact))
        accepted = bool(
            verification["accepted"]
            and employee_ok
            and source_unchanged
            and download_sha == checkpoint["result_sha256"]
        )
        run.status = "completed" if accepted else "failed"
        run.final_output = {
            "business_result": {
                "protocol": BUSINESS_HARNESS_PROTOCOL,
                "status": verification["status"] if accepted else "failed",
                "success": accepted and verification["status"] == "completed",
                "summary": f"导入 {stored_count} 条，异常 {anomaly_count} 条",
                "file_name": "result.xlsx",
                "sha256": download_sha,
                "trace_id": checkpoint["trace_id"],
                "task_id": checkpoint["task_id"],
                "run_id": run.run_id,
                "loaded_from_storage": True,
                "employee_success": employee_ok,
                "source_unchanged": source_unchanged,
            }
        }
        run.metadata["approval_loaded_from_storage"] = True
        run.metadata["result_sha256"] = download_sha
        orchestrator.save_run(run)
        queue.finish(run.run_id, owner, "completed" if accepted else "failed")
        for event, details in (
            (
                "approval.decided",
                {"approved": True, "loaded_from_storage": True, "request_ids": [request_id]},
            ),
            (
                "agent.verified",
                {"verification": verification, "source_unchanged": source_unchanged},
            ),
            ("erp.updated", {"replayed": imported["replayed"], "stored_count": stored_count}),
        ):
            _audit(
                event,
                str(checkpoint["trace_id"]),
                str(checkpoint["task_id"]),
                str(checkpoint["user_id"]),
                tenant_text,
                **details,
            )
        return _workflow_receipt(
            request_id,
            success=accepted,
            loaded_from_storage=True,
            stored_count=stored_count,
            verification_status=verification["status"],
            result_sha256=download_sha,
            source_unchanged=source_unchanged,
            employee_success=employee_ok,
            replayed=imported["replayed"],
        )
    except _IMPORT_ERRORS as exc:
        queue.finish(
            run.run_id,
            owner,
            "failed",
            error_code="invalid_approved_input"
            if isinstance(exc, (ValueError, EltError))
            else "upstream_unavailable",
        )
        raise
