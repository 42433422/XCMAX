"""Operations advance from original business facts, never a skipped dispatch."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from modstore_server import production_line_orchestrator as pipeline


def run(awaitable):
    return asyncio.run(awaitable)


@pytest.mark.parametrize("step_id", ["O1", "O3", "O4", "O5", "O6", "O8", "O9", "O10"])
def test_missing_business_fact_cannot_complete_or_be_approved(step_id):
    orch = pipeline.ProductionLineOrchestrator()
    orch._release_train_subset = True
    result = run(orch.run_step(step_id, {}))
    assert result.status.value == "waiting_evidence"
    assert result.data["result"]["ok"] is False
    assert run(orch.approve_step(step_id, admin_user_id=1)).status != pipeline.StepStatus.COMPLETED


def test_retry_cannot_bypass_approval(monkeypatch):
    orch = pipeline.ProductionLineOrchestrator()
    orch._release_train_subset = True
    calls = []

    async def transient(step, context):
        calls.append(step.step_id)
        if len(calls) == 1:
            raise OSError("temporary")
        return {"step": step.step_id, "result": {"ok": True}}

    monkeypatch.setattr(orch, "_execute_step", transient)
    result = run(orch.run_step("P3", {}))
    assert result.status == pipeline.StepStatus.AWAITING_APPROVAL
    assert calls == ["P3", "P3"]


def test_full_pipeline_visits_each_step_once_and_preserves_scope(monkeypatch):
    orch = pipeline.ProductionLineOrchestrator()
    steps = [
        replace(row, approval_gate=pipeline.ApprovalGate.NONE)
        for row in pipeline.OPERATIONS_LINE_STEPS[:3]
    ]
    monkeypatch.setattr(pipeline, "OPERATIONS_LINE_STEPS", steps)
    monkeypatch.setattr(pipeline, "ALL_STEPS", steps)
    calls = []

    async def observed(step, context):
        calls.append((step.step_id, context.get("business")))
        return {"step": step.step_id, "result": {"ok": True}}

    monkeypatch.setattr(orch, "_execute_step", observed)
    scope = {"landing_contact_id": 7}
    result = run(orch.run_full_pipeline(pipeline.LineType.OPERATIONS, context={"business": scope}))
    assert result["ok"] is True
    assert calls == [(row.step_id, scope) for row in steps]


def test_five_line_status_does_not_promote_static_baseline(monkeypatch):
    orch = pipeline.ProductionLineOrchestrator()
    monkeypatch.setattr(pipeline, "get_production_line_orchestrator", lambda: orch)
    status = pipeline.get_five_line_status()
    assert status["overall_automation_rate"] == 0
    assert all(row["automation_rate"] == 0 for row in status["lines"])


@pytest.fixture
def business(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from modstore_server import payment_orders
    from modstore_server import production_line_business as consumer
    from modstore_server.auth_service import verified_email_digest
    from modstore_server.db.db_base import Base
    from modstore_server.db.work_orders import WorkOrderEvent
    from modstore_server.models_cs import CustomerServiceSession

    engine = create_engine("sqlite://")
    tables = [
        model.__table__
        for model in (
            consumer.User,
            consumer.LandingContactSubmission,
            WorkOrderEvent,
            consumer.CustomerValueReceipt,
            consumer.Invoice,
            consumer.ReconciliationReport,
            CustomerServiceSession,
            consumer.CustomerServiceTicket,
        )
    ]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(consumer, "get_session_factory", lambda: factory)
    monkeypatch.setenv("PAYMENT_BACKEND", "python")
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    now = datetime.now(UTC) - timedelta(hours=2)
    payment_orders.create(
        out_trade_no="customer-order-business",
        subject="客户交付",
        total_amount="100.00",
        user_id=11,
        order_kind="plan",
        plan_id="enterprise",
    )
    payment_orders.merge_fields(
        "customer-order-business",
        status="paid",
        paid_at=now.isoformat(),
        payment_provider="bank",
        provider_trade_no="bank-business-1",
        provider_verification="bank_statement_reconciled",
        payment_environment="production",
    )
    with factory() as db:
        db.add(
            consumer.User(
                id=11,
                username="business-owner",
                password_hash="x",
                is_enterprise=True,
                email="owner@example.test",
                account_state="active",
                verified_email_sha256=verified_email_digest("owner@example.test"),
            )
        )
        db.add(
            consumer.User(id=12, username="other-owner", password_hash="x", account_state="active")
        )
        db.add(
            consumer.LandingContactSubmission(
                id=7,
                name="客户",
                email="owner@example.test",
                company="客户企业",
                message="需要制作一个每日库存分析报告",
                meta_json=json.dumps({"privacy_agreed": True}),
            )
        )
        db.commit()
    scope = {
        "customer_user_id": 11,
        "order_no": "customer-order-business",
        "customer_goal_id": "goal-business",
        "artifact_id": "report-business",
        "artifact_sha256": "c" * 64,
    }
    return consumer, factory, scope, now


def test_original_lead_creates_one_requirement_not_a_sale(business):
    consumer, factory, _, _ = business
    from modstore_server.db.work_orders import WorkOrderEvent

    scope = {"business": {"landing_contact_id": 7}}
    first = consumer.observe_business_step("O2", scope)["result"]
    again = consumer.observe_business_step("O2", scope)["result"]
    assert first == again
    assert first["status"] == "completed"
    assert first["evidence"]["stage"] == "prospect"
    assert first["evidence"]["payment_verified"] is False
    with factory() as db:
        assert db.query(WorkOrderEvent).count() == 1
    assert consumer.observe_business_step("O4", scope)["result"]["status"] == "waiting_evidence"


def test_payment_ignores_claimed_success_and_rejects_other_owner(business):
    consumer, _, scope, _ = business
    actual = consumer.observe_business_step("O4", {"business": scope})["result"]
    assert actual["status"] == "completed"
    forged = consumer.observe_business_step(
        "O4",
        {
            "business": {**scope, "customer_user_id": 12},
            "result": actual,
            "payment_verified": True,
        },
    )["result"]
    assert forged["status"] == "waiting_evidence"
    assert forged["reason"] == "payment_customer_mismatch"


def _append(business, kind, minute, **extra):
    from modstore_server import payment_orders
    from modstore_server.customer_value_evidence import append_customer_value_receipt

    _, factory, scope, now = business
    evidence = {"artifact_sha256": scope["artifact_sha256"], **extra.pop("evidence", {})}
    return append_customer_value_receipt(
        {
            "receipt_kind": kind,
            "verification_status": "verified",
            "lifecycle_v2": True,
            "source_event_id": f"business:{kind}:{minute}",
            "customer_ref": "paid-user:11",
            "customer_goal_id": scope["customer_goal_id"],
            "order_no": scope["order_no"],
            "artifact_id": scope["artifact_id"],
            "acceptance_id": "customer-confirmation",
            "environment": "production",
            "occurred_at": (now + timedelta(minutes=minute)).isoformat(),
            "evidence": evidence,
            **extra,
        },
        payment_order=payment_orders.find(scope["order_no"]),
        session_factory=factory,
    )


def _create_value_facts(business, overrides=None):
    consumer, factory, scope, now = business

    def append(kind, minute, **extra):
        replacement = dict((overrides or {}).get(kind) or {})
        evidence = {**extra.pop("evidence", {}), **replacement.pop("evidence", {})}
        return _append(business, kind, minute, **{**extra, **replacement, "evidence": evidence})

    agreement = {
        "baseline": 1,
        "target": 2,
        "comparison": "ge",
        "unit": "reports/hour",
        "measurement_window": "accepted-period",
        "agreement_sha256": "a" * 64,
        "customer_confirmed": True,
    }
    outcome = ((overrides or {}).get("outcome") or {}).get("evidence") or {}
    agreement.update({name: outcome[name] for name in ("baseline", "target") if name in outcome})
    _append(business, "goal", 1, evidence=agreement)
    _append(business, "delivery", 2)
    append(
        "first_use",
        3,
        evidence={
            "run_id": "business-native-run",
            "success": True,
            "business_output": True,
            "task_type": "report",
        },
    )
    append(
        "outcome",
        4,
        evidence={
            **agreement,
            "measured_value": 3,
            "source_material_summary": "原始报告执行统计",
            "source_material_sha256": "b" * 64,
        },
    )
    return {"business": scope}


def test_private_mod_production_consumes_original_business_graph_without_host_dispatch(
    business, monkeypatch
):
    from modstore_server import employee_orchestrator

    consumer, factory, scope, now = business

    def forbid_dispatch(*args, **kwargs):
        raise AssertionError("customer workflow must retain its original execution")

    monkeypatch.setattr(employee_orchestrator, "plan_and_dispatch", forbid_dispatch)
    orch = pipeline.ProductionLineOrchestrator()
    orch._release_train_subset = True
    context = {"business": scope}
    waiting = run(orch.run_step("P2", context))
    assert waiting.status == pipeline.StepStatus.WAITING_EVIDENCE
    _create_value_facts(business)
    completed = run(orch.run_step("P2", context))
    assert completed.data["result"]["status"] == "completed"
    assert completed.data["result"]["evidence"]["source"] == "customer_value_receipts"


def test_real_order_delivery_and_customer_confirmation_complete_separate_steps(business):
    consumer, factory, scope, now = business
    context = _create_value_facts(business)
    assert consumer.observe_business_step("O8", context)["result"]["status"] == "waiting_evidence"
    _append(business, "acceptance", 5, evidence={"customer_confirmed": True})
    for step in ["O1", "O2", "O3", "O4", "O5", "O6", "O7", "O8"]:
        assert (
            consumer.observe_business_step(step, context)["result"]["status"] == "completed"
        ), step
    forged = {"business": {**scope, "artifact_sha256": "f" * 64}}
    assert consumer.observe_business_step("O8", forged)["result"]["status"] == "waiting_evidence"
    with factory() as db:
        db.add(
            consumer.Invoice(
                user_id=11,
                order_ids_json=json.dumps([scope["order_no"]]),
                amount=100,
                status="issued",
                issued_at=now,
                pdf_url="https://invoices.example/issued.pdf",
            )
        )
        db.add(
            consumer.ReconciliationReport(
                period_start=now - timedelta(hours=1),
                period_end=now + timedelta(hours=1),
                total_orders=1,
                total_gmv=100,
                status="confirmed",
                confirmed_at=now,
            )
        )
        db.commit()
    for step in ["O9", "O10"]:
        assert consumer.observe_business_step(step, context)["result"]["status"] == "completed"
    _append(business, "refund", 6)
    assert consumer.observe_business_step("O8", context)["result"]["reason"] == "payment_refunded"


@pytest.mark.parametrize(
    ("kind", "replacement"),
    [
        ("first_use", {"artifact_id": "different-delivery"}),
        ("first_use", {"evidence": {"artifact_sha256": "f" * 64}}),
        ("outcome", {"artifact_id": "different-delivery"}),
        ("outcome", {"evidence": {"measured_value": float("inf")}}),
        ("outcome", {"evidence": {"measured_value": True, "target": 1}}),
        ("outcome", {"evidence": {"baseline": float("-inf")}}),
    ],
)
def test_customer_value_cannot_reuse_other_artifact_or_nonfinite_measurement(
    business, kind, replacement
):
    consumer, factory, scope, _ = business
    _create_value_facts(business, {kind: replacement})
    _append(business, "acceptance", 5, evidence={"customer_confirmed": True})
    step = "O6" if kind == "first_use" else "O8"
    assert (
        consumer.observe_business_step(step, {"business": scope})["result"]["status"]
        == "waiting_evidence"
    )


def test_approval_rechecks_payment_and_cannot_approve_a_refunded_order(business):
    from modstore_server import payment_orders

    _, _, scope, _ = business
    orch = pipeline.ProductionLineOrchestrator()
    orch._release_train_subset = True
    assert (
        run(orch.run_step("O4", {"business": scope})).status
        == pipeline.StepStatus.AWAITING_APPROVAL
    )
    payment_orders.merge_fields(scope["order_no"], refunded=True)
    result = run(orch.approve_step("O4", admin_user_id=1))
    assert result.status.value == "waiting_evidence"
    assert result.error == "payment_refunded"


def test_prospect_binding_requires_customer_verified_email(business):
    consumer, factory, _, _ = business
    with factory() as db:
        user = db.get(consumer.User, 11)
        assert consumer.bind_prospect_to_customer(db, user, 7)["customer_user_id"] == 11
        user.verified_email_sha256 = None
        with pytest.raises(consumer.MissingEvidence, match="verified_email"):
            consumer.bind_prospect_to_customer(db, user, 7)


def test_lead_cannot_borrow_a_customer_payment_without_authenticated_binding(business):
    consumer, _, scope, _ = business
    result = consumer.observe_business_step(
        "O4",
        {
            "business": {**scope, "landing_contact_id": 7},
        },
    )["result"]
    assert result["status"] == "waiting_evidence"
    assert result["reason"] == "prospect_customer_binding_missing"


def test_existing_requirement_cannot_claim_changed_prospect_input(business):
    consumer, factory, _, _ = business
    context = {"business": {"landing_contact_id": 7}}
    assert consumer.observe_business_step("O2", context)["result"]["ok"]
    with factory.begin() as db:
        db.get(consumer.LandingContactSubmission, 7).message = "与原工单不同的要求"
    result = consumer.observe_business_step("O2", context)["result"]
    assert result["status"] == "waiting_evidence"
    assert result["reason"] == "original_requirement_changed"


def test_original_public_intake_persists_requirement_without_external_send(business, monkeypatch):
    from fastapi import BackgroundTasks
    from starlette.requests import Request

    from modstore_server import market_auth_api
    from modstore_server.db.work_orders import WorkOrderEvent

    consumer, factory, _, _ = business
    monkeypatch.setattr(market_auth_api, "get_session_factory", lambda: factory)
    monkeypatch.setattr(market_auth_api, "_public_contact_rate_allow", lambda *_args: None)
    monkeypatch.setattr(market_auth_api, "_resolve_market_user_id_by_email", lambda *_args: None)
    body = market_auth_api.PublicContactDTO(
        name="New customer",
        email="new@example.test",
        message="Generate a weekly stock report",
        privacy_agreed=True,
    )
    tasks = BackgroundTasks()
    response = market_auth_api.api_public_contact_submit(
        body,
        Request(
            {
                "type": "http",
                "headers": [],
                "client": ("127.0.0.1", 1),
            }
        ),
        tasks,
    )
    assert response["ok"]
    with factory() as db:
        event = db.query(WorkOrderEvent).one()
        context = json.loads(event.context)
        assert context["source_id"] == response["id"]
        assert context["stage"] == "prospect" and context["payment_verified"] is False
    assert (
        consumer.observe_business_step(
            "O2",
            {
                "business": {"landing_contact_id": response["id"]},
            },
        )["result"]["evidence"]["work_order_id"]
        == event.wo_id
    )
