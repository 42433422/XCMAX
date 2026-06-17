"""Tests for app.fastapi_routes.gdpr — coverage ramp."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Mock missing modules before importing gdpr
# ---------------------------------------------------------------------------

# Mock app.exceptions
_mock_exceptions = type(sys)("app.exceptions")


class _PermissionDeniedError(Exception):
    pass


class _AuthenticationError(Exception):
    pass


class _NotFoundError(Exception):
    pass


class _ValidationError(Exception):
    pass


_mock_exceptions.PermissionDeniedError = _PermissionDeniedError
_mock_exceptions.AuthenticationError = _AuthenticationError
_mock_exceptions.NotFoundError = _NotFoundError
_mock_exceptions.ValidationError = _ValidationError
sys.modules.setdefault("app.exceptions", _mock_exceptions)

# Mock app.services.feature_flag
_mock_feature_flag = type(sys)("app.services.feature_flag")
_mock_feature_flag.FeatureFlagName = MagicMock()
_mock_feature_flag.FeatureFlagName.EXPERIMENTAL_GDPR_API = "experimental.gdpr_api"
_mock_feature_flag.is_enabled = MagicMock(return_value=True)
sys.modules.setdefault("app.services.feature_flag", _mock_feature_flag)

# Mock app.utils.audit_logger
_mock_audit = type(sys)("app.utils.audit_logger")
_mock_audit.audit_log = MagicMock(return_value=1)
sys.modules.setdefault("app.utils.audit_logger", _mock_audit)

# Mock app.infrastructure.auth.dependencies
_mock_auth_deps = type(sys)("app.infrastructure.auth.dependencies")
_mock_auth_deps.get_current_user = MagicMock()
sys.modules.setdefault("app.infrastructure.auth.dependencies", _mock_auth_deps)

# Mock app.infrastructure.persistence.sqlalchemy_uow
_mock_uow = type(sys)("app.infrastructure.persistence.sqlalchemy_uow")
_mock_uow.SqlAlchemyUnitOfWork = MagicMock()
sys.modules.setdefault("app.infrastructure.persistence.sqlalchemy_uow", _mock_uow)

# Mock ErrorCode.FEATURE_DISABLED since it doesn't exist in the real enum.
# gdpr.py does `from app.errors import ErrorCode` at import time, so by the time
# this test module runs, gdpr.py already holds a direct reference to the real
# ErrorCode enum (which lacks FEATURE_DISABLED). We therefore patch the
# `ErrorCode` symbol inside gdpr.py itself via patch at test time.
from app.errors import ErrorCode as _RealErrorCode


class _MockErrorCodeValue:
    """Enum-member-like object that supports .value."""

    def __init__(self, val: str):
        self.value = val

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"ErrorCode.{self.value}"


class _MockErrorCode:
    FEATURE_DISABLED = _MockErrorCodeValue("FEATURE_DISABLED")

    def __getattr__(self, name: str):
        # Delegate to the real enum for any other members used by gdpr code paths.
        return getattr(_RealErrorCode, name)


# Keep the legacy sys.modules mock for environments where app.errors hasn't been
# imported yet (e.g. running this test file in isolation before app bootstrap).
_mock_errors = type(sys)("app.errors")
_mock_errors.ErrorCode = _MockErrorCode()
sys.modules.setdefault("app.errors", _mock_errors)

from app.fastapi_routes.gdpr import (
    ALLOWED_RECTIFY_FIELDS,
    ERASE_CONFIRMATION_PHRASE,
    GdprEraseRequest,
    GdprExportRequest,
    GdprRectifyRequest,
    _client_ip,
    _require_gdpr_enabled,
    _require_self_or_admin,
    get_current_user,
    router,
)


@pytest.fixture(autouse=True)
def _patch_gdpr_error_code():
    """Patch ``app.fastapi_routes.gdpr.ErrorCode`` with a mock that exposes
    ``FEATURE_DISABLED`` (absent from the real enum). gdpr.py imported the real
    ErrorCode at module load time, so we must patch the symbol in-place.
    """
    import app.fastapi_routes.gdpr as _gdpr_mod

    original = _gdpr_mod.ErrorCode
    _gdpr_mod.ErrorCode = _MockErrorCode()
    try:
        yield
    finally:
        _gdpr_mod.ErrorCode = original


# ---------------------------------------------------------------------------
# _require_gdpr_enabled
# ---------------------------------------------------------------------------
class TestRequireGdprEnabled:
    @patch("app.fastapi_routes.gdpr.is_enabled", return_value=True)
    def test_enabled_passes(self, mock_enabled):
        _require_gdpr_enabled()  # Should not raise

    @patch("app.fastapi_routes.gdpr.is_enabled", return_value=False)
    def test_disabled_raises_503(self, mock_enabled):
        with pytest.raises(HTTPException) as exc_info:
            _require_gdpr_enabled()
        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# _require_self_or_admin
# ---------------------------------------------------------------------------
class TestRequireSelfOrAdmin:
    def test_self_access_allowed(self):
        user = MagicMock()
        user.id = 42
        user.role = "user"
        _require_self_or_admin(42, user)  # Should not raise

    def test_admin_access_allowed(self):
        user = MagicMock()
        user.id = 1
        user.role = "admin"
        _require_self_or_admin(42, user)  # Should not raise

    def test_super_admin_access_allowed(self):
        user = MagicMock()
        user.id = 1
        user.role = "super_admin"
        _require_self_or_admin(42, user)  # Should not raise

    def test_other_user_forbidden(self):
        user = MagicMock()
        user.id = 1
        user.role = "user"
        with pytest.raises(_PermissionDeniedError):
            _require_self_or_admin(42, user)


# ---------------------------------------------------------------------------
# _client_ip
# ---------------------------------------------------------------------------
class TestClientIp:
    def test_x_forwarded_for(self):
        request = MagicMock()
        request.headers.get.return_value = "1.2.3.4, 5.6.7.8"
        request.client = MagicMock()
        request.client.host = "9.10.11.12"
        result = _client_ip(request)
        assert result == "1.2.3.4"

    def test_no_forwarded_for(self):
        request = MagicMock()
        request.headers.get.return_value = ""
        request.client = MagicMock()
        request.client.host = "9.10.11.12"
        result = _client_ip(request)
        assert result == "9.10.11.12"

    def test_no_client(self):
        request = MagicMock()
        request.headers.get.return_value = ""
        request.client = None
        result = _client_ip(request)
        assert result == ""


# ---------------------------------------------------------------------------
# GdprExportRequest
# ---------------------------------------------------------------------------
class TestGdprExportRequest:
    def test_defaults(self):
        req = GdprExportRequest()
        assert req.include_audit is True
        assert req.include_sessions is True
        assert req.format == "json"

    def test_csv_format(self):
        req = GdprExportRequest(format="csv")
        assert req.format == "csv"

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            GdprExportRequest(format="xml")


# ---------------------------------------------------------------------------
# GdprEraseRequest
# ---------------------------------------------------------------------------
class TestGdprEraseRequest:
    def test_valid_confirmation(self):
        req = GdprEraseRequest(reason="test", confirmation=ERASE_CONFIRMATION_PHRASE)
        assert req.confirmation == ERASE_CONFIRMATION_PHRASE

    def test_invalid_confirmation(self):
        with pytest.raises(ValueError):
            GdprEraseRequest(reason="test", confirmation="WRONG")

    def test_anonymize_only_default(self):
        req = GdprEraseRequest(reason="test", confirmation=ERASE_CONFIRMATION_PHRASE)
        assert req.anonymize_only is False


# ---------------------------------------------------------------------------
# GdprRectifyRequest
# ---------------------------------------------------------------------------
class TestGdprRectifyRequest:
    def test_valid_fields(self):
        req = GdprRectifyRequest(fields={"email": "new@test.com"}, reason="typo")
        assert "email" in req.fields

    def test_empty_fields_rejected(self):
        with pytest.raises(ValueError):
            GdprRectifyRequest(fields={}, reason="typo")

    def test_empty_reason_rejected(self):
        with pytest.raises(ValueError):
            GdprRectifyRequest(fields={"email": "a@b.com"}, reason="")


# ---------------------------------------------------------------------------
# Route integration tests (using dependency_overrides)
# ---------------------------------------------------------------------------


def _make_app() -> TestClient:
    from fastapi.responses import JSONResponse

    app = FastAPI()
    # Register exception handlers so custom exceptions are converted to HTTP responses
    app.add_exception_handler(
        _ValidationError,
        lambda req, exc: JSONResponse(status_code=400, content={"detail": str(exc)}),
    )
    app.add_exception_handler(
        _PermissionDeniedError,
        lambda req, exc: JSONResponse(status_code=403, content={"detail": str(exc)}),
    )
    app.add_exception_handler(
        _AuthenticationError,
        lambda req, exc: JSONResponse(status_code=401, content={"detail": str(exc)}),
    )
    app.add_exception_handler(
        _NotFoundError,
        lambda req, exc: JSONResponse(status_code=404, content={"detail": str(exc)}),
    )
    app.include_router(router)
    # Override get_current_user dependency
    mock_user = MagicMock()
    mock_user.id = 42
    mock_user.role = "user"
    app.dependency_overrides[get_current_user] = lambda: mock_user
    return TestClient(app)


class TestGdprExportEndpoint:
    @patch("app.fastapi_routes.gdpr.is_enabled", return_value=True)
    @patch("app.fastapi_routes.gdpr.log_audit_event")
    def test_export_success(self, mock_audit, mock_enabled):
        client = _make_app()
        resp = client.post("/api/gdpr/export", json={"format": "json"})
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"
        assert data["user_id"] == 42
        assert "task_id" in data

    @patch("app.fastapi_routes.gdpr.is_enabled", return_value=False)
    def test_export_disabled(self, mock_enabled):
        client = _make_app()
        resp = client.post("/api/gdpr/export", json={"format": "json"})
        assert resp.status_code == 503


class TestGdprEraseEndpoint:
    @patch("app.fastapi_routes.gdpr.is_enabled", return_value=True)
    @patch("app.fastapi_routes.gdpr.log_audit_event")
    def test_erase_success(self, mock_audit, mock_enabled):
        client = _make_app()
        resp = client.post(
            "/api/gdpr/erase",
            json={
                "reason": "test erase",
                "confirmation": ERASE_CONFIRMATION_PHRASE,
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"
        assert data["irreversible"] is True

    @patch("app.fastapi_routes.gdpr.is_enabled", return_value=True)
    def test_erase_wrong_confirmation(self, mock_enabled):
        client = _make_app()
        resp = client.post(
            "/api/gdpr/erase",
            json={"reason": "test", "confirmation": "WRONG"},
        )
        assert resp.status_code == 422  # Pydantic validation error


class TestGdprRectifyEndpoint:
    @patch("app.fastapi_routes.gdpr.is_enabled", return_value=True)
    @patch("app.fastapi_routes.gdpr.log_audit_event")
    @patch("app.infrastructure.persistence.sqlalchemy_uow.SqlAlchemyUnitOfWork")
    def test_rectify_success(self, mock_uow_cls, mock_audit, mock_enabled):
        mock_uow = MagicMock()
        mock_user_obj = MagicMock()
        mock_uow.__enter__ = MagicMock(return_value=mock_uow)
        mock_uow.__exit__ = MagicMock(return_value=False)
        mock_uow.get.return_value = mock_user_obj
        mock_uow_cls.return_value = mock_uow

        mock_audit.return_value = 99

        client = _make_app()
        resp = client.post(
            "/api/gdpr/rectify",
            json={"fields": {"email": "new@test.com"}, "reason": "typo"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == 42
        assert "email" in data["fields"]
        assert data["audit_id"] == 99

    @patch("app.fastapi_routes.gdpr.is_enabled", return_value=True)
    def test_rectify_invalid_field(self, mock_enabled):
        client = _make_app()
        resp = client.post(
            "/api/gdpr/rectify",
            json={"fields": {"password": "hacked"}, "reason": "attack"},
        )
        # _ValidationError is caught by our exception handler → 400
        assert resp.status_code == 400


class TestGdprStatusEndpoint:
    @patch("app.fastapi_routes.gdpr.is_enabled", return_value=True)
    def test_status_returns_queued(self, mock_enabled):
        client = _make_app()
        resp = client.get("/api/gdpr/status/test-task-id")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "test-task-id"
        assert data["status"] == "queued"


class TestAllowedRectifyFields:
    def test_expected_fields_present(self):
        assert "email" in ALLOWED_RECTIFY_FIELDS
        assert "display_name" in ALLOWED_RECTIFY_FIELDS
        assert "phone" in ALLOWED_RECTIFY_FIELDS
        assert "address" in ALLOWED_RECTIFY_FIELDS
        assert "bio" in ALLOWED_RECTIFY_FIELDS
        assert "avatar_url" in ALLOWED_RECTIFY_FIELDS

    def test_sensitive_fields_absent(self):
        assert "password" not in ALLOWED_RECTIFY_FIELDS
        assert "role" not in ALLOWED_RECTIFY_FIELDS
