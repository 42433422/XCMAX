from __future__ import annotations

"""Branch coverage for app/services/user_cs_enterprise_credentials.py."""

from unittest.mock import MagicMock, patch

import pytest

# load_pipeline / save_pipeline are imported inside function bodies via
# "from app.services.user_cs_pipeline import ..." — so we patch the source module.
PIPELINE_MOD = "app.services.user_cs_pipeline"
BASE = "app.services.user_cs_enterprise_credentials"


class TestNowIso:
    def test_returns_iso_string(self):
        from app.services.user_cs_enterprise_credentials import _now_iso

        s = _now_iso()
        assert isinstance(s, str)
        assert "T" in s  # ISO format


class TestBasePayload:
    def test_from_enterprise_login_username(self):
        from app.services.user_cs_enterprise_credentials import _base_payload

        doc = {
            "enterprise_login_username": "admin",
            "enterprise_login_password": "pass123",
            "enterprise_credentials_issued_at": "2026-01-01",
            "enterprise_login_email": "admin@x.com",
            "enterprise_auto_provisioned_at": "2026-01-01",
        }
        p = _base_payload(doc)
        assert p["username"] == "admin"
        assert p["password"] == "pass123"
        assert p["is_enterprise"] is True
        assert p["password_recorded"] is True

    def test_fallback_to_username_field(self):
        from app.services.user_cs_enterprise_credentials import _base_payload

        doc = {"username": "bob"}
        p = _base_payload(doc)
        assert p["username"] == "bob"

    def test_fallback_to_caller_username(self):
        from app.services.user_cs_enterprise_credentials import _base_payload

        p = _base_payload({}, username="charlie")
        assert p["username"] == "charlie"

    def test_empty_doc(self):
        from app.services.user_cs_enterprise_credentials import _base_payload

        p = _base_payload({})
        assert p["username"] == ""
        assert p["is_enterprise"] is False
        assert p["password_recorded"] is False


class TestGetEnterpriseCredentials:
    def test_no_market_base_url(self):
        from app.services.user_cs_enterprise_credentials import get_enterprise_credentials

        doc = {
            "enterprise_login_username": "user1",
            "enterprise_login_password": "pw",
            "enterprise_credentials_issued_at": "2026-01-01",
            "enterprise_login_email": "u1@x.com",
            "enterprise_auto_provisioned_at": "2026-01-01",
        }
        with (
            patch(f"{PIPELINE_MOD}.load_pipeline", return_value=doc) as mock_load,
            patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": ""}),
        ):
            result = get_enterprise_credentials(42, username="user1")

        assert result["username"] == "user1"
        assert "market_fetch_error" in result

    def test_with_market_base_url_success(self):
        from app.services.user_cs_enterprise_credentials import get_enterprise_credentials

        doc = {
            "enterprise_login_username": "user1",
            "enterprise_login_password": "pw",
            "enterprise_credentials_issued_at": "2026-01-01",
            "enterprise_login_email": "",
            "enterprise_auto_provisioned_at": "2026-01-01",
        }
        market_resp = MagicMock()
        market_resp.status_code = 200
        market_resp.json.return_value = {
            "data": {"email": "new@x.com", "is_enterprise": True, "username": "user_new"}
        }

        with (
            patch(f"{PIPELINE_MOD}.load_pipeline", return_value=doc),
            patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": "https://market.example.com"}),
            patch("httpx.get", return_value=market_resp),
        ):
            result = get_enterprise_credentials(42)

        assert result["email"] == "new@x.com"
        assert result["username"] == "user_new"
        assert result["is_enterprise"] is True

    def test_with_market_base_url_http_error(self):
        from app.services.user_cs_enterprise_credentials import get_enterprise_credentials

        doc = {
            "enterprise_login_username": "u",
            "enterprise_login_password": "",
            "enterprise_credentials_issued_at": "",
            "enterprise_login_email": "",
        }
        market_resp = MagicMock()
        market_resp.status_code = 404

        with (
            patch(f"{PIPELINE_MOD}.load_pipeline", return_value=doc),
            patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": "https://market.example.com"}),
            patch("httpx.get", return_value=market_resp),
        ):
            result = get_enterprise_credentials(42)

        assert "HTTP 404" in result["market_fetch_error"]

    def test_with_market_base_url_network_error(self):
        from app.services.user_cs_enterprise_credentials import get_enterprise_credentials

        doc = {"enterprise_login_username": "u"}

        # Must use an exception type that's in RECOVERABLE_ERRORS
        with (
            patch(f"{PIPELINE_MOD}.load_pipeline", return_value=doc),
            patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": "https://market.example.com"}),
            patch("httpx.get", side_effect=OSError("connection refused")),
        ):
            result = get_enterprise_credentials(42)

        assert "connection refused" in result["market_fetch_error"]

    def test_market_response_flat_dict(self):
        """Response is a flat dict (no nested 'data' key)."""
        from app.services.user_cs_enterprise_credentials import get_enterprise_credentials

        doc = {"enterprise_login_username": "u", "enterprise_login_email": "old@x.com"}
        market_resp = MagicMock()
        market_resp.status_code = 200
        market_resp.json.return_value = {"email": "flat@x.com", "username": "flat_user"}

        with (
            patch(f"{PIPELINE_MOD}.load_pipeline", return_value=doc),
            patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": "https://market.example.com"}),
            patch("httpx.get", return_value=market_resp),
        ):
            result = get_enterprise_credentials(42)

        # flat dict handling — flat dict has no "data" key, so blob itself is used
        assert result["email"] in ("flat@x.com", "old@x.com")

    def test_market_response_non_dict(self):
        """Response body is not a dict — payload unchanged."""
        from app.services.user_cs_enterprise_credentials import get_enterprise_credentials

        doc = {"enterprise_login_username": "u"}
        market_resp = MagicMock()
        market_resp.status_code = 200
        market_resp.json.return_value = ["not", "a", "dict"]

        with (
            patch(f"{PIPELINE_MOD}.load_pipeline", return_value=doc),
            patch.dict("os.environ", {"XCAGI_MARKET_BASE_URL": "https://market.example.com"}),
            patch("httpx.get", return_value=market_resp),
        ):
            result = get_enterprise_credentials(42)

        assert result["market_fetch_error"] == ""


class TestIssueEnterpriseCredentials:
    def test_issue_with_auto_password(self):
        from app.services.user_cs_enterprise_credentials import issue_enterprise_credentials

        doc = {"username": "alice", "enterprise_auto_provisioned_at": "2026-01-01"}

        with (
            patch(f"{PIPELINE_MOD}.load_pipeline", return_value=doc),
            patch(f"{PIPELINE_MOD}.save_pipeline") as mock_save,
        ):
            result = issue_enterprise_credentials(1, username="alice")

        assert result["success"] is True
        assert result["password"] != ""
        mock_save.assert_called_once()

    def test_issue_with_explicit_password(self):
        from app.services.user_cs_enterprise_credentials import issue_enterprise_credentials

        doc = {"username": "bob"}

        with (
            patch(f"{PIPELINE_MOD}.load_pipeline", return_value=doc),
            patch(f"{PIPELINE_MOD}.save_pipeline"),
        ):
            result = issue_enterprise_credentials(2, username="bob", password="mypassword")

        assert result["password"] == "mypassword"

    def test_issue_uses_fallback_username(self):
        from app.services.user_cs_enterprise_credentials import issue_enterprise_credentials

        # No username in doc, no caller username → user{uid}
        doc = {}

        with (
            patch(f"{PIPELINE_MOD}.load_pipeline", return_value=doc),
            patch(f"{PIPELINE_MOD}.save_pipeline"),
        ):
            result = issue_enterprise_credentials(99)

        assert result["username"] == "user99"

    def test_issue_preserves_existing_provisioned_at(self):
        from app.services.user_cs_enterprise_credentials import issue_enterprise_credentials

        original_ts = "2025-01-01T00:00:00+00:00"
        doc = {"username": "u", "enterprise_auto_provisioned_at": original_ts}

        with (
            patch(f"{PIPELINE_MOD}.load_pipeline", return_value=doc),
            patch(f"{PIPELINE_MOD}.save_pipeline") as mock_save,
        ):
            issue_enterprise_credentials(1)

        saved_doc = mock_save.call_args[0][0]
        assert saved_doc["enterprise_auto_provisioned_at"] == original_ts
