"""外置策略评估与风险门集成的测试。"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.application.workflow.risk_gate import HybridRiskGate
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.infrastructure.policy import external_policy

POLICY_URL = "http://opa.internal/v1/decisions"


def _plan(*, tool_id: str = "products", action: str = "query") -> PlanGraph:
    return PlanGraph(
        plan_id="plan-external-policy",
        intent="external_policy",
        nodes=[WorkflowNode(node_id="read", tool_id=tool_id, action=action, risk="low")],
        risk_level="low",
    )


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


def _install_post(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> _FakeResponse:
        calls.append({"url": url, **kwargs})
        return handler(url, kwargs)

    monkeypatch.setattr(external_policy.httpx, "post", fake_post)
    return calls


def _result(**overrides: Any) -> _FakeResponse:
    payload = {"allow": True, "require_approval": False, "reason": ""}
    payload.update(overrides)
    return _FakeResponse({"result": payload})


def test_policy_enabled_follows_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_POLICY_URL", raising=False)
    assert external_policy.policy_enabled() is False

    monkeypatch.setenv("XCAGI_POLICY_URL", "   ")
    assert external_policy.policy_enabled() is False

    monkeypatch.setenv("XCAGI_POLICY_URL", POLICY_URL)
    assert external_policy.policy_enabled() is True


def test_policy_env_parsing_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_POLICY_TIMEOUT", raising=False)
    monkeypatch.delenv("XCAGI_POLICY_FAIL_MODE", raising=False)
    assert external_policy.policy_timeout() == 2.0
    assert external_policy.policy_fail_mode() == "open"

    monkeypatch.setenv("XCAGI_POLICY_TIMEOUT", "0.5")
    monkeypatch.setenv("XCAGI_POLICY_FAIL_MODE", "closed")
    assert external_policy.policy_timeout() == 0.5
    assert external_policy.policy_fail_mode() == "closed"

    monkeypatch.setenv("XCAGI_POLICY_TIMEOUT", "-1")
    monkeypatch.setenv("XCAGI_POLICY_FAIL_MODE", "unknown")
    assert external_policy.policy_timeout() == 2.0
    assert external_policy.policy_fail_mode() == "open"


def test_safe_context_drops_sensitive_fields() -> None:
    filtered = external_policy.safe_context(
        {
            "tenant_id": "tenant-1",
            "mod_id": "mod-1",
            "actor_role": "owner",
            "ui_surface": "desktop",
            "api_token": "secret-token",
            "password": "secret-password",
            "authorization": "Bearer secret",
            "nested": {"token": "secret"},
        }
    )
    assert filtered == {
        "tenant_id": "tenant-1",
        "mod_id": "mod-1",
        "actor_role": "owner",
        "ui_surface": "desktop",
    }


def test_external_policy_deny_blocks_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_POLICY_URL", POLICY_URL)
    monkeypatch.setenv("XCAGI_POLICY_TOKEN", "policy-token")
    calls = _install_post(
        monkeypatch,
        lambda url, kwargs: _result(allow=False, reason="租户策略禁止该动作"),
    )

    decision = HybridRiskGate().evaluate(
        _plan(), {"tenant_id": "tenant-1", "api_token": "must-not-leak"}
    )

    assert decision.allowed is False
    assert decision.decision == "blocked"
    assert decision.requires_confirmation is False
    assert "外置策略拒绝" in decision.reason
    assert "租户策略禁止该动作" in decision.reason

    sent = calls[0]
    assert sent["url"] == POLICY_URL
    assert sent["json"]["input"]["context"] == {"tenant_id": "tenant-1"}
    assert sent["json"]["input"]["actions"] == [
        {
            "action": "products.query",
            "tool_id": "products",
            "operation": "query",
            "risk_level": "low",
        }
    ]
    assert "must-not-leak" not in str(sent["json"])
    assert sent["headers"]["Authorization"] == "Bearer policy-token"


def test_network_failure_fail_open_matches_builtin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XCAGI_POLICY_URL", raising=False)
    baseline = HybridRiskGate().evaluate(_plan(), {}).to_dict()

    monkeypatch.setenv("XCAGI_POLICY_URL", POLICY_URL)
    monkeypatch.setenv("XCAGI_POLICY_FAIL_MODE", "open")

    def boom(url: str, kwargs: dict[str, Any]) -> _FakeResponse:
        raise httpx.ConnectError("policy service down")

    _install_post(monkeypatch, boom)
    decision = HybridRiskGate().evaluate(_plan(), {})

    assert decision.to_dict() == baseline


def test_network_failure_fail_closed_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_POLICY_URL", POLICY_URL)
    monkeypatch.setenv("XCAGI_POLICY_FAIL_MODE", "closed")

    def boom(url: str, kwargs: dict[str, Any]) -> _FakeResponse:
        raise httpx.ReadTimeout("policy service timeout")

    _install_post(monkeypatch, boom)
    decision = HybridRiskGate().evaluate(_plan(), {})

    assert decision.allowed is False
    assert decision.decision == "blocked"
    assert decision.requires_confirmation is False
    assert "策略服务不可用" in decision.reason


def test_malformed_response_fail_open_matches_builtin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XCAGI_POLICY_URL", raising=False)
    baseline = HybridRiskGate().evaluate(_plan(), {}).to_dict()

    monkeypatch.setenv("XCAGI_POLICY_URL", POLICY_URL)
    monkeypatch.setenv("XCAGI_POLICY_FAIL_MODE", "open")
    _install_post(monkeypatch, lambda url, kwargs: _FakeResponse({"result": "oops"}))

    assert HybridRiskGate().evaluate(_plan(), {}).to_dict() == baseline


def test_external_require_approval_escalates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_POLICY_URL", POLICY_URL)
    _install_post(
        monkeypatch,
        lambda url, kwargs: _result(allow=True, require_approval=True, reason="高风险租户"),
    )

    decision = HybridRiskGate().evaluate(_plan(), {})

    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.decision == "require_human"
    assert decision.blocking_nodes == ["read"]
    assert "外置策略要求人工审批" in decision.reason


def test_external_allow_does_not_relax_builtin_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_POLICY_URL", POLICY_URL)
    _install_post(monkeypatch, lambda url, kwargs: _result(allow=True))

    decision = HybridRiskGate().evaluate(_plan(tool_id="unregistered_tool"), {})

    assert decision.allowed is False
    assert decision.decision == "blocked"
    assert decision.reason == "plan contains actions denied by autonomy_guard"
