"""Original upstream accounting survives a lost ACK and a fresh scheduler tick."""

from __future__ import annotations

import asyncio
import json
import secrets
import warnings
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, text

from modstore_server import llm_key_resolver
from modstore_server import llm_usage_readback as source
from modstore_server import strategic_portfolio as p
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_portfolio_usage as usage
from modstore_server import strategic_usage_reconciliation as recovery
from modstore_server.db.strategic import StrategicDecision
from tests import test_strategic_portfolio as base

database = base.database
MODEL = "approved-gateway-route"


@pytest.fixture
def upstream_master(tmp_path, monkeypatch):
    """Use the upstream master authenticator with isolated local configuration."""
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    monkeypatch.setenv("MODSTORE_DATA_DIR", str(tmp_path / "platform-config"))
    monkeypatch.setenv("LITELLM_UI_PATH", str(tmp_path / "upstream-ui"))
    key = "sk-" + secrets.token_urlsafe(32)
    monkeypatch.setenv("LITELLM_MASTER_KEY", key)
    monkeypatch.delenv("XCMAX_LITELLM_MASTER_KEY", raising=False)
    monkeypatch.setenv("LITELLM_BASE_URL", "https://gateway.test/v1")
    # Account for the pinned proxy's Swagger Field(example=...) and UI scan
    # warnings at import, retaining the suite's warning errors everywhere else.
    from pydantic.warnings import PydanticDeprecatedSince20

    with warnings.catch_warnings(record=True) as upstream_warnings:
        warnings.filterwarnings(
            "always",
            message="Using extra keyword arguments on `Field`",
            category=PydanticDeprecatedSince20,
            module=r"litellm\.proxy\.common_utils\.swagger_utils",
        )
        warnings.filterwarnings(
            "always",
            message="unclosed scandir iterator",
            category=ResourceWarning,
            module=r"litellm\.proxy\.proxy_server",
        )
        from litellm.proxy import proxy_server
    assert all(
        (
            item.filename.endswith("litellm/proxy/common_utils/swagger_utils.py")
            and isinstance(item.message, PydanticDeprecatedSince20)
        )
        or (
            item.filename.endswith("litellm/proxy/proxy_server.py")
            and isinstance(item.message, ResourceWarning)
            and str(item.message).startswith("unclosed scandir iterator")
        )
        for item in upstream_warnings
    )
    from litellm.proxy.common_utils.user_api_key_cache import UserApiKeyCache

    for name, value in {
        "master_key": key,
        "general_settings": {},
        "user_api_key_cache": UserApiKeyCache(),
        "prisma_client": None,
        "llm_router": None,
        "user_custom_auth": None,
        "open_telemetry_logger": None,
    }.items():
        monkeypatch.setattr(proxy_server, name, value)
    return proxy_server


@pytest.fixture
def gateway(database, tmp_path, monkeypatch, upstream_master):
    url = f"sqlite:///{tmp_path / 'upstream.db'}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                'CREATE TABLE "LiteLLM_AccountingEvent" (event_id TEXT PRIMARY KEY, kind TEXT, schema_version INTEGER, payload TEXT)'
            )
        )
    monkeypatch.setattr(source, "ledger_source", lambda: (url, "isolated-upstream"))
    monkeypatch.setattr(source, "_accounting_engine", lambda _: create_engine(url))
    yield engine
    engine.dispose()


def admit(database, *, key="one"):
    caps = base.limits()
    caps["tariffs"][0].update(provider="litellm", model=MODEL)
    base.seed_owner(database)
    proposed = p.create_portfolio_proposal(
        owner_user_id=7,
        goal="Improve delivery",
        period="2026-Q4",
        limits=caps,
        opportunities=[base.opportunity()],
        idempotency_key=key,
    )
    decision_id = proposed["decision"]["decision_id"]
    p.authorize_portfolio(
        decision_id,
        owner_user_id=7,
        actor="admin:7",
        expected_proposal_sha256=proposed["decision"]["decision_payload"]["proposal_sha256"],
    )
    p.plan_portfolio(decision_id)
    task = runtime._claim(decision_id, 7)
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        reservation = usage.prepare_platform_call("litellm", MODEL, [], 100)
        with usage.platform_call_reservation(reservation):
            usage.require_call_reservation(provider="litellm", model=MODEL, start_transport=True)
            headers = usage.transport_headers("litellm")
            assert headers == {"x-litellm-call-id": reservation["request_id"]}
        usage.complete_platform_call(reservation, None)
    call = p.portfolio_status(decision_id)["tasks"]["a"]["calls"][reservation["request_id"]]
    return decision_id, task, reservation, call["transport_binding"]


async def authenticate_gateway(key=None):
    from litellm.proxy.auth.user_api_key_auth import user_api_key_auth_builder
    from starlette.requests import Request

    key = llm_key_resolver.platform_api_key("litellm") if key is None else key
    body = json.dumps({"model": MODEL, "messages": []}).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "path": "/v1/chat/completions",
            "headers": [(b"authorization", f"Bearer {key}".encode())],
            "query_string": b"",
            "scheme": "https",
            "server": ("gateway.test", 443),
            "client": ("127.0.0.1", 1234),
        },
        receive,
    )
    authenticated = await user_api_key_auth_builder(
        request=request,
        api_key=f"Bearer {key}",
        azure_api_key_header=None,
        anthropic_api_key_header=None,
        google_ai_studio_api_key_header=None,
        azure_apim_header=None,
        request_data={"model": MODEL},
    )
    # Finish the upstream's local auth-cache and service-log tasks in this loop.
    await asyncio.sleep(0)
    return authenticated


def upstream_events(binding, *, prompt=12, completion=7, attempt_id="original-provider-response"):
    # Derive the spend identity from real authentication, never from the binding.
    from litellm.proxy.litellm_pre_call_utils import LiteLLMProxyRequestSetup
    from litellm.proxy.spend_tracking.spend_tracking_utils import get_logging_payload
    from litellm.proxy.spend_tracking.usage_capture import (
        UsageCaptureContext,
        usage_writes,
    )

    now = datetime.now(UTC)
    context = UsageCaptureContext(
        caller_id=binding["request_id"],
        attempt_id=attempt_id,
        parent_request_id=None,
        retry_of_attempt_id=None,
        job_id=None,
        charge_eligible=True,
        request_count_eligible=True,
        ownership="attempt",
        pricing="{}",
    )
    authenticated = asyncio.run(authenticate_gateway())
    data = LiteLLMProxyRequestSetup.add_user_api_key_auth_to_request_metadata(
        {"metadata": {"model_group": MODEL}}, authenticated, "metadata"
    )
    captured = []
    get_logging_payload(
        {
            "call_type": "acompletion",
            "model": "provider-model",
            "litellm_params": {"metadata": data["metadata"], "custom_llm_provider": "openai"},
        },
        {
            "id": context.attempt_id,
            "model": "provider-model",
            "usage": {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
            },
        },
        now,
        now,
        capture_usage=lambda payload, usage_json: captured.extend(
            usage_writes(payload, usage_json, context)
        ),
    )
    return [
        {
            "event_id": item.event.event_id,
            "kind": "inbound_usage" if index == 0 else "outbound_usage",
            "schema_version": 1,
            "payload": json.loads(item.envelope),
        }
        for index, item in enumerate(captured)
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


@pytest.mark.parametrize("matching_count", [2, 4])
def test_accounting_query_keeps_json_dialect_and_original_request_limit(
    tmp_path, monkeypatch, matching_count
):
    from sqlalchemy import event
    from sqlalchemy.dialects import postgresql, sqlite

    url = f"sqlite:///{tmp_path / 'query.db'}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                'CREATE TABLE "LiteLLM_AccountingEvent" '
                "(event_id TEXT PRIMARY KEY, kind TEXT, schema_version INTEGER, payload TEXT)"
            )
        )
    request_id = "original-accounting-request"
    rows = [
        ("unrelated", "outbound_usage", "other-request"),
        ("other-kind", "cost", request_id),
        *(
            (f"original-{index}", "outbound_usage" if index else "inbound_usage", request_id)
            for index in range(matching_count)
        ),
    ]
    persist(
        engine,
        [
            {
                "event_id": identity,
                "kind": kind,
                "schema_version": 1,
                "payload": {"event": {"request_id": original}},
            }
            for identity, kind, original in rows
        ],
    )
    statements = []
    event.listen(
        engine,
        "before_execute",
        lambda _conn, statement, _many, _params, _options: statements.append(statement),
    )
    monkeypatch.setattr(source, "ledger_source", lambda: (url, "query-source"))
    monkeypatch.setattr(source, "_accounting_engine", lambda _: engine)
    found = source._events({"request_id": request_id, "ledger_source_sha256": "query-source"})
    assert len(found) == min(matching_count, 3)
    assert {row["event_id"] for row in found} <= {
        f"original-{index}" for index in range(matching_count)
    }
    assert all(row["kind"] in {"inbound_usage", "outbound_usage"} for row in found)
    assert len(statements) == 1
    # The same executed query must retain JSON1 support on older SQLite,
    # while the production PostgreSQL source extracts a parameterized text ID.
    sqlite_query = statements[0].compile(dialect=sqlite.dialect())
    assert "->" not in str(sqlite_query)
    pg_query = statements[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"render_postcompile": True}
    )
    assert "->>" in str(pg_query) and "JSON_EXTRACT" not in str(pg_query)
    assert request_id not in str(pg_query)
    assert {"event", "request_id", request_id, "inbound_usage", "outbound_usage", 3} <= set(
        pg_query.params.values()
    )


def test_lost_ack_settles_original_usage_and_original_execution_without_replay(
    database, gateway, monkeypatch
):
    from litellm.constants import LITELLM_PROXY_MASTER_KEY_ALIAS

    decision_id, task, held, binding = admit(database)
    assert binding["accounting_identity_scheme"] == "litellm_master_alias_v1"
    assert binding["accounting_identity"] == LITELLM_PROXY_MASTER_KEY_ALIAS
    assert "credential_sha256" not in binding
    assert str(llm_key_resolver.platform_api_key("litellm")) not in json.dumps(binding)
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
    "credential", ["sk-incorrect-master", "litellm_proxy_master_key", "a" * 64]
)
def test_upstream_authentication_rejects_alias_digest_and_wrong_bearer(upstream_master, credential):
    from litellm.proxy._types import ProxyException

    with pytest.raises(ProxyException):
        asyncio.run(authenticate_gateway(credential))


@pytest.mark.parametrize("configuration", ["plain", "stored", "other_provider", "missing"])
def test_admission_requires_the_environment_master_snapshot(
    upstream_master, monkeypatch, configuration
):
    from modstore_server.platform_model_config import PlatformApiKey

    original = llm_key_resolver.platform_api_key("litellm")
    if configuration == "missing":
        rejected = None
    elif configuration == "plain":
        rejected = original.encode().decode()
    else:
        snapshot = dict(original.configuration)
        snapshot["source" if configuration == "stored" else "provider"] = (
            "stored" if configuration == "stored" else "openai"
        )
        rejected = PlatformApiKey(original, snapshot)
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _: rejected)
    with pytest.raises(p.PortfolioError):
        source.transport_identity("litellm")


def test_server_master_environment_alias_keeps_the_same_contract(upstream_master, monkeypatch):
    monkeypatch.delenv("LITELLM_MASTER_KEY")
    monkeypatch.setenv("XCMAX_LITELLM_MASTER_KEY", upstream_master.master_key)
    identity = source.transport_identity("litellm")
    authenticated = asyncio.run(authenticate_gateway())
    assert identity["accounting_identity"] == authenticated.api_key
    assert authenticated.via_virtual_key is True


@pytest.mark.parametrize(
    "change",
    [
        {"accounting_identity_scheme": "litellm_master_alias_v2"},
        {"accounting_identity_scheme": None},
        {"accounting_identity": "some_other_alias"},
        {"accounting_identity": "a" * 64},
        {"credential_sha256": "a" * 64},
        {"credential_sha256": None},
        {"remove": "accounting_identity_scheme"},
        {"remove": "accounting_identity"},
    ],
)
def test_ambiguous_or_unknown_identity_protocol_cannot_settle(database, gateway, change):
    decision_id, _, held, binding = admit(database)
    persist(gateway, upstream_events(binding))
    changed = {**binding, **change}
    if "remove" in changed:
        changed.pop(changed.pop("remove"))

    def historical_record(_row, _proposal, state, _session):
        call = state["tasks"]["a"]["calls"][held["request_id"]]
        call.update(transport_binding=changed, transport_binding_sha256=p.digest(changed))

    p.mutate_portfolio(decision_id, historical_record)
    assert source.read_usage(changed) is None
    assert recovery.reconcile_pending_usage()["settled"] == 0
    call = p.portfolio_status(decision_id)["tasks"]["a"]["calls"][held["request_id"]]
    assert call["status"] == "unknown" and "actual_tokens" not in call


@pytest.mark.parametrize("archived_identity", ["original", "different", "master_alias"])
def test_historical_hash_binding_requires_its_original_archived_identity(
    database, gateway, monkeypatch, archived_identity
):
    decision_id, _, held, binding = admit(database)
    events = upstream_events(binding)
    historical = {
        key: value
        for key, value in binding.items()
        if key not in {"accounting_identity_scheme", "accounting_identity"}
    }
    # A pre-upgrade stored binding and its archived ledger share this original
    # value. It is not recalculated from today's master or reinterpreted as one.
    historical["credential_sha256"] = "e" * 64
    if archived_identity != "master_alias":
        old_key = historical["credential_sha256"] if archived_identity == "original" else "f" * 64
        for event in events:
            next(item for item in event["payload"]["event"]["dimensions"] if item["name"] == "key")[
                "value"
            ] = old_key

    def historical_record(_row, _proposal, state, _session):
        call = state["tasks"]["a"]["calls"][held["request_id"]]
        call.update(transport_binding=historical, transport_binding_sha256=p.digest(historical))

    p.mutate_portfolio(decision_id, historical_record)
    persist(gateway, events)
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-" + secrets.token_urlsafe(32))
    monkeypatch.setattr(runtime, "_execute", lambda *_: pytest.fail("replayed employee"))
    assert recovery.reconcile_pending_usage()["settled"] == (archived_identity == "original")
    call = p.portfolio_status(decision_id)["tasks"]["a"]["calls"][held["request_id"]]
    assert call["transport_binding"] == historical
    assert call["transport_binding_sha256"] == p.digest(historical)
    assert call["status"] == ("settled" if archived_identity == "original" else "unknown")
    assert recovery.reconcile_pending_usage()["settled"] == 0


@pytest.mark.parametrize("legacy_identity", [None, "", "E" * 64, "a" * 63, "g" * 64])
def test_malformed_historical_identity_remains_unresolved(upstream_master, legacy_identity):
    assert source.read_usage({"provider": "litellm", "credential_sha256": legacy_identity}) is None


def test_master_rotation_preserves_original_binding_and_late_accounting(
    database, gateway, upstream_master, monkeypatch
):
    decision_id, _, held, binding = admit(database)
    original = deepcopy(binding)
    persist(gateway, upstream_events(binding))
    replacement = "sk-" + secrets.token_urlsafe(32)
    monkeypatch.setenv("LITELLM_MASTER_KEY", replacement)
    monkeypatch.setattr(upstream_master, "master_key", replacement)
    monkeypatch.setattr(runtime, "_execute", lambda *_: pytest.fail("replayed employee"))
    assert recovery.reconcile_pending_usage()["settled"] == 1
    call = p.portfolio_status(decision_id)["tasks"]["a"]["calls"][held["request_id"]]
    assert call["transport_binding"] == original
    assert call["transport_binding_sha256"] == p.digest(original)
    assert call["actual_tokens"] == 19
    assert recovery.reconcile_pending_usage()["settled"] == 0


@pytest.mark.parametrize("changed", ["endpoint", "ledger"])
def test_changed_gateway_or_ledger_does_not_attribute_original_usage(
    database, gateway, monkeypatch, changed
):
    decision_id, _, held, binding = admit(database)
    persist(gateway, upstream_events(binding))
    if changed == "endpoint":
        monkeypatch.setenv("LITELLM_BASE_URL", "https://another-gateway.test/v1")
    else:
        monkeypatch.setattr(source, "ledger_source", lambda: (str(gateway.url), "another-ledger"))
    assert recovery.reconcile_pending_usage()["settled"] == 0
    call = p.portfolio_status(decision_id)["tasks"]["a"]["calls"][held["request_id"]]
    assert call["status"] == "unknown" and "actual_tokens" not in call


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
        "different_attempt_identity",
        "different_caller_identity",
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
    elif corruption == "different_attempt_identity":
        envelope["event"]["attempt_id"] = "unrelated-provider-response"
    elif corruption == "different_caller_identity":
        events[0]["event_id"] = events[0]["payload"]["event"]["event_id"] = "unrelated-caller"
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


def test_invalid_earlier_portfolio_does_not_block_other_original_usage(database, gateway):
    decision_id, _, _, binding = admit(database)
    persist(gateway, upstream_events(binding))
    invalid = '{"transport_binding":'
    with database() as session:
        session.add(
            StrategicDecision(
                decision_id="old-invalid-ledger",
                title="原账本损坏待核对",
                proposed_by="admin:7",
                scope="strategy_portfolio",
                execution_result_json=invalid,
                updated_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        session.commit()
    assert recovery.reconcile_pending_usage() == {"checked": 1, "settled": 1}
    assert p.portfolio_status(decision_id)["tasks"]["a"]["actual_tokens"] == 19
    with database() as session:
        assert (
            session.scalar(
                select(StrategicDecision.execution_result_json).where(
                    StrategicDecision.decision_id == "old-invalid-ledger"
                )
            )
            == invalid
        )


@pytest.mark.parametrize("field", ["started_at", "deadline"])
@pytest.mark.parametrize(
    "invalid", [None, 17, [], {}, "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"]
)
def test_malformed_original_time_preserves_hold_without_blocking_later_call(
    database, gateway, field, invalid
):
    first, _, held, binding = admit(database, key="malformed")
    second, _, _, valid = admit(database, key="valid")
    malformed = {**binding, field: invalid}

    def corrupt(_row, _proposal, state, _session):
        call = state["tasks"]["a"]["calls"][held["request_id"]]
        call.update(
            status="pending" if field == "deadline" else "unknown",
            transport_binding=malformed,
            transport_binding_sha256=p.digest(malformed),
        )

    p.mutate_portfolio(first, corrupt)
    with database() as session:
        row = session.scalar(
            select(StrategicDecision).where(StrategicDecision.decision_id == first)
        )
        row.updated_at = datetime.now(UTC) - timedelta(days=1)
        session.commit()
    before = p.portfolio_status(first)["tasks"]["a"]["calls"][held["request_id"]]
    persist(gateway, upstream_events(binding))
    persist(gateway, upstream_events(valid, attempt_id="second-provider-response"))

    if field == "started_at":
        assert source.read_usage(malformed) is None
    assert recovery.reconcile_pending_usage()["settled"] == 1
    after = p.portfolio_status(first)["tasks"]["a"]["calls"][held["request_id"]]
    for key in ("status", "reserved_tokens", "reserved_cost_cents", "transport_binding"):
        assert after[key] == before[key]
    assert "actual_tokens" not in after
    assert p.portfolio_status(first)["halted"] is True
    assert p.portfolio_status(second)["tasks"]["a"]["actual_tokens"] == 19


@pytest.mark.parametrize("field", ["started_at", "deadline"])
@pytest.mark.parametrize(
    "invalid", [None, 17, [], {}, "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"]
)
def test_malformed_planning_time_keeps_owner_slot_without_starving_other_owner(
    database, gateway, field, invalid
):
    from modstore_server.db.identity import User
    from modstore_server.db.llm_chat import LlmClientRequest

    base.seed_owner(database)
    with database() as session:
        session.add(
            User(id=8, username="second-planning-owner", password_hash="unused", is_admin=True)
        )
        session.commit()
    budget = base.planning_budget(provider="litellm", model=MODEL)
    for owner in (7, 8):
        with usage.planning_usage_scope(owner, budget):
            held = usage.prepare_platform_call("litellm", MODEL, [], 100)
            with usage.platform_call_reservation(held):
                usage.require_call_reservation(
                    provider="litellm", model=MODEL, start_transport=True
                )
            usage.complete_platform_call(held, None)
        with database() as session:
            row = session.scalar(
                select(LlmClientRequest).where(
                    LlmClientRequest.client_request_id == held["request_id"]
                )
            )
            record = json.loads(row.done_json)
            persist(
                gateway,
                upstream_events(record["transport_binding"], attempt_id=f"provider-{owner}"),
            )
            if owner == 7:
                record["transport_binding"][field] = invalid
                record["transport_binding_sha256"] = p.digest(record["transport_binding"])
                row.state = "processing" if field == "deadline" else "unknown"
                row.done_json = p._json(record)
                row.updated_at = datetime.now(UTC) - timedelta(days=1)
                malformed = row.done_json
                expected_state = row.state
                first_request = row.client_request_id
                session.commit()

    assert recovery.reconcile_pending_usage()["settled"] == 1
    with database() as session:
        original = session.scalar(
            select(LlmClientRequest).where(LlmClientRequest.client_request_id == first_request)
        )
        assert original.state == expected_state and original.done_json == malformed
        slots = session.scalars(
            select(LlmClientRequest)
            .where(LlmClientRequest.client_request_id == "strategy-planning-slot")
            .order_by(LlmClientRequest.user_id)
        ).all()
        assert [row.state for row in slots] == ["unknown", "completed"]
        assert json.loads(slots[1].done_json)["actual_tokens"] == 19
    with usage.planning_usage_scope(7, budget):
        with pytest.raises(p.PortfolioError, match="requires reconciliation"):
            usage.prepare_platform_call("litellm", MODEL, [], 100)


@pytest.mark.parametrize("invalid", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"])
def test_invalid_provider_time_does_not_starve_later_original_usage(database, gateway, invalid):
    first, _, held, binding = admit(database, key="invalid-provider-time")
    second, _, _, valid = admit(database, key="valid-provider-time")
    events = upstream_events(binding)
    for event in events:
        event["payload"]["event"]["started_at"] = invalid
    persist(gateway, events)
    persist(gateway, upstream_events(valid, attempt_id="second-provider-response"))

    assert recovery.reconcile_pending_usage()["settled"] == 1
    call = p.portfolio_status(first)["tasks"]["a"]["calls"][held["request_id"]]
    assert call["status"] == "unknown" and "actual_tokens" not in call
    assert p.portfolio_status(first)["halted"] is True
    assert p.portfolio_status(second)["tasks"]["a"]["actual_tokens"] == 19


def test_usage_scan_rotates_same_timestamp_calls_before_readback(database, gateway, monkeypatch):
    decision_id, _, held, binding = admit(database)
    frozen = datetime.now(UTC)
    second_binding = {**binding, "request_id": "later-original-call"}

    def add_second(_row, _proposal, state, _session):
        calls = state["tasks"]["a"]["calls"]
        calls[held["request_id"]]["readback_checked_at"] = frozen.isoformat()
        calls[second_binding["request_id"]] = {
            **deepcopy(calls[held["request_id"]]),
            "transport_binding": second_binding,
            "transport_binding_sha256": p.digest(second_binding),
        }

    p.mutate_portfolio(decision_id, add_second)
    persist(gateway, upstream_events(second_binding))

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(recovery, "datetime", FrozenDatetime)
    assert recovery.reconcile_pending_usage(limit=1) == {"checked": 1, "settled": 0}
    assert recovery.reconcile_pending_usage(limit=1) == {"checked": 1, "settled": 1}
    calls = p.portfolio_status(decision_id)["tasks"]["a"]["calls"]
    assert calls[held["request_id"]]["status"] == "unknown"
    assert calls[second_binding["request_id"]]["actual_tokens"] == 19


@pytest.mark.parametrize("clock_rollback", [0, 600])
def test_portfolio_rotation_survives_mutation_with_a_fixed_or_earlier_clock(
    database, gateway, monkeypatch, clock_rollback
):
    first, second = sorted(
        [admit(database, key="one"), admit(database, key="two")], key=lambda item: item[0]
    )
    persist(gateway, upstream_events(second[3]))
    stamp = datetime.now(UTC)
    with database() as session:
        for row in session.scalars(select(StrategicDecision)):
            row.updated_at = stamp
        session.commit()

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return stamp - timedelta(seconds=clock_rollback)

    monkeypatch.setattr(recovery, "datetime", FrozenDatetime)
    monkeypatch.setattr(p, "datetime", FrozenDatetime)
    assert recovery.reconcile_pending_usage(limit=1) == {"checked": 1, "settled": 0}
    assert recovery.reconcile_pending_usage(limit=1) == {"checked": 1, "settled": 1}
    assert (
        p.portfolio_status(first[0])["tasks"]["a"]["calls"][first[2]["request_id"]]["status"]
        == "unknown"
    )
    assert p.portfolio_status(second[0])["tasks"]["a"]["actual_tokens"] == 19
