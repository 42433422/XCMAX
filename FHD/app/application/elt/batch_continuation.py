"""Bind the unfinished files of an approved import to its existing workflow task."""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from typing import Any
from typing import cast as type_cast

from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.run_lifecycle import requires_retry_reconciliation
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.task_context import task_context_of
from app.application.attachment_artifacts.models import ArtifactScope, artifact_scope_from_context
from app.application.attachment_artifacts.store import ArtifactStore
from app.application.elt.service_support import load_json
from app.application.shipment_excel_elt_security import open_elt_input_file
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_from_dict
from app.db.models.elt import EltRun, EltRunRow, EltUpload
from app.db.models.shipment import ShipmentRecord
from app.db.session import get_db
from app.domain.task_lifecycle.results import execution_result_outcome_unknown
from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.time import utc_now_naive


class BatchContinuationBlocked(ValueError):
    """A public reason why the original import cannot safely be continued."""


def unchanged_source_upload(db: Any, run: EltRun) -> bool:
    upload = db.get(EltUpload, run.upload_id)
    if (
        upload is None
        or upload.owner_user_id != run.owner_user_id
        or upload.tenant_id != run.tenant_id
        or not run.file_sha256
        or upload.sha256 != run.file_sha256
    ):
        return False
    expires_at = upload.expires_at
    if expires_at and expires_at.replace(tzinfo=expires_at.tzinfo or UTC) <= datetime.now(UTC):
        return False
    try:
        with open_elt_input_file(upload.storage_path, owner_user_id=run.owner_user_id) as stream:
            return (
                hashlib.file_digest(type_cast(io.BufferedIOBase, stream), "sha256").hexdigest()
                == run.file_sha256
            )
    except (OSError, ValueError):
        return False


def shipment_parent_writes_present(db: Any, parent: EltRun) -> bool:
    """An ELT receipt must still have its original business rows after a cleanup."""
    from app.application.elt.targets.orders import ShipmentAdapter

    if not parent.executed_rows:
        return False
    records = (
        db.query(ShipmentRecord)
        .join(EltRunRow, cast(ShipmentRecord.id, String) == EltRunRow.match_ref)
        .filter(
            EltRunRow.run_id == parent.id,
            EltRunRow.owner_user_id == parent.owner_user_id,
            EltRunRow.tenant_id == parent.tenant_id,
            EltRunRow.final_action == "new",
            EltRunRow.execution_status == "success",
            ShipmentRecord.tenant_id == parent.tenant_id,
        )
        .all()
    )
    return len(records) == parent.executed_rows and all(
        ShipmentAdapter._belongs_to_current_run(record, parent.id) for record in records
    )


def _owned_run(db: Session, run_id: str, scope: ArtifactScope) -> EltRun | None:
    run = db.get(EltRun, run_id)
    if (
        run is not None
        and str(run.owner_user_id) == scope.owner_user_id
        and str(run.tenant_id) == scope.tenant_id
    ):
        return run
    return None


def _unfinished_companion(db: Any, data: dict[str, Any], scope: ArtifactScope) -> str | None:
    if (data.get("target_type"), data.get("status")) != ("shipment_records", "completed"):
        return None
    parent_id = data.get("run_id")
    if not isinstance(parent_id, str) or not parent_id:
        return None
    parent = _owned_run(db, parent_id, scope)
    if (
        parent is None
        or (parent.target_type, parent.status) != ("shipment_records", "completed")
        or not (parent.confirmed_at and parent.executed_at)
        or parent.rolled_back_at
        or parent.rollback_status in {"completed", "partial", "running", "outcome_unknown"}
        or not load_json(parent.receipt_json, {})
    ):
        return None
    parent_details = load_json(parent.summary_json, {})
    link = (
        parent_details.get("linked_customer_products_preview")
        if isinstance(parent_details, dict)
        else None
    )
    child_id = link.get("run_id") if isinstance(link, dict) else None
    if not isinstance(child_id, str) or not child_id:
        return None
    child = _owned_run(db, child_id, scope)
    if (
        child is None
        or child.target_type != "customer_products"
        or child.upload_id != parent.upload_id
        or child.file_sha256 != parent.file_sha256
    ):
        return None
    details = load_json(child.summary_json, {})
    if not isinstance(details, dict) or details.get("linked_from_shipment_preview") != parent_id:
        return None
    if child.status == "completed":
        return None
    if (
        child.status in {"executing", "persisting", "outcome_unknown", "partial"}
        or child.operation_kind not in {None, "preview_queue", "preview"}
        or child.confirmed_at is not None
        or child.executed_at is not None
        or child.executed_rows
        or load_json(child.receipt_json, {})
    ):
        raise BatchContinuationBlocked("原任务的客户及产品有已提交的写入，请先核对原回执。")
    pending = child.status in {"queued", "previewing", "preview_ready"}
    lease_failed = child.status in {"failed", "interrupted"} and child.error_code in {
        "ELT_EXECUTION_INTERRUPTED",
        "ELT_OPERATION_LEASE_LOST",
    }
    if (
        (pending or lease_failed)
        and shipment_parent_writes_present(db, parent)
        and unchanged_source_upload(db, child)
    ):
        return child_id
    return None


def _original_uploads(paths: list[str], previous: AgentRun, scope: ArtifactScope) -> list[str]:
    created_at = datetime.fromisoformat(previous.created_at).astimezone(UTC).replace(tzinfo=None)
    return _resolve_uploads(paths, previous.metadata["runtime_context"], scope, created_at)


def _resolve_uploads(
    paths: list[str], context: dict, scope: ArtifactScope, created_at: datetime
) -> list[str]:
    manifest = (context.get("file_context") or {}).get("attachment_manifest") or []
    artifact_ids = {item.get("name"): item.get("id") for item in manifest if isinstance(item, dict)}
    store = ArtifactStore(scope=scope) if artifact_ids else None
    owner, tenant = int(scope.owner_user_id), int(scope.tenant_id)
    with tenant_scope(tenant), get_db() as db:
        uploads = (
            db.query(EltUpload)
            .filter(
                EltUpload.owner_user_id == owner,
                EltUpload.tenant_id == tenant,
                EltUpload.expires_at > utc_now_naive(),
                EltUpload.created_at <= created_at,
                or_(EltUpload.id.in_(paths), EltUpload.file_name.in_(paths)),
            )
            .order_by(EltUpload.created_at.desc(), EltUpload.id.desc())
            .all()
        )
        ids = {upload.id: upload for upload in uploads}
        selected = []
        for path in paths:
            if path in ids:
                selected.append(path)
                continue
            artifact_id = artifact_ids.get(path)
            record = (
                store.get(artifact_id)
                if store and isinstance(artifact_id, str) and artifact_id
                else None
            )
            if record is None or record.name != path:
                raise BatchContinuationBlocked(
                    "原任务的剩余附件已过期或无法核对，请在原会话补传对应文件。"
                )
            for upload in uploads:
                if upload.file_name != path or upload.size_bytes != record.size:
                    continue
                try:
                    with open_elt_input_file(upload.storage_path, owner_user_id=owner) as stream:
                        digest = hashlib.file_digest(
                            type_cast(io.BufferedIOBase, stream),
                            lambda: hashlib.sha1(usedforsecurity=False),
                        ).hexdigest()
                except (OSError, ValueError):
                    continue
                if digest == record.sha1:
                    selected.append(upload.id)
                    break
            else:
                raise BatchContinuationBlocked(
                    "原任务的剩余附件已过期或无法核对，请在原会话补传对应文件。"
                )
        return selected


def bind_durable_batch(plan: PlanGraph, context: dict) -> None:
    """Freeze verified sources before the risk gate and the approval fingerprint."""
    if len(plan.nodes) != 1 or not context.get("_actor_authorization"):
        return
    node = plan.nodes[0]
    paths = node.params.get("file_paths")
    if (node.tool_id, node.action) != ("elt_import", "execute") or not isinstance(paths, list):
        return
    scope = artifact_scope_from_context(context)
    if scope is None or not scope.tenant_id or not scope.conversation_id or not paths:
        raise BatchContinuationBlocked("导入附件没有可核对的账号和会话归属，任务尚未提交。")
    try:
        if str(_bound_actor(context).id) != scope.owner_user_id:
            raise AgentModAuthorizationError("actor scope mismatch")
        uploads = _resolve_uploads(paths, context, scope, utc_now_naive())
    except (AgentModAuthorizationError, TypeError, ValueError) as exc:
        raise BatchContinuationBlocked("导入附件无法按本轮上传回执核对，任务尚未提交。") from exc
    if len(set(uploads)) != len(paths):
        raise BatchContinuationBlocked("附件清单中存在重复上传记录，任务尚未提交。")
    node.params["file_paths"] = uploads
    plan.metadata["durable_elt_batch"] = True


_OBSERVABLE_STATES = {"queued", "running", "retrying", "waiting_user", "paused", "blocked"}


def batch_turn_view(run: AgentRun, *, include_terminal: bool = False) -> dict[str, str] | None:
    context = run.metadata.get("runtime_context") or {}
    turn_id = str(context.get("turn_id") or "")
    if (
        not turn_id
        or (run.status not in _OBSERVABLE_STATES and not include_terminal)
        or not any(
            (step.tool_id, step.action) == ("elt_import", "execute")
            and step.params.get("file_paths")
            for step in run.steps
        )
    ):
        return None
    status: str = run.status
    message = ""
    if status not in _OBSERVABLE_STATES:
        from app.domain.task_lifecycle.results import execution_result_error

        steps = [step for step in run.steps if (step.tool_id, step.action) == ("elt_import", "execute")]
        if status == "completed" and steps and all(
            step.status == "completed"
            and isinstance(step.output, dict)
            and step.output.get("success") is True
            and not execution_result_error(step.output)
            for step in steps
        ):
            message = "原导入任务已完成，请查看任务回执。"
        elif status in {"failed", "cancelled", "rejected"}:
            status = "failed" if status == "failed" else "interrupted"
            message = "原导入任务未完成，请查看任务回执。"
        else:
            status = "unknown"
            message = "原导入任务结果尚待核对。"
    return {
        "turn_id": turn_id,
        "run_id": run.run_id,
        "status": status,
        "task_id": str(task_context_of(run).get("task_id") or run.run_id),
        **({"message": message} if message else {}),
    }


def active_batch_turn(
    *, owner: str, tenant: str, mod: str, session: str, revision: int, turn_id: str | None = None,
    include_terminal: bool = False,
) -> dict[str, str] | None:
    from app.application.agent_orchestrator import AgentOrchestrator

    if not (owner and tenant and session):
        return None
    def matches(run: AgentRun) -> bool:
        saved = run.metadata.get("runtime_context") or {}
        return (
            run.user_id == owner
            and str(saved.get("tenant_id") or "") == tenant
            and str(saved.get("mod_id") or saved.get("active_mod_id") or "") == mod
            and str(saved.get("session_id") or saved.get("conversation_id") or "") == session
            and saved.get("_conversation_revision") == revision
            and (not turn_id or saved.get("turn_id") == turn_id)
        )

    superseded: set[str] = set()
    for run in AgentOrchestrator().list_runs(user_id=owner, limit=50, matches=matches):
        if parent := task_context_of(run).get("parent_run_id"):
            superseded.add(str(parent))
        if run.run_id not in superseded:
            view = batch_turn_view(run, include_terminal=include_terminal and bool(turn_id))
            if view:
                return view
    return None


def _remaining_files(
    paths: list[str], output: dict, scope: ArtifactScope
) -> tuple[list[str], list[str]]:
    results = output.get("results") or []
    by_path = {
        path: item
        for item in results
        if isinstance(item, dict) and isinstance(path := item.get("file_path"), str)
    }
    deferred = set(paths) - by_path.keys()
    if (
        len(results) != len(by_path)
        or not by_path.keys() <= set(paths)
        or output.get("deferred_count") != len(deferred)
        or any(execution_result_outcome_unknown(item) for item in by_path.values())
    ):
        raise BatchContinuationBlocked("原任务的文件回执不完整，请先核对原任务。")
    unfinished = set(deferred)
    companions = []
    with tenant_scope(int(scope.tenant_id)), get_db() as db:
        for path, item in by_path.items():
            data = item.get("data")
            if not isinstance(data, dict):
                continue
            if companion := _unfinished_companion(db, data, scope):
                companions.append(companion)
            run_id = data.get("run_id")
            if (
                item.get("preview") is True
                and item.get("error_code") == "elt_preview_not_ready"
                and (
                    data.get("stage") in {"queued", "parsing", "source_loaded", "transforming"}
                    or (item.get("deferred") is True and data.get("status") == "preview_ready")
                )
                and isinstance(run_id, str)
                and run_id
                and (source_run := _owned_run(db, run_id, scope)) is not None
                and source_run.confirmed_at is None
                and source_run.executed_at is None
                and source_run.status in {"queued", "previewing", "preview_ready", "interrupted"}
            ):
                unfinished.add(path)
    return [path for path in paths if path in unfinished], list(dict.fromkeys(companions))


def build_batch_continuation(context: dict[str, Any]) -> tuple[PlanGraph, dict[str, Any]] | None:
    from app.application.agent_orchestrator import AgentOrchestrator

    session = str(context.get("session_id") or context.get("conversation_id") or "")
    tenant = str(context.get("tenant_id") or "")
    revision = context.get("_conversation_revision")
    mod = str(context.get("mod_id") or context.get("active_mod_id") or "")
    if (
        not (session and tenant and context.get("_actor_authorization"))
        or type(revision) is not int
    ):
        return None
    try:
        owner = str(_bound_actor(context).id)
    except AgentModAuthorizationError:
        raise BatchContinuationBlocked("原任务的账号授权已失效，请重新登录后续接。") from None
    scope = ArtifactScope(owner, tenant, mod, session)
    previous = None
    for run in AgentOrchestrator().list_runs(user_id=owner, limit=50):
        saved = run.metadata.get("runtime_context") or {}
        if (
            run.steps
            and run.user_id == owner
            and str(saved.get("tenant_id")) == tenant
            and str(saved.get("session_id") or saved.get("conversation_id") or "") == session
            and str(saved.get("mod_id") or saved.get("active_mod_id") or "") == mod
            and saved.get("_conversation_revision") == revision
        ):
            previous = run
            break
    if previous is None:
        return None
    original = plan_from_dict(previous.metadata.get("plan"))
    if original is not None and original.metadata.get("source") == "elt_batch_continuation":
        parent_id = original.metadata.get("continued_from_run_id")
        if (
            not parent_id
            or task_context_of(previous).get("parent_run_id") != parent_id
            or original.plan_id != previous.plan_id
            or original.plan_id != f"continue-{parent_id}"
        ):
            raise BatchContinuationBlocked("原导入续接记录无法核对，请在原任务查看回执。")
        if previous.status in {"queued", "running", "retrying", "waiting_user"}:
            raise BatchContinuationBlocked("原导入续接仍在处理，请在任务面板查看进度或确认。")
        run_ids = [
            str(node.params["run_id"])
            for node in original.nodes
            if (node.tool_id, node.action) == ("elt_import", "preview")
            and node.params.get("run_id")
        ]
        hint = f" 原预演编号为 {'、'.join(run_ids)}。" if run_ids else ""
        raise BatchContinuationBlocked("请在数据对接中心按原任务回执核对已有结果和剩余项。" + hint)
    if len(previous.steps) != 1:
        return None
    step = previous.steps[0]
    paths = step.params.get("file_paths")
    if (step.tool_id, step.action) != ("elt_import", "execute") or not isinstance(paths, list):
        return None
    if previous.status in {"queued", "running", "retrying"}:
        raise BatchContinuationBlocked("原导入任务正在执行，可在任务面板查看进度。")
    if previous.status not in {"failed", "blocked", "completed"}:
        return None
    output = step.output or {}
    if requires_retry_reconciliation(previous) or execution_result_outcome_unknown(output):
        if legacy := build_legacy_batch_continuation(previous, context):
            return legacy
        raise BatchContinuationBlocked("原任务有尚未核实的写入，请先在原任务核对回执。")
    approval = previous.metadata.get("approval_receipt") or {}
    if (
        original is None
        or original.plan_id != previous.plan_id
        or len(original.nodes) != 1
        or (
            original.nodes[0].node_id,
            original.nodes[0].tool_id,
            original.nodes[0].action,
            original.nodes[0].params,
        )
        != (step.node_id, step.tool_id, step.action, step.params)
        or approval.get("step_id") != step.step_id
        or approval.get("action") != step.action
        or not (
            output.get("error_code") == "elt_execute_batch_incomplete"
            or (previous.status == "completed" and output.get("success") is True)
        )
        or not paths
        or any(not isinstance(path, str) or not path for path in paths)
        or len(paths) != len(set(paths))
    ):
        raise BatchContinuationBlocked("原导入缺少可续接的文件回执，请在原任务核对。")
    files, companions = _remaining_files(paths, output, scope)
    if not (files or companions):
        if previous.status == "completed":
            return None
        raise BatchContinuationBlocked("原导入的剩余文件需要在数据对接中心核对。")
    nodes = []
    todo = []
    if companions:
        todo.append(f"核对 {len(companions)} 份客户及产品预演，单独确认后导入")
        for index, run_id in enumerate(companions):
            nodes.append(
                WorkflowNode(
                    f"review_companion_{index + 1}",
                    "elt_import",
                    "preview",
                    {"run_id": run_id},
                    risk="low",
                    description=todo[-1],
                )
            )
    if files:
        uploads = _original_uploads(files, previous, scope)
        todo.append(f"导入原任务剩余的 {len(uploads)} 份文件")
        nodes.append(
            WorkflowNode(
                "import_remaining",
                "elt_import",
                "execute",
                {**step.params, "file_paths": uploads},
                risk="high",
                depends_on=[nodes[-1].node_id] if nodes else [],
                description=todo[-1],
            )
        )
    task = task_context_of(previous)
    plan = PlanGraph(
        plan_id=f"continue-{previous.run_id}",
        intent="；".join(todo),
        todo_steps=todo,
        risk_level="high",
        nodes=nodes,
        metadata={"source": "elt_batch_continuation", "continued_from_run_id": previous.run_id},
    )
    return plan, {
        "task_id": task["task_id"],
        "task_title": task["title"],
        "root_run_id": task["root_run_id"],
        "parent_run_id": previous.run_id,
        "task_attempt": int(task["attempt"]) + 1,
    }


def _legacy_completed_receipt(db: Any, row: EltRun) -> bool:
    receipt = load_json(row.receipt_json, {})
    if (
        row.status != "completed"
        or not (row.confirmed_at and row.executed_at)
        or row.rollback_status
        or row.rolled_back_at
        or row.operation_token
        or not isinstance(receipt, dict)
        or receipt.get("run_id") != row.id
        or receipt.get("target_type") != row.target_type
        or receipt.get("executed_rows") != row.executed_rows
        or not (
            receipt.get("partial") is False
            or (
                row.target_type == "customer_products"
                and receipt.get("partial") is True
                and row.error_rows > 0
                and receipt.get("error_rows") == row.error_rows
            )
        )
    ):
        return False
    ledger = db.query(EltRunRow).filter_by(
        run_id=row.id,
        tenant_id=row.tenant_id,
        owner_user_id=row.owner_user_id,
    )
    if ledger.filter(EltRunRow.execution_status.in_(("failed", "rolled_back"))).first():
        return False
    written = ledger.filter_by(execution_status="success").count()
    return written == row.executed_rows and (
        row.target_type != "shipment_records"
        or not written
        or shipment_parent_writes_present(db, row)
    )


def build_legacy_batch_continuation(
    previous: AgentRun, context: dict[str, Any]
) -> tuple[PlanGraph, dict[str, Any]] | None:
    """Reconcile a clean worker exit using the original approval and native ELT receipts."""
    from app.application.workflow.approval_persistence import _validated_snapshot
    from app.application.workflow.workflow_types import plan_fingerprint
    from app.db import SessionLocal
    from app.db.models.approval import ApprovalRequest
    from app.request_active_mod_ctx import get_request_active_mod_id

    if previous.status != "blocked" or len(previous.steps) != 1:
        return None
    step = previous.steps[0]
    if (step.tool_id, step.action, step.output.get("error_code")) != (
        "elt_import",
        "execute",
        "tool_worker_exited",
    ):
        return None
    blocked = BatchContinuationBlocked("原导入的审批、附件或入库回执无法完整核对，请在原任务核对。")
    original = plan_from_dict(previous.metadata.get("plan"))
    if original is None or original.metadata.get("durable_elt_batch") is True:
        return None
    saved = previous.metadata.get("runtime_context") or {}
    scope = artifact_scope_from_context(context)
    approval = previous.metadata.get("approval_receipt") or {}
    nested = step.output.get("reconciliation_evidence")
    paths = step.params.get("file_paths")
    if (
        scope is None
        or scope != artifact_scope_from_context(saved)
        or scope.owner_user_id != previous.user_id
        or not (scope.conversation_id and scope.tenant_id and scope.mod_id and saved.get("turn_id"))
        or type(context.get("_conversation_revision")) is not int
        or context["_conversation_revision"] != saved.get("_conversation_revision")
        or step.output.get("outcome") != "unknown"
        or step.output.get("reconciliation_required") is not True
        or "cleanup_unresolved" in step.output
        or not isinstance(nested, dict)
        or nested.get("error_code") != "tool_worker_exited"
        or nested.get("outcome") != "unknown"
        or "cleanup_unresolved" in nested
        or step.output.get("io_reconciliation")
        or original.plan_id != previous.plan_id
        or len(original.nodes) != 1
        or not isinstance(paths, list)
        or not 2 <= len(paths) <= 50
        or any(not isinstance(p, str) or not p or "/" in p or "\\" in p for p in paths)
        or len(set(paths)) != len(paths)
        or any(step.params.get(key) for key in ("run_id", "run_ids", "file_path", "upload_id"))
    ):
        raise blocked
    node = original.nodes[0]
    if (
        (node.node_id, node.tool_id, node.action, node.params)
        != (step.node_id, step.tool_id, step.action, step.params)
        or (approval.get("step_id"), approval.get("tool_id"), approval.get("action"))
        != (step.step_id, step.tool_id, step.action)
        or approval.get("approved_by") != scope.owner_user_id
        or not approval.get("approval_request_id")
        or approval.get("plan_sha256") != plan_fingerprint(original)
    ):
        raise blocked
    try:
        actor = str(_bound_actor(context).id)
        started = datetime.fromisoformat(step.started_at).astimezone(UTC).replace(tzinfo=None)
        owner, tenant = int(scope.owner_user_id), int(scope.tenant_id)
    except (AgentModAuthorizationError, ValueError) as exc:
        raise blocked from exc
    if actor != scope.owner_user_id or get_request_active_mod_id() != scope.mod_id:
        raise blocked
    upload_ids = _original_uploads(paths, previous, scope)

    origin = {
        "run_id": previous.run_id,
        "step_id": step.step_id,
        "turn_id": saved["turn_id"],
        "conversation_id": scope.conversation_id,
        "mod_id": scope.mod_id,
    }
    with tenant_scope(tenant), SessionLocal() as db:
        request = (
            db.query(ApprovalRequest)
            .filter_by(
                request_no=approval["approval_request_id"],
                tenant_id=tenant,
                applicant_id=owner,
                status="approved",
            )
            .one_or_none()
        )
        snapshot = _validated_snapshot(request) if request is not None else None
        data = load_json(request.business_data, {}) if snapshot else {}
        claim = data.get("agent_execution_claim")
        if claim is None:
            execution = data.get("workflow_execution")
            if (
                isinstance(execution, dict)
                and (execution.get("status"), execution.get("code"))
                == ("approved", "outcome_unknown")
                and execution.get("success") is False
                and execution.get("workflow_executed") is False
            ):
                claim = data
        if (
            not snapshot
            or snapshot.get("agent_run_id") != previous.run_id
            or snapshot.get("approved_step_id") not in {step.step_id, step.node_id}
            or plan_fingerprint(snapshot["plan"]) != approval["plan_sha256"]
            or not isinstance(claim, dict)
            or claim.get("agent_run_id") != previous.run_id
            or claim.get("approved_step_id") != snapshot["approved_step_id"]
        ):
            raise BatchContinuationBlocked("原导入的已批准计划与保存的审批凭据无法核对。")
        uploads = (
            db.query(EltUpload)
            .filter(
                EltUpload.owner_user_id == owner,
                EltUpload.tenant_id == tenant,
                EltUpload.id.in_(upload_ids),
            )
            .all()
        )
        by_id = {upload.id: upload for upload in uploads}
        hashes = {upload.sha256 for upload in uploads}
        if len(by_id) != len(paths) or len(hashes) != len(paths):
            raise BatchContinuationBlocked("原导入的附件编号缺失或文件内容存在重复，需核对原任务。")
        for name, upload_id in zip(paths, upload_ids, strict=True):
            upload = by_id[upload_id]
            if name != upload.file_name or not _legacy_source_matches(upload, owner):
                raise BatchContinuationBlocked(f"无法核对原附件「{name}」的文件内容。")
        runs = (
            db.query(EltRun)
            .filter(
                EltRun.owner_user_id == owner,
                EltRun.tenant_id == tenant,
                or_(
                    EltRun.upload_id.in_(upload_ids),
                    EltRun.file_sha256.in_(hashes)
                    & or_(
                        EltRun.created_at >= started,
                        EltRun.updated_at >= started,
                    ),
                ),
            )
            .all()
        )
        members: dict[str, dict[str, EltRun]] = {upload_id: {} for upload_id in upload_ids}
        for row in runs:
            if row.upload_id not in members or row.file_sha256 != by_id[row.upload_id].sha256:
                raise BatchContinuationBlocked(
                    "找到来源相同但对应其他上传记录的入库，请核对原任务。"
                )
            members[row.upload_id][row.id] = row
        tail = []
        for name, upload_id in zip(paths, upload_ids, strict=True):
            file_runs = members[upload_id]
            if not file_runs:
                tail.append(upload_id)
                continue
            if tail or not _legacy_completed_file(db, file_runs, origin):
                raise BatchContinuationBlocked(f"附件「{name}」的原入库回执仍需核对，任务未提交。")
        if not tail or len(tail) == len(upload_ids):
            raise blocked
    task = task_context_of(previous)
    description = f"导入原任务中确认尚未提交的 {len(tail)} 份附件"
    plan = PlanGraph(
        plan_id=f"continue-{previous.run_id}",
        intent=description,
        risk_level="high",
        todo_steps=[description],
        nodes=[
            WorkflowNode(
                "import_remaining",
                "elt_import",
                "execute",
                {**step.params, "file_paths": tail},
                risk="high",
                description=description,
            )
        ],
        metadata={
            "source": "elt_batch_continuation",
            "continued_from_run_id": previous.run_id,
            "durable_elt_batch": True,
            "legacy_elt_tail_recheck": True,
        },
    )
    return plan, {
        "task_id": task["task_id"],
        "task_title": task["title"],
        "root_run_id": task["root_run_id"],
        "parent_run_id": previous.run_id,
        "task_attempt": int(task["attempt"]) + 1,
    }


def _legacy_source_matches(upload: EltUpload, owner: int) -> bool:
    try:
        with open_elt_input_file(upload.storage_path, owner_user_id=owner) as source:
            return (
                hashlib.file_digest(type_cast(io.BufferedIOBase, source), "sha256").hexdigest()
                == upload.sha256
            )
    except (OSError, ValueError):
        return False


def _legacy_completed_file(db: Session, rows: dict[str, EltRun], origin: dict[str, str]) -> bool:
    parents = [row for row in rows.values() if row.target_type in {"shipment_records", "abnormal"}]
    if len(parents) != 1:
        return False
    parent = parents[0]
    details = load_json(parent.summary_json, {})
    if not isinstance(details, dict) or details.get("chat_import_origin") != origin:
        return False
    if not _legacy_completed_receipt(db, parent):
        return False
    link = details.get("linked_customer_products_preview")
    if parent.target_type == "abnormal":
        if (
            len(rows) != 1
            or link is not None
            or parent.executed_rows
            or parent.new_rows
            or parent.update_rows
            or parent.error_rows
            or parent.total_rows != parent.skip_rows
        ):
            return False
        ledger = db.query(EltRunRow).filter_by(
            run_id=parent.id,
            tenant_id=parent.tenant_id,
            owner_user_id=parent.owner_user_id,
        )
        return ledger.count() == ledger.filter_by(final_action="skip").count() == parent.skip_rows
    if link is None:
        return len(rows) == 1
    child_id = link.get("run_id") if isinstance(link, dict) else None
    child = rows.get(child_id) if isinstance(child_id, str) else None
    if len(rows) != 2 or child is None or child.target_type != "customer_products":
        return False
    child_details = load_json(child.summary_json, {})
    return (
        isinstance(child_details, dict)
        and child_details.get("linked_from_shipment_preview") == parent.id
        and child_details.get("chat_import_origin") in (None, origin)
        and _legacy_completed_receipt(db, child)
    )
