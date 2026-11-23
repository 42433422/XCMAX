"""Protocol/mechanism fixtures, never evidence that a production model qualified."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from app.infrastructure.codex import qualification as qualification
from app.infrastructure.codex.local_server import LocalRuntimeServer
from app.infrastructure.codex.policy import QUALIFICATION_CHECKS, ModelRoute, RuntimeSettings
from tests.test_application.test_codex_gateway_integration import _events


def route(**kwargs):
    return ModelRoute(
        **{
            "base_url": "https://independent.example/v1",
            "model": "fixture-model",
            "provider_id": "independent",
            "upstream_vendor": "test-fixture",
            "context_window": 32000,
            "max_output_tokens": 4000,
            **kwargs,
        }
    )


def message(index=1):
    return {
        "type": "message",
        "id": f"message-{index}",
        "status": "completed",
        "role": "assistant",
        "phase": "final_answer",
        "content": [
            {"type": "output_text", "text": "Fixture receipt verified.", "annotations": []}
        ],
    }


def probe_at(tmp_path):
    probe = qualification._Probe(tmp_path)
    probe.initialize()
    return probe


def test_model_egress_denies_before_any_connection_and_pins_route(monkeypatch):
    contacted = []

    async def run():
        guard = qualification.IndependentModelTransport(route())
        guard._http = httpx.MockTransport(
            lambda request: contacted.append(request) or httpx.Response(200)
        )
        async with httpx.AsyncClient(
            transport=guard, trust_env=False, follow_redirects=False
        ) as client:
            for destination in (
                "https://api.openai.com/v1/responses",
                "https://chatgpt.com/v1/responses",
                "https://tenant.openai.azure.com/v1/responses",
                "https://another-independent.example/v1/responses",
                "https://independent.example/v1/responses?redirect=1",
            ):
                with pytest.raises(qualification.ModelEgressDenied):
                    await client.post(destination, json={})
            assert guard.denied == 5 and guard.connections_attempted == 0 and contacted == []
            assert (await client.post(route().base_url + "/responses", json={})).status_code == 200
            assert guard.connections_attempted == 1 and len(contacted) == 1
            with pytest.raises(qualification.ModelEgressDenied):
                await client.get(route().base_url + "/responses")

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    asyncio.run(run())


def test_probe_audits_rejected_replay_and_has_no_production_tool_surface(tmp_path):
    probe = probe_at(tmp_path)
    assert not probe.invoke("execute_action", {"sql": "DROP TABLE receipt"})["success"]
    assert probe.invoke("execute_action", {"nonce": probe.nonce})["success"]
    assert not probe.invoke("execute_action", {"nonce": probe.nonce})["success"]
    probe.phase = "resumed"
    assert probe.invoke("task_evidence", {"nonce": probe.nonce})["verified"]
    assert not probe.invoke("production_action", {"nonce": probe.nonce})["success"]
    snapshot = probe.snapshot()
    assert snapshot["row_verified"]
    assert len([call for call in snapshot["calls"] if call[0] == "execute_action"]) == 3
    checks = qualification._checks(probe, route())
    assert checks["business_receipt_verified"] == "FAIL"
    assert checks["forced_compaction_restart_same_task_no_replay"] == "FAIL"


def test_probe_rejects_extra_receipt_rows_in_bounded_read(tmp_path):
    probe = probe_at(tmp_path)
    assert probe.invoke("execute_action", {"nonce": probe.nonce})["success"]
    with sqlite3.connect(probe.database) as db:
        db.executemany("INSERT INTO receipt VALUES (?)", [("extra-one",), ("extra-two",)])
    assert not probe.invoke("task_evidence", {"nonce": probe.nonce})["verified"]
    assert not probe.snapshot()["row_verified"]
    assert qualification._checks(probe, route())["business_receipt_verified"] == "FAIL"


@pytest.mark.parametrize("overflow", [False, True])
def test_probe_call_ledger_limit_cannot_hide_later_replay(tmp_path, overflow):
    probe = probe_at(tmp_path)
    probe.invoke("execute_action", {"nonce": probe.nonce})
    probe.invoke("task_evidence", {"nonce": probe.nonce})
    probe.phase = "resumed"
    for _ in range(qualification._MAX_PROBE_CALLS - 2 + int(overflow)):
        assert probe.invoke("task_evidence", {"nonce": probe.nonce})["verified"]
    if overflow:
        # The replay lies after the bounded prefix; merely inspecting its calls
        # would falsely see exactly one write and successful reads in both phases.
        assert not probe.invoke("execute_action", {"nonce": probe.nonce})["success"]
    probe.recovery = {
        "thread_id": "thread-fixture",
        "resumed_thread_id": "thread-fixture",
        "compaction": {"thread_id": "thread-fixture", "turn_id": "compact-fixture"},
        "first_process_id": 1,
        "second_process_id": 2,
    }
    snapshot = probe.snapshot()
    assert snapshot["calls_complete"] is (not overflow)
    assert len(snapshot["calls"]) == qualification._MAX_PROBE_CALLS + int(overflow)
    checks = qualification._checks(probe, route())
    for name in (
        "multi_turn_tools",
        "business_receipt_verified",
        "forced_compaction_restart_same_task_no_replay",
    ):
        assert checks[name] == ("FAIL" if overflow else "PASS")


@pytest.mark.parametrize(
    "defect", ["headers_missing", "headers_duplicate", "fallback", "model", "usage", "truncated"]
)
def test_failed_upstream_evidence_never_releases_tool_output(tmp_path, monkeypatch, defect):
    probe = probe_at(tmp_path)
    headers = [
        ("content-type", "text/event-stream"),
        ("x-litellm-attempted-retries", "0"),
        ("x-litellm-attempted-fallbacks", "0"),
    ]
    if defect == "headers_missing":
        headers.pop()
    if defect == "headers_duplicate":
        headers.append(("x-litellm-attempted-retries", "0"))
    if defect == "fallback":
        headers[-1] = ("x-litellm-attempted-fallbacks", "1")
    values = _events(1, message(), "wrong-model" if defect == "model" else route().model)
    if defect == "truncated":
        values.pop()
    if defect == "usage":
        value = json.loads(values[-1].decode()[6:])
        value["response"]["usage"] = {"input_tokens": -1, "output_tokens": 2}
        values[-1] = ("data: " + json.dumps(value) + "\n\n").encode()
    original = qualification.IndependentModelTransport

    class FixtureGuard(original):
        def __init__(self, route):
            super().__init__(route)
            self._http = httpx.MockTransport(
                lambda _request: httpx.Response(200, headers=headers, content=b"".join(values))
            )

    monkeypatch.setattr(qualification, "IndependentModelTransport", FixtureGuard)

    async def run():
        app = qualification._probe_app(route(), probe, "model-token", "mcp-token")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            denied = await client.post("/v1/responses", json={"stream": True})
            assert denied.status_code == 401 and probe.models == []
            response = await client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer model-token"},
                json={"stream": True, "model": route().model, "input": "probe", "tools": []},
            )
            assert response.status_code == 502
            assert "response.output_item" not in response.text

    asyncio.run(run())
    assert probe.network == {"scope": "host_model_egress", "denied_before_connect": True}
    assert not probe.models[0]["completed"] and probe.error_code
    assert probe.snapshot()["calls"] == []


@pytest.mark.parametrize("key_source", ["platform", "user_override"])
def test_market_receipt_binds_actual_identity_usage_and_settlement(key_source):
    bound = route(
        gateway_kind="market",
        credential="account-secret",
        route_token="route-secret",
        model="independent/source-model",
        config_revision="revision-one",
        key_source=key_source,
    )
    byok = key_source == "user_override"
    response = {
        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        "xcagi": {
            "schema": "xcmax.responses-billing.v1",
            "provider": bound.provider_id,
            "model": "source-model",
            "key_source": key_source,
            "config_revision": bound.config_revision,
            "client_request_id": "client-1",
            "request_id": "attempt-1",
            "hold_no": "hold-1",
            "billed": not byok,
            "charge_amount": "0.00" if byok else "0.10",
            "billing_status": "byok" if byok else "settled",
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        },
    }
    assert qualification._market_receipt(response, bound, "client-1")["request_id"] == "attempt-1"
    for key, invalid in (
        ("config_revision", "stale"),
        ("client_request_id", "replayed"),
        ("model", "replacement-model"),
        ("usage", {}),
        ("charge_amount", "NaN"),
        ("billing_status", "unsettled"),
    ):
        changed = {**response, "xcagi": {**response["xcagi"], key: invalid}}
        with pytest.raises(qualification._QualificationError):
            qualification._market_receipt(changed, bound, "client-1")


def test_failed_qualification_keeps_evidence_without_publishing_pass(tmp_path, monkeypatch):
    destination = tmp_path / "qualifications" / "qualification.json"
    settings = RuntimeSettings(route=route(), runtime_root=tmp_path, qualification_file=destination)
    monkeypatch.setattr(qualification, "verify_installation", lambda: None)

    async def failed(_settings, _owner, probe):
        probe.invoke("execute_action", {"nonce": probe.nonce})
        raise RuntimeError("Bearer account-secret https://secret.example")

    monkeypatch.setattr(qualification, "_run_probe", failed)
    result = qualification.qualify_runtime(
        settings,
        owner_scope="private-owner",
        upstream_evidence={
            "checks": dict.fromkeys(QUALIFICATION_CHECKS, "PASS"),
            "model_kind": "real",
        },
    )
    assert not result["ok"] and not destination.exists()
    assert result["model_attempted"] is True
    assert len(result["evidence_refs"]) == 1
    serialized = (
        json.dumps(result)
        + (destination.parent.glob("attempt-*/evidence.json").__next__()).read_text()
    )
    assert "account-secret" not in serialized and "private-owner" not in serialized
    assert result["checks"]["responses_stream"] == "FAIL"


def test_failed_installation_preflight_proves_no_model_attempt(tmp_path, monkeypatch):
    destination = tmp_path / "qualification.json"
    settings = RuntimeSettings(route=route(), runtime_root=tmp_path, qualification_file=destination)

    def unavailable():
        raise RuntimeError("private-component-path")

    async def must_not_start(*_args):
        raise AssertionError("installation failure must never contact a model")

    monkeypatch.setattr(qualification, "verify_installation", unavailable)
    monkeypatch.setattr(qualification, "_run_probe", must_not_start)
    result = qualification.qualify_runtime(settings, owner_scope="fixture")
    assert result["ok"] is False and result["model_attempted"] is False
    assert result["error_code"] == "runtime_qualification_unavailable"
    assert result["evidence_refs"] == [] and not destination.exists()
    assert "private-component-path" not in json.dumps(result)


def test_host_change_during_probe_preserves_failure_without_publishing_pass(tmp_path, monkeypatch):
    destination = tmp_path / "qualification.json"
    settings = RuntimeSettings(route=route(), runtime_root=tmp_path, qualification_file=destination)
    monkeypatch.setattr("app.build_identity.verified_source_sha", lambda: "a" * 40)
    monkeypatch.setattr(qualification, "verify_installation", lambda: None)

    async def changed(*_args):
        monkeypatch.setattr("app.build_identity.verified_source_sha", lambda: "b" * 40)

    monkeypatch.setattr(qualification, "_run_probe", changed)
    result = qualification.qualify_runtime(settings, owner_scope="fixture")
    assert result["ok"] is False and result["model_attempted"] is True
    assert result["error_code"] == "runtime_host_changed"
    assert len(result["evidence_refs"]) == 1 and not destination.exists()


def test_private_evidence_writer_preserves_digest_on_windows_newline_translation(
    tmp_path, monkeypatch
):
    from app.infrastructure.codex import transport

    fdopen = transport.os.fdopen

    def windows_text_stream(fd, *args, **kwargs):
        # TextIOWrapper's Windows default translates LF. Exercise those bytes on any host.
        if args and "b" not in args[0]:
            kwargs.setdefault("newline", "\r\n")
        return fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(transport.os, "fdopen", windows_text_stream)
    monkeypatch.setattr(qualification, "verify_installation", lambda: None)

    async def synthetic_probe(*_args):
        return None

    # Exercise publication and readback, not real-provider qualification.
    monkeypatch.setattr(qualification, "_run_probe", synthetic_probe)
    monkeypatch.setattr(
        qualification, "_checks", lambda *_args: dict.fromkeys(QUALIFICATION_CHECKS, "PASS")
    )
    settings = RuntimeSettings(
        route=route(), runtime_root=tmp_path, qualification_file=tmp_path / "qualification.json"
    )
    result = qualification.qualify_runtime(settings, owner_scope="synthetic-test-only")
    assert result["ok"] is True
    assert settings.require_qualified() == settings.route


@pytest.mark.parametrize("provider", ["deepseek", "litellm"])
def test_market_direct_counter_proof_does_not_fabricate_litellm_headers(
    tmp_path, monkeypatch, provider
):
    probe = probe_at(tmp_path)
    bound = route(
        gateway_kind="market",
        provider_id=provider,
        model=provider + "/source-model",
        response_model="source-model",
        credential="account-secret",
        route_token="snapshot-secret",
        config_revision="revision-one",
        key_source="user_override",
    )

    def respond(request):
        events = _events(1, message(), bound.response_model)
        terminal = json.loads(events[-1].decode()[6:])
        result = terminal["response"]
        result["xcagi"] = {
            "schema": "xcmax.responses-billing.v1",
            "provider": provider,
            "model": "source-model",
            "config_revision": bound.config_revision,
            "key_source": bound.key_source,
            "client_request_id": request.headers["idempotency-key"],
            "request_id": "attempt-1",
            "hold_no": "byok-attempt-1",
            "billed": False,
            "billing_status": "byok",
            "charge_amount": "0.00",
            "usage": result["usage"],
        }
        events[-1] = ("data: " + json.dumps(terminal) + "\n\n").encode()
        return httpx.Response(
            200,
            content=b"".join(events),
            headers={
                "content-type": "text/event-stream",
                "x-xcmax-upstream-attempts": "1",
                "x-xcmax-upstream-fallbacks": "0",
            },
        )

    original = qualification.IndependentModelTransport

    class FixtureGuard(original):
        def __init__(self, route):
            super().__init__(route)
            self._http = httpx.MockTransport(respond)

    monkeypatch.setattr(qualification, "IndependentModelTransport", FixtureGuard)

    async def run():
        app = qualification._probe_app(bound, probe, "model-token", "mcp-token")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            return await client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer model-token"},
                json={"stream": True, "model": bound.model, "input": "probe", "tools": []},
            )

    response = asyncio.run(run())
    assert response.status_code == (200 if provider == "deepseek" else 502)
    assert probe.models[0]["completed"] is (provider == "deepseek")
    if provider == "deepseek":
        assert probe.models[0]["billing"]["billing_status"] == "byok"
    else:
        assert probe.error_code == "runtime_upstream_attempts_unverified"


def _tool_target(tools, name):
    for tool in tools:
        if tool.get("type") == "function" and tool.get("name") == "mcp__xcmax__" + name:
            return {"name": tool["name"]}
        if tool.get("type") == "namespace" and any(
            item.get("name") == name for item in tool.get("tools", [])
        ):
            return {"namespace": tool["name"], "name": name}
    raise AssertionError("Pinned CLI did not expose the isolated qualification MCP tool")


@pytest.mark.parametrize("maximum", [1024, 4000])
def test_real_cli_forced_compaction_restart_same_thread_without_probe_replay(tmp_path, maximum):
    """Real 0.171 CLI/MCP/SQLite, synthetic model; no qualification is published."""
    pytest.importorskip("openai_codex")
    pytest.importorskip("codex_cli_bin")
    qualification.verify_installation()
    probe = probe_at(tmp_path)
    upstream, calls = FastAPI(), []

    @upstream.post("/v1/responses")
    async def respond(request: Request):
        body = await request.json()
        calls.append(body)
        index = len(calls)
        if index in {1, 2, 5}:
            name = "execute_action" if index == 1 else "task_evidence"
            item = {
                "type": "function_call",
                "id": f"fc-{index}",
                "call_id": f"call-{index}",
                **_tool_target(body["tools"], name),
                "arguments": json.dumps({"nonce": probe.nonce}),
                "status": "completed",
            }
        else:
            item = message(index)
        return StreamingResponse(
            iter(_events(index, item, body["model"])),
            media_type="text/event-stream",
            headers={"x-litellm-attempted-retries": "0", "x-litellm-attempted-fallbacks": "0"},
        )

    with LocalRuntimeServer(upstream) as server:
        bound = replace(route(max_output_tokens=maximum), base_url=server.url + "/v1")
        settings = RuntimeSettings(
            route=bound,
            runtime_root=tmp_path,
            turn_timeout_seconds=30,
            qualification_file=tmp_path / "must-not-exist.json",
        )
        asyncio.run(qualification._run_probe(settings, "fixture-only-owner", probe))
    assert qualification._checks(probe, bound) == dict.fromkeys(QUALIFICATION_CHECKS, "PASS")
    assert probe.snapshot()["calls"] == [
        ("execute_action", "initial", 1),
        ("task_evidence", "initial", 1),
        ("task_evidence", "resumed", 1),
    ]
    assert len(calls) == 6
    assert all(body["max_output_tokens"] == min(maximum, 2048) for body in calls)
    assert probe.recovery["first_process_id"] != probe.recovery["second_process_id"]
    assert not settings.qualification_file.exists()
