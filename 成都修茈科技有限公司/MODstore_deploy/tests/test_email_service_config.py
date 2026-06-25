"""``email_service`` 配置识别 + 管理员排障 API 单测。

覆盖：

- ``_looks_like_placeholder`` 各类占位符 / 真实值
- ``assert_email_outbound_configured``：DEBUG / 已配置 / 未配置 / 占位符 各分支
- ``email_status``：``mode`` 字段（debug/smtp/unconfigured）
- 管理员 API：非管理员 403、status 脱敏、test 发邮件 monkeypatch
- ``send_verification_email`` DEBUG 模式不连 SMTP，未配置抛 RuntimeError
"""

from __future__ import annotations

import os
import types
import uuid

import pytest

pytest.importorskip("fastapi")


# ----------------------------- pure helpers ----------------------------- #


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", True),
        ("   ", True),
        ("your-qq-smtp-auth-code", True),
        ("your-qq-smtp-password", True),
        ("YOUR-API-KEY", True),
        ("CHANGE_ME", True),
        ("change_me", True),
        ("change-this-secret", True),
        ("change-me-please", True),
        ("placeholder", True),
        ("TODO", True),
        ("xxxxxxxxxxxxx", True),
        ("请填写", True),
        ("real@qq.com", False),
        ("ge8nKdsLxxAxNmbg", False),  # 含 2 个 xx 不算占位符（真凭证常见模式）
        ("970882904@qq.com", False),
        ("abc123-real-token-xxx", False),  # 仅 3 个 x 不够 hint 阈值，避免误伤
    ],
)
def test_looks_like_placeholder(value, expected):
    from modstore_server.email_service import _looks_like_placeholder

    assert _looks_like_placeholder(value) is expected


def test_email_status_unconfigured_when_envs_missing(monkeypatch):
    from modstore_server import email_service as svc

    monkeypatch.delenv("MODSTORE_SMTP_USER", raising=False)
    monkeypatch.delenv("MODSTORE_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("MODSTORE_EMAIL_DEBUG", raising=False)
    monkeypatch.setattr(svc, "_load_modstore_env", lambda: None)

    s = svc.email_status()
    assert s["mode"] == "unconfigured"
    assert s["configured"] is False
    assert s["debug"] is False
    assert s["password_set"] is False


def test_email_status_unconfigured_when_placeholder(monkeypatch):
    from modstore_server import email_service as svc

    monkeypatch.setenv("MODSTORE_SMTP_USER", "real@qq.com")
    monkeypatch.setenv("MODSTORE_SMTP_PASSWORD", "your-qq-smtp-auth-code")
    monkeypatch.delenv("MODSTORE_EMAIL_DEBUG", raising=False)
    monkeypatch.setattr(svc, "_load_modstore_env", lambda: None)

    s = svc.email_status()
    assert s["mode"] == "unconfigured"
    assert s["configured"] is False
    assert s["placeholder_password"] is True
    assert s["password_set"] is False


def test_email_status_debug_mode(monkeypatch):
    from modstore_server import email_service as svc

    monkeypatch.delenv("MODSTORE_SMTP_USER", raising=False)
    monkeypatch.delenv("MODSTORE_SMTP_PASSWORD", raising=False)
    monkeypatch.setenv("MODSTORE_EMAIL_DEBUG", "1")
    monkeypatch.setattr(svc, "_load_modstore_env", lambda: None)

    s = svc.email_status()
    assert s["mode"] == "debug"
    assert s["debug"] is True


def test_email_status_smtp_mode(monkeypatch):
    from modstore_server import email_service as svc

    monkeypatch.setenv("MODSTORE_SMTP_USER", "real@qq.com")
    monkeypatch.setenv("MODSTORE_SMTP_PASSWORD", "ge8nKdsLxxAxNmbg")
    monkeypatch.delenv("MODSTORE_EMAIL_DEBUG", raising=False)
    monkeypatch.setattr(svc, "_load_modstore_env", lambda: None)

    s = svc.email_status()
    assert s["mode"] == "smtp"
    assert s["configured"] is True


def test_load_modstore_env_reads_synced_then_local(tmp_path, monkeypatch):
    from modstore_server.env_loader import load_modstore_env

    (tmp_path / ".env").write_text(
        "MODSTORE_SMTP_USER=placeholder@example.com\n"
        "MODSTORE_SMTP_PASSWORD=your-qq-smtp-auth-code\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.production.synced").write_text(
        "MODSTORE_SMTP_USER=real@qq.com\n"
        "MODSTORE_SMTP_PASSWORD=real-secret-123456\n"
        "MODSTORE_RUN_BACKGROUND_JOBS=1\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.local").write_text(
        "MODSTORE_DAILY_DIGEST_ENABLED=1\n" "MODSTORE_RUN_BACKGROUND_JOBS=0\n",
        encoding="utf-8",
    )
    for key in (
        "MODSTORE_SMTP_USER",
        "MODSTORE_SMTP_PASSWORD",
        "MODSTORE_RUN_BACKGROUND_JOBS",
        "MODSTORE_DAILY_DIGEST_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)

    loaded = load_modstore_env(tmp_path, include_synced=True, include_local=True)

    assert len(loaded) == 3
    assert os.environ["MODSTORE_SMTP_USER"] == "real@qq.com"
    assert os.environ["MODSTORE_SMTP_PASSWORD"] == "real-secret-123456"
    assert os.environ["MODSTORE_RUN_BACKGROUND_JOBS"] == "0"
    assert os.environ["MODSTORE_DAILY_DIGEST_ENABLED"] == "1"


def test_assert_email_outbound_configured_passes_in_debug(monkeypatch):
    from modstore_server import email_service as svc

    monkeypatch.setenv("MODSTORE_EMAIL_DEBUG", "1")
    monkeypatch.delenv("MODSTORE_SMTP_USER", raising=False)
    monkeypatch.delenv("MODSTORE_SMTP_PASSWORD", raising=False)
    monkeypatch.setattr(svc, "_load_modstore_env", lambda: None)

    svc.assert_email_outbound_configured()  # 不抛


def test_assert_email_outbound_configured_passes_when_real_smtp(monkeypatch):
    from modstore_server import email_service as svc

    monkeypatch.setenv("MODSTORE_SMTP_USER", "real@qq.com")
    monkeypatch.setenv("MODSTORE_SMTP_PASSWORD", "ge8nKdsLxxAxNmbg")
    monkeypatch.delenv("MODSTORE_EMAIL_DEBUG", raising=False)
    monkeypatch.setattr(svc, "_load_modstore_env", lambda: None)

    svc.assert_email_outbound_configured()  # 不抛


def test_assert_email_outbound_configured_rejects_placeholder(monkeypatch):
    """关键回归：``.env.production`` 的占位符不应被当作已配置。"""
    from modstore_server import email_service as svc

    monkeypatch.setenv("MODSTORE_SMTP_USER", "970882904@qq.com")
    monkeypatch.setenv("MODSTORE_SMTP_PASSWORD", "your-qq-smtp-auth-code")
    monkeypatch.delenv("MODSTORE_EMAIL_DEBUG", raising=False)
    monkeypatch.setattr(svc, "_load_modstore_env", lambda: None)

    with pytest.raises(RuntimeError) as exc:
        svc.assert_email_outbound_configured()
    assert "未配置邮件服务" in str(exc.value)
    assert "MODSTORE_EMAIL_DEBUG" in str(exc.value)


def test_assert_email_outbound_configured_rejects_empty(monkeypatch):
    from modstore_server import email_service as svc

    monkeypatch.delenv("MODSTORE_SMTP_USER", raising=False)
    monkeypatch.delenv("MODSTORE_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("MODSTORE_EMAIL_DEBUG", raising=False)
    monkeypatch.setattr(svc, "_load_modstore_env", lambda: None)

    with pytest.raises(RuntimeError):
        svc.assert_email_outbound_configured()


def test_send_verification_email_debug_does_not_use_smtp(monkeypatch, capsys):
    """DEBUG 模式不应触碰 ``smtplib``；验证码打印到 stdout。"""
    from modstore_server import email_service as svc

    monkeypatch.setenv("MODSTORE_EMAIL_DEBUG", "1")
    monkeypatch.delenv("MODSTORE_SMTP_USER", raising=False)
    monkeypatch.delenv("MODSTORE_SMTP_PASSWORD", raising=False)
    monkeypatch.setattr(svc, "_load_modstore_env", lambda: None)

    def boom(*_args, **_kwargs):
        raise AssertionError("DEBUG 模式不应连 SMTP")

    monkeypatch.setattr(svc.smtplib, "SMTP_SSL", boom)
    svc.send_verification_email("user@example.com", "123456", "register")
    captured = capsys.readouterr().out
    assert "[MODSTORE_EMAIL_DEBUG]" in captured
    assert "123456" in captured


def test_send_verification_email_unconfigured_raises(monkeypatch):
    from modstore_server import email_service as svc

    monkeypatch.delenv("MODSTORE_SMTP_USER", raising=False)
    monkeypatch.delenv("MODSTORE_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("MODSTORE_EMAIL_DEBUG", raising=False)
    monkeypatch.setattr(svc, "_load_modstore_env", lambda: None)

    with pytest.raises(RuntimeError):
        svc.send_verification_email("u@x.com", "123456")


# ----------------------------- admin API ----------------------------- #


def _make_user(is_admin: bool = False):
    from modstore_server.models import User, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        user = User(
            username=f"em_user_{uuid.uuid4().hex[:8]}",
            email=f"em_{uuid.uuid4().hex[:8]}@pytest.local",
            password_hash="x",
            is_admin=is_admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return types.SimpleNamespace(id=user.id, username=user.username, is_admin=is_admin)


def test_status_endpoint_masks_user_and_omits_password(client, monkeypatch):
    from modstore_server import email_admin_api as ea
    from modstore_server.app import app

    monkeypatch.setenv("MODSTORE_SMTP_USER", "alice@example.com")
    monkeypatch.setenv("MODSTORE_SMTP_PASSWORD", "real-secret-1234567890")
    monkeypatch.delenv("MODSTORE_EMAIL_DEBUG", raising=False)
    from modstore_server import email_service as svc

    monkeypatch.setattr(svc, "_load_modstore_env", lambda: None)

    user = _make_user(is_admin=False)
    app.dependency_overrides[ea._get_current_user] = lambda: user
    try:
        r = client.get("/api/admin/email/status")
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "smtp"
        assert body["configured"] is True
        assert body["password_set"] is True
        # 用户名脱敏：a***e@example.com
        assert body["user"].endswith("@example.com")
        assert body["user"] != "alice@example.com"
        assert "***" in body["user"]
        # 不应该出现密码字段
        assert "password" not in body
        assert "real-secret" not in str(body)
    finally:
        app.dependency_overrides.pop(ea._get_current_user, None)


def test_test_endpoint_requires_admin(client, monkeypatch):
    from modstore_server import email_admin_api as ea
    from modstore_server.app import app

    user = _make_user(is_admin=False)
    app.dependency_overrides[ea._require_admin] = lambda: (_ for _ in ()).throw(
        __import__("fastapi").HTTPException(403, "需要管理员权限")
    )
    app.dependency_overrides[ea._get_current_user] = lambda: user
    try:
        r = client.post("/api/admin/email/test", json={"to": "test@example.com"})
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(ea._require_admin, None)
        app.dependency_overrides.pop(ea._get_current_user, None)


def test_test_endpoint_validates_email_format(client, monkeypatch):
    from modstore_server import email_admin_api as ea
    from modstore_server.app import app

    admin = _make_user(is_admin=True)
    app.dependency_overrides[ea._require_admin] = lambda: admin
    app.dependency_overrides[ea._get_current_user] = lambda: admin
    try:
        r = client.post("/api/admin/email/test", json={"to": "not-an-email"})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(ea._require_admin, None)
        app.dependency_overrides.pop(ea._get_current_user, None)


def test_test_endpoint_in_debug_returns_ok_without_smtp(client, monkeypatch):
    """DEBUG 模式：不连 SMTP 也能"成功"，返回 mode=debug。"""
    from modstore_server import email_admin_api as ea
    from modstore_server import email_service as svc
    from modstore_server.app import app

    monkeypatch.setenv("MODSTORE_EMAIL_DEBUG", "1")
    monkeypatch.delenv("MODSTORE_SMTP_USER", raising=False)
    monkeypatch.delenv("MODSTORE_SMTP_PASSWORD", raising=False)
    monkeypatch.setattr(svc, "_load_modstore_env", lambda: None)
    monkeypatch.setattr(
        svc.smtplib,
        "SMTP_SSL",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("DEBUG 不应连 SMTP")),
    )

    admin = _make_user(is_admin=True)
    app.dependency_overrides[ea._require_admin] = lambda: admin
    app.dependency_overrides[ea._get_current_user] = lambda: admin
    try:
        r = client.post("/api/admin/email/test", json={"to": "ok@example.com"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["mode"] == "debug"
    finally:
        app.dependency_overrides.pop(ea._require_admin, None)
        app.dependency_overrides.pop(ea._get_current_user, None)


def test_test_endpoint_returns_400_when_unconfigured(client, monkeypatch):
    """无凭证、未开 DEBUG → 400 + 明确文案，而不是 500。"""
    from modstore_server import email_admin_api as ea
    from modstore_server import email_service as svc
    from modstore_server.app import app

    monkeypatch.delenv("MODSTORE_SMTP_USER", raising=False)
    monkeypatch.delenv("MODSTORE_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("MODSTORE_EMAIL_DEBUG", raising=False)
    monkeypatch.setattr(svc, "_load_modstore_env", lambda: None)

    admin = _make_user(is_admin=True)
    app.dependency_overrides[ea._require_admin] = lambda: admin
    app.dependency_overrides[ea._get_current_user] = lambda: admin
    try:
        r = client.post("/api/admin/email/test", json={"to": "ok@example.com"})
        assert r.status_code == 400
        assert "未配置邮件服务" in r.text
    finally:
        app.dependency_overrides.pop(ea._require_admin, None)
        app.dependency_overrides.pop(ea._get_current_user, None)


def test_digest_now_returns_502_when_digest_not_delivered(client, monkeypatch):
    from modstore_server import email_admin_api as ea
    from modstore_server.app import app

    admin = _make_user(is_admin=True)
    app.dependency_overrides[ea._require_admin] = lambda: admin
    monkeypatch.setattr(
        "modstore_server.daily_digest.run_daily_digest_email",
        lambda: {
            "ok": False,
            "delivered": False,
            "reason": "no_email_delivered",
            "delivery_rows": [{"to": "ops@example.com", "mode": "unconfigured"}],
        },
    )
    try:
        r = client.post("/api/admin/email/digest-now")
        assert r.status_code == 502
        body = r.json()
        assert body["detail"]["reason"] == "no_email_delivered"
        assert body["detail"]["delivery_rows"]
    finally:
        app.dependency_overrides.pop(ea._require_admin, None)


def test_mask_user_helper():
    from modstore_server.email_admin_api import _mask_user

    assert _mask_user("") == ""
    assert _mask_user("a@b.com") == "a***@b.com"
    assert _mask_user("alice@example.com") == "a***e@example.com"
    assert _mask_user("ab@x.cn") == "a***@x.cn"
    assert _mask_user("nopart") == "n***t"
    assert _mask_user("ab") == "***"
