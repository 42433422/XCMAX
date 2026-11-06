"""Claimed cross-module execution and the idempotent HTTP body.

The workbook parse and approval park stay in ``cross_module_chain``. This module
owns one claimed queue row: the product write, the response stored in that same
transaction, and the handoff that must not block the approval request thread.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.application.agent_orchestrator.business_harness import BUSINESS_HARNESS_PROTOCOL
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.elt.errors import EltError
from app.application.elt.targets.helpers import assert_created_row_unchanged
from app.application.elt.targets.products import ProductAdapter
from app.db.models.product import Product
from app.domain.task_lifecycle.control import SessionBook
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope


class InjectedTransactionFault(RuntimeError):
    """Test-only interrupt at a real commit boundary. Off unless XCAGI_TX_FAULT is set."""


def raise_if_tx_fault(point: str) -> None:
    """Fault injection for interrupted commits. The default environment does nothing."""
    mode = os.environ.get("XCAGI_TX_FAULT", "").strip()
    if mode and mode == point:
        raise InjectedTransactionFault(point)


def _import_approved_products(
    db: Session, checkpoint: dict[str, Any], products: list[dict[str, Any]]
) -> tuple[dict[str, Any], int]:
    """Keep the key, products and receipt in the caller's single transaction."""
    from app.application.agent_orchestrator import cross_module_chain as chain

    tenant = str(checkpoint["tenant_id"])
    run_id = str(checkpoint["run_id"])
    fingerprint = str(checkpoint["approval_fingerprint"])
    if str(current_tenant_id()) != tenant or products != checkpoint.get("qualifying"):
        raise ValueError("写入范围与审批快照不一致")
    book = SessionBook(db)
    prior = book.claim_key(
        chain._DELIVERY_MODULE, tenant, str(checkpoint["idempotency_key"]), fingerprint, run_id
    )
    if prior and prior != run_id:
        raise ValueError("幂等键属于其他任务，已阻止写入")
    record = book.get(chain._DELIVERY_MODULE, tenant, run_id)
    receipt = record.get("delivery")
    replayed = receipt is not None
    binding = {key: checkpoint[key] for key in ("tenant_id", "user_id", "task_id", "run_id")}
    if receipt is None:
        imported = chain.import_products(db, [{"data": product} for product in products])
        receipt = {
            "binding": binding,
            "fingerprint": fingerprint,
            "written": imported["written"],
        }
        record["delivery"] = receipt
        book.put(chain._DELIVERY_MODULE, tenant, run_id, record)
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
    _persist_http_result(
        db,
        checkpoint,
        http_status=200,
        execution_status="committed",
        body={
            "success": True,
            "idempotency_key": str(checkpoint["idempotency_key"]),
            "request_digest": fingerprint,
            "execution_status": "committed",
            "business_result_ref": _business_result_ref(checkpoint),
            "data": {
                "run_id": run_id,
                "task_id": str(checkpoint["task_id"]),
                "status": "committed",
                "stored_count": len(seen),
                "replayed": replayed,
            },
        },
        overwrite=False,
    )
    return {"count": len(seen), "replayed": replayed}, len(seen)


def _business_result_ref(checkpoint: dict[str, Any]) -> dict[str, str]:
    from app.application.agent_orchestrator import cross_module_chain as chain

    return {
        "module": chain._DELIVERY_MODULE,
        "tenant_id": str(checkpoint.get("tenant_id") or ""),
        "run_id": str(checkpoint.get("run_id") or ""),
        "task_id": str(checkpoint.get("task_id") or ""),
    }


def _persist_http_result(
    db: Session,
    checkpoint: dict[str, Any],
    *,
    http_status: int,
    execution_status: str,
    body: dict[str, Any],
    overwrite: bool,
) -> None:
    """Store the client payload in the same database as the business rows."""
    from app.application.agent_orchestrator import cross_module_chain as chain

    tenant = str(checkpoint.get("tenant_id") or "")
    key = str(checkpoint.get("idempotency_key") or "")
    if not tenant or not key:
        return
    book = SessionBook(db)
    current = book.get(chain._RESPONSE_MODULE, tenant, key)
    if current.get("body") and (not overwrite or current.get("execution_status") != "committed"):
        return
    book.put(
        chain._RESPONSE_MODULE,
        tenant,
        key,
        {
            "idempotency_key": key,
            "request_digest": str(checkpoint.get("approval_fingerprint") or ""),
            "execution_status": execution_status,
            "http_status": int(http_status),
            "body": body,
            "business_result_ref": _business_result_ref(checkpoint),
        },
    )


def load_cross_module_http_result(tenant_id: str, idempotency_key: str) -> dict[str, Any] | None:
    """Read the committed response. Missing rows are not an execution."""
    from app.application.agent_orchestrator import cross_module_chain as chain

    if not str(tenant_id or "").strip() or not str(idempotency_key or "").strip():
        return None
    from app.db.session import get_db

    with get_db() as db:
        stored = SessionBook(db).get(chain._RESPONSE_MODULE, str(tenant_id), str(idempotency_key))
    if not isinstance(stored, dict) or not isinstance(stored.get("body"), dict):
        return None
    return stored


def resume_cross_module_http(
    workflow: dict[str, Any], *, request_id: str, loaded_from_storage: bool
) -> dict[str, Any]:
    """Continue the same task from the stored approval snapshot."""
    from app.application.agent_orchestrator import cross_module_chain as chain

    try:
        return _resume_cross_module_http(
            workflow, request_id=request_id, loaded_from_storage=loaded_from_storage
        )
    except chain._IMPORT_ERRORS as exc:
        logging.getLogger(__name__).warning(
            "cross-module resume failed type=%s", type(exc).__name__
        )
        return chain._workflow_receipt(
            request_id, success=False, loaded_from_storage=loaded_from_storage
        )


def execute_claimed_cross_module(
    orchestrator: AgentOrchestrator,
    run: AgentRun,
    *,
    owner: str,
    queue: Any,
    request_id: str,
    finish: bool,
) -> dict[str, Any]:
    """Run one already-claimed queue row. Callers finish the lease unless faulted."""
    from app.application.agent_orchestrator import cross_module_chain as chain
    from app.application.agent_orchestrator.artifact_files import store_spreadsheet
    from app.application.agent_orchestrator.run_models import artifact_from_dict
    from app.db.session import get_db

    context = run.metadata.get("runtime_context") or {}
    checkpoint = context.get("cross_module_checkpoint")
    if not isinstance(checkpoint, dict) or run.status == "rejected":
        if finish:
            queue.finish(run.run_id, owner, "failed", error_code="approval_rejected")
        return chain._workflow_receipt(request_id, success=False, loaded_from_storage=True)
    products = list(checkpoint.get("qualifying") or [])
    source = Path(checkpoint["source_path"])
    result_path = Path(checkpoint["result_path"])
    original_hash = str(checkpoint["original_sha256"])
    user_id = int(checkpoint["user_id"])
    tenant_text = str(checkpoint["tenant_id"])
    try:
        raise_if_tx_fault("crash_before_import")
        with get_db() as db, tenant_scope(int(tenant_text)):
            imported, stored_count = _import_approved_products(db, checkpoint, products)
            _, source_body = chain._source_bytes(source, user_id=user_id, db=db)
            if hashlib.sha256(source_body).hexdigest() != original_hash:
                raise ValueError("上传文件已变化，已回滚导入")
            raise_if_tx_fault("rollback_before_commit")
        raise_if_tx_fault("crash_after_commit")
        with tenant_scope(int(tenant_text)):
            employee = chain._run_employee(
                "excel-full-read-employee",
                "读取导入结果",
                {"file_path": str(result_path)},
                result_path.parent,
                user_id=user_id,
            )
        employee_ok = bool(employee["result"].get("success"))
        anomaly_count = int(checkpoint.get("anomaly_count") or 0)
        verification = chain.verify_against_data(
            qualifying_count=len(products),
            anomaly_count=anomaly_count,
            stored_count=stored_count,
            tool_success=True,
            result_sha=str(checkpoint["result_sha256"]),
            result_path=result_path,
        )
        _, source_body = chain._source_bytes(source, user_id=user_id)
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
        business_status = verification["status"] if accepted else "failed"
        run.status = "completed" if accepted else "failed"
        run.final_output = {
            "business_result": {
                "protocol": BUSINESS_HARNESS_PROTOCOL,
                "status": business_status,
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
                "idempotency_key": checkpoint["idempotency_key"],
                "request_digest": checkpoint.get("approval_fingerprint"),
            }
        }
        run.metadata["approval_loaded_from_storage"] = True
        run.metadata["result_sha256"] = download_sha
        orchestrator.save_run(run)
        receipt = chain._workflow_receipt(
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
        response_body = {
            "success": accepted,
            "idempotency_key": str(checkpoint["idempotency_key"]),
            "request_digest": str(checkpoint.get("approval_fingerprint") or ""),
            "execution_status": business_status,
            "business_result_ref": _business_result_ref(checkpoint),
            "data": {
                "run_id": run.run_id,
                "task_id": str(checkpoint["task_id"]),
                "status": run.status,
                "final_output": run.final_output,
                "stored_count": stored_count,
                "replayed": imported["replayed"],
            },
            "workflow": receipt,
        }
        with get_db() as db:
            _persist_http_result(
                db,
                checkpoint,
                http_status=200,
                execution_status=business_status,
                body=response_body,
                overwrite=True,
            )
        if finish:
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
            chain._audit(
                event,
                str(checkpoint["trace_id"]),
                str(checkpoint["task_id"]),
                str(checkpoint["user_id"]),
                tenant_text,
                **details,
            )
        return receipt
    except InjectedTransactionFault:
        raise
    except chain._IMPORT_ERRORS as exc:
        if finish:
            queue.finish(
                run.run_id,
                owner,
                "failed",
                error_code="invalid_approved_input"
                if isinstance(exc, (ValueError, EltError))
                else "upstream_unavailable",
            )
        raise


def _stored_receipt(run: AgentRun, request_id: str) -> dict[str, Any] | None:
    from app.application.agent_orchestrator import cross_module_chain as chain

    context = run.metadata.get("runtime_context") or {}
    checkpoint = context.get("cross_module_checkpoint") or {}
    stored = load_cross_module_http_result(
        str(checkpoint.get("tenant_id") or ""),
        str(checkpoint.get("idempotency_key") or ""),
    )
    if stored is None:
        return None
    workflow = stored["body"].get("workflow")
    if isinstance(workflow, dict) and workflow.get("approval_request_id"):
        return workflow
    data = stored["body"].get("data") if isinstance(stored["body"].get("data"), dict) else {}
    return chain._workflow_receipt(
        request_id,
        success=bool(stored["body"].get("success")),
        loaded_from_storage=True,
        stored_count=int(data.get("stored_count") or 0),
        replayed=True,
        idempotent_replay=True,
    )


_TERMINAL_QUEUE_STATES = frozenset(
    {"succeeded", "failed", "rejected", "cancelled", "timed_out", "completed"}
)


def drive_cross_module_execution(
    orchestrator: AgentOrchestrator,
    run: AgentRun,
    queue: Any,
    request_id: str,
) -> dict[str, Any]:
    """Claim on this worker, or leave the run with the dispatcher.

    The caller is the approval request thread when a person approves. It must
    not poll or sleep. A running dispatcher is woken and finishes the claim.
    """
    from app.application.agent_orchestrator import cross_module_chain as chain
    from app.application.agent_orchestrator.task_dispatcher import get_agent_task_dispatcher

    dispatcher = get_agent_task_dispatcher()
    dispatcher.notify()
    # A dispatcher left over from another database must not strand this request.
    same_queue = getattr(dispatcher, "_execution_repo", None) is queue
    if dispatcher.snapshot().get("running") and same_queue:
        return _handoff_receipt(run, queue, request_id)
    owner = chain._QUEUE_OWNER + "-" + uuid.uuid4().hex
    claimed = queue.claim(owner, lease_seconds=60, run_id=run.run_id)
    if claimed is None or claimed.run_id != run.run_id:
        return _handoff_receipt(run, queue, request_id)
    return execute_claimed_cross_module(
        orchestrator, run, owner=owner, queue=queue, request_id=request_id, finish=True
    )


def _handoff_receipt(run: AgentRun, queue: Any, request_id: str) -> dict[str, Any]:
    """Return a finished body, or accept the queue handoff. Never sleep."""
    from app.application.agent_orchestrator import cross_module_chain as chain

    current = queue.get(run.run_id)
    state = "" if current is None else str(current.state)
    if state in _TERMINAL_QUEUE_STATES:
        stored = _stored_receipt(run, request_id)
        if stored is not None:
            return stored
        return chain._workflow_receipt(
            request_id,
            success=state in {"succeeded", "completed"},
            loaded_from_storage=True,
        )
    return chain._workflow_receipt(
        request_id,
        success=False,
        loaded_from_storage=True,
        execution_accepted=True,
        queue_state=state or "queued",
    )


def _resume_cross_module_http(
    workflow: dict[str, Any], *, request_id: str, loaded_from_storage: bool
) -> dict[str, Any]:
    from app.application.agent_orchestrator import cross_module_chain as chain
    from app.application.agent_orchestrator.task_execution_repository import (
        get_task_execution_repository,
    )

    context = workflow.get("runtime_context") if isinstance(workflow, dict) else None
    checkpoint = context.get("cross_module_checkpoint") if isinstance(context, dict) else None
    if not loaded_from_storage or not isinstance(checkpoint, dict):
        return chain._workflow_receipt(request_id, success=False, loaded_from_storage=False)
    orchestrator = AgentOrchestrator()
    run = orchestrator.get_run(str(checkpoint.get("run_id") or ""))
    if run is None:
        return chain._workflow_receipt(request_id, success=False, loaded_from_storage=True)
    if run.status == "rejected":
        return chain._workflow_receipt(request_id, success=False, loaded_from_storage=True)
    chain._approved_products(workflow, run, checkpoint, request_id)
    source = Path(checkpoint["source_path"])
    result_path = Path(checkpoint["result_path"])
    original_hash = str(checkpoint["original_sha256"])
    user_id = int(checkpoint["user_id"])
    _, source_body = chain._source_bytes(source, user_id=user_id)
    if (
        hashlib.sha256(source_body).hexdigest() != original_hash
        or not result_path.is_file()
        or chain._sha256(result_path) != checkpoint["result_sha256"]
    ):
        return chain._workflow_receipt(
            request_id, success=False, loaded_from_storage=True, source_unchanged=False
        )
    queue = get_task_execution_repository()
    current = queue.get(run.run_id)
    if current is not None and current.state in {"rejected", "cancelled"}:
        return chain._workflow_receipt(request_id, success=False, loaded_from_storage=True)
    if current is not None and current.state in {"succeeded", "completed"}:
        stored = _stored_receipt(run, request_id)
        if stored is not None:
            return stored
    run.metadata["cross_module_dispatch"] = "approved"
    run.status = "queued"
    run.add_event("task.queued", "审批已通过，任务进入执行队列", {"priority": 1})
    orchestrator.save_run(run)
    released = queue.enqueue(run, requested_by=chain._QUEUE_OWNER, priority=1)
    if released is None or released.state != "queued":
        return chain._workflow_receipt(request_id, success=False, loaded_from_storage=True)
    return drive_cross_module_execution(orchestrator, run, queue, request_id)
