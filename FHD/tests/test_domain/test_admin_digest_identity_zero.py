"""Tests for app.domain.admin_digest_identity."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.domain.admin_digest_identity import (
    daily_digest_identity_code,
    digest_identity_payload,
    verify_digest_identity_code,
)


class TestDailyDigestIdentityCode:
    """Tests for daily_digest_identity_code."""

    def test_returns_6_char_hex(self) -> None:
        code = daily_digest_identity_code()
        assert len(code) == 6
        assert all(c in "0123456789ABCDEF" for c in code)

    def test_returns_uppercase(self) -> None:
        code = daily_digest_identity_code()
        assert code == code.upper()

    def test_deterministic_for_same_day(self) -> None:
        code1 = daily_digest_identity_code("2026-01-15")
        code2 = daily_digest_identity_code("2026-01-15")
        assert code1 == code2

    def test_different_for_different_days(self) -> None:
        code1 = daily_digest_identity_code("2026-01-15")
        code2 = daily_digest_identity_code("2026-01-16")
        assert code1 != code2

    def test_custom_day_parameter(self) -> None:
        code = daily_digest_identity_code("2025-12-25")
        assert len(code) == 6

    def test_uses_env_secret(self) -> None:
        with patch.dict("os.environ", {"XCMAX_DIGEST_IDENTITY_SECRET": "custom-secret"}):
            code1 = daily_digest_identity_code("2026-01-15")
        with patch.dict("os.environ", {"XCMAX_DIGEST_IDENTITY_SECRET": "other-secret"}):
            code2 = daily_digest_identity_code("2026-01-15")
        assert code1 != code2

    def test_strips_day_whitespace(self) -> None:
        code1 = daily_digest_identity_code("  2026-01-15  ")
        code2 = daily_digest_identity_code("2026-01-15")
        assert code1 == code2


class TestVerifyDigestIdentityCode:
    """Tests for verify_digest_identity_code."""

    def test_valid_code_returns_true(self) -> None:
        code = daily_digest_identity_code("2026-06-16")
        assert verify_digest_identity_code(code, day="2026-06-16") is True

    def test_invalid_code_returns_false(self) -> None:
        assert verify_digest_identity_code("ZZZZZZ") is False

    def test_wrong_code_returns_false(self) -> None:
        assert verify_digest_identity_code("000000") is False

    def test_empty_code_returns_false(self) -> None:
        assert verify_digest_identity_code("") is False

    def test_none_code_returns_false(self) -> None:
        assert verify_digest_identity_code(None) is False

    def test_short_code_returns_false(self) -> None:
        assert verify_digest_identity_code("ABC") is False

    def test_long_code_returns_false(self) -> None:
        assert verify_digest_identity_code("ABCDEF1") is False

    def test_non_hex_chars_returns_false(self) -> None:
        assert verify_digest_identity_code("GHIJKL") is False

    def test_case_insensitive(self) -> None:
        code = daily_digest_identity_code("2026-06-16")
        assert verify_digest_identity_code(code.lower(), day="2026-06-16") is True


class TestDigestIdentityPayload:
    """Tests for digest_identity_payload."""

    def test_returns_success_dict(self) -> None:
        result = digest_identity_payload()
        assert result["success"] is True
        assert "data" in result

    def test_data_contains_code(self) -> None:
        result = digest_identity_payload()
        data = result["data"]
        assert len(data["code"]) == 6
        assert data["valid"] is True

    def test_data_contains_expires(self) -> None:
        result = digest_identity_payload()
        data = result["data"]
        assert "expires_at" in data

    def test_data_source_is_local(self) -> None:
        result = digest_identity_payload()
        assert result["data"]["source"] == "local"

    def test_custom_digest_api_base(self) -> None:
        result = digest_identity_payload(digest_api_base="https://api.test.com")
        assert result["data"]["digest_api_base"] == "https://api.test.com"

    def test_daily_digest_id_is_none(self) -> None:
        result = digest_identity_payload()
        assert result["data"]["daily_digest_id"] is None
