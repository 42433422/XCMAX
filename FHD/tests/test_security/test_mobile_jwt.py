"""移动端 JWT 安全回归测试（P0-1）。

锁定：PyJWT 算法白名单（拒绝 ``alg=none`` 与非 HS256）、iss/aud 校验、
refresh token 一次性使用（重放拒绝）、无硬编码回退密钥。
"""

from __future__ import annotations

import inspect

import jwt
import pytest

from app.security import mobile_jwt as m


@pytest.fixture(autouse=True)
def _stable_secret(monkeypatch):
    # 固定密钥，使签发/验证一致；并隔离每个用例的 refresh jti 黑名单。
    monkeypatch.setenv("SECRET_KEY", "unit-test-secret-key-32-bytes-min-aaaa")
    m._used_refresh_jti.clear()
    yield
    m._used_refresh_jti.clear()


class TestIssueVerify:
    def test_round_trip_access_token(self):
        toks = m.issue_mobile_tokens(user_id=42, session_id="sess-1", username="alice")
        payload = m.verify_mobile_jwt(toks["access_token"])
        assert payload is not None
        assert payload["typ"] == "access"
        assert payload["user_id"] == 42
        assert payload["aud"] == m.MOBILE_JWT_AUD
        assert payload["iss"] == m.MOBILE_JWT_ISS

    def test_bearer_helper_extracts_user_id(self):
        toks = m.issue_mobile_tokens(user_id=7, session_id="s")
        assert m.user_id_from_mobile_bearer(f"Bearer {toks['access_token']}") == 7
        assert m.user_id_from_mobile_bearer("garbage") is None
        assert m.user_id_from_mobile_bearer(None) is None


class TestAlgorithmConfusion:
    def test_rejects_alg_none(self):
        # 无签名 (alg=none) token 必须被拒绝（算法混淆攻击）。
        forged = jwt.encode(
            {"user_id": 1, "typ": "access", "aud": m.MOBILE_JWT_AUD, "iss": m.MOBILE_JWT_ISS},
            key="",
            algorithm="none",
        )
        assert m.verify_mobile_jwt(forged) is None

    def test_rejects_non_hs256_algorithm(self):
        # 用白名单之外的算法（HS512）签发，即便密钥正确也应被拒。
        secret = m._secret_key()
        forged = jwt.encode(
            {"user_id": 1, "typ": "access", "aud": m.MOBILE_JWT_AUD, "iss": m.MOBILE_JWT_ISS},
            secret,
            algorithm="HS512",
        )
        assert m.verify_mobile_jwt(forged) is None

    def test_rejects_wrong_issuer_and_audience(self):
        secret = m._secret_key()
        wrong_iss = jwt.encode(
            {"user_id": 1, "typ": "access", "aud": m.MOBILE_JWT_AUD, "iss": "evil"},
            secret,
            algorithm=m.MOBILE_JWT_ALG,
        )
        wrong_aud = jwt.encode(
            {"user_id": 1, "typ": "access", "aud": "other-app", "iss": m.MOBILE_JWT_ISS},
            secret,
            algorithm=m.MOBILE_JWT_ALG,
        )
        assert m.verify_mobile_jwt(wrong_iss) is None
        assert m.verify_mobile_jwt(wrong_aud) is None

    def test_rejects_missing_required_claims(self):
        secret = m._secret_key()
        # 无 exp/aud/iss，options.require 应触发拒绝。
        forged = jwt.encode({"user_id": 1, "typ": "access"}, secret, algorithm=m.MOBILE_JWT_ALG)
        assert m.verify_mobile_jwt(forged) is None


class TestRefreshOneTimeUse:
    def test_refresh_rotates_then_rejects_replay(self):
        toks = m.issue_mobile_tokens(user_id=9, session_id="s9")
        rotated = m.refresh_mobile_access_token(toks["refresh_token"])
        assert rotated is not None
        assert "access_token" in rotated and "refresh_token" in rotated
        # 重放同一 refresh token 必须被拒绝（一次性使用）。
        assert m.refresh_mobile_access_token(toks["refresh_token"]) is None

    def test_access_token_cannot_be_used_as_refresh(self):
        toks = m.issue_mobile_tokens(user_id=9, session_id="s9")
        assert m.refresh_mobile_access_token(toks["access_token"]) is None


class TestNoHardcodedSecret:
    def test_module_source_has_no_predictable_fallback(self):
        src = inspect.getsource(m)
        # 仅当作为代码中的字符串字面量使用时才算违规；文档注释里提及旧值无妨。
        assert '"xcagi-dev-secret"' not in src
        assert "'xcagi-dev-secret'" not in src

    def test_unset_secret_uses_unpredictable_random_fallback(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        # 回退密钥应是进程级随机值，而非可预测常量。
        assert m._FALLBACK_SECRET
        assert m._FALLBACK_SECRET != "xcagi-dev-secret"
        assert len(m._FALLBACK_SECRET) >= 32
