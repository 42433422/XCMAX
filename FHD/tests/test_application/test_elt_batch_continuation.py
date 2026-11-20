import hashlib
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.application.agent_orchestrator import (
    AgentOrchestrator,
    InMemoryAgentRunRepository,
    SQLAlchemyAgentRunRepository,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.elt import batch_continuation
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from app.db.models.elt import EltRun, EltRunRow, EltTemplate, EltTemplateVersion, EltUpload
from app.db.models.shipment import ShipmentRecord


@pytest.fixture(params=["memory", "sqlite"])
def continuation_repository(request, tmp_path):
    if request.param == "memory":
        yield InMemoryAgentRunRepository()
        return
    engine = create_engine(f"sqlite:///{tmp_path / 'continuation.db'}")
    try:
        yield SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
    finally:
        engine.dispose()


@pytest.mark.parametrize("entrypoint", ["continue", "active"])
@pytest.mark.parametrize("present", [False, True])
def test_batch_lookup_does_not_hydrate_unrelated_account_history(
    monkeypatch, tmp_path, entrypoint, present
):
    engine = create_engine(f"sqlite:///{tmp_path / 'scoped-history.db'}")
    _assert_batch_scope_lookup(monkeypatch, engine, entrypoint, present)


def _assert_batch_scope_lookup(monkeypatch, engine, entrypoint, present):
    """The same native query contract is exercised by the PostgreSQL CI suite."""
    from app.application.agent_orchestrator.run_models import RunContextScope
    from app.db.models.agent import AgentRunRecord

    factory = sessionmaker(bind=engine)
    repository = SQLAlchemyAgentRunRepository(session_factory=factory)
    context = {
        "_actor_authorization": {"test": True},
        "tenant_id": 1,
        "mod_id": "mod",
        "session_id": "chat",
        "_conversation_revision": 3,
        "turn_id": "turn",
    }
    step = AgentStep("import", "elt_import", "execute", params={"file_paths": ["upload"]})
    target = AgentRun("2", "original", status="running", steps=[step])
    target.metadata["runtime_context"] = context
    try:
        if present:
            repository.save(target)
        # Each newer row differs in only one scope dimension. More than two
        # streaming batches must neither be hydrated nor hide the original run.
        mismatches = (
            {"tenant_id": 9},
            {"mod_id": "other"},
            {"session_id": "other"},
            {"_conversation_revision": 4},
        )
        repository._ensure_schema()
        with factory.begin() as db:
            for index in range(208):
                other = AgentRun("2", f"other-{index}", status="running", steps=[step])
                other.metadata["runtime_context"] = {**context, **mismatches[index % 4]}
                repository.save_in_session(db, other)
        decoded = []
        mapper = repository._record_to_run

        def record_decoding(record):
            decoded.append(record.run_id)
            return mapper(record)

        monkeypatch.setattr(repository, "_record_to_run", record_decoding)
        orchestrator = AgentOrchestrator(repository=repository)
        monkeypatch.setattr(
            "app.application.agent_orchestrator.AgentOrchestrator", lambda: orchestrator
        )
        monkeypatch.setattr(batch_continuation, "_bound_actor", lambda _: SimpleNamespace(id=2))
        if entrypoint == "active":
            result = batch_continuation.active_batch_turn(
                owner="2", tenant="1", mod="mod", session="chat", revision=3
            )
            assert (result or {}).get("run_id") == (target.run_id if present else None)
        elif present:
            with pytest.raises(batch_continuation.BatchContinuationBlocked, match="正在执行"):
                batch_continuation.build_batch_continuation(context)
        else:
            assert batch_continuation.build_batch_continuation(context) is None
        assert decoded == ([target.run_id] if present else [])

        monkeypatch.setattr(repository, "_record_to_run", mapper)
        legacy_ids = set()
        for nonstandard in (False, True):
            legacy = AgentRun("2", "legacy scope", status="running", steps=[step])
            legacy.metadata["runtime_context"] = {
                "tenant_id": "1",
                "mod_id": "",
                "active_mod_id": "mod",
                "session_id": None,
                "conversation_id": "chat",
                "_conversation_revision": 3.0,
            }
            if nonstandard:
                legacy.final_output["legacy_value"] = float("nan")
            repository.save(legacy)
            legacy_ids.add(legacy.run_id)
        broken = repository.save(AgentRun("2", "invalid legacy payload"))
        with factory.begin() as db:
            db.get(AgentRunRecord, broken.run_id).payload_json = "{"
        assert {
            run.run_id
            for run in repository.list_recent(
                user_id="2", runtime_scope=RunContextScope("1", "mod", "chat", 3)
            )
        } == legacy_ids | ({target.run_id} if present else set())
        assert (
            repository.list_recent(
                user_id="2", runtime_scope=RunContextScope("1", "mod", "missing", 3)
            )
            == []
        )
        assert (
            repository.list_recent(
                user_id="2",
                runtime_scope=RunContextScope("1", "mod", "chat", 3),
                matches=lambda _: False,
            )
            == []
        )
        for old_tenant in (0, False, None):
            old_context = {**context, "tenant_id": old_tenant, "session_id": "old-tenant"}
            old_run = AgentRun("2", "legacy tenant", status="running", steps=[step])
            old_run.metadata["runtime_context"] = old_context
            repository.save(old_run)
            # Continuation has always used str(value), while the active-view
            # predicate uses str(value or ""). Keep both native entrypoints.
            with pytest.raises(batch_continuation.BatchContinuationBlocked, match="正在执行"):
                batch_continuation.build_batch_continuation(
                    {**old_context, "tenant_id": str(old_tenant)}
                )
            assert (
                batch_continuation.active_batch_turn(
                    owner="2",
                    tenant=str(old_tenant),
                    mod="mod",
                    session="old-tenant",
                    revision=3,
                )
                is None
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "case", ["ready", "waiting_linked_preview", "unknown", "foreign", "already_committed"]
)
def test_continue_batch_preserves_approved_scope_and_excludes_written_files(
    monkeypatch, case, continuation_repository
):
    scope = {
        "_actor_authorization": {"test": True},
        "tenant_id": 1,
        "session_id": "session",
        "mod_id": "test-mod",
        "_conversation_revision": 3,
    }
    params = {"file_paths": ["written.xlsx", "stopped.xlsx", "pending.xlsx"]}
    node = WorkflowNode("import", "elt_import", "execute", params, risk="high")
    plan = PlanGraph("original", "导入", nodes=[node], risk_level="high")
    step = AgentStep(
        node_id=node.node_id,
        tool_id=node.tool_id,
        action=node.action,
        params=params,
        status="failed",
        output={
            "success": False,
            "error_code": "elt_execute_batch_incomplete",
            "deferred_count": 1,
            "results": [
                {"file_path": "written.xlsx", "success": True},
                {
                    "file_path": "stopped.xlsx",
                    "success": False,
                    "preview": True,
                    "error_code": "elt_preview_not_ready",
                    "data": {
                        "run_id": "preview",
                        "stage": "parsing",
                        **(
                            {"stage": "preview_ready", "status": "preview_ready"}
                            if case == "waiting_linked_preview"
                            else {}
                        ),
                    },
                    **({"deferred": True} if case == "waiting_linked_preview" else {}),
                    **({"outcome": "unknown"} if case == "unknown" else {}),
                },
            ],
        },
    )
    run = AgentRun(user_id="2", message="导入", status="failed", plan_id=plan.plan_id, steps=[step])
    run.metadata.update(
        plan=plan_to_dict(plan),
        approval_receipt={"step_id": step.step_id, "action": "execute"},
        runtime_context={**scope, **({"mod_id": "another-mod"} if case == "foreign" else {})},
        task_context={
            "task_id": "original-task",
            "title": "导入",
            "root_run_id": run.run_id,
            "attempt": 1,
        },
    )
    source_run = SimpleNamespace(
        owner_user_id=2,
        tenant_id=1,
        status="interrupted",
        confirmed_at=True if case == "already_committed" else None,
        executed_at=None,
    )
    continuation_repository.save(run)
    foreign_scopes = (
        {"tenant_id": 9},
        {"session_id": "other-session"},
        {"mod_id": "other-mod"},
        {"_conversation_revision": 4},
    )
    # More than one recent-history window must not hide the approved batch.
    for index in range(64):
        other = AgentRun(user_id="2", message=f"unrelated-{index}", steps=[step])
        other.metadata["runtime_context"] = {**scope, **foreign_scopes[index % 4]}
        continuation_repository.save(other)
    outsider = AgentRun(user_id="9", message="same scope, other owner", steps=[step])
    outsider.metadata["runtime_context"] = scope
    continuation_repository.save(outsider)
    assert run.run_id not in {
        item.run_id for item in continuation_repository.list_recent(user_id="2", limit=50)
    }
    orchestrator = AgentOrchestrator(repository=continuation_repository)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.AgentOrchestrator",
        lambda: orchestrator,
    )
    monkeypatch.setattr(batch_continuation, "_bound_actor", lambda _: SimpleNamespace(id=2))
    monkeypatch.setattr(
        batch_continuation,
        "get_db",
        lambda: nullcontext(SimpleNamespace(get=lambda *_: source_run)),
    )
    monkeypatch.setattr(
        batch_continuation,
        "_original_uploads",
        lambda paths, *_: [f"upload:{path}" for path in paths],
    )
    if case == "unknown":
        with pytest.raises(batch_continuation.BatchContinuationBlocked):
            batch_continuation.build_batch_continuation(scope)
    elif case == "foreign":
        assert batch_continuation.build_batch_continuation(scope) is None
    else:
        result = batch_continuation.build_batch_continuation(scope)
        assert result is not None
        resumed, task = result
        files = ["upload:pending.xlsx"]
        if case in {"ready", "waiting_linked_preview"}:
            files.insert(0, "upload:stopped.xlsx")
        assert resumed.nodes[0].params == {"file_paths": files}
        assert resumed.nodes[0].risk == "high"
        assert task == {
            "task_id": "original-task",
            "task_title": "导入",
            "root_run_id": run.run_id,
            "parent_run_id": run.run_id,
            "task_attempt": 2,
        }
        assert step.params == params and run.status == "failed"


@pytest.mark.parametrize(
    "case",
    [
        "previewing",
        "preview_ready",
        "interrupted",
        "lease_failed",
        "mixed",
        "unknown",
        "submitted",
        "execute_lease",
        "complete",
        "parent_cleaned",
        "foreign",
        "changed_source",
        "missing_source",
        "parse_failed",
    ],
)
def test_continue_completed_shipments_only_reviews_proven_original_companions(monkeypatch, case):
    scope = {
        "_actor_authorization": {"test": True},
        "tenant_id": 1,
        "session_id": "session",
        "mod_id": "test-mod",
        "_conversation_revision": 3,
    }
    mixed = case == "mixed"
    paths = ["shipment.xlsx", "remaining.xlsx"] if mixed else ["shipment.xlsx"]
    params = {"file_paths": paths}
    node = WorkflowNode("import", "elt_import", "execute", params, risk="high")
    original = PlanGraph("original", "导入", nodes=[node], risk_level="high")
    status = "failed" if mixed else "completed"
    step = AgentStep(
        node_id=node.node_id,
        tool_id=node.tool_id,
        action=node.action,
        params=params,
        status=status,
        output={
            "success": not mixed,
            "error_code": "elt_execute_batch_incomplete" if mixed else None,
            "deferred_count": int(mixed),
            "results": [
                {
                    "file_path": "shipment.xlsx",
                    "success": True,
                    # Old receipts could report success and omit the companion entirely.
                    "data": {
                        "run_id": "shipment",
                        "target_type": "shipment_records",
                        "status": "completed",
                    },
                }
            ],
        },
    )
    previous = AgentRun(
        user_id="2", message="导入", status=status, plan_id=original.plan_id, steps=[step]
    )
    previous.metadata.update(
        plan=plan_to_dict(original),
        approval_receipt={"step_id": step.step_id, "action": "execute"},
        runtime_context=scope,
    )
    contents = b"workbook bytes"
    sha256 = hashlib.sha256(contents).hexdigest()
    shared = {"owner_user_id": 2, "tenant_id": 1, "upload_id": "upload", "file_sha256": sha256}
    shipment = SimpleNamespace(
        **shared,
        target_type="shipment_records",
        status="completed",
        confirmed_at=True,
        executed_at=True,
        rolled_back_at=None,
        rollback_status=None,
        receipt_json='{"rows": 3}',
        summary_json='{"linked_customer_products_preview": {"run_id": "companion"}}',
    )
    companion = SimpleNamespace(
        **shared,
        target_type="customer_products",
        status={
            "lease_failed": "failed",
            "parse_failed": "failed",
            "unknown": "outcome_unknown",
            "complete": "completed",
        }.get(case, case if case in {"preview_ready", "interrupted"} else "previewing"),
        confirmed_at=True if case == "submitted" else None,
        executed_at=None,
        executed_rows=0,
        operation_kind="execute_queue" if case == "execute_lease" else None,
        receipt_json="{}",
        error_code=(
            "ELT_OPERATION_LEASE_LOST"
            if case == "lease_failed"
            else "ELT_EXECUTION_INTERRUPTED"
            if case == "interrupted"
            else None
        ),
        summary_json='{"linked_from_shipment_preview": "shipment"}',
    )
    if case == "foreign":
        companion.tenant_id = 9
    upload = SimpleNamespace(
        owner_user_id=2,
        tenant_id=1,
        sha256=sha256,
        expires_at=None,
        storage_path="fixture.xlsx",
    )
    records = {
        (EltRun, "shipment"): shipment,
        (EltRun, "companion"): companion,
        (EltUpload, "upload"): upload,
    }

    def open_source(path, *, owner_user_id):
        assert (path, owner_user_id) == ("fixture.xlsx", 2)
        if case == "missing_source":
            raise FileNotFoundError(path)
        return nullcontext(BytesIO(b"changed" if case == "changed_source" else contents))

    monkeypatch.setattr(
        "app.application.agent_orchestrator.AgentOrchestrator",
        lambda: SimpleNamespace(list_runs=lambda **_: [previous]),
    )
    monkeypatch.setattr(batch_continuation, "_bound_actor", lambda _: SimpleNamespace(id=2))
    monkeypatch.setattr(
        batch_continuation,
        "get_db",
        lambda: nullcontext(SimpleNamespace(get=lambda *key: records.get(key))),
    )
    monkeypatch.setattr(batch_continuation, "open_elt_input_file", open_source)
    monkeypatch.setattr(
        batch_continuation, "shipment_parent_writes_present", lambda *_: case != "parent_cleaned"
    )
    monkeypatch.setattr(
        batch_continuation,
        "_original_uploads",
        lambda paths, *_: [f"upload:{path}" for path in paths],
    )

    if case in {"unknown", "submitted", "execute_lease"}:
        with pytest.raises(batch_continuation.BatchContinuationBlocked, match="核对原回执"):
            batch_continuation.build_batch_continuation(scope)
    elif case in {
        "complete",
        "parent_cleaned",
        "foreign",
        "changed_source",
        "missing_source",
        "parse_failed",
    }:
        assert batch_continuation.build_batch_continuation(scope) is None
    else:
        plan, task = batch_continuation.build_batch_continuation(scope)
        assert plan.nodes[0].params == {"run_id": "companion"}
        assert plan.nodes[0].action == "preview"
        assert plan.nodes[0].risk == "low"
        assert len(plan.nodes) == (2 if mixed else 1)
        if mixed:
            assert plan.nodes[1].depends_on == [plan.nodes[0].node_id]
            assert plan.nodes[1].params == {"file_paths": ["upload:remaining.xlsx"]}

        continued = AgentRun(
            user_id=previous.user_id,
            message="继续",
            status="failed",
            plan_id=plan.plan_id,
            steps=[
                AgentStep(
                    node_id=node.node_id,
                    tool_id=node.tool_id,
                    action=node.action,
                    params=node.params,
                )
                for node in plan.nodes
            ],
        )
        continued.metadata.update(
            plan=plan_to_dict(plan),
            runtime_context=scope,
            task_context={"parent_run_id": task["parent_run_id"]},
        )
        monkeypatch.setattr(
            "app.application.agent_orchestrator.AgentOrchestrator",
            lambda: SimpleNamespace(list_runs=lambda **_: [continued, previous]),
        )
        with pytest.raises(
            batch_continuation.BatchContinuationBlocked, match="原预演编号为 companion"
        ):
            batch_continuation.build_batch_continuation(scope)


def test_continue_dispatch_uses_the_regular_approval_gate_without_replanning(monkeypatch):
    from unittest.mock import Mock

    from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch

    plan = PlanGraph(
        "continued",
        "续接原导入",
        nodes=[
            WorkflowNode(
                "import",
                "elt_import",
                "execute",
                {"file_paths": ["remaining"]},
                risk="high",
            )
        ],
    )
    callbacks, planner, risk_gate, approval = Mock(), Mock(), Mock(), Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (
        True,
        {"data": {"data": {"reason": "no_pending_workflow"}}},
    )
    callbacks._merge_tool_runtime_context.return_value = {"chat_approval_mode": "manual"}
    callbacks._persist_plan_state.return_value = True
    risk_gate.evaluate.return_value = SimpleNamespace(
        allowed=True,
        requires_confirmation=False,
        blocked_nodes=[],
        blocking_nodes=[],
        denied_nodes=[],
        reason="原任务续接",
    )
    approval.get_approval_required_nodes.return_value = plan.nodes
    monkeypatch.setattr(
        batch_continuation,
        "build_batch_continuation",
        lambda _: (plan, {"task_id": "original-task"}),
    )
    pending = {}
    result = PlannedWorkflowDispatch(pending, callbacks, planner, risk_gate, approval).handle(
        "user", "继续", "normal", {}, "继续"
    )
    planner.plan.assert_not_called()
    risk_gate.evaluate.assert_called_once_with(plan=plan, context={})
    assert pending["user"]["runtime_context"]["task_id"] == "original-task"
    assert pending["user"]["approval_required"] is True
    assert result["data"]["data"]["approval_required"] is True


def test_shipment_readback_rejects_cleaned_or_replaced_business_rows():
    engine = create_engine("sqlite://")
    for model in (EltUpload, EltTemplate, EltTemplateVersion, EltRun, EltRunRow, ShipmentRecord):
        model.__table__.create(engine)
    parent = EltRun(
        id="original",
        tenant_id=1,
        owner_user_id=2,
        upload_id="upload",
        file_sha256="fixture",
        target_type="shipment_records",
        executed_rows=1,
    )
    shipment = {
        "id": 19,
        "tenant_id": 1,
        "purchase_unit": "test",
        "product_name": "test",
        "quantity_kg": 1.0,
        "quantity_tins": 1,
    }
    try:
        with Session(engine) as db:
            db.add(
                EltUpload(
                    id="upload",
                    tenant_id=1,
                    owner_user_id=2,
                    file_name="fixture.xlsx",
                    suffix=".xlsx",
                    size_bytes=1,
                    sha256="fixture",
                    storage_path="fixture.xlsx",
                )
            )
            db.flush()
            db.add(parent)
            db.flush()
            original = ShipmentRecord(**shipment, parsed_data='{"elt_run_id":"original"}')
            db.add_all(
                [
                    original,
                    EltRunRow(
                        run_id="original",
                        tenant_id=1,
                        owner_user_id=2,
                        source_sheet="test",
                        source_row=2,
                        match_ref="19",
                        final_action="new",
                        execution_status="success",
                    ),
                ]
            )
            db.flush()
            assert batch_continuation.shipment_parent_writes_present(db, parent)

            db.delete(original)
            db.flush()
            assert not batch_continuation.shipment_parent_writes_present(db, parent)

            db.add(ShipmentRecord(**shipment, parsed_data='{"elt_run_id":"replacement"}'))
            db.flush()
            assert not batch_continuation.shipment_parent_writes_present(db, parent)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "case",
    [
        "verified",
        "companion_partial",
        "abnormal_skip",
        "abnormal_write",
        "tail_preview",
        "missing_rows",
        "bad_approval",
        "unclean",
    ],
)
def test_legacy_exit_requires_approved_contiguous_native_prefix(monkeypatch, case):
    from uuid import uuid4

    from app.application.elt.service_support import dump_json
    from app.application.workflow.approval_persistence import (
        SNAPSHOT_KEY,
        SNAPSHOT_VERSION,
        _contract_digest,
    )
    from app.application.workflow.workflow_types import plan_fingerprint
    from app.db.models.approval import ApprovalRequest

    start = datetime.now(UTC)
    paths = ["original.xlsx", "tail.xlsx"]
    uploads = [str(uuid4()), str(uuid4())]
    node = WorkflowNode("approve", "elt_import", "execute", {"file_paths": paths}, risk="high")
    plan = PlanGraph("legacy", "导入", nodes=[node], risk_level="high")
    output = {"error_code": "tool_worker_exited", "outcome": "unknown"}
    step = AgentStep(
        node_id=node.node_id,
        tool_id=node.tool_id,
        action=node.action,
        params=node.params,
        status="failed",
        started_at=start.isoformat(),
        output={
            **output,
            "reconciliation_required": True,
            "reconciliation_evidence": {
                **output,
                **({"cleanup_unresolved": True} if case == "unclean" else {}),
            },
        },
    )
    context = {
        "user_id": "2",
        "tenant_id": "1",
        "mod_id": "mod",
        "conversation_id": "chat",
        "turn_id": "turn",
        "_conversation_revision": 1,
    }
    run = AgentRun("2", "导入", status="blocked", plan_id=plan.plan_id, steps=[step])
    run.metadata.update(
        plan=plan_to_dict(plan),
        runtime_context=context,
        approval_receipt={
            "step_id": step.step_id,
            "tool_id": node.tool_id,
            "action": node.action,
            "approved_by": "2",
            "approval_request_id": "request",
            "plan_sha256": plan_fingerprint(plan),
        },
    )
    origin = {
        "run_id": run.run_id,
        "step_id": step.step_id,
        "mod_id": "mod",
        "turn_id": "turn",
        "conversation_id": "chat",
    }
    approval_node = {
        "node_id": node.node_id,
        "tool_id": node.tool_id,
        "action": node.action,
        "params": node.params,
    }
    approval_snapshot = {
        "version": SNAPSHOT_VERSION,
        "plan_id": plan.plan_id,
        "node": approval_node,
        "plan": plan_to_dict(plan),
        "plan_sha256": plan_fingerprint(plan),
        "contract_sha256": _contract_digest(plan),
        "tenant_id": 1,
        "agent_run_id": run.run_id,
        "approved_step_id": node.node_id,
    }
    engine = create_engine("sqlite://")
    with engine.connect() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=OFF")
    for model in (
        ApprovalRequest,
        EltUpload,
        EltTemplate,
        EltTemplateVersion,
        EltRun,
        EltRunRow,
        ShipmentRecord,
    ):
        model.__table__.create(engine)
    monkeypatch.setattr("app.db.SessionLocal", lambda: Session(engine))
    monkeypatch.setattr("app.request_active_mod_ctx.get_request_active_mod_id", lambda: "mod")
    monkeypatch.setattr(batch_continuation, "_bound_actor", lambda _: SimpleNamespace(id=2))
    monkeypatch.setattr(batch_continuation, "_original_uploads", lambda *_: uploads)
    monkeypatch.setattr(
        batch_continuation, "open_elt_input_file", lambda path, **_: BytesIO(path.encode())
    )
    try:
        with Session(engine) as db:
            db.add(
                ApprovalRequest(
                    request_no="request",
                    tenant_id=1,
                    flow_id=1,
                    business_type="workflow_tool",
                    applicant_id=2,
                    title="approval",
                    status="approved",
                    business_data=dump_json(
                        {
                            **approval_node,
                            "plan_id": plan.plan_id,
                            SNAPSHOT_KEY: approval_snapshot,
                            "agent_run_id": "another-run" if case == "bad_approval" else run.run_id,
                            "approved_step_id": node.node_id,
                            "workflow_execution": {
                                "status": "approved",
                                "code": "outcome_unknown",
                                "success": False,
                                "workflow_executed": False,
                            },
                        }
                    ),
                )
            )
            for path, upload_id in zip(paths, uploads, strict=True):
                db.add(
                    EltUpload(
                        id=upload_id,
                        tenant_id=1,
                        owner_user_id=2,
                        file_name=path,
                        suffix=".xlsx",
                        size_bytes=len(path),
                        storage_path=path,
                        sha256=hashlib.sha256(path.encode()).hexdigest(),
                        expires_at=start + timedelta(days=1),
                    )
                )
            parent, child = str(uuid4()), str(uuid4())
            partial = case == "companion_partial"
            abnormal = case in {"abnormal_skip", "abnormal_write"}
            parent_summary = {
                "chat_import_origin": origin,
                "linked_customer_products_preview": {"run_id": child},
            }
            native_runs = (
                [(parent, "abnormal", {"chat_import_origin": origin}, 0)]
                if abnormal
                else [
                    (parent, "shipment_records", parent_summary, 0),
                    (
                        child,
                        "customer_products",
                        {"linked_from_shipment_preview": parent},
                        int(partial),
                    ),
                ]
            )
            written = int(case != "abnormal_skip")
            for run_id, target, details, errors in native_runs:
                db.add(
                    EltRun(
                        id=run_id,
                        tenant_id=1,
                        owner_user_id=2,
                        upload_id=uploads[0],
                        file_sha256=hashlib.sha256(paths[0].encode()).hexdigest(),
                        target_type=target,
                        status="completed",
                        total_rows=1,
                        executed_rows=written,
                        skip_rows=1 - written,
                        error_rows=errors,
                        confirmed_at=start,
                        executed_at=start,
                        summary_json=dump_json(details),
                        receipt_json=dump_json(
                            {
                                "run_id": run_id,
                                "target_type": target,
                                "executed_rows": written,
                                "partial": bool(errors),
                                "error_rows": errors,
                            }
                        ),
                    )
                )
                if case != "missing_rows" or run_id != child:
                    db.add(
                        EltRunRow(
                            run_id=run_id,
                            tenant_id=1,
                            owner_user_id=2,
                            source_row=1,
                            final_action="new" if written else "skip",
                            execution_status="success" if written else None,
                            match_ref="19",
                        )
                    )
            db.add(
                ShipmentRecord(
                    id=19,
                    tenant_id=1,
                    purchase_unit="test",
                    product_name="test",
                    quantity_kg=1.0,
                    quantity_tins=1,
                    parsed_data=dump_json({"elt_run_id": parent}),
                )
            )
            if case == "tail_preview":
                db.add(
                    EltRun(
                        id=str(uuid4()),
                        tenant_id=1,
                        owner_user_id=2,
                        upload_id=uploads[1],
                        file_sha256=hashlib.sha256(paths[1].encode()).hexdigest(),
                        target_type="shipment_records",
                        status="preview_ready",
                    )
                )
            db.commit()
        if case in {"verified", "companion_partial", "abnormal_skip"}:
            renewed, lineage = batch_continuation.build_legacy_batch_continuation(run, context)
            assert renewed.nodes[0].params["file_paths"] == uploads[1:]
            assert renewed.metadata["durable_elt_batch"] is True
            assert lineage["parent_run_id"] == run.run_id
        else:
            with pytest.raises(batch_continuation.BatchContinuationBlocked):
                batch_continuation.build_legacy_batch_continuation(run, context)
    finally:
        engine.dispose()


def test_terminal_batch_receipt_requires_actual_step_success():
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.elt.batch_continuation import batch_turn_view

    step = AgentStep(
        node_id="import",
        tool_id="elt_import",
        action="execute",
        status="completed",
        params={"file_paths": ["upload-1"]},
        output={"success": True},
    )
    run = AgentRun(
        user_id="1",
        message="import",
        status="completed",
        steps=[step],
        metadata={"runtime_context": {"turn_id": "turn-1"}},
    )
    assert batch_turn_view(run) is None
    assert batch_turn_view(run, include_terminal=True)["status"] == "completed"
    step.output = {"success": True, "requires_reconciliation": True}
    assert batch_turn_view(run, include_terminal=True)["status"] == "unknown"
    run.status = "failed"
    assert batch_turn_view(run, include_terminal=True)["status"] == "failed"
    run.status = "cancelled"
    assert batch_turn_view(run, include_terminal=True)["status"] == "interrupted"


def test_durable_plan_canonicalizes_content_before_freezing_approval(monkeypatch):
    now = datetime.now(UTC).replace(tzinfo=None)
    engine = create_engine("sqlite://")
    EltUpload.__table__.create(engine)
    with Session(engine) as db:
        for upload_id, name, suffix, sha in (
            ("a", "same.xlsx", ".xlsx", "1"),
            ("b", "same.xlsx", ".xlsx", "1"),
            ("c", "other.xlsx", ".xlsx", "1"),
            ("d", "same.xlsx", ".xlsx", "2"),
        ):
            db.add(
                EltUpload(
                    id=upload_id,
                    owner_user_id=2,
                    tenant_id=1,
                    file_name=name,
                    suffix=suffix,
                    storage_path=f"uploads/{upload_id}",
                    sha256=sha,
                    size_bytes=1,
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                )
            )
        db.commit()
        monkeypatch.setattr(batch_continuation, "get_db", lambda: nullcontext(db))
        monkeypatch.setattr(batch_continuation, "tenant_scope", lambda _: nullcontext())
        monkeypatch.setattr(batch_continuation, "_bound_actor", lambda _: SimpleNamespace(id=2))
        monkeypatch.setattr(
            batch_continuation,
            "artifact_scope_from_context",
            lambda _: SimpleNamespace(owner_user_id="2", tenant_id="1", conversation_id="chat"),
        )

        plan = PlanGraph(
            "test",
            "import",
            nodes=[
                WorkflowNode(
                    "import", "elt_import", "execute", {"file_paths": ["b", "a", "c", "d"]}
                )
            ],
        )
        batch_continuation.bind_durable_batch(plan, {"_actor_authorization": {"bound": True}})

        assert plan.metadata["durable_elt_batch"] is True
        # Retain the first selected source and same bytes under a different name.
        assert plan.nodes[0].params["file_paths"] == ["b", "c", "d"]
        plan.nodes[0].params["file_paths"] = ["a", "a"]
        with pytest.raises(batch_continuation.BatchContinuationBlocked, match="重复上传记录"):
            batch_continuation.bind_durable_batch(plan, {"_actor_authorization": {"bound": True}})
