"""Actual native ELT transactions must have independently readable business effects."""

from __future__ import annotations

import copy
import csv
import io
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.application.agent_orchestrator import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.elt.preview_confirmation import preview_revision, publish_preview
from app.application.elt.service_support import dump_json, load_json
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from app.db.models.elt import EltDynamicRow, EltRun, EltRunRow, EltUpload
from app.db.models.product import Product
from app.db.models.purchase import PurchaseOrderItem, Supplier
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.shipment import ShipmentRecord
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_agent_user_decision_pause import _approve_and_execute


@pytest.fixture
def native_execution(trusted_actor, tmp_path, monkeypatch):
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.application.agent_orchestrator.tool_permission import clear_idempotent_replay_for_tests
    from app.application.elt.service import EltService
    from app.application.elt.targets import get_adapter
    from app.application.elt.targets.targets_base import json_safe
    from app.domain.shared_services import tools_workflow_elt

    actor = trusted_actor(role="admin")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("FHD_ELT_CENTER_ENABLED", "1")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "claims.sqlite"))
    clear_idempotent_replay_for_tests()
    service = EltService()
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: service)
    for module in ("service_execution", "service_support"):
        monkeypatch.setattr(f"app.application.elt.{module}.new_session", actor.factory)
    monkeypatch.setattr(tools_workflow_elt, "_finalize_import", lambda *_, **__: ({}, {}, ""))

    def submit(run_id, tenant_id, owner, valid_rows_only, *, operation_token):
        with tenant_scope(tenant_id):
            service._execute_worker(run_id, owner, valid_rows_only, operation_token=operation_token)

    monkeypatch.setattr(service, "_submit_execution", submit)

    def prepare(target="dynamic_table", payloads=None, *, allowed_updates=(), dedupe_keys=()):
        defaults = {
            "dynamic_table": [{"code": "A", "amount": "7"}, {"code": "B", "amount": "9"}],
            "customers": [{"customer_name": "Verified customer", "contact_phone": "123"}],
            "products": [
                {
                    "unit": "Verified customer",
                    "name": "Verified product",
                    "model_number": "P-1",
                    "price": "3.50",
                }
            ],
            "customer_products": [
                {
                    "customer_name": "Verified customer",
                    "name": "Verified product",
                    "model_number": "P-1",
                    "price": "3.50",
                }
            ],
            "shipment_records": [
                {
                    "purchase_unit": "Verified customer",
                    "product_name": "Verified product",
                    "quantity_kg": "5",
                    "unit_price": "3.50",
                    "amount": "17.50",
                }
            ],
            "purchase_orders": [
                {
                    "external_order_no": "verified-order-1",
                    "supplier_name": "Verified supplier",
                    "order_date": "2026-11-21",
                    "product_model": "P-1",
                    "product_name": "Verified product",
                    "quantity": "2.5",
                    "unit_price": "3.50",
                }
            ],
        }
        payloads = copy.deepcopy(payloads if payloads is not None else defaults[target])
        source = io.StringIO()
        headers = list(dict.fromkeys(key for row in payloads for key in row))
        writer = csv.DictWriter(source, fieldnames=headers)
        writer.writeheader()
        writer.writerows(payloads)
        content = source.getvalue().encode()
        identity = str(uuid4())
        adapter = get_adapter(target)
        with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
            saved = service.save_upload(
                db,
                owner_user_id=actor.user_id,
                file_name=f"{identity}.csv",
                content_type="text/csv",
                stream=io.BytesIO(content),
            )
            upload = db.get(EltUpload, saved["upload_id"])
            db.flush()
            native = EltRun(
                id=uuid4().hex,
                tenant_id=actor.tenant_id,
                owner_user_id=actor.user_id,
                upload_id=upload.id,
                file_sha256=upload.sha256,
                target_type=target,
                status="preview_ready",
                stage="preview_ready",
                total_rows=len(payloads),
                draft_json=dump_json(
                    {
                        "field_mappings": [
                            {"source": key, "target": key, "confirmed": True} for key in headers
                        ],
                        "allowed_update_fields": list(allowed_updates),
                        "dynamic_schema": {"dedupe_keys": list(dedupe_keys)},
                    }
                ),
            )
            db.add(native)
            db.flush()
            cache = {}
            for index, data in enumerate(payloads, 2):
                decision = adapter.preview(
                    db,
                    data,
                    allowed_update_fields=set(allowed_updates),
                    context={
                        "run_id": native.id,
                        "file_sha256": upload.sha256,
                        "file_name": upload.file_name,
                        "source_row": index,
                        "_preview_cache": cache,
                    },
                )
                assert decision.action in {"new", "update", "skip"}, decision.issues
                setattr(
                    native,
                    f"{decision.action}_rows",
                    getattr(native, f"{decision.action}_rows") + 1,
                )
                db.add(
                    EltRunRow(
                        run_id=native.id,
                        tenant_id=actor.tenant_id,
                        owner_user_id=actor.user_id,
                        source_sheet="Data",
                        source_row=index,
                        final_action=decision.action,
                        match_ref=decision.match_ref,
                        source_json=dump_json(data),
                        normalized_json=dump_json(data),
                        before_json=dump_json(json_safe(decision.before or {})),
                        after_json=dump_json(json_safe(decision.after or {})),
                    )
                )
            publish_preview(db, native)
            params = {"run_id": native.id, "preview_revision": preview_revision(native)}
        return params

    def dispatch(params, *, corrupt=None, context=None):
        step = AgentStep(
            "import",
            "elt_import",
            "execute",
            params=copy.deepcopy(params),
            risk="high",
            status="waiting_user",
        )
        plan = PlanGraph(
            "native-elt",
            "import",
            nodes=[
                WorkflowNode(
                    step.node_id,
                    step.tool_id,
                    step.action,
                    params=copy.deepcopy(params),
                    risk=step.risk,
                )
            ],
        )
        run = AgentRun(
            user_id=str(actor.user_id),
            message="verify native import",
            status="waiting_user",
            plan_id=plan.plan_id,
            steps=[step],
            metadata={
                "runtime_context": {**actor.context, **(context or {})},
                "plan": plan_to_dict(plan),
            },
        )
        repo = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
        executor = MagicMock()

        def execute(dispatched, *, runtime_context, **_kwargs):
            with tenant_scope(actor.tenant_id):
                result = AgentToolExecutor().execute(dispatched, runtime_context=runtime_context)
                assert result["success"] is True, result
                if corrupt:
                    with actor.factory.begin() as db:
                        member = result["results"][0] if result.get("batch") else result
                        corrupt(db, db.get(EltRun, member["data"]["run_id"]))
                return result

        executor.execute_with_deadline.side_effect = execute
        service = AgentOrchestrator(repository=repo, tool_executor=executor)
        repo.save(run)
        return SimpleNamespace(
            run=_approve_and_execute(service, run, actor),
            executor=executor,
            repo=repo,
            service=service,
        )

    return SimpleNamespace(actor=actor, prepare=prepare, dispatch=dispatch)


def _prepare_native(case, target):
    if target == "purchase_orders":
        with tenant_scope(case.actor.tenant_id), case.actor.factory.begin() as db:
            db.add(
                Supplier(tenant_id=case.actor.tenant_id, code="verified", name="Verified supplier")
            )
            db.add(
                Product(
                    tenant_id=case.actor.tenant_id,
                    name="Verified product",
                    model_number="P-1",
                    unit="kg",
                )
            )
    return case.prepare(target)


@pytest.mark.parametrize(
    "target",
    [
        "dynamic_table",
        "customers",
        "products",
        "customer_products",
        "shipment_records",
        "purchase_orders",
    ],
)
def test_real_native_sql_import_is_independently_verified(native_execution, target):
    case = native_execution
    params = _prepare_native(case, target)
    result = case.dispatch(params)
    assert result.run.status == "completed", result.run.final_output.get("verification")
    verification = result.run.tool_calls[0].metadata["verification"]
    assert verification["accepted"] is True
    evidence = next(
        check["evidence"] for check in verification["checks"] if check["source"] == "elt_execution"
    )
    with tenant_scope(case.actor.tenant_id), case.actor.factory() as db:
        native = db.get(EltRun, params["run_id"])
        assert native.status == "completed" and native.executed_rows > 0
        assert evidence["file_sha256"] == native.file_sha256
        assert evidence["readback"]["rows_checked"] == native.executed_rows
        if target in {"products", "customer_products"}:
            assert sum(evidence["readback"]["verified_products_by_unit"].values()) > 0
        assert load_json(native.receipt_json, {})["executed_rows"] == native.executed_rows
    assert result.executor.execute_with_deadline.call_count == 1


def _assert_no_replay(result, actor):
    original = copy.deepcopy(result.run.tool_calls[0].output)
    assert original["success"] is True
    assert result.run.status == "blocked"
    assert result.run.tool_calls[0].metadata["verification"]["accepted"] is False
    for _ in range(2):
        current = result.service.continue_run(
            result.run.run_id, approved_by=str(actor.user_id), runtime_context=actor.context
        )
        assert current.status == "blocked"
        assert current.tool_calls[0].output == original
    assert result.executor.execute_with_deadline.call_count == 1


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "payload",
        "owner",
        "confirmation",
        "plan",
        "unknown",
        "execution_state",
        "requires_reconciliation",
        "operation",
    ],
)
def test_unproven_native_execution_preserves_receipt_and_never_replays(native_execution, change):
    from app.application.elt.preview_confirmation import CONFIRMATION_KEY

    case = native_execution
    params = case.prepare()

    def corrupt(db, native):
        if change in {"missing", "payload", "owner"}:
            row = db.query(EltDynamicRow).filter_by(run_id=native.id).first()
            if change == "missing":
                db.delete(row)
            elif change == "payload":
                row.payload_json = '{"code":"A","amount":"999"}'
            else:
                row.owner_user_id = 999999
        elif change == "confirmation":
            details = load_json(native.summary_json, {})
            details[CONFIRMATION_KEY].pop("plan_sha256")
            native.summary_json = dump_json(details)
        elif change == "plan":
            row = db.query(EltRunRow).filter_by(run_id=native.id).first()
            row.normalized_json = '{"code":"unapproved","amount":"7"}'
        elif change in {"unknown", "execution_state", "requires_reconciliation"}:
            field = "summary_json" if change == "execution_state" else "receipt_json"
            marker = {
                "unknown": {"outcome": "unknown"},
                "execution_state": {"execution_state": "outcome_unknown"},
                "requires_reconciliation": {"requires_reconciliation": True},
            }[change]
            setattr(native, field, dump_json({**load_json(getattr(native, field), {}), **marker}))
        else:
            native.operation_kind, native.operation_token = "execute", "unsettled-owner"

    result = case.dispatch(params, corrupt=corrupt)
    _assert_no_replay(result, case.actor)


@pytest.mark.parametrize("changed", [False, True])
def test_dynamic_dedupe_requires_matching_real_content(native_execution, changed):
    case = native_execution
    first = case.dispatch(case.prepare(dedupe_keys=("code",)))
    assert first.run.status == "completed"
    payloads = [{"code": "A", "amount": "99" if changed else "7"}, {"code": "B", "amount": "9"}]
    params = case.prepare(payloads=payloads, dedupe_keys=("code",))
    result = case.dispatch(params)
    with tenant_scope(case.actor.tenant_id), case.actor.factory() as db:
        assert db.get(EltRun, params["run_id"]).executed_rows == 0
        assert db.query(EltDynamicRow).count() == 2
    if changed:
        _assert_no_replay(result, case.actor)
    else:
        assert result.run.status == "completed", result.run.final_output.get("verification")
        assert result.run.tool_calls[0].metadata["verification"]["accepted"] is True


def test_multiple_approved_updates_read_the_final_business_image(native_execution):
    case = native_execution
    with tenant_scope(case.actor.tenant_id), case.actor.factory.begin() as db:
        db.add(
            PurchaseUnit(
                tenant_id=case.actor.tenant_id, unit_name="Verified customer", contact_phone="old"
            )
        )
    params = case.prepare(
        "customers",
        [
            {"customer_name": "Verified customer", "contact_phone": "first"},
            {"customer_name": "Verified customer", "contact_phone": "last"},
        ],
        allowed_updates=("contact_phone",),
    )
    result = case.dispatch(params)
    assert result.run.status == "completed", result.run.final_output.get("verification")
    with tenant_scope(case.actor.tenant_id), case.actor.factory() as db:
        assert db.query(PurchaseUnit).one().contact_phone == "last"
        assert db.get(EltRun, params["run_id"]).executed_rows == 2


@pytest.mark.parametrize("change", [None, "alias", "source", "origin"])
def test_file_execution_is_bound_before_native_run_selection(native_execution, monkeypatch, change):
    from app.application.elt.service_history import HistoryServiceMixin
    from app.domain.shared_services import tools_workflow_elt

    case = native_execution
    original = case.prepare()
    chosen = (
        case.prepare(payloads=[{"code": "C", "amount": "4"}]) if change == "source" else original
    )
    with tenant_scope(case.actor.tenant_id), case.actor.factory() as db:
        upload_id = db.get(EltRun, original["run_id"]).upload_id
        upload_name = db.get(EltUpload, upload_id).file_name
        preview = tools_workflow_elt._summary(
            HistoryServiceMixin().run_dict(db.get(EltRun, chosen["run_id"]))
        )

    # Replace perception scheduling only; the selected preview has an actual
    # upload, native rows and published manifest, and executes the real worker.
    def preview_ready(params, runtime_context, **kwargs):
        assert params["file_path"] == upload_id
        return {
            "success": True,
            "preview": True,
            "message": "ready",
            "data": {**preview, "executable": True},
        }

    monkeypatch.setattr(tools_workflow_elt, "_preview", preview_ready)

    def corrupt(db, native):
        if change == "origin":
            details = load_json(native.summary_json, {})
            details["chat_import_origin"]["turn_id"] = "unrelated-turn"
            native.summary_json = dump_json(details)

    result = case.dispatch(
        {"file_paths": [upload_id, upload_name] if change == "alias" else [upload_id]},
        context={"conversation_id": "original-conversation", "turn_id": "original-turn"},
        corrupt=corrupt,
    )
    if change in {"source", "origin"}:
        _assert_no_replay(result, case.actor)
    else:
        assert result.run.status == "completed", result.run.final_output.get("verification")
        assert result.run.tool_calls[0].metadata["verification"]["accepted"] is True


def test_skipped_rows_do_not_claim_verified_business_writes(native_execution):
    case = native_execution
    with tenant_scope(case.actor.tenant_id), case.actor.factory.begin() as db:
        db.add(PurchaseUnit(tenant_id=case.actor.tenant_id, unit_name="Verified customer"))
    result = case.dispatch(case.prepare("customers"))
    _assert_no_replay(result, case.actor)


@pytest.mark.parametrize(
    "target", ["customers", "products", "customer_products", "purchase_orders", "shipment_records"]
)
def test_native_row_ledger_cannot_replace_actual_business_readback(native_execution, target):
    case = native_execution
    params = _prepare_native(case, target)

    def corrupt(db, native):
        if target in {"customers", "customer_products"}:
            db.query(PurchaseUnit).one().contact_phone = "unexpected"
        elif target == "products":
            db.query(Product).one().name = "unexpected"
        elif target == "purchase_orders":
            db.query(PurchaseOrderItem).one().quantity += 1
        else:
            db.query(ShipmentRecord).one().amount += 1

    result = case.dispatch(params, corrupt=corrupt)
    _assert_no_replay(result, case.actor)


def test_approved_plan_digest_never_flushes_unrelated_business_state(native_execution):
    from app.application.elt.preview_confirmation import execution_plan_sha256

    case = native_execution
    params = case.prepare()
    with tenant_scope(case.actor.tenant_id), case.actor.factory() as db:
        native = db.get(EltRun, params["run_id"])
        before = execution_plan_sha256(db, native)
        pending = PurchaseUnit(tenant_id=case.actor.tenant_id, unit_name="must remain pending")
        db.add(pending)
        assert execution_plan_sha256(db, native) == before
        assert pending.id is None and pending in db.new
