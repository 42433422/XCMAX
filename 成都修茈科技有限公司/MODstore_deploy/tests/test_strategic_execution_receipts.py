"""Strategy consumes native employee evidence without treating an empty response as success."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server.db.strategic import StrategicActionItem
from modstore_server.employee_path_guard import check_path_guard
from modstore_server.employee_verification import run_verification
from modstore_server.strategic_execution_receipts import evaluate_execution_receipt
from tests.test_strategic_portfolio import database as database
from tests.test_strategic_portfolio import opportunity, proposal


def native_receipt():
    """Use the actual verifier/guard schema emitted inside phase-04's wrapper."""
    inner = {
        "outputs": [{"handler": "http_request", "status_code": 200, "response": "Report returned"}]
    }
    config = {"workspace_policy": {"scope_globs": ["docs/**"], "forbidden_globs": ["**/.env"]}}
    inner["path_guard"] = check_path_guard(
        config=config, result=inner, employee_id="test-qa-runner"
    )
    inner["verification"] = run_verification(
        employee_id="test-qa-runner",
        task="Summarize the report",
        result=inner,
        config=config,
        reasoning={
            "reasoning": json.dumps({"status": "success", "summary": "The report was summarized"})
        },
    )
    return {
        "employee_id": "test-qa-runner",
        "pack": {"id": "fixture", "version": "1.0.0"},
        "result": inner,
        "executed_at": datetime.now(UTC).isoformat(),
        "llm_tokens": 0,
    }


def corrupted_receipt(kind):
    receipt = native_receipt()
    inner = receipt["result"]
    if kind == "empty":
        return {}
    if kind == "http_500":
        inner["outputs"][0]["status_code"] = 500
    elif kind == "handler_error":
        inner["outputs"][0]["error"] = "request failed"
    elif kind == "handler_status_error":
        inner["outputs"][0] = {"handler": "wechat_notify", "status": "error"}
    elif kind == "mixed_success_and_failure":
        inner["outputs"] = [
            {"handler": "echo", "ok": True, "output": "done"},
            {"handler": "http_request", "status_code": 500},
        ]
    elif kind == "mixed_success_and_missing":
        inner["outputs"].append({"handler": "unconfirmed"})
    elif kind == "verification_failed":
        inner["verification"]["passed"] = False
    elif kind == "verification_unknown":
        inner["verification"]["status"] = "unknown"
    elif kind == "verification_missing":
        inner.pop("verification")
    elif kind == "verification_counts":
        inner["verification"]["ok_count"] += 1
    elif kind == "verification_check_unknown":
        next(check for check in inner["verification"]["checks"] if not check.get("skipped"))[
            "ok"
        ] = None
    elif kind == "verification_empty":
        inner["verification"] = {
            "passed": True,
            "checks": [],
            "ok_count": 0,
            "total_count": 0,
            "failed_count": 0,
        }
    elif kind == "path_guard_failed":
        inner["path_guard"]["ok"] = False
    elif kind == "path_guard_violation":
        inner["path_guard"]["violations"] = [{"path": "private.env"}]
    elif kind == "path_guard_unchecked":
        inner["path_guard"]["checked"] = False
    elif kind == "path_guard_missing":
        inner.pop("path_guard")
    elif kind == "outputs_missing":
        inner["outputs"] = []
    elif kind == "transport_only":
        inner = {"outputs": inner["outputs"]}
        receipt["result"] = inner
    elif kind == "boolean_only":
        return {"ok": True}
    return receipt


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("empty", "unknown"),
        ("http_500", "failed"),
        ("handler_error", "failed"),
        ("handler_status_error", "failed"),
        ("mixed_success_and_failure", "failed"),
        ("mixed_success_and_missing", "unknown"),
        ("verification_failed", "failed"),
        ("verification_unknown", "unknown"),
        ("verification_missing", "unknown"),
        ("verification_counts", "unknown"),
        ("verification_check_unknown", "unknown"),
        ("verification_empty", "unknown"),
        ("path_guard_failed", "failed"),
        ("path_guard_violation", "failed"),
        ("path_guard_unchecked", "unknown"),
        ("path_guard_missing", "unknown"),
        ("outputs_missing", "unknown"),
        ("transport_only", "unknown"),
        ("boolean_only", "unknown"),
    ],
)
def test_receipts_require_all_execution_control_evidence(kind, expected):
    assert evaluate_execution_receipt(corrupted_receipt(kind)).status == expected


def test_real_verification_and_path_guard_accept_phase04_without_overall_ok():
    receipt = native_receipt()
    assert "ok" not in receipt and "status" not in receipt
    assert receipt["result"]["verification"]["passed"] is True
    assert evaluate_execution_receipt(receipt).status == "completed"


def test_business_payload_status_does_not_control_execution_state():
    worker = {
        "ok": True,
        "status": "completed",
        "result": {"status": "queued", "order": {"status": "error"}},
    }
    assert evaluate_execution_receipt(worker).status == "completed"
    native = native_receipt()
    native["result"]["outputs"][0]["response"] = {"status": "failed", "count": 3}
    assert evaluate_execution_receipt(native).status == "completed"


@pytest.mark.parametrize("terminal", [{"status": "completed"}, {"completed": True}])
def test_trusted_worker_explicit_terminal_contract(terminal):
    assert evaluate_execution_receipt({"ok": True, **terminal}).status == "completed"


@pytest.mark.parametrize(
    "kind", ["empty", "verification_unknown", "transport_only", "path_guard_unchecked"]
)
def test_unknown_receipts_preserve_budget_block_dependencies_and_cannot_replay(
    database, monkeypatch, kind
):
    decision_id = proposal(database, rows=[opportunity("a"), opportunity("b", depends_on=["a"])])
    portfolio.plan_portfolio(decision_id)
    task = runtime._claim(decision_id, 7)
    assert task["opportunity_id"] == "a"
    runtime._finish(task, corrupted_receipt(kind), 1)
    state = portfolio.portfolio_status(decision_id)
    saved = state["tasks"]["a"]
    assert saved["status"] == "unknown" and state["halted"]
    assert saved["completed_at"] is None and "b" not in state["tasks"]
    assert all(
        runtime._consumed(saved, resource) == saved["reservation"][resource]
        for resource in portfolio.RESOURCES
    )
    with database() as session:
        action = session.scalars(
            select(StrategicActionItem).where(
                StrategicActionItem.action_id == runtime._action_id(decision_id, "a")
            )
        ).one()
        assert action.status == "blocked" and action.completed_at is None
    with pytest.raises(portfolio.PortfolioError):
        runtime._claim(decision_id, 7)
    with pytest.raises(portfolio.PortfolioError):
        runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    monkeypatch.setattr(runtime, "_execute", lambda _task: pytest.fail("uncertain task replayed"))
    with pytest.raises(portfolio.PortfolioError):
        runtime.run_portfolio_cycle(decision_id)


def test_failed_handler_cannot_unlock_dependent_even_if_another_succeeded(database):
    decision_id = proposal(database, rows=[opportunity("a"), opportunity("b", depends_on=["a"])])
    portfolio.plan_portfolio(decision_id)
    task = runtime._claim(decision_id, 7)
    runtime._finish(task, corrupted_receipt("mixed_success_and_failure"), 1)
    state = portfolio.portfolio_status(decision_id)
    assert state["tasks"]["a"]["status"] == "failed" and "b" not in state["tasks"]
    if state["halted"]:
        with pytest.raises(portfolio.PortfolioError):
            runtime._claim(decision_id, 7)
    else:
        assert runtime._claim(decision_id, 7) is None


def test_unknown_receipt_cannot_claim_customer_payment_even_with_matching_artifact(
    database, monkeypatch
):
    from modstore_server import customer_value_payment_source
    from modstore_server.db.customer_value import CustomerValueReceipt

    decision_id = proposal(database, rows=[opportunity(customer_goal_ids=["goal-a"])])
    portfolio.plan_portfolio(decision_id)
    task = runtime._claim(decision_id, 7)
    runtime._finish(task, {"ok": True, "artifact_id": "artifact-a", "artifact_sha256": "b" * 64}, 1)
    moment = datetime.now(UTC)
    with database() as session:
        for kind in ("outcome", "acceptance"):
            session.add(
                CustomerValueReceipt(
                    receipt_id=f"unknown-{kind}",
                    receipt_kind=kind,
                    verification_status="verified",
                    customer_ref="paid-user:7",
                    customer_goal_id="goal-a",
                    order_no="real-payment",
                    artifact_id="artifact-a",
                    evidence_json=json.dumps({"artifact_sha256": "b" * 64}),
                    evidence_digest="c" * 64,
                    occurred_at=moment,
                    currency="CNY",
                    environment="production",
                )
            )
        session.commit()
    monkeypatch.setattr(
        customer_value_payment_source,
        "load_authoritative_payment_orders",
        lambda _days: {
            "source_available": True,
            "source_authoritative": True,
            "orders": [
                {
                    "out_trade_no": "real-payment",
                    "status": "paid",
                    "user_id": 7,
                    "amount_cents": 100,
                    "paid_at": moment.isoformat(),
                    "payment_provider": "alipay",
                    "provider_verification": "alipay_signed_callback",
                    "provider_trade_no": "provider-payment",
                    "environment": "production",
                }
            ],
        },
    )
    outcome = runtime._business_outcome(portfolio.portfolio_status(decision_id))
    assert outcome["revenue_cents"] == 0 and outcome["paid_order_count"] == 0


def test_async_control_fields_remain_pending_without_examining_business_payload():
    receipt = native_receipt()
    receipt["result"]["outputs"] = [
        {"handler": "durable_queue", "status": "queued", "job_id": "job-1"}
    ]
    assert evaluate_execution_receipt(receipt).status == "pending"
    receipt["result"]["outputs"].append({"handler": "other", "ok": False, "error": "failed"})
    assert evaluate_execution_receipt(receipt).status == "unknown"
    accepted = native_receipt()
    accepted["result"]["outputs"][0]["status_code"] = 202
    assert evaluate_execution_receipt(accepted).status == "pending"
    assert evaluate_execution_receipt({"ok": False, "queued": True}).status == "unknown"


def test_outer_execution_verification_cannot_be_overridden_by_inner_success():
    receipt = native_receipt()
    receipt["verification"] = {"passed": False}
    assert evaluate_execution_receipt(receipt).status == "failed"


@pytest.mark.parametrize("worker", [False, True])
@pytest.mark.parametrize("failure", ["no_receipt", "exception"])
def test_missing_or_interrupted_callback_receipt_never_releases_budget(
    database, monkeypatch, worker, failure
):
    from modstore_server import strategic_portfolio_usage as usage

    decision_id = proposal(database)

    def execute(_task):
        if failure == "exception":
            raise ConnectionError("completed operation may have lost its receipt")
        return None

    if worker:
        portfolio.plan_portfolio(decision_id)
        task = runtime._claim(decision_id, 7)
        with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
            binding = usage.bind_portfolio_worker("queue:unknown", owner_user_id=7)
        runtime._finish(task, {"status": "queued", "worker_receipt_id": "queue:unknown"}, 1)
        state = runtime.execute_portfolio_worker(binding, owner_user_id=7, execute=execute)
    else:
        monkeypatch.setattr(runtime, "_execute", execute)
        state = runtime.run_portfolio_cycle(decision_id)
    saved = state["tasks"]["a"]
    assert state["halted"] and saved["status"] == "unknown"
    assert runtime._consumed(saved, "cost_cents") == saved["reservation"]["cost_cents"]
