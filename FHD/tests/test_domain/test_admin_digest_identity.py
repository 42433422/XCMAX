"""Tests for app.domain.admin_digest_identity."""

from __future__ import annotations

import pytest

from app.domain.admin_digest_identity import (
    daily_digest_identity_code,
    digest_identity_payload,
    verify_digest_identity_code,
)


class TestDailyDigestIdentityCode:
    def test_returns_6_char_hex(self):
        code = daily_digest_identity_code()
        assert len(code) == 6
        assert all(c in "0123456789ABCDEF" for c in code)

    def test_deterministic_for_same_day(self):
        code1 = daily_digest_identity_code("2026-06-16")
        code2 = daily_digest_identity_code("2026-06-16")
        assert code1 == code2

    def test_different_day_different_code(self):
        code1 = daily_digest_identity_code("2026-06-16")
        code2 = daily_digest_identity_code("2026-06-17")
        assert code1 != code2

    def test_custom_day_parameter(self):
        code = daily_digest_identity_code("2025-01-01")
        assert len(code) == 6

    def test_env_secret_affects_code(self, monkeypatch):
        code_default = daily_digest_identity_code("2026-06-16")
        monkeypatch.setenv("XCMAX_DIGEST_IDENTITY_SECRET", "custom-secret-123")
        code_custom = daily_digest_identity_code("2026-06-16")
        assert code_default != code_custom


class TestVerifyDigestIdentityCode:
    def test_valid_code_returns_true(self):
        code = daily_digest_identity_code("2026-06-16")
        assert verify_digest_identity_code(code, day="2026-06-16") is True

    def test_invalid_code_returns_false(self):
        assert verify_digest_identity_code("ZZZZZZ") is False

    def test_wrong_code_returns_false(self):
        assert verify_digest_identity_code("000000", day="2026-06-16") is False

    def test_empty_code_returns_false(self):
        assert verify_digest_identity_code("") is False

    def test_none_code_returns_false(self):
        assert verify_digest_identity_code(None) is False

    def test_short_code_returns_false(self):
        assert verify_digest_identity_code("ABC") is False

    def test_non_hex_code_returns_false(self):
        assert verify_digest_identity_code("GHIJKL") is False

    def test_case_insensitive(self):
        code = daily_digest_identity_code("2026-06-16")
        assert verify_digest_identity_code(code.lower(), day="2026-06-16") is True


class TestDigestIdentityPayload:
    def test_returns_success_dict(self):
        result = digest_identity_payload()
        assert result["success"] is True
        assert "data" in result

    def test_data_contains_code(self):
        result = digest_identity_payload()
        data = result["data"]
        assert "code" in data
        assert len(data["code"]) == 6

    def test_data_contains_expires_at(self):
        result = digest_identity_payload()
        data = result["data"]
        assert "expires_at" in data
        assert data["valid"] is True

    def test_data_source_is_local(self):
        result = digest_identity_payload()
        assert result["data"]["source"] == "local"

    def test_custom_digest_api_base(self):
        result = digest_identity_payload(digest_api_base="https://example.com")
        assert result["data"]["digest_api_base"] == "https://example.com"
