"""Business selectors keep host identity through real SQL approvals and services."""

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


def _runtime(actor, monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "claims.sqlite"))
    clear_idempotent_replay_for_tests()
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory)
    parent = AgentRun(user_id=str(actor.user_id), message="处理已选业务对象", status="running")
    parent.metadata.update(runtime_type="xiaox", runtime_context=actor.context)
    contract = build_goal_contract(parent)
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(parent)
    store = XiaoxBindingStore(repository)
    grant = store.create(parent.run_id)

    def orchestrator(runs):
        return AgentOrchestrator(
            repository=runs, tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute)
        )

    bridge = XiaoxToolBridge(store, orchestrator(repository))

    def execute(call_id, tool, action, params):
        capability = bridge.invoke(
            grant.mcp_token, "capability_describe", {"tool_id": tool, "action": action}
        )["capability"]
        return bridge.invoke(
            grant.mcp_token,
            "execute_action",
            {
                "call_id": call_id,
                "tool_id": tool,
                "action": action,
                "params": params,
                "schema_digest": capability["schema_digest"],
            },
        )

    def approve(call_id, pending, *, before_dispatch=None):
        assert pending["pending_approval"] is True, pending
        child = repository.get(pending["run_id"])
        approval = issue_approval_grant(child, principal_id=str(actor.user_id))
        assert approval is not None
        approve_and_enqueue(
            repository,
            queue,
            run_id=child.run_id,
            token=approval["grant"],
            principal_id=str(actor.user_id),
            runtime_context=actor.context,
            authenticated_actor_binding=actor.context["_actor_authorization"],
        )
        if before_dispatch is not None:
            before_dispatch()
        owner = "business-target-worker"
        execution = queue.claim(owner, run_id=child.run_id, lease_seconds=120)
        assert execution is not None
        AgentTaskDispatcher(
            execution_repository=queue,
            run_repository=repository,
            orchestrator_factory=orchestrator,
        )._execute_claim(execution, owner)
        return bridge.invoke(grant.mcp_token, "task_evidence", {"call_id": call_id})

    return SimpleNamespace(
        actor=actor,
        repository=repository,
        parent=parent,
        store=store,
        bridge=bridge,
        grant=grant,
        execute=execute,
        approve=approve,
    )


def _assert_execution_scope(state, receipt, params):
    child = state.repository.get(receipt["run_id"])
    assert child.steps[0].params == params
    context = child.metadata["runtime_context"]
    assert context["parent_run_id"] == state.parent.run_id
    assert context["_actor_authorization"] == state.actor.context["_actor_authorization"]
    assert str(context["tenant_id"]) == str(state.actor.tenant_id)
    assert str(context["actor_id"]) == str(state.actor.user_id)
    if child.tool_calls:
        scope = child.tool_calls[0].metadata["verification_contract"]["scope"]
        assert scope["run_id"] == child.run_id
        assert scope["run_id"] != params.get("run_id")
    return child


def _elt_preview(
    store, *, tenant=1, product="已审产品", region_count=0, csv=False, order_prefix="REVIEW"
):
    if csv:
        assert not region_count
        content = BytesIO(
            f"购买单位,产品名称,型号,桶数,单价\n已审客户,{product},REVIEW-1,2,12.5\n".encode()
        )
    else:
        book = Workbook()
        if region_count:
            for index in range(region_count):
                sheet = book.active if index == 0 else book.create_sheet()
                sheet.title = f"送货-{index + 1}"
                sheet.append(["已审工厂送货单"])
                sheet.append(
                    [
                        "购货单位：已审客户     联系人：张总       2026年11月01日         "
                        f"订单编号：{order_prefix}-{index + 1}"
                    ]
                )
                sheet.append(
                    [
                        "产品型号",
                        None,
                        None,
                        "产品名称",
                        "数量/件",
                        "规格/KG",
                        "数量/KG",
                        "单价/元",
                        "金额/元",
                    ]
                )
                sheet.append(
                    [f"{order_prefix}-{index + 1}", None, None, product, 2, 20, 40, 12.5, 500]
                )
                sheet.append(["合计", None, None, None, 2, None, 40, None, 500])
        else:
            sheet = book.active
            sheet.title = "出货"
            sheet.append(["购买单位", "产品名称", "型号", "桶数", "单价"])
            sheet.append(["已审客户", product, "REVIEW-1", 2, 12.5])
        content = BytesIO()
        book.save(content)
        book.close()
        content.seek(0)
    with tenant_scope(tenant), store.factory() as db:
        upload = store.service.save_upload(
            db,
            owner_user_id=7,
            file_name="shipments.csv" if csv else "shipments.xlsx",
            content_type="text/csv"
            if csv
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            stream=content,
        )
        db.commit()
        preview = store.service.create_preview(
            db, owner_user_id=7, upload_id=upload["upload_id"], target_type="shipment_records"
        )
    store.executor.futures[-1].result(timeout=10)
    with tenant_scope(tenant), store.factory() as db:
        return store.service.get_run(db, run_id=preview["id"], owner_user_id=7)


@pytest.fixture
def elt_runtime(preview_store, request, monkeypatch, tmp_path):
    from app.application import dataset_rag_app_service as rag
    from app.application.template_app_service import TemplateApplicationService
    from app.db.init_db import init_template_tables
    from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore

    actor = request.getfixturevalue("trusted_actor")(
        user_id=7, tenant_id=1, role="importer", permissions=["elt.execute"]
    )
    monkeypatch.setattr("app.db.session.SessionLocal", preview_store.factory)
    monkeypatch.setattr("app.db.SessionLocal", preview_store.factory)
    # Lazy imports must retain the production path provider, not a fixture lambda
    # that would keep later tools on this test's workspace after teardown.
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FHD_ELT_LLM", "off")
    monkeypatch.setenv("FHD_ELT_CENTER_ENABLED", "1")
    monkeypatch.setattr(
        "app.application.elt.service.get_elt_service", lambda: preview_store.service
    )
    knowledge = rag.DatasetRagApplicationService(
        embedder=lambda _text: [1.0, 0.0],
        storage_path=tmp_path / "knowledge.json",
        vector_index_path=tmp_path / "knowledge-vectors.sqlite",
        allowed_roots=[tmp_path],
        rebuild_workers_enabled=False,
    )
    monkeypatch.setattr(rag, "_dataset_rag_app_service", knowledge)
    monkeypatch.setattr(rag, "get_dataset_rag_app_service", lambda: knowledge)
    with preview_store.factory() as db:
        init_template_tables(str(db.get_bind().url.database))
    templates = TemplateApplicationService(FileSystemTemplateStore(str(tmp_path)))
    monkeypatch.setattr(
        "app.application.template_app_service.get_template_app_service", lambda: templates
    )
    state = _runtime(actor, monkeypatch, tmp_path)
    state.elt = preview_store
    state.knowledge = knowledge
    state.templates = templates
    return state


def _execute_elt(state, preview, *, call_id="import"):
    params = {
        "run_id": preview["id"],
        "preview_revision": preview["preview_revision"],
        "accept_suggested": True,
    }
    pending = state.execute(call_id, "elt_import", "execute", params)
    done = state.approve(call_id, pending)
    return done, _assert_execution_scope(state, done, params)


def _elt_auxiliary(state, preview):
    from app.application.elt.service_support import load_json
    from app.db.models.elt import EltRun

    with state.elt.factory() as db:
        run = db.get(EltRun, preview["id"])
        return load_json(run.receipt_json, {}).get("auxiliary")


def _execute_elt_business(state, preview):
    with tenant_scope(state.actor.tenant_id), state.elt.factory() as db:
        state.elt.service.execute(
            db,
            run_id=preview["id"],
            owner_user_id=state.actor.user_id,
            confirmed=True,
            valid_rows_only=False,
            preview_revision=preview["preview_revision"],
            accept_suggested=True,
            chat_context=state.actor.context,
        )
    state.elt.executor.futures[-1].result(timeout=10)
    with tenant_scope(state.actor.tenant_id), state.elt.factory() as db:
        current = state.elt.service.get_run(
            db, run_id=preview["id"], owner_user_id=state.actor.user_id
        )
    assert current["status"] == "completed" and current["summary"]["executed"] == 1
    return current


def _verify_elt_child(child):
    from app.application.agent_orchestrator.result_verification import verify_step_result
    from app.application.agent_orchestrator.task_background import task_execution_context

    observed = copy.deepcopy(child)
    step = observed.steps[0]
    return verify_step_result(
        run=observed,
        step=step,
        call=observed.tool_calls[0],
        context={
            **observed.metadata["runtime_context"],
            "run_id": observed.run_id,
            "step_id": step.step_id,
            "node_id": step.node_id,
            **task_execution_context(observed, step),
        },
    )


def _assert_elt_auxiliary(state, preview, child, *, templates):
    from sqlalchemy import text

    auxiliary = _elt_auxiliary(state, preview)
    output = child.tool_calls[0].output["data"]
    assert auxiliary["schema"] == "xcmax.elt-auxiliary.v1"
    assert auxiliary["state"] == "returned"
    assert auxiliary["binding"] == {
        "run_id": preview["id"],
        "tenant_id": state.actor.tenant_id,
        "owner_user_id": state.actor.user_id,
        "upload_id": preview["upload_id"],
        "file_sha256": preview["file_sha256"],
        "preview_revision": preview["preview_revision"],
    }
    assert auxiliary["knowledge"] == output["knowledge"]
    assert auxiliary["template"] == output["template"]
    evidence = auxiliary["knowledge"]["evidence"]
    snapshot = state.knowledge._repository.read_committed_dataset("office-docking")
    document = snapshot["documents"][evidence["document_id"]]
    assert document["tenant_id"] == str(state.actor.tenant_id)
    assert document["version"] == evidence["version"]
    assert document["metadata"]["document_content_hash"] == evidence["text_sha256"]
    chunks = [
        chunk
        for chunk in snapshot["chunks"]
        if chunk["metadata"].get("document_id") == document["document_id"]
    ]
    assert len(chunks) == document["chunk_count"] == evidence["chunk_count"] > 0
    assert all(chunk["metadata"]["tenant_id"] == str(state.actor.tenant_id) for chunk in chunks)
    items = auxiliary["template"].get("evidence", {}).get("items", [])
    assert len(items) == templates
    with state.elt.factory() as db:
        for item in items:
            row = (
                db.execute(
                    text("SELECT * FROM templates WHERE id=:id"), {"id": item["template_id"]}
                )
                .mappings()
                .one()
            )
            assert row["tenant_id"] == state.actor.tenant_id
            assert row["template_key"] == item["template_key"]
            assert row["template_name"] == item["template_name"]
            assert (
                hashlib.sha256(Path(row["original_file_path"]).read_bytes()).hexdigest()
                == (item["file_sha256"])
            )
    return auxiliary


def test_owned_elt_preview_is_reviewed_approved_executed_and_independently_verified(elt_runtime):
    from app.db.models import ShipmentRecord
    from app.db.models.elt import EltRun

    state = elt_runtime
    preview = _elt_preview(state.elt)
    assert preview["status"] == "preview_ready", preview
    params = {"run_id": preview["id"], "accept_suggested": True}
    pending = state.execute("review", "elt_import", "preview", params)
    _assert_execution_scope(state, pending, params)
    with state.elt.factory() as db:
        assert db.query(EltRun).count() == 1 and db.query(ShipmentRecord).count() == 0
    reviewed = state.approve("review", pending)
    assert reviewed["verified"] is True, state.repository.get(reviewed["run_id"]).tool_calls
    child = _assert_execution_scope(state, reviewed, params)
    output = child.tool_calls[0].output
    assert output["data"]["run_id"] == preview["id"]
    assert output["data"]["preview_revision"] == preview["preview_revision"]
    params = {
        "run_id": preview["id"],
        "preview_revision": output["data"]["preview_revision"],
        "accept_suggested": True,
    }
    pending = state.execute("import", "elt_import", "execute", params)
    with state.elt.factory() as db:
        assert db.query(ShipmentRecord).count() == 0
    done = state.approve("import", pending)
    child = _assert_execution_scope(state, done, params)
    assert done["verified"] is True, {
        "receipt": done,
        "output": child.tool_calls[0].output,
        "verification": child.tool_calls[0].metadata.get("verification"),
    }
    assert child.tool_calls[0].output["committed"] is True
    assert child.tool_calls[0].metadata["verification"]["accepted"] is True
    auxiliary = _assert_elt_auxiliary(state, preview, child, templates=0)
    assert auxiliary["knowledge"]["action"] == "new"
    assert auxiliary["template"]["action"] == "skip"
    assert auxiliary["template"]["reason"] == "no_region"
    assert "原件已同步到知识库" in child.tool_calls[0].output["message"]
    assert "未切出模板区段" in child.tool_calls[0].output["message"]
    replay = state.execute("repeat", "elt_import", "execute", params)
    assert replay["run_id"] == done["run_id"] and replay["verified"] is True
    with state.elt.factory() as db:
        assert db.query(ShipmentRecord).count() == 1
        assert db.get(EltRun, preview["id"]).executed_rows == 1


@pytest.mark.parametrize("region_count,csv", [(0, True), (1, False), (2, False)])
def test_elt_real_auxiliary_documents_and_templates_are_independently_verified(
    elt_runtime, monkeypatch, region_count, csv
):
    from app.db.models import ShipmentRecord

    state = elt_runtime
    ingest = Mock(wraps=state.knowledge.ingest_document)
    save_template = Mock(wraps=state.templates.save_template)
    monkeypatch.setattr(state.knowledge, "ingest_document", ingest)
    monkeypatch.setattr(state.templates, "save_template", save_template)
    preview = _elt_preview(state.elt, region_count=region_count, csv=csv)
    assert len(preview["source_features"].get("regions", [])) == region_count
    done, child = _execute_elt(state, preview)
    assert done["verified"] is True, child.tool_calls[0].output
    auxiliary = _assert_elt_auxiliary(state, preview, child, templates=region_count)
    assert auxiliary["knowledge"]["action"] == "new"
    assert auxiliary["template"]["action"] == ("new" if region_count else "skip")
    assert "原件已同步到知识库" in child.tool_calls[0].output["message"]
    if region_count:
        assert "已登记模板到模板库" in child.tool_calls[0].output["message"]
    if csv:
        evidence = auxiliary["knowledge"]["evidence"]
        assert evidence["raw_text_sha256"] != evidence["text_sha256"]
    assert _verify_elt_child(child)["accepted"] is True
    repeated = state.execute("repeat", "elt_import", "execute", child.steps[0].params)
    assert repeated["run_id"] == done["run_id"] and repeated["verified"] is True
    assert ingest.call_count == 1
    assert save_template.call_count == region_count
    with state.elt.factory() as db:
        assert db.query(ShipmentRecord).count() == max(1, region_count)


def test_elt_duplicate_auxiliary_receipts_prove_every_existing_region(elt_runtime, monkeypatch):
    from sqlalchemy import text

    from app.domain.shared_services.tools_workflow_elt import (
        _knowledge_receipt,
        _template_receipt,
    )

    state = elt_runtime
    preview = _elt_preview(state.elt, region_count=2)
    # Existing assets are created by the actual receipt writers, before this
    # business import. The finalizer must read and prove those exact assets.
    with tenant_scope(state.actor.tenant_id):
        seeded_knowledge = _knowledge_receipt(preview, state.actor.user_id)
        seeded_templates = _template_receipt(preview, state.actor.user_id)
    assert seeded_knowledge["action"] == seeded_templates["action"] == "new"
    before = state.knowledge._repository.read_committed_dataset("office-docking")
    original_run_id = preview["id"]
    with tenant_scope(state.actor.tenant_id), state.elt.factory() as db:
        new_preview = state.elt.service.create_preview(
            db,
            owner_user_id=state.actor.user_id,
            upload_id=preview["upload_id"],
            target_type="shipment_records",
        )
    state.elt.executor.futures[-1].result(timeout=10)
    with tenant_scope(state.actor.tenant_id), state.elt.factory() as db:
        preview = state.elt.service.get_run(
            db, run_id=new_preview["id"], owner_user_id=state.actor.user_id
        )
    assert preview["id"] != original_run_id
    ingest = Mock(wraps=state.knowledge.ingest_document)
    save_template = Mock(wraps=state.templates.save_template)
    monkeypatch.setattr(state.knowledge, "ingest_document", ingest)
    monkeypatch.setattr(state.templates, "save_template", save_template)
    done, child = _execute_elt(state, preview)
    assert done["verified"] is True, child.tool_calls[0].output
    auxiliary = _assert_elt_auxiliary(state, preview, child, templates=2)
    assert auxiliary["knowledge"]["action"] == auxiliary["template"]["action"] == "skip"
    items = auxiliary["template"]["evidence"]["items"]
    assert {item["target"]["region_id"] for item in items} == {
        region["id"] for region in preview["source_features"]["regions"]
    }
    assert all(item["action"] == "skip" for item in items)
    assert {item["template_id"] for item in items} == set(seeded_templates["template_ids"])
    assert auxiliary["knowledge"]["match_ref"] == seeded_knowledge["match_ref"]
    after = state.knowledge._repository.read_committed_dataset("office-docking")
    assert after["documents"] == before["documents"] and after["chunks"] == before["chunks"]
    ingest.assert_not_called()
    save_template.assert_not_called()
    with state.elt.factory() as db:
        assert db.execute(text("SELECT count(*) FROM templates")).scalar_one() == 2


def test_elt_same_region_in_different_uploads_cannot_reuse_another_files_template(elt_runtime):
    state = elt_runtime
    original = _elt_preview(state.elt, product="原文件产品", region_count=1)
    first, first_child = _execute_elt(state, original, call_id="first")
    assert first["verified"] is True, first_child.tool_calls[0].output
    changed = _elt_preview(state.elt, product="新文件产品", region_count=1, order_prefix="NEXT")
    assert original["file_sha256"] != changed["file_sha256"]
    assert (
        original["source_features"]["regions"][0]["id"]
        == (changed["source_features"]["regions"][0]["id"])
    )
    second, second_child = _execute_elt(state, changed, call_id="second")
    assert second["verified"] is True, second_child.tool_calls[0].output
    first_item = _elt_auxiliary(state, original)["template"]["evidence"]["items"][0]
    second_item = _assert_elt_auxiliary(state, changed, second_child, templates=1)["template"][
        "evidence"
    ]["items"][0]
    assert second_item["action"] == "new"
    assert first_item["template_id"] != second_item["template_id"]
    assert first_item["template_key"] != second_item["template_key"]


@pytest.mark.parametrize("write_before_failure", [False, True])
def test_elt_knowledge_failure_never_replays_an_already_committed_business_import(
    elt_runtime, monkeypatch, write_before_failure
):
    from app.db.models import ShipmentRecord
    from app.domain.shared_services.tools_workflow_elt import _execute

    state = elt_runtime
    ingest_document = state.knowledge.ingest_document

    def lose_knowledge_receipt(*args, **kwargs):
        if write_before_failure:
            assert ingest_document(*args, **kwargs)["success"] is True
        raise OSError("injected knowledge store failure")

    ingest = Mock(side_effect=lose_knowledge_receipt)
    monkeypatch.setattr(state.knowledge, "ingest_document", ingest)
    preview = _elt_preview(state.elt)
    done, child = _execute_elt(state, preview)
    assert done["verified"] is False and done["outcome"] == "unknown"
    assert child.status == "blocked"
    assert child.tool_calls[0].output["committed"] is True
    auxiliary = _elt_auxiliary(state, preview)
    assert auxiliary["state"] == "returned" and auxiliary["knowledge"]["action"] == "unknown"
    with pytest.raises(XiaoxBindingError) as error:
        state.execute("retry", "elt_import", "execute", child.steps[0].params)
    assert error.value.code == "reconciliation_required"
    with tenant_scope(state.actor.tenant_id):
        reread = _execute(child.steps[0].params, state.actor.context)
    assert reread["data"]["knowledge"] == auxiliary["knowledge"]
    assert reread["data"]["template"] == auxiliary["template"]
    assert _verify_elt_child(child)["accepted"] is False
    assert ingest.call_count == 1
    if write_before_failure:
        snapshot = state.knowledge._repository.read_committed_dataset("office-docking")
        assert len(snapshot["documents"]) == 1
    else:
        assert not state.knowledge._repository.storage_path.exists()
    with state.elt.factory() as db:
        assert db.query(ShipmentRecord).count() == 1


def test_elt_partial_template_failure_retains_written_evidence_and_blocks_completion(
    elt_runtime, monkeypatch
):
    from sqlalchemy import text

    from app.db.models import ShipmentRecord
    from app.domain.shared_services.tools_workflow_elt import _execute

    state = elt_runtime
    original_save = state.templates.save_template
    attempts = []

    def fail_second_template(payload, *args, **kwargs):
        attempts.append(payload["template_key"])
        if len(attempts) == 2:
            return {"success": False, "message": "injected second template failure"}
        return original_save(payload, *args, **kwargs)

    monkeypatch.setattr(state.templates, "save_template", fail_second_template)
    preview = _elt_preview(state.elt, region_count=2)
    done, child = _execute_elt(state, preview)
    assert done["verified"] is False and done["outcome"] == "unknown"
    assert child.status == "blocked" and child.tool_calls[0].output["committed"] is True
    auxiliary = _elt_auxiliary(state, preview)
    template = auxiliary["template"]
    assert auxiliary["state"] == "returned" and template["action"] == "error"
    assert len(template["evidence"]["items"]) == len(template["failed_targets"]) == 1
    with tenant_scope(state.actor.tenant_id):
        reread = _execute(child.steps[0].params, state.actor.context)
    assert reread["data"]["template"] == template
    assert len(attempts) == 2
    with state.elt.factory() as db:
        assert db.query(ShipmentRecord).count() == 2
        assert db.execute(text("SELECT count(*) FROM templates")).scalar_one() == 1


@pytest.mark.parametrize(
    "change",
    [
        "knowledge_document",
        "knowledge_chunk",
        "knowledge_tenant",
        "knowledge_missing",
        "template_row",
        "template_file",
        "template_tenant",
        "template_missing",
        "upload_sha256",
        "source_features",
        "auxiliary_binding",
        "auxiliary_missing",
        "auxiliary_started",
        "old_store_baseline",
        "old_features_baseline",
    ],
)
def test_elt_readback_rejects_changed_or_missing_auxiliary_facts(elt_runtime, monkeypatch, change):
    from sqlalchemy import text

    from app.application.elt import auxiliary_verification
    from app.application.elt.preview_confirmation import REVIEW_KEY
    from app.application.elt.service_support import dump_json, load_json
    from app.db.models import ShipmentRecord
    from app.db.models.elt import EltRun, EltUpload

    state = elt_runtime
    preview = _elt_preview(state.elt, region_count=1)
    old_field = {
        "old_store_baseline": "auxiliary_store_sha256",
        "old_features_baseline": "source_features_sha256",
    }.get(change)
    if old_field:
        capture = auxiliary_verification.capture_auxiliary_sources

        def legacy_sources(run):
            baseline = capture(run)
            baseline.pop(old_field)
            return baseline

        with monkeypatch.context() as old_deployment:
            old_deployment.setattr(
                auxiliary_verification, "capture_auxiliary_sources", legacy_sources
            )
            done, child = _execute_elt(state, preview)
        assert done["verified"] is False
        assert (
            old_field
            not in child.tool_calls[0].metadata["verification_contract"]["elt_execution_baseline"]
        )
    else:
        done, child = _execute_elt(state, preview)
        assert done["verified"] is True, child.tool_calls[0].output
        assert _verify_elt_child(child)["accepted"] is True
    auxiliary = _elt_auxiliary(state, preview)
    if change.startswith("knowledge_"):
        storage = state.knowledge._repository.storage_path
        raw = json.loads(storage.read_text())
        snapshot = raw["datasets"]["office-docking"]
        document_id = auxiliary["knowledge"]["evidence"]["document_id"]
        document = snapshot["documents"][document_id]
        if change == "knowledge_document":
            document["metadata"]["elt_run_id"] = "different-import"
        elif change == "knowledge_chunk":
            snapshot["chunks"][0]["text"] = "原件中没有的内容"
        elif change == "knowledge_tenant":
            document["tenant_id"] = document["metadata"]["tenant_id"] = "2"
        else:
            snapshot["documents"].pop(document_id)
            snapshot["chunks"] = []
        storage.write_text(json.dumps(raw, ensure_ascii=False))
    elif change.startswith("template_"):
        template_id = auxiliary["template"]["evidence"]["items"][0]["template_id"]
        with state.elt.factory.begin() as db:
            if change == "template_file":
                path = db.execute(
                    text("SELECT original_file_path FROM templates WHERE id=:id"),
                    {"id": template_id},
                ).scalar_one()
                with Path(path).open("ab") as stream:
                    stream.write(b"changed template bytes")
            else:
                mutation = {
                    "template_row": "UPDATE templates SET template_name='changed' WHERE id=:id",
                    "template_tenant": "UPDATE templates SET tenant_id=2 WHERE id=:id",
                    "template_missing": "DELETE FROM templates WHERE id=:id",
                }[change]
                db.execute(text(mutation), {"id": template_id})
    elif not old_field:
        with state.elt.factory.begin() as db:
            run = db.get(EltRun, preview["id"])
            if change == "upload_sha256":
                db.get(EltUpload, run.upload_id).sha256 = "0" * 64
            elif change == "source_features":
                features = load_json(run.source_features_json, {})
                features["regions"][0]["id"] = "different-region"
                run.source_features_json = dump_json(features)
                assert (
                    load_json(run.summary_json, {})[REVIEW_KEY]["revision"]
                    == (preview["preview_revision"])
                )
            else:
                receipt = load_json(run.receipt_json, {})
                if change == "auxiliary_binding":
                    receipt["auxiliary"]["binding"]["tenant_id"] = 2
                elif change == "auxiliary_started":
                    receipt["auxiliary"]["state"] = "started"
                else:
                    receipt.pop("auxiliary")
                run.receipt_json = dump_json(receipt)
    dispatch = Mock(side_effect=AssertionError("readback must not dispatch business actions"))
    monkeypatch.setattr(AgentToolExecutor, "execute", dispatch)
    observed = _verify_elt_child(child)
    assert observed["accepted"] is False, (change, observed)
    assert observed["status"] in {"failed", "inconclusive"}
    dispatch.assert_not_called()
    with state.elt.factory() as db:
        assert db.query(ShipmentRecord).count() == 1
