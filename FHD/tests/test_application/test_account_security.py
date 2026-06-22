"""账户安全：登录失败锁定 + TOTP(MFA) 单元测试。"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from app.application import account_security as s
from app.utils.time import utc_now_naive


class TestLockout:
    def test_lock_after_threshold(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MAX_LOGIN_ATTEMPTS", "3")
        u = SimpleNamespace(failed_login_attempts=0, locked_until=None)
        assert s.register_failed_attempt(u) is False
        assert s.register_failed_attempt(u) is False
        assert s.register_failed_attempt(u) is True  # 第 3 次触发锁定
        assert s.is_locked(u) is True
        assert s.lock_remaining_seconds(u) > 0
        assert u.failed_login_attempts == 0  # 锁定后计数清零

    def test_reset(self):
        u = SimpleNamespace(
            failed_login_attempts=5, locked_until=utc_now_naive() + timedelta(minutes=5)
        )
        s.reset_failed_attempts(u)
        assert u.failed_login_attempts == 0
        assert u.locked_until is None
        assert s.is_locked(u) is False

    def test_expired_lock_not_locked(self):
        u = SimpleNamespace(
            failed_login_attempts=0, locked_until=utc_now_naive() - timedelta(minutes=1)
        )
        assert s.is_locked(u) is False
        assert s.lock_remaining_seconds(u) == 0


class TestTotp:
    def test_roundtrip(self):
        sec = s.generate_totp_secret()
        assert s.verify_totp(sec, s.totp_now(sec)) is True

    def test_window_tolerance(self):
        sec = s.generate_totp_secret()
        # 上一时间步生成的码，在 window=1 容差内仍有效
        assert s.verify_totp(sec, s.totp_now(sec, at=1000), at=1030) is True

    def test_reject_invalid(self):
        sec = s.generate_totp_secret()
        assert s.verify_totp(sec, "000000") is False
        assert s.verify_totp(sec, "") is False
        assert s.verify_totp("", "123456") is False
        assert s.verify_totp(sec, "abc") is False

    def test_provisioning_uri(self):
        sec = s.generate_totp_secret()
        uri = s.provisioning_uri(sec, "alice", issuer="XCMAX")
        assert uri.startswith("otpauth://totp/")
        assert f"secret={sec}" in uri
        assert "issuer=XCMAX" in uri
