"""deploy_context：档位归一化与健康负载字段。"""

from __future__ import annotations

import pytest


def test_normalized_deploy_tier_defaults_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODSTORE_DEPLOY_TIER", raising=False)
    monkeypatch.delenv("DEPLOYMENT_ENV", raising=False)
    from modstore_server.deploy_context import normalized_deploy_tier

    assert normalized_deploy_tier() == "local"


def test_normalized_deploy_tier_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    from modstore_server.deploy_context import is_production_tier, normalized_deploy_tier

    monkeypatch.setenv("MODSTORE_DEPLOY_TIER", "prod")
    assert normalized_deploy_tier() == "production"
    assert is_production_tier() is True

    monkeypatch.setenv("MODSTORE_DEPLOY_TIER", "sandbox")
    assert normalized_deploy_tier() == "staging"
    assert is_production_tier() is False


def test_health_payload_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_DEPLOY_TIER", "staging")
    from modstore_server.deploy_context import health_payload

    d = health_payload()
    assert d["deploy_tier"] == "staging"
    assert "git_sha" in d and isinstance(d["git_sha"], str)
    assert "hostname" in d
