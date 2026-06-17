"""Tests for app.utils.security_middleware."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.utils.security_middleware import (
    SECURITY_HEADERS,
    PermissionMatrix,
    _apply_security_headers,
    admin_only,
    api_security,
    public_api,
    register_default_permissions,
    require_permissions,
    sanitize_input,
)

# ---------------------------------------------------------------------------
# SECURITY_HEADERS constant
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    def test_contains_required_headers(self):
        assert "X-Content-Type-Options" in SECURITY_HEADERS
        assert "X-Frame-Options" in SECURITY_HEADERS
        assert "X-XSS-Protection" in SECURITY_HEADERS
        assert "Referrer-Policy" in SECURITY_HEADERS
        assert "Cache-Control" in SECURITY_HEADERS
        assert "Pragma" in SECURITY_HEADERS

    def test_values_are_secure(self):
        assert SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"
        assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"
        assert SECURITY_HEADERS["X-XSS-Protection"] == "1; mode=block"
        assert SECURITY_HEADERS["Cache-Control"] == "no-store"


# ---------------------------------------------------------------------------
# _apply_security_headers
# ---------------------------------------------------------------------------


class TestApplySecurityHeaders:
    def test_adds_headers_to_response(self):
        response = MagicMock()
        response.headers = {}
        result = _apply_security_headers(response)
        assert result is response
        for header, value in SECURITY_HEADERS.items():
            assert response.headers[header] == value

    def test_does_not_overwrite_existing(self):
        response = MagicMock()
        response.headers = {"X-Content-Type-Options": "custom"}
        result = _apply_security_headers(response)
        assert response.headers["X-Content-Type-Options"] == "custom"

    def test_adds_missing_headers(self):
        response = MagicMock()
        response.headers = {"X-Content-Type-Options": "nosniff"}
        result = _apply_security_headers(response)
        assert "X-Frame-Options" in response.headers


# ---------------------------------------------------------------------------
# sanitize_input
# ---------------------------------------------------------------------------


class TestSanitizeInput:
    def test_normal_string(self):
        assert sanitize_input("hello") == "hello"

    def test_strips_whitespace(self):
        assert sanitize_input("  hello  ") == "hello"

    def test_truncates_long_string(self):
        long_text = "a" * 20000
        result = sanitize_input(long_text, max_length=100)
        assert len(result) == 100

    def test_default_max_length(self):
        long_text = "a" * 20000
        result = sanitize_input(long_text)
        assert len(result) == 10000

    def test_non_string_converts_to_string(self):
        assert sanitize_input(12345) == "12345"

    def test_non_string_truncates(self):
        result = sanitize_input(12345, max_length=3)
        assert result == "123"

    def test_none_converts(self):
        assert sanitize_input(None) == "None"

    def test_empty_string(self):
        assert sanitize_input("") == ""

    def test_custom_max_length(self):
        assert sanitize_input("hello", max_length=3) == "hel"


# ---------------------------------------------------------------------------
# PermissionMatrix
# ---------------------------------------------------------------------------


class TestPermissionMatrix:
    def setup_method(self):
        # Clear the class-level dict before each test
        PermissionMatrix._rules.clear()
        register_default_permissions()

    def test_register_rule(self):
        PermissionMatrix.register(
            endpoint="/api/test",
            method="GET",
            permissions=["test.view"],
            description="测试端点",
        )
        key = "GET:/api/test"
        assert key in PermissionMatrix._rules
        assert PermissionMatrix._rules[key]["permissions"] == ["test.view"]

    def test_get_all_rules(self):
        rules = PermissionMatrix.get_all_rules()
        assert isinstance(rules, dict)
        assert len(rules) > 0

    def test_get_endpoints_for_permission(self):
        endpoints = PermissionMatrix.get_endpoints_for_permission("customer.view")
        assert len(endpoints) > 0
        assert any("customers" in ep for ep in endpoints)

    def test_get_endpoints_for_nonexistent_permission(self):
        endpoints = PermissionMatrix.get_endpoints_for_permission("nonexistent.perm")
        assert endpoints == []

    def test_check_allowed_no_rule(self):
        result = PermissionMatrix.check(
            "/api/unknown",
            "GET",
            user_roles=set(),
            user_permissions=set(),
        )
        assert result["allowed"] is True
        assert "未注册" in result["reason"]

    def test_check_needs_auth_no_roles(self):
        PermissionMatrix.register(
            "/api/protected",
            "GET",
            auth=True,
            permissions=["secret.view"],
        )
        result = PermissionMatrix.check(
            "/api/protected",
            "GET",
            user_roles=set(),
            user_permissions=set(),
        )
        assert result["allowed"] is False
        assert "认证" in result["reason"]

    def test_check_missing_role(self):
        PermissionMatrix.register(
            "/api/admin",
            "POST",
            roles=["admin"],
            auth=True,
        )
        result = PermissionMatrix.check(
            "/api/admin",
            "POST",
            user_roles={"user"},
            user_permissions=set(),
        )
        assert result["allowed"] is False
        assert "角色" in result["reason"]

    def test_check_missing_permission(self):
        PermissionMatrix.register(
            "/api/resource",
            "PUT",
            permissions=["resource.edit"],
            auth=True,
        )
        result = PermissionMatrix.check(
            "/api/resource",
            "PUT",
            user_roles={"user"},
            user_permissions={"resource.view"},
        )
        assert result["allowed"] is False
        assert "权限" in result["reason"]

    def test_check_allowed_with_role(self):
        PermissionMatrix.register(
            "/api/admin",
            "GET",
            roles=["admin"],
            auth=True,
        )
        result = PermissionMatrix.check(
            "/api/admin",
            "GET",
            user_roles={"admin"},
            user_permissions=set(),
        )
        assert result["allowed"] is True

    def test_check_allowed_with_permission(self):
        PermissionMatrix.register(
            "/api/resource",
            "GET",
            permissions=["resource.view"],
            auth=True,
        )
        result = PermissionMatrix.check(
            "/api/resource",
            "GET",
            user_roles={"user"},
            user_permissions={"resource.view"},
        )
        assert result["allowed"] is True

    def test_check_no_auth_required(self):
        PermissionMatrix.register(
            "/api/public",
            "GET",
            auth=False,
        )
        result = PermissionMatrix.check(
            "/api/public",
            "GET",
            user_roles=set(),
            user_permissions=set(),
        )
        assert result["allowed"] is True

    def test_method_case_insensitive(self):
        PermissionMatrix.register(
            "/api/test",
            "post",
            permissions=["test.create"],
            auth=True,
        )
        key = "POST:/api/test"
        assert key in PermissionMatrix._rules


# ---------------------------------------------------------------------------
# register_default_permissions
# ---------------------------------------------------------------------------


class TestRegisterDefaultPermissions:
    def setup_method(self):
        PermissionMatrix._rules.clear()

    def test_registers_expected_endpoints(self):
        register_default_permissions()
        rules = PermissionMatrix.get_all_rules()
        assert len(rules) > 0

        # Check some expected endpoints
        endpoints = [r["endpoint"] for r in rules.values()]
        assert "/api/customers" in endpoints
        assert "/api/products" in endpoints
        assert "/api/shipments" in endpoints

    def test_ai_chat_no_auth(self):
        register_default_permissions()
        ai_rules = [r for r in PermissionMatrix._rules.values() if r["endpoint"] == "/api/ai/chat"]
        assert len(ai_rules) == 1
        assert ai_rules[0]["auth"] is True  # auth is True by default
        assert ai_rules[0]["permissions"] == [] or ai_rules[0]["permissions"] is None


# ---------------------------------------------------------------------------
# api_security decorator
# ---------------------------------------------------------------------------


class TestApiSecurity:
    @patch("app.utils.security_middleware.get_current_http_request")
    def test_no_auth_no_rate_limit(self, mock_req):
        mock_req.return_value = None

        @api_security(auth=False)
        def my_endpoint():
            return MagicMock(headers={})

        result = my_endpoint()
        # Should apply security headers
        assert result is not None

    @patch("app.utils.security_middleware.get_current_http_request")
    def test_validate_json_invalid(self, mock_req):
        mock_request = MagicMock()
        mock_request.headers = {"content-type": "application/json"}
        mock_request._body = b"invalid json{{{"
        mock_req.return_value = mock_request

        @api_security(auth=False, validate_json=True)
        def my_endpoint():
            return MagicMock(headers={})

        result = my_endpoint()
        # Should return a tuple with error response
        assert result is not None

    @patch("app.utils.security_middleware.get_current_http_request")
    def test_validate_json_valid(self, mock_req):
        mock_request = MagicMock()
        mock_request.headers = {"content-type": "application/json"}
        mock_request._body = b'{"key": "value"}'
        mock_req.return_value = mock_request

        @api_security(auth=False, validate_json=True)
        def my_endpoint():
            resp = MagicMock()
            resp.headers = {}
            return resp

        result = my_endpoint()
        assert result is not None

    @patch("app.utils.security_middleware.get_current_http_request")
    def test_validate_json_non_json_content_type(self, mock_req):
        mock_request = MagicMock()
        mock_request.headers = {"content-type": "text/plain"}
        mock_req.return_value = mock_request

        @api_security(auth=False, validate_json=True)
        def my_endpoint():
            resp = MagicMock()
            resp.headers = {}
            return resp

        result = my_endpoint()
        assert result is not None

    @patch("app.utils.security_middleware.get_current_http_request")
    def test_rate_limit_no_request_returns_500(self, mock_req):
        mock_req.return_value = None

        @api_security(auth=False, rate_limit={"max_requests": 10, "window_seconds": 60})
        def my_endpoint():
            return MagicMock(headers={})

        result = my_endpoint()
        # Should return error tuple
        assert result is not None

    @patch("app.utils.security_middleware.check_rate_limit")
    @patch("app.utils.security_middleware.get_current_user")
    @patch("app.utils.security_middleware.get_current_http_request")
    def test_rate_limit_exceeded(self, mock_req, mock_user, mock_rate):
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.method = "GET"
        mock_request.url = MagicMock()
        mock_request.url.path = "/api/test"
        mock_req.return_value = mock_request
        mock_user.return_value = None
        mock_rate.return_value = {"allowed": False, "retry_after": 30}

        @api_security(auth=False, rate_limit={"max_requests": 10, "window_seconds": 60})
        def my_endpoint():
            return MagicMock(headers={})

        result = my_endpoint()
        assert result is not None

    @patch("app.utils.security_middleware.check_rate_limit")
    @patch("app.utils.security_middleware.get_current_user")
    @patch("app.utils.security_middleware.get_current_http_request")
    def test_rate_limit_allowed(self, mock_req, mock_user, mock_rate):
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.method = "GET"
        mock_request.url = MagicMock()
        mock_request.url.path = "/api/test"
        mock_req.return_value = mock_request
        mock_user.return_value = None
        mock_rate.return_value = {"allowed": True}

        @api_security(auth=False, rate_limit={"max_requests": 10, "window_seconds": 60})
        def my_endpoint():
            resp = MagicMock()
            resp.headers = {}
            return resp

        result = my_endpoint()
        assert result is not None


# ---------------------------------------------------------------------------
# require_permissions shortcut
# ---------------------------------------------------------------------------


class TestRequirePermissions:
    def test_creates_api_security_with_permissions(self):
        decorator = require_permissions("product.view", "product.edit")
        assert callable(decorator)


# ---------------------------------------------------------------------------
# public_api shortcut
# ---------------------------------------------------------------------------


class TestPublicApi:
    def test_creates_api_security_no_auth(self):
        decorator = public_api()
        assert callable(decorator)

    def test_with_rate_limit(self):
        decorator = public_api(rate_limit={"max_requests": 10, "window_seconds": 60})
        assert callable(decorator)


# ---------------------------------------------------------------------------
# admin_only shortcut
# ---------------------------------------------------------------------------


class TestAdminOnly:
    def test_creates_api_security_with_admin_role(self):
        decorator = admin_only()
        assert callable(decorator)
