"""Web 端无状态 JWT（签发 / 验证 / refresh 轮转 / flag 门控）单元测试。"""

from __future__ import annotations

from app.security import web_jwt as w


class TestWebJwt:
    def test_issue_and_verify(self):
        toks = w.issue_web_tokens(user_id=7, username="bob", account_kind="enterprise")
        assert "access_token" in toks and "refresh_token" in toks
        payload = w.verify_web_jwt(toks["access_token"])
        assert payload is not None
        assert payload["typ"] == "access"
        assert payload["user_id"] == 7
        assert payload["account_kind"] == "enterprise"

    def test_verify_rejects_garbage(self):
        assert w.verify_web_jwt("not.a.jwt") is None
        assert w.verify_web_jwt("") is None

    def test_refresh_rotation_one_time(self):
        toks = w.issue_web_tokens(user_id=7)
        rotated = w.refresh_web_access_token(toks["refresh_token"])
        assert rotated is not None and "access_token" in rotated
        # 一次性：同一 refresh 不能复用
        assert w.refresh_web_access_token(toks["refresh_token"]) is None

    def test_access_token_cannot_refresh(self):
        toks = w.issue_web_tokens(user_id=7)
        assert w.refresh_web_access_token(toks["access_token"]) is None

    def test_resolve_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_WEB_JWT_AUTH", raising=False)
        toks = w.issue_web_tokens(user_id=7)
        assert w.web_jwt_auth_enabled() is False
        # flag 关闭时不查库、直接返回 None（保持有状态 session 行为）
        assert w.resolve_user_from_web_jwt(toks["access_token"]) is None

    def test_flag_enabled_detection(self, monkeypatch):
        monkeypatch.setenv("XCAGI_WEB_JWT_AUTH", "1")
        assert w.web_jwt_auth_enabled() is True
