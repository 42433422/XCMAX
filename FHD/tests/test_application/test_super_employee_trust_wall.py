"""超级员工信任墙端到端守卫：产品域被结构性收紧，工厂域保持全权。

覆盖图里那四层纵深（工作区 / 凭证 / 工具面 / 派工不泄密），任一退化即 CI 红。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.application.claude_super_employee_service import ClaudeSuperEmployeeService
from app.application.execution_scope import (
    FACTORY_TOKEN_ENV,
    CapabilityGrant,
    ExecutionScope,
    factory_context,
)
from app.application.workspaces import get_workspace_registry


@pytest.fixture
def repo_root() -> Path:
    return get_workspace_registry().get("xcmax").root


def _svc() -> ClaudeSuperEmployeeService:
    return ClaudeSuperEmployeeService()


# ── 工作区层：产品域绝不落到服务端工程树 ──


def test_product_cwd_never_inside_repo_even_if_client_points_there(repo_root):
    svc = _svc()
    svc._grant = CapabilityGrant.product()
    # 客户试图把 workspace_root 指向服务端 repo（或任意宿主路径）—— 产品域一律忽略，用隔离临时区。
    cwd = Path(svc._cli_workspace({"workspace_root": str(repo_root)}))
    assert cwd.resolve() != repo_root.resolve()
    assert repo_root.resolve() not in cwd.resolve().parents
    # 产品域 cwd 恒为隔离临时区，与客户传入路径无关（防 path-injection）。
    assert str(cwd) == svc._product_ephemeral_workspace()


def test_factory_cwd_resolves_to_workspace_root(repo_root):
    svc = _svc()
    svc._grant = CapabilityGrant(ExecutionScope.FACTORY, "xcmax")
    cwd = Path(svc._cli_workspace({"request_id": "t1"}))
    assert cwd.resolve() == repo_root.resolve()


# ── 工具面层：产品域禁写/执行类工具，工厂域不限 ──


def test_product_cmd_is_restricted():
    svc = _svc()
    svc._grant = CapabilityGrant.product()
    cmd = svc._conversation_cmd("/bin/claude", "hi", None)
    assert "--disallowedTools" in cmd
    assert "default" in cmd  # 权限模式降到 default
    assert "acceptEdits" not in cmd
    assert "bypassPermissions" not in cmd


def test_factory_cmd_is_unrestricted():
    svc = _svc()
    svc._grant = CapabilityGrant(ExecutionScope.FACTORY, "xcmax")
    cmd = svc._conversation_cmd("/bin/claude", "hi", None)
    assert "--disallowedTools" not in cmd
    assert "acceptEdits" in cmd


# ── 凭证层：产品域剥掉平台令牌与 git 凭证 ──


def test_product_subprocess_env_strips_factory_secrets(monkeypatch):
    monkeypatch.setenv(FACTORY_TOKEN_ENV, "platform-secret")
    monkeypatch.setenv("XCMAX_FACTORY_ANYTHING", "x")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_xxx")
    svc = _svc()
    svc._grant = CapabilityGrant.product()
    env = svc._cli_subprocess_env()
    assert env is not None
    assert FACTORY_TOKEN_ENV not in env
    assert "XCMAX_FACTORY_ANYTHING" not in env
    assert "GITHUB_TOKEN" not in env


def test_factory_subprocess_env_keeps_environment(monkeypatch):
    monkeypatch.setenv(FACTORY_TOKEN_ENV, "platform-secret")
    monkeypatch.delenv("XCMAX_CLI_PROXY", raising=False)
    svc = _svc()
    svc._grant = CapabilityGrant(ExecutionScope.FACTORY, "xcmax")
    # 工厂域且无代理：继承环境（返回 None），与历史行为一致，令牌保留。
    assert svc._cli_subprocess_env() is None


# ── 派工层：产品域不暴露工程路径；令牌绝不入派工/持久化载荷 ──


def test_product_dispatch_request_hides_server_path_and_scrubs_token():
    svc = _svc()
    svc._grant = CapabilityGrant.product()
    req = svc._build_dispatch_request(
        request_id="r1",
        created_at="now",
        user_id=1,
        message="修复一下登录",
        context={"_factory_token": "should-not-leak", "source": "admin_im"},
    )
    assert req["workspace_root"] == ""  # 产品域不向远端暴露服务端 repo 路径
    assert req["scope"] == "product"
    assert "_factory_token" not in str(req)  # 令牌被纵深剔除


def test_factory_dispatch_request_carries_workspace(repo_root):
    svc = _svc()
    svc._grant = CapabilityGrant(ExecutionScope.FACTORY, "xcmax")
    req = svc._build_dispatch_request(
        request_id="r2",
        created_at="now",
        user_id=1,
        message="加个接口",
        context={},
    )
    assert req["scope"] == "factory"
    assert req["workspace_id"] == "xcmax"
    assert req["workspace_root"] == str(repo_root)


def test_default_grant_is_product_deny_by_default():
    # 任何绕过 invoke 的实例化路径也落在安全档。
    assert _svc()._grant.scope is ExecutionScope.PRODUCT


# ── 审计层：信任决策留痕（#7）──


def _stub_dispatch(svc, monkeypatch):
    """挡掉网络/CLI 重路径，让 invoke 走到落库 + 审计日志即可。"""
    monkeypatch.setattr(svc, "_should_reply_with_cli", lambda text, ctx: False)
    monkeypatch.setattr(svc, "_dispatch", lambda req: {"status": "queued", "accepted": False})
    monkeypatch.setattr(svc, "_cli_reply_body", lambda text, ctx: "")


def test_factory_dispatch_is_audited(tmp_path, caplog, monkeypatch):
    monkeypatch.setenv(FACTORY_TOKEN_ENV, "platform-secret")
    svc = ClaudeSuperEmployeeService(storage_root=tmp_path)
    _stub_dispatch(svc, monkeypatch)
    with caplog.at_level(logging.INFO):
        svc.invoke(user_id=7, message="加个接口", context=factory_context("xcmax"))
    assert any(
        "factory dispatch" in r.getMessage() and "workspace=xcmax" in r.getMessage()
        for r in caplog.records
    )


def test_rejected_factory_token_warns(tmp_path, caplog, monkeypatch):
    monkeypatch.setenv(FACTORY_TOKEN_ENV, "platform-secret")
    svc = ClaudeSuperEmployeeService(storage_root=tmp_path)
    _stub_dispatch(svc, monkeypatch)
    with caplog.at_level(logging.WARNING):
        # 带令牌却不匹配 → 降级产品域 + 警告留痕（可疑越权尝试）。
        svc.invoke(user_id=7, message="hi", context={"_factory_token": "wrong-guess"})
    assert any("token rejected" in r.getMessage() for r in caplog.records)
