"""Real management policy, LangGraph and SQL receipts over a simulated gateway."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from modstore_server import auth_service, employee_runtime, llm_catalog, models
from modstore_server import xiaoc_life_api as life_api
from modstore_server import xiaoc_life_reconciliation as reconciliation
from modstore_server import xiaoc_life_runtime as runtime
from modstore_server import xiaoc_life_store as life
from modstore_server.db.llm_chat import LlmCallLog, LlmClientRequest
from modstore_server.db.xiaoc_life import XiaoCLifeEvent, XiaoCLifeState
from modstore_server.employee_runtime import load_employee_pack_resolved
from modstore_server.infrastructure import http_clients
from tests.platform_model_support import isolated as isolated
from tests.test_strategic_portfolio import database as database
from tests.test_strategic_portfolio import seed_owner

MODEL = "xcmax-doubao-code"  # Deliberately different from the old guessed bench model.
PROMPT_TOKENS, COMPLETION_TOKENS = 137, 29


@pytest.fixture
def gateway_life(database, monkeypatch, tmp_path):
    for module in (life, life_api, reconciliation, models, auth_service):
        monkeypatch.setattr(module, "get_session_factory", lambda: database)
    # This fixture shares the SQL setup with the employee integration tests;
    # restore its pack seam so only gateway HTTP is simulated here.
    monkeypatch.setattr(
        employee_runtime, "load_employee_pack_resolved", load_employee_pack_resolved
    )
    seed_owner(database)
    key = "sk-life-gateway-fixture-" + tmp_path.name
    monkeypatch.setenv("LITELLM_MASTER_KEY", key)
    monkeypatch.setenv("LITELLM_BASE_URL", "http://127.0.0.1:14000")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    for name in (
        "MODSTORE_SLO_REPORT_PATH",
        "MODSTORE_INTENT_REPORT_PATH",
        "MODSTORE_LEGACY_REPORT_PATH",
        "MODSTORE_DOMAIN_AUDIT_PATH",
    ):
        monkeypatch.setenv(name, str(tmp_path / "unavailable-report.json"))
    monkeypatch.setattr(llm_catalog, "_cache", {})
    monkeypatch.setattr(llm_catalog, "_last_force_refresh", {})
    monkeypatch.setattr(http_clients, "_external_async_client", None)
    gateway = {"calls": [], "max_budget": 100.0, "budget_http_status": 200}

    def respond(request):
        gateway["calls"].append(request)
        assert request.url.host == "127.0.0.1" and request.url.port == 14000
        assert request.headers["Authorization"] == f"Bearer {key}"
        assert key not in str(request.url)
        if request.url.path == "/v1/models":
            assert request.method == "GET"
            return httpx.Response(
                200,
                json={"object": "list", "data": [{"id": MODEL, "type": "chat"}]},
            )
        if request.url.path == "/global/spend":
            assert request.method == "GET"
            return httpx.Response(
                gateway["budget_http_status"],
                # The reporting window must not replace current-window spend.
                json={"max_budget": gateway["max_budget"], "spend": 999999.0},
            )
        if request.url.path == "/user/info":
            assert request.method == "GET"
            assert dict(request.url.params) == {"user_id": "litellm-proxy-budget"}
            return httpx.Response(
                200,
                json={
                    "user_id": "litellm-proxy-budget",
                    "user_info": {
                        "user_id": "litellm-proxy-budget",
                        "max_budget": gateway["max_budget"],
                        "spend": 10.0,
                        "budget_duration": "30d",
                        "budget_reset_at": (life.utcnow() + timedelta(days=1)).isoformat(),
                    },
                },
            )
        assert request.method == "POST" and request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == MODEL
        observations = json.loads(body["messages"][1]["content"])["observations"]
        ref = observations[0]["ref"]
        assert ref.startswith("company:assets:")
        # Both durable reservations must already exist before outbound HTTP.
        with database() as session:
            pending = session.scalars(
                select(LlmClientRequest).where(
                    LlmClientRequest.client_request_id.startswith("strategy-discovery-")
                )
            ).one()
            assert pending.state == "processing"
            receipt = json.loads(pending.done_json)
            admission = receipt["admission"]
            assert admission["source"] == "litellm_proxy_budget_api"
            assert admission["budget_source"] == "existing_platform_gateway_budget"
            assert admission["remaining_percent"] == 90
            active = json.loads(session.get(XiaoCLifeState, life.IDENTITY_ID).state_json)[
                "active_cycle"
            ]
            assert any(
                step.get("request_id") == pending.client_request_id for step in active["steps"]
            )
            gateway["request_id"] = pending.client_request_id
        decision = {
            "action": "propose",
            "summary": "根据已读取的模型目录提出验证任务。",
            "evidence_refs": [ref],
            "goal": {
                "title": "验证网关模型交付能力",
                "description": "在独立任务授权后核验模型能力，记录原始结果。",
                "evidence_refs": [ref],
            },
            "interests": [],
            "self_assessment": None,
        }
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-life-gateway",
                "object": "chat.completion",
                "model": MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(decision)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": PROMPT_TOKENS,
                    "completion_tokens": COMPLETION_TOKENS,
                    "total_tokens": PROMPT_TOKENS + COMPLETION_TOKENS,
                },
                **gateway.get("response_overrides", {}),
            },
            headers=gateway.get("response_headers", {}),
        )

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda _self, _url: transport)
    app = FastAPI()
    app.include_router(life_api.router)
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer " + auth_service.create_access_token(
                7, "portfolio-owner", is_admin=True
            )
            current = client.get("/life").json()
            configured = client.put(
                "/life",
                json={
                    "expected_revision": current["revision"],
                    "level": 5,
                    "policy": {
                        "daily_token_limit": 100_000,
                        "daily_cycle_limit": 4,
                        "exploration_percent": 0,
                        "authorization_expires_at": (life.utcnow() + timedelta(days=1)).isoformat(),
                    },
                },
            )
            assert configured.status_code == 200, configured.text
            gateway["client"] = client
            yield gateway
    finally:
        if http_clients._external_async_client is not None:
            asyncio.run(http_clients._external_async_client.aclose())


def test_default_gateway_cognition_settles_both_ledgers_and_repeated_ticks_are_idle(
    gateway_life, database
):
    gateway = gateway_life
    state = asyncio.run(runtime.tick_async())
    cycle = next(event for event in state["events"] if event["id"].startswith("cycle:"))
    total = PROMPT_TOKENS + COMPLETION_TOKENS
    assert cycle["status"] == "completed", cycle
    assert cycle["model"] == f"litellm/{MODEL}" and cycle["actual_tokens"] == total
    assert state["budget"]["used_tokens"] == total and state["budget"]["reserved_tokens"] == 0
    assert state["budget"]["cycles"] == 1 and state["unknown_usage"] is False
    assert len(state["goals"]) == 1 and state["goals"][0]["status"] == "proposed"
    assert "decision_id" not in state["goals"][0]
    assert state["goals"][0]["evidence_refs"][0] in cycle["evidence_refs"]
    with database() as session:
        request = session.scalars(
            select(LlmClientRequest).where(
                LlmClientRequest.client_request_id == gateway["request_id"]
            )
        ).one()
        assert request.state == "completed"
        receipt = json.loads(request.done_json)
        assert receipt == cycle["details"]["model_receipts"][0]
        assert receipt["status"] == "settled" and receipt["actual_tokens"] == total
        assert receipt["cost_basis"] == "gateway_reported_token_usage_not_supplier_invoice"
        assert receipt["supplier_cost_cents"] is None
        call = session.scalars(select(LlmCallLog)).one()
        assert (call.provider, call.model, call.user_id) == ("litellm", MODEL, 7)
        assert (call.prompt_tokens, call.completion_tokens) == (PROMPT_TOKENS, COMPLETION_TOKENS)
        assert call.total_tokens == total and call.estimated is False
        assert call.hold_no == gateway["request_id"][-64:]
        assert session.scalar(select(func.count()).select_from(XiaoCLifeState)) == 1
    paths = [request.url.path for request in gateway["calls"]]
    assert "/v1/models" in paths
    assert paths[-3:] == ["/global/spend", "/user/info", "/v1/chat/completions"]
    before = len(gateway["calls"])
    for _ in range(2):
        assert asyncio.run(runtime.tick_async())["status"] == "idle"
    assert len(gateway["calls"]) == before
    after = gateway["client"].get("/life").json()
    assert after["budget"] == state["budget"] and after["goals"] == state["goals"]
    with database() as session:
        assert session.scalar(select(func.count()).select_from(LlmCallLog)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(XiaoCLifeEvent)
                .where(XiaoCLifeEvent.id.startswith("cycle:"))
            )
            == 1
        )


@pytest.mark.parametrize("missing_budget", ["unlimited", "database_unavailable"])
def test_gateway_without_verified_budget_blocks_cognition_before_model_request(
    gateway_life, database, missing_budget
):
    gateway = gateway_life
    if missing_budget == "unlimited":
        gateway["max_budget"] = 0
    else:
        gateway["budget_http_status"] = 500
    state = asyncio.run(runtime.tick_async())
    cycle = next(event for event in state["events"] if event["id"].startswith("cycle:"))
    assert cycle["status"] == "blocked", cycle
    assert cycle["details"]["reason"] == "platform_quota_unknown_or_exhausted"
    assert cycle["actual_tokens"] == 0 and cycle["details"]["steps"] == []
    assert state["budget"]["used_tokens"] == state["budget"]["reserved_tokens"] == 0
    assert not state["goals"] and state["unknown_usage"] is False
    assert any(request.url.path == "/v1/models" for request in gateway["calls"])
    assert all(request.method == "GET" for request in gateway["calls"])
    with database() as session:
        assert session.scalar(select(func.count()).select_from(LlmCallLog)) == 0
        assert session.scalar(select(func.count()).select_from(LlmClientRequest)) == 0
    before = len(gateway["calls"])
    assert asyncio.run(runtime.tick_async())["status"] == "idle"
    assert len(gateway["calls"]) == before


@pytest.mark.parametrize(
    "response_overrides,response_headers",
    [
        ({"usage": {}}, {}),
        ({"usage": {"completion_tokens": COMPLETION_TOKENS}}, {}),
        ({"model": "different-upstream-model"}, {}),
        ({}, {"X-LiteLLM-Attempted-Fallbacks": "1"}),
        ({}, {"X-LiteLLM-Attempted-Fallbacks": "unreported"}),
    ],
)
def test_unverified_gateway_receipt_retains_both_holds_without_replaying(
    gateway_life, database, response_overrides, response_headers
):
    gateway = gateway_life
    gateway.update(response_overrides=response_overrides, response_headers=response_headers)
    state = asyncio.run(runtime.tick_async())
    cycle = next(event for event in state["events"] if event["id"].startswith("cycle:"))
    assert cycle["status"] == "unknown" and cycle["actual_tokens"] is None
    assert cycle["details"]["reason"] == "model_usage_unknown"
    assert state["unknown_usage"] is True and not state["goals"]
    assert state["budget"]["used_tokens"] == 0 and state["budget"]["reserved_tokens"] > 0
    with database() as session:
        requests = session.scalars(
            select(LlmClientRequest).where(
                LlmClientRequest.client_request_id.in_(
                    [gateway["request_id"], "strategy-planning-slot"]
                )
            )
        ).all()
        assert len(requests) == 2 and all(row.state == "unknown" for row in requests)
        for row in requests:
            receipt = json.loads(row.done_json)
            assert receipt == cycle["details"]["model_receipts"][0]
            assert receipt["actual_tokens"] is None and receipt["reserved_tokens"] > 0
        call = session.scalars(select(LlmCallLog)).one()
        assert call.status == "strategy_planning_unknown" and call.estimated is True
    before = len(gateway["calls"])
    assert asyncio.run(runtime.tick_async())["status"] == "idle"
    after = gateway["client"].get("/life").json()
    assert after["unknown_usage"] is True and after["budget"] == state["budget"]
    assert len(gateway["calls"]) == before
