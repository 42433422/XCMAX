"""执行信任域 :mod:`app.application.execution_scope` 的安全不变量守卫。

把"deny-by-default + 令牌不可伪造 + 闸门硬拒"钉死成回归门。
"""

from __future__ import annotations

import pytest

from app.application.execution_scope import (
    FACTORY_TOKEN_ENV,
    CapabilityGrant,
    ExecutionScope,
    factory_context,
    require_factory_capability,
)


def test_resolve_defaults_to_product_without_token(monkeypatch):
    monkeypatch.delenv(FACTORY_TOKEN_ENV, raising=False)
    assert CapabilityGrant.resolve({}).scope is ExecutionScope.PRODUCT
    assert CapabilityGrant.resolve(None).scope is ExecutionScope.PRODUCT
    # 即便客户在请求体里塞 factory token，没有配置平台密钥也无效。
    assert CapabilityGrant.resolve({"_factory_token": "anything"}).scope is ExecutionScope.PRODUCT


def test_resolve_factory_only_with_exact_platform_token(monkeypatch):
    monkeypatch.setenv(FACTORY_TOKEN_ENV, "platform-secret")
    ok = CapabilityGrant.resolve({"_factory_token": "platform-secret", "workspace_id": "xcmax"})
    assert ok.scope is ExecutionScope.FACTORY
    assert ok.workspace_id == "xcmax"
    # 错令牌一律降级（不可伪造）。
    assert CapabilityGrant.resolve({"_factory_token": "guess"}).scope is ExecutionScope.PRODUCT
    assert CapabilityGrant.resolve({"_factory_token": ""}).scope is ExecutionScope.PRODUCT


def test_factory_context_omits_token_when_platform_key_unset(monkeypatch):
    monkeypatch.delenv(FACTORY_TOKEN_ENV, raising=False)
    ctx = factory_context("xcmax")
    # 未配密钥 == 工厂禁用：返回的 context 不含令牌，resolve 仍判产品域。
    assert "_factory_token" not in ctx
    assert CapabilityGrant.resolve(ctx).scope is ExecutionScope.PRODUCT


def test_factory_context_injects_token_when_configured(monkeypatch):
    monkeypatch.setenv(FACTORY_TOKEN_ENV, "platform-secret")
    ctx = factory_context("repo-2", base={"source": "admin_im"})
    assert ctx["_factory_token"] == "platform-secret"
    assert ctx["workspace_id"] == "repo-2"
    assert ctx["source"] == "admin_im"  # 保留 base 字段
    assert CapabilityGrant.resolve(ctx).scope is ExecutionScope.FACTORY


def test_require_factory_capability_gate():
    require_factory_capability(CapabilityGrant(ExecutionScope.FACTORY, "xcmax"))  # 不抛
    with pytest.raises(PermissionError):
        require_factory_capability(CapabilityGrant.product())
    with pytest.raises(PermissionError):
        require_factory_capability(None)  # type: ignore[arg-type]
