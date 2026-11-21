"""Original upstream accounting survives a lost ACK and a fresh scheduler tick."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text

from modstore_server import llm_key_resolver
from modstore_server import llm_usage_readback as source
from modstore_server import strategic_portfolio as p
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_portfolio_usage as usage
from modstore_server import strategic_usage_reconciliation as recovery
from tests import test_strategic_portfolio as base

database = base.database
MODEL = "approved-gateway-route"


@pytest.fixture
def gateway(database, tmp_path, monkeypatch):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    url = f"sqlite:///{tmp_path / 'upstream.db'}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                'CREATE TABLE "LiteLLM_AccountingEvent" (event_id TEXT PRIMARY KEY, kind TEXT, schema_version INTEGER, payload TEXT)'
            )
        )
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _: "sk-test-gateway")
    monkeypatch.setattr(llm_key_resolver, "platform_base_url", lambda _: "https://gateway.test/v1")
    monkeypatch.setattr(source, "ledger_source", lambda: (url, "isolated-upstream"))
    monkeypatch.setattr(source, "_accounting_engine", lambda _: create_engine(url))
    yield engine
    engine.dispose()


def admit(database):
    caps = base.limits()
    caps["tariffs"][0].update(provider="litellm", model=MODEL)
    decision_id, task = base.claim_proposal(database, caps=caps)
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        reservation = usage.prepare_platform_call("litellm", MODEL, [], 100)
        with usage.platform_call_reservation(reservation):
            usage.require_call_reservation(provider="litellm", model=MODEL, start_transport=True)
            headers = usage.transport_headers("litellm")
            assert headers == {"x-litellm-call-id": reservation["request_id"]}
        usage.complete_platform_call(reservation, None)
    call = p.portfolio_status(decision_id)["tasks"]["a"]["calls"][reservation["request_id"]]
    return decision_id, task, reservation, call["transport_binding"]


def upstream_events(binding, *, prompt=12, completion=7):
    # Use the actual pinned upstream writer contract, not an invented receipt.
    from litellm.proxy.spend_tracking.usage_capture import (
        UsageCaptureContext,
        usage_writes,
    )

    now = datetime.now(UTC)
    context = UsageCaptureContext(
        caller_id=binding["request_id"],
        attempt_id="original-provider-response",
        parent_request_id=None,
        retry_of_attempt_id=None,
        job_id=None,
        charge_eligible=True,
        request_count_eligible=True,
        ownership="attempt",
        pricing="{}",
    )
    payload = {
        "request_tags": "[]",
        "status": "success",
        "startTime": now,
        "endTime": now,
        "call_type": "acompletion",
        "api_key": binding["credential_sha256"],
        "model_group": MODEL,
        "model": "provider-model",
        "custom_llm_provider": "openai",
    }
    writes = usage_writes(
        payload,
        json.dumps(
            {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
            }
        ),
        context,
    )
    return [
        {
            "event_id": item.event.event_id,
            "kind": "inbound_usage" if index == 0 else "outbound_usage",
            "schema_version": 1,
            "payload": json.loads(item.envelope),
        }
        for index, item in enumerate(writes)
    ]


def persist(engine, events):
    with engine.begin() as connection:
        for event in events:
            connection.execute(
                text(
                    'INSERT INTO "LiteLLM_AccountingEvent" VALUES (:event_id, :kind, :schema_version, :payload)'
                ),
                {**event, "payload": json.dumps(event["payload"])},
            )


def test_lost_ack_settles_original_usage_and_original_execution_without_replay(
    database, gateway, monkeypatch
):
    decision_id, task, held, binding = admit(database)
    runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    assert p.portfolio_status(decision_id)["tasks"]["a"]["status"] == "unknown"
    persist(gateway, upstream_events(binding))
    assert source.read_usage(binding) is not None
    monkeypatch.setattr(runtime, "_execute", lambda *_: pytest.fail("replayed employee"))
    assert recovery.reconcile_pending_usage() == {"checked": 1, "settled": 1}
    state = p.portfolio_status(decision_id)
    saved = state["tasks"]["a"]
    assert saved["status"] == "completed"
    assert saved["actual_tokens"] == 19
    assert saved["calls"][held["request_id"]]["readback"]["source"] == "litellm_accounting_v1"
    assert state["halted"] is False
    assert recovery.reconcile_pending_usage()["settled"] == 0
    assert runtime.run_portfolio_cycle(decision_id)["processed"] == 0


@pytest.mark.parametrize(
    "corruption",
    [
        "estimated",
        "unknown",
        "other_key",
        "other_model",
        "missing_inbound",
        "extra_attempt",
        "wrong_request",
        "changed_usage",
        "bool_tokens",
        "retry",
        "aggregate",
    ],
)
def test_untrusted_or_incomplete_evidence_keeps_original_hold(database, gateway, corruption):
    decision_id, _, held, binding = admit(database)
    events = upstream_events(binding)
    envelope = events[1]["payload"]
    if corruption in {"estimated", "unknown"}:
        envelope["usage_source"] = corruption
    elif corruption in {"other_key", "other_model"}:
        name = "key" if corruption == "other_key" else "model_group"
        for event in events:
            next(
                value for value in event["payload"]["event"]["dimensions"] if value["name"] == name
            )["value"] = "unrelated"
    elif corruption == "missing_inbound":
        events = events[1:]
    elif corruption == "extra_attempt":
        extra = deepcopy(events[1])
        extra["event_id"] = extra["payload"]["event"]["event_id"] = "another-attempt"
        events.append(extra)
    elif corruption == "wrong_request":
        envelope["event"]["request_id"] = "unrelated"
    elif corruption == "changed_usage":
        envelope["usage"]["prompt_tokens"] = 11
        envelope["usage"]["total_tokens"] = 18
    elif corruption == "bool_tokens":
        envelope["usage"]["prompt_tokens"] = True
    elif corruption == "retry":
        envelope["event"]["retry_of_attempt_id"] = "earlier-paid-attempt"
    elif corruption == "aggregate":
        envelope["ownership"] = "aggregate"
    persist(gateway, events)
    assert recovery.reconcile_pending_usage()["settled"] == 0
    call = p.portfolio_status(decision_id)["tasks"]["a"]["calls"][held["request_id"]]
    assert call["status"] == "unknown"
    assert "actual_tokens" not in call


def test_accounting_does_not_claim_unknown_business_success(database, gateway):
    decision_id, task, held, binding = admit(database)
    runtime._finish(task, {"ok": False, "status": "dispatch_unknown"}, 1)
    persist(gateway, upstream_events(binding))
    assert recovery.reconcile_pending_usage()["settled"] == 1
    saved = p.portfolio_status(decision_id)["tasks"]["a"]
    assert saved["calls"][held["request_id"]]["status"] == "settled"
    assert saved["status"] == "unknown"
    assert p.portfolio_status(decision_id)["halted"] is True


def test_readback_after_revocation_settles_cost_without_renewing_authority(database, gateway):
    decision_id, task, _, binding = admit(database)
    runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    p.stop_portfolio(decision_id, owner_user_id=7, actor="admin:7", reason="operator veto")
    persist(gateway, upstream_events(binding))
    assert recovery.reconcile_pending_usage()["settled"] == 1
    state = p.portfolio_status(decision_id)
    assert state["halted"] and state["stop_reason"] == "operator veto"
    assert state["tasks"]["a"]["actual_tokens"] == 19


def test_concurrent_readback_discharges_one_reservation(database, gateway):
    decision_id, task, _, binding = admit(database)
    runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    persist(gateway, upstream_events(binding))
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: recovery.reconcile_pending_usage(), range(2)))
    assert sum(item["settled"] for item in results) == 1
    assert p.portfolio_status(decision_id)["tasks"]["a"]["actual_tokens"] == 19


def test_planning_readback_releases_original_single_call_slot(database, gateway):
    from sqlalchemy import select

    from modstore_server.db.llm_chat import LlmClientRequest

    base.seed_owner(database)
    budget = base.planning_budget(provider="litellm", model=MODEL)
    with usage.planning_usage_scope(7, budget):
        held = usage.prepare_platform_call("litellm", MODEL, [], 100)
        with usage.platform_call_reservation(held):
            usage.require_call_reservation(provider="litellm", model=MODEL, start_transport=True)
        usage.complete_platform_call(held, None)
    with database() as session:
        row = session.scalar(
            select(LlmClientRequest).where(LlmClientRequest.client_request_id == held["request_id"])
        )
        binding = json.loads(row.done_json)["transport_binding"]
    persist(gateway, upstream_events(binding))
    assert recovery.reconcile_pending_usage()["settled"] == 1
    with database() as session:
        row = session.scalar(
            select(LlmClientRequest).where(
                LlmClientRequest.client_request_id == "strategy-planning-slot"
            )
        )
        assert row.state == "completed"
        assert json.loads(row.done_json)["actual_tokens"] == 19
    with usage.planning_usage_scope(7, budget):
        assert usage.prepare_platform_call("litellm", MODEL, [], 100)


def test_changed_transport_identity_does_not_discharge_hold(database, gateway):
    decision_id, _, held, binding = admit(database)
    persist(gateway, upstream_events(binding))

    def corrupt(_row, _proposal, state, _session):
        state["tasks"]["a"]["calls"][held["request_id"]]["transport_binding"]["owner_user_id"] = 8

    p.mutate_portfolio(decision_id, corrupt)
    assert recovery.reconcile_pending_usage()["settled"] == 0
    assert (
        p.portfolio_status(decision_id)["tasks"]["a"]["calls"][held["request_id"]]["status"]
        == "unknown"
    )


def test_measured_overrun_is_accounted_and_does_not_reopen_spending(database, gateway):
    decision_id, task, _, binding = admit(database)
    runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    persist(gateway, upstream_events(binding, prompt=100_000))
    assert recovery.reconcile_pending_usage()["settled"] == 1
    state = p.portfolio_status(decision_id)
    assert state["tasks"]["a"]["actual_tokens"] == 100_007
    assert state["halted"] and state["stop_reason"] == "upstream_usage_exceeded_reservation"


def test_scheduler_waits_for_usage_without_withdrawing_original_mandate(
    database, gateway, monkeypatch
):
    from modstore_server import strategic_portfolio_scheduler as scheduler
    from modstore_server import strategic_remote_receipts

    decision_id, task, _, _ = admit(database)
    runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: database)
    monkeypatch.setattr(strategic_remote_receipts, "reconcile_pending_reports", lambda **_: {})
    result = scheduler.tick()
    assert result["results"] == [{"decision_id": decision_id, "status": "waiting_for_usage"}]
    assert p.portfolio_status(decision_id)["status"] == "executing"
