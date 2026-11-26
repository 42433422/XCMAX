"""Xiaox recovery and ownership of business targets."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from openpyxl import Workbook

from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_permission import clear_idempotent_replay_for_tests
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.infrastructure.tenant_scope import tenant_scope
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_etl_preview_task_boundaries import preview_store as preview_store
from tests.test_application.test_xiaox_business_targets import (
    _assert_execution_scope,
    _elt_auxiliary,
    _elt_preview,
    _execute_elt,
    _execute_elt_business,
    _runtime,
)
from tests.test_application.test_xiaox_business_targets import (
    elt_runtime as elt_runtime,
)


@pytest.mark.parametrize("missing_anchor", [False, True])
def test_elt_stopped_original_receipt_reopens_sql_and_reverifies_without_dispatch(
    elt_runtime, monkeypatch, missing_anchor
):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.agent_orchestrator.verification_recovery import (
        reverify_run,
        verification_can_finalize,
    )
    from app.application.elt import preview_confirmation
    from app.application.elt.service_support import dump_json, load_json
    from app.db.models import ShipmentRecord
    from app.db.models.elt import EltRun

    state = elt_runtime
    preview = _elt_preview(state.elt, region_count=1)
    # The actual writers complete. Only the first independent read is unavailable,
    # leaving the original successful receipt and frozen contract for recovery.
    with monkeypatch.context() as unavailable:
        unavailable.setattr(
            preview_confirmation,
            "verify_agent_execution",
            Mock(side_effect=OSError("injected readback outage")),
        )
        done, child = _execute_elt(state, preview)
    assert done["verified"] is False and child.status == "blocked"
    assert child.tool_calls[0].output["success"] is True
    assert child.tool_calls[0].output["committed"] is True
    original = copy.deepcopy(child.tool_calls[0])
    auxiliary = _elt_auxiliary(state, preview)
    assert auxiliary["state"] == "returned"
    if missing_anchor:
        with state.elt.factory.begin() as db:
            run = db.get(EltRun, preview["id"])
            receipt = load_json(run.receipt_json, {})
            receipt.pop("auxiliary")
            run.receipt_json = dump_json(receipt)
    dispatch = Mock(side_effect=AssertionError("recovery must not dispatch business actions"))
    ingest = Mock(wraps=state.knowledge.ingest_document)
    save_template = Mock(wraps=state.templates.save_template)
    monkeypatch.setattr(AgentToolExecutor, "execute", dispatch)
    monkeypatch.setattr(state.knowledge, "ingest_document", ingest)
    monkeypatch.setattr(state.templates, "save_template", save_template)
    with state.actor.factory() as db:
        url = db.get_bind().url
    reopened = create_engine(url)
    repository = SQLAlchemyAgentRunRepository(
        session_factory=sessionmaker(bind=reopened), auto_create=False
    )
    try:
        for _ in range(2):
            recovered = reverify_run(repository, child.run_id)
            assert recovered.status == "blocked"
            assert recovered.metadata["verification"]["accepted"] is (not missing_anchor)
            assert len(recovered.tool_calls) == 1
            assert recovered.tool_calls[0].output == original.output
            assert (
                recovered.tool_calls[0].metadata["verification_contract"]
                == (original.metadata["verification_contract"])
            )
            assert recovered.tool_calls[0].cost_units == original.cost_units
            assert recovered.steps[0].attempt_count == 1
        assert verification_can_finalize(recovered) is (not missing_anchor)
        if not missing_anchor:
            orchestrator = AgentOrchestrator(repository=repository)
            queued = orchestrator.retry_run(
                child.run_id,
                requested_by=str(state.actor.user_id),
                auto_execute=False,
                authenticated_actor_binding=state.actor.context["_actor_authorization"],
            )
            assert queued.status == "queued"
            queue = SQLAlchemyTaskExecutionRepository(session_factory=sessionmaker(bind=reopened))
            execution = queue.claim("recovery-worker", run_id=child.run_id, lease_seconds=120)
            assert execution is not None
            AgentTaskDispatcher(
                execution_repository=queue,
                run_repository=repository,
                orchestrator_factory=lambda runs: AgentOrchestrator(repository=runs),
            )._execute_claim(execution, "recovery-worker")
            completed = repository.get(child.run_id)
            assert completed.status == "completed", completed.error
            assert len(completed.tool_calls) == 1
            assert completed.tool_calls[0].output == original.output
            assert completed.steps[0].attempt_count == 1
            receipt = XiaoxBindingStore(repository).receipt_snapshot(state.parent.run_id)[0][
                "receipt"
            ]
            assert receipt["verified"] is True and receipt["run_id"] == child.run_id
            parent = repository.get(state.parent.run_id)
            assert parent.metadata["non_retryable"] is True
            assert parent.metadata["recovery"]["state"] == "manual_reconciliation_required"
            with pytest.raises(XiaoxBindingError) as error:
                state.bridge.invoke(state.grant.mcp_token, "task_evidence", {"call_id": "import"})
            assert error.value.code == "reconciliation_required"
        dispatch.assert_not_called()
        ingest.assert_not_called()
        save_template.assert_not_called()
    finally:
        reopened.dispose()
    with state.elt.factory() as db:
        assert db.query(ShipmentRecord).count() == 1


def test_elt_finalize_claim_programming_error_propagates_unchanged(elt_runtime, monkeypatch):
    from app.domain.shared_services.tools_workflow_elt import _finalize_import

    state = elt_runtime
    preview = _elt_preview(state.elt)
    current = _execute_elt_business(state, preview)
    error = RuntimeError("injected finalizer claim programming failure")
    claim = Mock(side_effect=error)
    monkeypatch.setattr("app.application.elt.operation_owner.claim_operation", claim)
    with tenant_scope(state.actor.tenant_id), pytest.raises(RuntimeError) as raised:
        _finalize_import(current, state.actor.user_id)
    assert raised.value is error
    claim.assert_called_once()
    assert _elt_auxiliary(state, preview) is None


def test_elt_concurrent_finalizers_claim_once_and_exclude_rollback(elt_runtime, monkeypatch):
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    from threading import Barrier, Event

    from app.application.elt import operation_owner
    from app.application.elt.errors import EltConflict
    from app.db.models import ShipmentRecord
    from app.db.models.elt import EltRun
    from app.domain.shared_services.tools_workflow_elt import _finalize_import

    state = elt_runtime
    preview = _elt_preview(state.elt)
    current = _execute_elt_business(state, preview)
    arrived, writing, release = Barrier(2), Event(), Event()
    original_ingest = state.knowledge.ingest_document

    def pause_writer(*args, **kwargs):
        writing.set()
        assert release.wait(timeout=10), "finalizer test did not release the writer"
        return original_ingest(*args, **kwargs)

    ingest = Mock(side_effect=pause_writer)
    monkeypatch.setattr(state.knowledge, "ingest_document", ingest)
    claim = operation_owner.claim_operation

    def simultaneous_claim(db, run, kind, **kwargs):
        if kind == "batch_execute":
            arrived.wait(timeout=10)
        return claim(db, run, kind, **kwargs)

    monkeypatch.setattr(operation_owner, "claim_operation", simultaneous_claim)

    def finalize():
        with tenant_scope(state.actor.tenant_id):
            return _finalize_import(current, state.actor.user_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(finalize) for _ in range(2)]
        try:
            assert writing.wait(timeout=10)
            assert _elt_auxiliary(state, preview)["state"] == "started"
            completed, _ = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
            assert len(completed) == 1
            rejected = next(iter(completed)).result()
            assert rejected[0]["action"] == rejected[1]["action"] == "unknown"
            with tenant_scope(state.actor.tenant_id), state.elt.factory() as db:
                with pytest.raises(EltConflict) as error:
                    state.elt.service.rollback(
                        db, run_id=preview["id"], owner_user_id=state.actor.user_id
                    )
                assert error.value.code == "ELT_RUN_BUSY"
        finally:
            release.set()
        results = [future.result(timeout=10) for future in futures]
    assert sum(result[0]["action"] == "new" for result in results) == 1
    assert ingest.call_count == 1
    auxiliary = _elt_auxiliary(state, preview)
    assert auxiliary["state"] == "returned"
    assert auxiliary["knowledge"]["action"] == "new"
    with state.elt.factory() as db:
        run = db.get(EltRun, preview["id"])
        assert run.operation_token is None and run.rollback_status is None
        assert db.query(ShipmentRecord).count() == 1


def test_elt_process_exit_after_auxiliary_write_is_not_replayed_after_restart(
    elt_runtime, monkeypatch
):
    from datetime import datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.elt.errors import EltConflict
    from app.application.elt.service import EltService
    from app.db.models import ShipmentRecord
    from app.db.models.elt import EltRun
    from app.domain.shared_services.tools_workflow_elt import _execute, _finalize_import

    class SimulatedProcessExit(BaseException):
        pass

    state = elt_runtime
    preview = _elt_preview(state.elt)
    current = _execute_elt_business(state, preview)
    original_ingest = state.knowledge.ingest_document

    def exit_after_commit(*args, **kwargs):
        assert original_ingest(*args, **kwargs)["success"] is True
        raise SimulatedProcessExit()

    ingest = Mock(side_effect=exit_after_commit)
    monkeypatch.setattr(state.knowledge, "ingest_document", ingest)
    with tenant_scope(state.actor.tenant_id), pytest.raises(SimulatedProcessExit):
        _finalize_import(current, state.actor.user_id)
    assert _elt_auxiliary(state, preview)["state"] == "started"
    with state.elt.factory.begin() as db:
        run = db.get(EltRun, preview["id"])
        assert run.operation_kind == "batch_execute" and run.operation_token
        run.operation_lease_until = datetime(2000, 1, 1)
        url = db.get_bind().url
    reopened = create_engine(url)
    factory = sessionmaker(bind=reopened)
    service = EltService()
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    monkeypatch.setattr("app.db.SessionLocal", factory)
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: service)
    params = {
        "run_id": preview["id"],
        "preview_revision": preview["preview_revision"],
        "accept_suggested": True,
    }
    try:
        with tenant_scope(state.actor.tenant_id):
            for _ in range(2):
                knowledge, template, _ = _finalize_import(current, state.actor.user_id)
                assert knowledge["action"] == template["action"] == "unknown"
                output = _execute(params, state.actor.context)
                # The existing stale-batch watchdog may already have marked the
                # whole run unknown; neither representation permits replay.
                if output.get("success") is True:
                    assert output["data"]["knowledge"]["action"] == "unknown"
                    assert output["data"]["template"]["action"] == "unknown"
                else:
                    assert output["outcome"] == "unknown" and output["reconciliation_required"]
            with factory() as db, pytest.raises(EltConflict) as error:
                service.rollback(db, run_id=preview["id"], owner_user_id=state.actor.user_id)
            assert error.value.code in {"ELT_RUN_BUSY", "ELT_ROLLBACK_NOT_ALLOWED"}
        assert ingest.call_count == 1
        snapshot = state.knowledge._repository.read_committed_dataset("office-docking")
        assert len(snapshot["documents"]) == 1
        assert _elt_auxiliary(state, preview)["state"] == "started"
        with factory() as db:
            assert db.query(ShipmentRecord).count() == 1
    finally:
        reopened.dispose()


@pytest.mark.parametrize("action", ["preview", "execute"])
def test_elt_business_target_does_not_adopt_the_target_tenant(elt_runtime, action):
    from app.db.models import ShipmentRecord
    from app.db.models.elt import EltRun

    state = elt_runtime
    foreign = _elt_preview(state.elt, tenant=2)
    params = {"run_id": foreign["id"]}
    if action == "execute":
        params.update(preview_revision=foreign["preview_revision"], accept_suggested=True)
    pending = state.execute("foreign", "elt_import", action, params)
    result = state.approve("foreign", pending)
    assert result["verified"] is False
    child = _assert_execution_scope(state, result, params)
    assert child.tool_calls[0].output["error_code"] == "ELT_NOT_FOUND"
    assert "已审客户" not in str(child.tool_calls[0].output)
    with tenant_scope(2), state.elt.factory() as db:
        assert db.get(EltRun, foreign["id"]).status == "preview_ready"
        assert db.query(ShipmentRecord).count() == 0


def test_elt_business_target_still_requires_the_exact_reviewed_revision(elt_runtime):
    from app.db.models import ShipmentRecord
    from app.db.models.elt import EltRun

    state = elt_runtime
    preview = _elt_preview(state.elt)
    params = {"run_id": preview["id"], "preview_revision": "0" * 64, "accept_suggested": True}
    pending = state.execute("changed-preview", "elt_import", "execute", params)
    result = state.approve("changed-preview", pending)
    child = _assert_execution_scope(state, result, params)
    assert result["verified"] is False
    assert child.tool_calls[0].output["error_code"] == "ELT_PREVIEW_CHANGED"
    with state.elt.factory() as db:
        assert db.get(EltRun, preview["id"]).status == "preview_ready"
        assert db.query(ShipmentRecord).count() == 0


def _change_elt_preview(state, preview):
    from app.application.elt.service_support import load_json
    from app.db.models.elt import EltRunRow

    mappings = copy.deepcopy(preview["draft"]["field_mappings"])
    product = next(item for item in mappings if item["target"] == "product_name")
    product.setdefault("transforms", []).append(
        {"op": "map", "values": {"已审产品": "未经本次审批的产品"}}
    )
    with state.elt.factory() as db:
        state.elt.service.update_draft(
            db, run_id=preview["id"], owner_user_id=7, patch={"field_mappings": mappings}
        )
    state.elt.executor.futures[-1].result(timeout=10)
    with state.elt.factory() as db:
        changed = state.elt.service.get_run(db, run_id=preview["id"], owner_user_id=7)
        assert changed["status"] == "preview_ready"
        assert changed["preview_revision"] != preview["preview_revision"]
        row = db.query(EltRunRow).filter_by(run_id=preview["id"]).one()
        assert load_json(row.normalized_json, {})["product_name"] == "未经本次审批的产品"


@pytest.mark.parametrize("selector", ["run_id", "run_ids"])
@pytest.mark.parametrize("revision", [None, "", "invalid"])
def test_existing_elt_selector_requires_revision_before_task_admission(
    elt_runtime, selector, revision
):
    from app.db.models import ShipmentRecord

    state = elt_runtime
    preview = _elt_preview(state.elt)
    target = preview["id"] if selector == "run_id" else [preview["id"]]
    params = {selector: target}
    if revision is not None:
        if selector == "run_id":
            params["preview_revision"] = revision
        else:
            params["preview_revisions"] = {preview["id"]: revision}
    rejected = state.execute("unversioned", "elt_import", "execute", params)
    assert rejected["status"] == "not_started", rejected
    assert rejected["error_code"] == "schema_validation_failed"
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}
    with state.elt.factory() as db:
        assert db.query(ShipmentRecord).count() == 0


@pytest.mark.parametrize("target_count", [1, 2])
@pytest.mark.parametrize("scalar_fallback", [False, True])
def test_elt_revision_map_cannot_omit_the_selected_run(elt_runtime, target_count, scalar_fallback):
    from app.db.models import ShipmentRecord
    from app.db.models.elt import EltRun

    state = elt_runtime
    previews = [_elt_preview(state.elt) for _ in range(target_count)]
    params = {
        "run_ids": [preview["id"] for preview in previews],
        "preview_revisions": {"different-run": "a" * 64},
        "accept_suggested": True,
    }
    if scalar_fallback:
        params["preview_revision"] = previews[0]["preview_revision"]
    pending = state.execute("missing-mapped-revision", "elt_import", "execute", params)
    result = state.approve("missing-mapped-revision", pending)
    child = _assert_execution_scope(state, result, params)
    with state.elt.factory() as db:
        assert db.query(ShipmentRecord).count() == 0, child.tool_calls[0].output
        assert {db.get(EltRun, preview["id"]).status for preview in previews} == {"preview_ready"}
    assert result["verified"] is False
    output = child.tool_calls[0].output
    items = output["results"] if target_count > 1 else [output]
    assert {item["error_code"] for item in items} == {"ELT_PREVIEW_CHANGED"}


def test_elt_batch_version_map_executes_original_targets_without_replaying(elt_runtime):
    from app.db.models import ShipmentRecord
    from app.db.models.elt import EltRun

    state = elt_runtime
    previews = [_elt_preview(state.elt, product=f"已审产品-{index}") for index in (1, 2)]
    params = {
        "run_ids": [preview["id"] for preview in previews],
        "preview_revisions": {preview["id"]: preview["preview_revision"] for preview in previews},
        "accept_suggested": True,
    }
    pending = state.execute("batch-import", "elt_import", "execute", params)
    result = state.approve("batch-import", pending)
    child = _assert_execution_scope(state, result, params)
    assert child.tool_calls[0].output["success"] is True, child.tool_calls[0].output
    assert result["verified"] is True and child.status == "completed", result
    assert child.tool_calls[0].metadata["verification"]["accepted"] is True
    reread = state.bridge.invoke(
        state.grant.mcp_token, "task_evidence", {"call_id": "batch-import"}
    )
    assert reread["verified"] is True and reread["run_id"] == result["run_id"]
    repeated = state.execute("batch-repeat", "elt_import", "execute", params)
    assert repeated["verified"] is True and repeated["run_id"] == result["run_id"]
    with state.elt.factory() as db:
        assert {row.product_name for row in db.query(ShipmentRecord).all()} == {
            "已审产品-1",
            "已审产品-2",
        }
        assert db.query(ShipmentRecord).count() == 2
        assert {db.get(EltRun, preview["id"]).status for preview in previews} == {"completed"}


def test_elt_batch_never_executes_the_target_missing_from_an_approved_revision_map(elt_runtime):
    from app.db.models import ShipmentRecord
    from app.db.models.elt import EltRun

    state = elt_runtime
    approved = _elt_preview(state.elt, product="版本已批准")
    omitted = _elt_preview(state.elt, product="版本未批准")
    params = {
        "run_ids": [approved["id"], omitted["id"]],
        "preview_revisions": {approved["id"]: approved["preview_revision"]},
        "accept_suggested": True,
    }
    pending = state.execute("partial-map", "elt_import", "execute", params)
    result = state.approve("partial-map", pending)
    child = _assert_execution_scope(state, result, params)
    output = child.tool_calls[0].output
    assert output["success"] is False and result["verified"] is False
    assert output["results"][0]["success"] is True
    assert output["results"][1]["error_code"] == "ELT_PREVIEW_CHANGED"
    run_count = len(state.repository.list_recent())
    with pytest.raises(XiaoxBindingError) as error:
        state.execute("partial-replay", "elt_import", "execute", params)
    assert error.value.code == "reconciliation_required"
    assert len(state.repository.list_recent()) == run_count
    with state.elt.factory() as db:
        assert [row.product_name for row in db.query(ShipmentRecord).all()] == ["版本已批准"]
        assert db.get(EltRun, approved["id"]).status == "completed"
        assert db.get(EltRun, omitted["id"]).status == "preview_ready"


def test_approved_elt_batch_revisions_cannot_follow_changed_previews(elt_runtime):
    from app.db.models import ShipmentRecord
    from app.db.models.elt import EltRun

    state = elt_runtime
    previews = [_elt_preview(state.elt) for _ in range(2)]
    params = {
        "run_ids": [preview["id"] for preview in previews],
        "preview_revisions": {preview["id"]: preview["preview_revision"] for preview in previews},
        "accept_suggested": True,
    }
    pending = state.execute("changed-batch", "elt_import", "execute", params)

    def change_previews():
        for preview in previews:
            _change_elt_preview(state, preview)

    result = state.approve("changed-batch", pending, before_dispatch=change_previews)
    child = _assert_execution_scope(state, result, params)
    assert result["verified"] is False
    assert {item["error_code"] for item in child.tool_calls[0].output["results"]} == {
        "ELT_PREVIEW_CHANGED"
    }
    with state.elt.factory() as db:
        assert db.query(ShipmentRecord).count() == 0
        assert {db.get(EltRun, preview["id"]).status for preview in previews} == {"preview_ready"}


def test_approved_elt_revision_cannot_follow_a_changed_preview(elt_runtime):
    from app.db.models import ShipmentRecord

    state = elt_runtime
    preview = _elt_preview(state.elt)
    params = {
        "run_id": preview["id"],
        "preview_revision": preview["preview_revision"],
        "accept_suggested": True,
    }
    pending = state.execute("reviewed", "elt_import", "execute", params)
    result = state.approve(
        "reviewed", pending, before_dispatch=lambda: _change_elt_preview(state, preview)
    )
    child = _assert_execution_scope(state, result, params)
    assert child.tool_calls[0].output["error_code"] == "ELT_PREVIEW_CHANGED"
    assert result["verified"] is False
    with state.elt.factory() as db:
        assert db.query(ShipmentRecord).count() == 0


def test_legacy_approved_unversioned_elt_task_is_blocked_without_rewriting_params(
    elt_runtime, monkeypatch
):
    from app.application import capability_catalog
    from app.application.agent_orchestrator import tool_spec
    from app.db.models import ShipmentRecord

    state = elt_runtime
    preview = _elt_preview(state.elt)
    original = tool_spec.get_tool_action_spec
    current = original("elt_import", "execute")
    legacy_schema = copy.deepcopy(current.input_schema)
    legacy_schema.pop("dependentRequired", None)
    legacy = replace(current, input_schema=legacy_schema)

    def old_spec(tool, action):
        return legacy if (tool, action) == ("elt_import", "execute") else original(tool, action)

    original_catalog = capability_catalog.build_tool_specs_v2

    def old_catalog():
        return {**original_catalog(), ("elt_import", "execute"): legacy}

    params = {"run_id": preview["id"], "accept_suggested": True}
    with monkeypatch.context() as old_deployment:
        old_deployment.setattr(tool_spec, "get_tool_action_spec", old_spec)
        old_deployment.setattr("app.infrastructure.xiaox.tools.get_tool_action_spec", old_spec)
        old_deployment.setattr(capability_catalog, "build_tool_specs_v2", old_catalog)
        pending = state.execute("legacy", "elt_import", "execute", params)
        assert pending.get("pending_approval") is True, pending

        def deploy_and_change():
            old_deployment.undo()
            _change_elt_preview(state, preview)

        result = state.approve("legacy", pending, before_dispatch=deploy_and_change)
    child = _assert_execution_scope(state, result, params)
    assert result["verified"] is False, result
    assert child.steps[0].params == params
    with state.elt.factory() as db:
        assert db.query(ShipmentRecord).count() == 0


@pytest.fixture
def memory_runtime(trusted_actor, monkeypatch, tmp_path):
    import app.domain.shared_services.user_memory_service as memory_mod

    actor = trusted_actor(tier="personal", permissions=["memory_v2.write"])
    state = _runtime(actor, monkeypatch, tmp_path)
    memory_dir = tmp_path / "memory"
    monkeypatch.setenv("XCAGI_USER_MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory_mod, "MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory_mod, "JSON_MEMORY_PATH", str(memory_dir / "memory_store.json"))
    memory_mod.reset_user_memory_service()
    try:
        state.memory = memory_mod.get_user_memory_service()
        yield state
    finally:
        memory_mod.reset_user_memory_service()


def test_memory_actions_bind_the_current_owner_without_model_identity(memory_runtime):
    from app.application.agent_task_context import scoped_personal_memory_id

    state = memory_runtime
    params = {
        "memory_type": "preference",
        "key": "report-format",
        "value": "table",
        "source": "user_explicit",
    }
    proposed = state.execute("propose", "memory_v2", "propose_candidate", params)
    proposed = state.approve("propose", proposed)
    assert proposed["verified"] is True, proposed
    child = _assert_execution_scope(state, proposed, params)
    memory_id = child.tool_calls[0].output["candidate"]["memory_id"]
    for action, extra in (
        ("confirm", {}),
        ("correct", {"value": "chart"}),
        ("reject", {"reason": "no longer needed"}),
        ("delete", {}),
    ):
        params = {"memory_id": memory_id, **extra}
        pending = state.execute(action, "memory_v2", action, params)
        completed = state.approve(action, pending)
        assert completed["verified"] is True, (
            action,
            state.repository.get(completed["run_id"]).tool_calls,
        )
        _assert_execution_scope(state, completed, params)
    owner = scoped_personal_memory_id(state.actor.context)
    rows = state.memory.list_memories(owner, status="deleted")
    assert len(rows) == 1 and rows[0]["status"] == "deleted" and rows[0]["revision"] == 5


def test_memory_business_id_cannot_select_another_tenants_memory(memory_runtime, trusted_actor):
    from app.application.agent_task_context import scoped_personal_memory_id

    state = memory_runtime
    other = trusted_actor(tenant_id=state.actor.tenant_id + 1, tier="personal")
    other_owner = scoped_personal_memory_id(other.context)
    created = state.memory.propose_memory_candidate(
        other_owner, "preference", "private-setting", "private-value", source="user_explicit"
    )["candidate"]
    params = {"memory_id": created["memory_id"]}
    pending = state.execute("foreign-memory", "memory_v2", "delete", params)
    result = state.approve("foreign-memory", pending)
    child = _assert_execution_scope(state, result, params)
    assert result["verified"] is False
    assert child.tool_calls[0].output["success"] is False
    assert "private-value" not in str(child.tool_calls[0].output)
    assert state.memory.list_memories(other_owner) == [created]


def test_optional_memory_owner_cannot_override_the_bound_actor(memory_runtime):
    state = memory_runtime
    params = {
        "user_id": str(state.actor.user_id),
        "memory_type": "preference",
        "key": "report-format",
        "value": "table",
    }
    with pytest.raises(XiaoxBindingError) as error:
        state.execute("identity", "memory_v2", "propose_candidate", params)
    assert error.value.code == "identity_override"
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}


@pytest.mark.parametrize("foreign", [False, True])
def test_cognition_business_run_selector_reaches_owned_outcome_service(
    trusted_actor, monkeypatch, tmp_path, foreign
):
    from app.application.enterprise_cognition.outcomes import OutcomeService
    from app.application.enterprise_cognition.service import EnterpriseCognitionService

    actor = trusted_actor(permissions=[])
    state = _runtime(actor, monkeypatch, tmp_path)
    target = AgentRun(user_id=str(actor.user_id), message="尚未绑定经营目标", status="completed")
    target.metadata["runtime_context"] = {
        **actor.context,
        **({"tenant_id": "999"} if foreign else {}),
    }
    state.repository.save(target)
    outcomes = OutcomeService(repository=state.repository)
    evaluate = Mock(wraps=outcomes.evaluate)
    monkeypatch.setattr(outcomes, "evaluate", evaluate)
    service = EnterpriseCognitionService(outcomes=outcomes)
    monkeypatch.setattr(
        "app.application.tools.enterprise_cognition.get_cognition_service", lambda: service
    )
    params = {"run_id": target.run_id}
    pending = state.execute("evaluate", "enterprise_cognition", "evaluate", params)
    result = state.approve("evaluate", pending)
    child = _assert_execution_scope(state, result, params)
    evaluate.assert_called_once_with(
        run_id=target.run_id, tenant_id=str(actor.tenant_id), actor_id=str(actor.user_id), mod_id=""
    )
    expected = "run_not_accessible" if foreign else "approved_plan_binding_mismatch"
    assert child.tool_calls[0].output["data"]["reason_code"] == expected
    assert result["verified"] is False
    assert state.repository.get(target.run_id).events == target.events


@pytest.mark.parametrize(
    "tool,action",
    [
        ("elt_import", "preview"),
        ("elt_import", "execute"),
        ("enterprise_cognition", "evaluate"),
    ],
)
@pytest.mark.parametrize(
    "field", ["tenant_id", "user_id", "runtime_context", "parent_run_id", "approved"]
)
def test_business_run_selectors_never_accept_runtime_authority(
    trusted_actor, monkeypatch, tmp_path, tool, action, field
):
    actor = trusted_actor(permissions=["elt.execute", "memory_v2.write"])
    state = _runtime(actor, monkeypatch, tmp_path)
    with pytest.raises(XiaoxBindingError) as error:
        state.execute("injected", tool, action, {"run_id": "existing-object", field: "forged"})
    assert error.value.code == "identity_override"
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}
    assert len(state.repository.list_recent()) == 1
