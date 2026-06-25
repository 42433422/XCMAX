"""auth_schema / common_schema Pydantic 模型单元测试。"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.auth_schema import (
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    TokenRefreshRequest,
    UserInfo,
)
from app.schemas.common_schema import ErrorResponse, PaginationMeta, SuccessResponse


class TestAuthSchema:
    def test_login_request_strips_username(self):
        req = LoginRequest(username="  alice  ", password="secret")
        assert req.username == "alice"

    def test_login_request_blank_username_raises(self):
        with pytest.raises(ValidationError):
            LoginRequest(username="   ", password="x")

    def test_login_response_defaults(self):
        resp = LoginResponse()
        assert resp.success is True
        assert resp.token_type == "bearer"
        assert resp.expires_in == 3600

    def test_token_refresh_request(self):
        req = TokenRefreshRequest(refresh_token="rtok")
        assert req.refresh_token == "rtok"

    def test_user_info_from_attributes(self):
        info = UserInfo(id=1, username="u", email="a@b.c", roles=["admin"])
        assert info.roles == ["admin"]

    def test_password_change_too_short_raises(self):
        with pytest.raises(ValidationError):
            PasswordChangeRequest(old_password="old", new_password="12345")

    def test_password_change_ok(self):
        req = PasswordChangeRequest(old_password="old", new_password="123456")
        assert len(req.new_password) >= 6


class TestCommonSchema:
    def test_error_response(self):
        err = ErrorResponse(message="fail", error_code="E1")
        assert err.success is False
        assert err.details is None

    def test_success_response_defaults(self):
        ok = SuccessResponse()
        assert ok.success is True
        assert ok.message == "操作成功"

    def test_pagination_meta(self):
        meta = PaginationMeta(total=100, page=2, per_page=20, total_pages=5)
        assert meta.total_pages == 5
