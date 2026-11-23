"""Original native accounting and original delivery must finish the same remote work."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest

from modstore_server import llm_key_resolver
from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_portfolio_scheduler as scheduler
from modstore_server import strategic_portfolio_usage as usage
from modstore_server import strategic_remote_bridge as remote
from modstore_server import strategic_remote_receipts as receipts
from modstore_server import strategic_usage_reconciliation as recovery
from tests import test_strategic_company_resources as company
from tests import test_strategic_portfolio as base
from tests import test_strategic_remote_bridge as reports
from tests import test_strategic_usage_reconciliation as accounting
from tests import test_strategic_workspace_bridge as engineering
from tests.test_strategic_responses import _http, _payload

database = base.database
configured = company.configured
upstream_master = accounting.upstream_master
gateway = accounting.gateway


@pytest.fixture(params=["report", "workspace"])
def original_remote(request, database, gateway, monkeypatch):
    """Select the native gateway before the existing approval/dispatch fixtures run."""
    # Load the real native writer before the artifact HTTP test transport is
    # installed; LiteLLM evaluates httpx.Client annotations on import.
    import_module("litellm.proxy.spend_tracking.usage_capture")
    original_opportunity, original_limits, original_budget = (
        base.opportunity,
        base.limits,
        company.budget,
    )

    def opportunity(*args, **kwargs):
        row = original_opportunity(*args, **kwargs)
        row["input_data"]["remote_execution"]["provider"] = "litellm"
        return row

    def limits(**kwargs):
        caps = original_limits(**kwargs)
        caps["tariffs"] = [{**item, "provider": "litellm"} for item in caps["tariffs"]]
        return caps

    def budget(factory, **kwargs):
        kwargs["tariffs"] = [{**item, "provider": "litellm"} for item in kwargs["tariffs"]]
        return original_budget(factory, **kwargs)

    monkeypatch.setattr(base, "opportunity", opportunity)
    monkeypatch.setattr(base, "limits", limits)
    monkeypatch.setattr(company, "budget", budget)
    monkeypatch.setattr(accounting, "MODEL", "approved-model")
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: database)
    platform_api_key = llm_key_resolver.platform_api_key
    platform_base_url = llm_key_resolver.platform_base_url
    kind = request.param
    fixture = (
        engineering.workspace.__wrapped__(request.getfixturevalue("configured"), monkeypatch)
        if kind == "workspace"
        else reports.remote.__wrapped__(database, monkeypatch)
    )
    with_fixture = next(fixture)
    try:
        monkeypatch.setattr(llm_key_resolver, "platform_api_key", platform_api_key)
        monkeypatch.setattr(llm_key_resolver, "platform_base_url", platform_base_url)
        with_fixture.kind = kind
        if kind == "workspace":
            with_fixture.allocation["provider"] = "litellm"
            engineering.start(with_fixture)
        else:
            reports.claim(with_fixture)
        yield with_fixture
    finally:
        fixture.close()


def model_call(work, monkeypatch, *, meter="absent"):
    saved = portfolio.portfolio_status(work.decision_id)["tasks"]["a"]
    seen = _http(
        monkeypatch,
        (work.decision_id, saved),
        meter=meter,
        provider="litellm",
        headers={"x-litellm-attempted-retries": "0", "x-litellm-attempted-fallbacks": "0"},
    )
    response = work.client.post(
        work.control + "/v1/responses", json=_payload(), headers=work.model_headers
    )
    assert response.status_code == 200, response.text
    call = next(iter(portfolio.portfolio_status(work.decision_id)["tasks"]["a"]["calls"].values()))
    binding = call["transport_binding"]
    assert seen["requests"][0].headers["x-litellm-call-id"] == binding["request_id"]
    assert binding["provider"] == "litellm" and binding["model"] == "approved-model"
    return binding, seen


def publish_original_terminal(work, monkeypatch):
    if work.kind == "workspace":
        work.github.phase("completed")
        engineering.original_terminal(work)
    else:
        work.github.publish(reports.notify(work))
        reports.download_transport(work, monkeypatch)


@pytest.mark.parametrize("stopped", [False, True])
def test_late_native_accounting_finishes_original_remote_without_replay(
    original_remote, gateway, monkeypatch, stopped
):
    work = original_remote
    binding, seen = model_call(work, monkeypatch)
    publish_original_terminal(work, monkeypatch)
    if stopped:
        portfolio.stop_portfolio(
            work.decision_id,
            owner_user_id=7,
            actor="admin:7",
            reason="operator veto while awaiting original accounting",
        )
    before = portfolio.portfolio_status(work.decision_id)
    saved = deepcopy(before["tasks"]["a"])
    original_request = remote.read_request(work.request_id)
    held = company.totals(work.company_id) if work.kind == "workspace" else None
    assert saved["status"] == "running"
    assert saved["actual_tokens"] == 0
    assert not receipts.reconcile_request(work.request_id)
    # No terminal receipt, guessed actual amount or failed remote may replace
    # the original running task while the gateway still owes an exact bill.
    after = portfolio.portfolio_status(work.decision_id)
    assert after["tasks"]["a"] == saved
    assert after["stop_reason"] == before["stop_reason"]
    assert remote.read_request(work.request_id) == original_request
    if held is not None:
        assert company.totals(work.company_id) == held
    assert recovery.reconcile_pending_usage()["settled"] == 0

    accounting.persist(gateway, accounting.upstream_events(binding))
    monkeypatch.setattr(runtime, "_execute", lambda *_: pytest.fail("replayed employee"))
    # The real scheduler calls the independent accounting reader and then the
    # original report/workspace reader, including for a withdrawn mandate.
    scheduler.tick()
    completed = portfolio.portfolio_status(work.decision_id)["tasks"]["a"]
    assert completed["status"] == "completed"
    assert completed["actual_tokens"] == 19
    assert completed["lease_token"] == saved["lease_token"]
    assert completed["worker_binding"] == saved["worker_binding"]
    call = completed["calls"][binding["request_id"]]
    assert call["status"] == "settled"
    assert call["readback"]["source"] == "litellm_accounting_v1"
    assert remote.read_request(work.request_id)[2] == "execution_completed"
    if work.kind == "workspace":
        assert completed["execution_receipt"]["artifact_sha256"] == "f" * 64
        assert company.totals(work.company_id)["slots"] == 0
    else:
        assert (
            completed["execution_receipt"]["remote_receipt"]["archive_digest"]
            == work.github.artifact["digest"]
        )
    scheduler.tick()
    state = portfolio.portfolio_status(work.decision_id)
    assert state["tasks"]["a"] == completed
    assert state["halted"] is stopped
    if stopped:
        assert state["stop_reason"] == before["stop_reason"]
        assert state["status"] == "withdrawn"
        assert (
            work.client.get(work.control + "/v1/models", headers=work.model_headers).status_code
            == 409
        )
    assert len(seen["requests"]) == len(work.github.writes) == 1
    assert recovery.reconcile_pending_usage()["settled"] == 0
    assert not receipts.reconcile_request(work.request_id)


def test_native_accounting_without_independent_terminal_does_not_claim_success(
    original_remote, gateway, monkeypatch
):
    work = original_remote
    binding, seen = model_call(work, monkeypatch)
    accounting.persist(gateway, accounting.upstream_events(binding))
    monkeypatch.setattr(runtime, "_execute", lambda *_: pytest.fail("replayed employee"))
    scheduler.tick()
    saved = portfolio.portfolio_status(work.decision_id)["tasks"]["a"]
    assert saved["actual_tokens"] == 19
    assert saved["status"] == "running"
    assert remote.read_request(work.request_id)[2] not in {"failed", "execution_completed"}
    assert len(seen["requests"]) == len(work.github.writes) == 1


@pytest.mark.parametrize("original_remote", ["workspace"], indirect=True)
def test_late_accounting_cannot_erase_native_compute_overrun(original_remote, gateway, monkeypatch):
    work = original_remote
    binding, seen = model_call(work, monkeypatch)
    publish_original_terminal(work, monkeypatch)
    work.github.jobs[0]["started_at"] = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
    accounting.persist(gateway, accounting.upstream_events(binding))
    scheduler.tick()
    state = portfolio.portfolio_status(work.decision_id)
    assert state["tasks"]["a"]["status"] == "completed"
    assert (
        state["tasks"]["a"]["compute_seconds"]
        > state["tasks"]["a"]["reservation"]["compute_seconds"]
    )
    assert state["halted"] and state["stop_reason"] == "compute_budget_exceeded"
    scheduler.tick()
    state = portfolio.portfolio_status(work.decision_id)
    assert state["halted"] and state["stop_reason"] == "compute_budget_exceeded"
    assert len(seen["requests"]) == len(work.github.writes) == 1


@pytest.mark.parametrize("original_remote", ["report"], indirect=True)
def test_call_admitted_during_artifact_readback_is_checked_inside_terminal_transaction(
    original_remote, monkeypatch
):
    work = original_remote
    _, seen = model_call(work, monkeypatch, meter="reported")
    publish_original_terminal(work, monkeypatch)
    finish = runtime._finish
    held = {}

    def concurrent_admission(task, result, elapsed, **kwargs):
        # The report reader already observed settled calls. An authorized
        # original worker admits one more call before the terminal CAS starts.
        with usage.portfolio_usage_scope(work.decision_id, "a", task["lease_token"]):
            held.update(usage.prepare_platform_call("litellm", "approved-model", [], 20))
        assert finish(task, result, elapsed, **kwargs) is None

    monkeypatch.setattr(runtime, "_finish", concurrent_admission)
    receipts.reconcile_request(work.request_id)
    saved = portfolio.portfolio_status(work.decision_id)["tasks"]["a"]
    assert saved["status"] == "running"
    assert saved["calls"][held["request_id"]]["status"] == "pending"
    assert remote.read_request(work.request_id)[2] == "reported"
    assert "artifact_sha256" not in saved.get("execution_receipt", {})
    assert len(seen["requests"]) == len(work.github.writes) == 1
