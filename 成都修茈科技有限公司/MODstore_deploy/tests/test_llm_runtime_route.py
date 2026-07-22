from __future__ import annotations

import json

import pytest

from modstore_server import llm_key_resolver, llm_runtime_route
from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner
from modstore_server.services import llm as llm_service


@pytest.fixture()
def route_file(tmp_path, monkeypatch):
    path = tmp_path / "runtime-route.json"
    monkeypatch.setenv("MODSTORE_LLM_RUNTIME_ROUTE_PATH", str(path))
    return path


def test_commit_route_persists_audit_without_secrets(route_file):
    fake_secret = "sk-unit-test-secret-value"
    out = llm_runtime_route.commit_runtime_route(
        "deepseek",
        "deepseek-chat",
        actor="employee:llm-ops-engineer",
        reason=f"primary provider recovery Bearer {fake_secret}",
        health={"ok": True, "status": 200, "error": f"Bearer {fake_secret}"},
    )

    assert out["ok"] is True
    assert out["current"]["provider"] == "deepseek"
    state = json.loads(route_file.read_text(encoding="utf-8"))
    assert state["current"]["model"] == "deepseek-chat"
    assert state["history"][-1]["actor"] == "employee:llm-ops-engineer"
    assert "api_key" not in route_file.read_text(encoding="utf-8").lower()
    assert fake_secret not in route_file.read_text(encoding="utf-8")


def test_commit_route_compare_and_swap_rejects_stale_revision(route_file):
    first = llm_runtime_route.commit_runtime_route(
        "deepseek",
        "model-a",
        actor="test",
        reason="initial route",
        expected_revision="",
    )
    revision = first["current"]["revision"]

    conflict = llm_runtime_route.commit_runtime_route(
        "openai",
        "model-b",
        actor="autopilot",
        reason="stale observation",
        expected_revision="stale-revision",
    )

    assert conflict["ok"] is False
    assert conflict["conflict"] is True
    assert conflict["error"] == "route_revision_conflict"
    assert conflict["actual_revision"] == revision
    assert llm_runtime_route.current_runtime_route()["model"] == "model-a"

    switched = llm_runtime_route.commit_runtime_route(
        "openai",
        "model-b",
        actor="autopilot",
        reason="fresh observation",
        expected_revision=revision,
    )
    assert switched["ok"] is True
    assert switched["current"]["model"] == "model-b"


def test_runtime_route_precedes_environment(route_file, monkeypatch):
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BENCH_PROVIDER", "openai")
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BENCH_MODEL", "gpt-4o-mini")
    llm_runtime_route.commit_runtime_route(
        "deepseek",
        "deepseek-chat",
        actor="test",
        reason="test precedence",
    )
    monkeypatch.setattr(
        llm_key_resolver,
        "platform_api_key",
        lambda provider: "configured" if provider in {"deepseek", "openai"} else None,
    )

    assert llm_service.resolve_platform_bench_llm() == ("deepseek", "deepseek-chat")


@pytest.mark.asyncio
async def test_switch_requires_catalog_and_health(route_file, monkeypatch):
    monkeypatch.setattr(
        llm_key_resolver,
        "platform_api_key",
        lambda provider: "configured" if provider == "deepseek" else None,
    )

    async def fake_catalog(provider=None, *, refresh=False):
        assert provider == "deepseek"
        return {
            "ok": True,
            "providers": [
                {
                    "provider": "deepseek",
                    "configured": True,
                    "models": ["deepseek-chat"],
                    "source": "remote",
                }
            ],
        }

    async def fake_probe(provider, model):
        return {"ok": True, "status": 200, "checked_at": "now"}

    monkeypatch.setattr(llm_runtime_route, "platform_model_catalog", fake_catalog)
    monkeypatch.setattr(llm_runtime_route, "_probe_route", fake_probe)

    rejected = await llm_runtime_route.switch_runtime_route(
        "deepseek",
        "not-in-catalog",
        actor="employee:llm-ops-engineer",
    )
    assert rejected["ok"] is False
    assert "not in platform catalog" in rejected["error"]
    assert not route_file.exists()

    switched = await llm_runtime_route.switch_runtime_route(
        "deepseek",
        "deepseek-chat",
        actor="employee:llm-ops-engineer",
        reason="healthy failover",
    )
    assert switched["ok"] is True
    assert switched["effective_for"] == "next_platform_employee_llm_call"
    assert llm_runtime_route.current_runtime_route()["model"] == "deepseek-chat"


@pytest.mark.asyncio
async def test_failed_health_check_does_not_change_route(route_file, monkeypatch):
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _provider: "configured")

    async def fake_catalog(provider=None, *, refresh=False):
        return {
            "ok": True,
            "providers": [{"provider": provider, "models": ["model-a"], "source": "remote"}],
        }

    async def failed_probe(provider, model):
        return {"ok": False, "status": 503, "error": "upstream unavailable"}

    monkeypatch.setattr(llm_runtime_route, "platform_model_catalog", fake_catalog)
    monkeypatch.setattr(llm_runtime_route, "_probe_route", failed_probe)
    result = await llm_runtime_route.switch_runtime_route(
        "openai",
        "model-a",
        actor="employee:llm-ops-engineer",
    )

    assert result["ok"] is False
    assert result["health"]["status"] == 503
    assert llm_runtime_route.current_runtime_route() is None


@pytest.mark.asyncio
async def test_non_chat_capability_cannot_become_employee_runtime(route_file, monkeypatch):
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _provider: "configured")
    probe_calls = []

    async def fake_catalog(provider=None, *, refresh=False):
        return {
            "ok": True,
            "providers": [
                {
                    "provider": provider,
                    "models": ["gpt-4o-mini-tts"],
                    "runtime_models": [],
                    "models_detailed": [
                        {
                            "id": "gpt-4o-mini-tts",
                            "category": "audio",
                            "capabilities": {
                                "input_modalities": ["text"],
                                "output_modalities": ["audio"],
                                "operations": ["text_to_speech"],
                            },
                            "runtime_selectable": False,
                        }
                    ],
                    "source": "remote",
                }
            ],
        }

    async def should_not_probe(provider, model):
        probe_calls.append((provider, model))
        return {"ok": True}

    monkeypatch.setattr(llm_runtime_route, "platform_model_catalog", fake_catalog)
    monkeypatch.setattr(llm_runtime_route, "_probe_route", should_not_probe)

    result = await llm_runtime_route.switch_runtime_route(
        "openai",
        "gpt-4o-mini-tts",
        actor="employee:llm-ops-engineer",
    )

    assert result["ok"] is False
    assert "cannot be used as employee chat runtime" in result["error"]
    assert result["model"]["capabilities"]["operations"] == ["text_to_speech"]
    assert probe_calls == []


@pytest.mark.asyncio
async def test_rollback_restores_previous_route(route_file, monkeypatch):
    llm_runtime_route.commit_runtime_route("deepseek", "model-a", actor="test", reason="a")
    llm_runtime_route.commit_runtime_route("openai", "model-b", actor="test", reason="b")

    async def healthy(provider, model):
        return {"ok": True, "status": 200}

    monkeypatch.setattr(llm_runtime_route, "_probe_route", healthy)
    result = await llm_runtime_route.rollback_runtime_route(
        actor="employee:llm-ops-engineer",
        reason="quality regression",
    )

    assert result["ok"] is True
    assert result["current"]["provider"] == "deepseek"
    assert result["current"]["model"] == "model-a"
    assert result["event"]["action"] == "rollback"


@pytest.mark.asyncio
async def test_only_llm_ops_employee_can_use_switch_tool(route_file, monkeypatch):
    calls = []

    async def fake_switch(provider, model, **kwargs):
        calls.append((provider, model, kwargs))
        return {"ok": True, "current": {"provider": provider, "model": model}}

    monkeypatch.setattr(llm_runtime_route, "switch_runtime_route", fake_switch)
    denied = await EmployeeAgentRunner(
        {"employee_id": "daily-orchestrator"}, workspace_root="."
    )._dispatch_tool(
        "switch_platform_llm_route",
        {"provider": "deepseek", "model": "deepseek-chat"},
    )
    assert denied["ok"] is False
    assert not calls

    allowed = await EmployeeAgentRunner(
        {"employee_id": "llm-ops-engineer"}, workspace_root="."
    )._dispatch_tool(
        "switch_platform_llm_route",
        {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "reason": "incident failover",
            "force": True,
        },
    )
    assert allowed["ok"] is True
    assert calls[0][2]["actor"] == "employee:llm-ops-engineer"
    assert calls[0][2]["force"] is False


@pytest.mark.asyncio
async def test_llm_ops_agent_can_actively_switch_in_react_loop(route_file, monkeypatch):
    tool_calls = []
    llm_round = 0

    async def fake_switch(provider, model, **kwargs):
        tool_calls.append((provider, model, kwargs))
        return {"ok": True, "effective_for": "next_platform_employee_llm_call"}

    async def fake_llm(messages, **kwargs):
        nonlocal llm_round
        llm_round += 1
        if llm_round == 1:
            protocol = "\n".join(str(m.get("content") or "") for m in messages)
            assert "switch_platform_llm_route" in protocol
            return {
                "ok": True,
                "content": json.dumps(
                    {
                        "thought": "目标模型已经明确，调用专属工具完成真实切换并等待回执。",
                        "tool": "switch_platform_llm_route",
                        "input": {
                            "provider": "deepseek",
                            "model": "deepseek-chat",
                            "reason": "operator request",
                        },
                    },
                    ensure_ascii=False,
                ),
            }
        return {
            "ok": True,
            "content": json.dumps(
                {"thought": "切换工具返回成功。", "answer": "已完成运行时模型切换。"},
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(llm_runtime_route, "switch_runtime_route", fake_switch)
    result = await EmployeeAgentRunner(
        {"employee_id": "llm-ops-engineer", "call_llm": fake_llm},
        workspace_root=".",
    ).run("切换到 deepseek/deepseek-chat")

    assert result["ok"] is True
    assert result["summary"] == "已完成运行时模型切换。"
    assert tool_calls[0][0:2] == ("deepseek", "deepseek-chat")
