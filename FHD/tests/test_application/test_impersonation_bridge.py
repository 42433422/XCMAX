"""Tests for app.application.impersonation_bridge."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.application.impersonation_bridge import (
    _BRIDGE,
    _BRIDGE_TTL_SEC,
    _copy_session_row_fields,
    _purge_expired_bridge_tokens,
    consume_impersonation_bridge_token,
    create_impersonation_bridge_token,
)


class TestBridgeTokenFlow:
    def setup_method(self):
        _BRIDGE.clear()

    def test_create_and_consume_token(self):
        token = create_impersonation_bridge_token("admin-session-123")
        assert isinstance(token, str)
        admin_sid = consume_impersonation_bridge_token(token)
        assert admin_sid == "admin-session-123"

    def test_consume_token_is_one_time(self):
        token = create_impersonation_bridge_token("admin-session-123")
        consume_impersonation_bridge_token(token)
        result = consume_impersonation_bridge_token(token)
        assert result is None

    def test_consume_invalid_token_returns_none(self):
        result = consume_impersonation_bridge_token("nonexistent-token")
        assert result is None

    def test_consume_empty_token_returns_none(self):
        result = consume_impersonation_bridge_token("")
        assert result is None

    def test_consume_none_token_returns_none(self):
        result = consume_impersonation_bridge_token(None)
        assert result is None

    def test_create_with_empty_session_id(self):
        token = create_impersonation_bridge_token("")
        result = consume_impersonation_bridge_token(token)
        assert result is None

    def test_create_with_none_session_id(self):
        token = create_impersonation_bridge_token(None)
        result = consume_impersonation_bridge_token(token)
        assert result is None

    def test_create_strips_whitespace(self):
        token = create_impersonation_bridge_token("  admin-sid  ")
        result = consume_impersonation_bridge_token(token)
        assert result == "admin-sid"


class TestPurgeExpiredTokens:
    def setup_method(self):
        _BRIDGE.clear()

    def test_expired_tokens_purged(self):
        _BRIDGE["old"] = {"admin_sid": "old-sid", "created_at": time.time() - _BRIDGE_TTL_SEC - 10}
        _BRIDGE["new"] = {"admin_sid": "new-sid", "created_at": time.time()}
        _purge_expired_bridge_tokens()
        assert "old" not in _BRIDGE
        assert "new" in _BRIDGE

    def test_no_expired_tokens(self):
        _BRIDGE["fresh"] = {"admin_sid": "sid", "created_at": time.time()}
        _purge_expired_bridge_tokens()
        assert "fresh" in _BRIDGE


class TestCopySessionRowFields:
    def test_copies_fields(self):
        source = MagicMock()
        source.user_id = 1
        source.market_access_token = "token"
        source.market_refresh_token = "refresh"
        source.market_user_id = "muid"
        source.entitled_mod_ids_json = "[]"
        source.account_kind = "enterprise"
        source.company_brand = "brand"
        source.market_is_admin = True
        source.market_is_enterprise = True
        source.impersonating_market_user_id = "imp_uid"
        source.impersonating_username = "imp_user"

        target = MagicMock()
        _copy_session_row_fields(source, target)

        assert target.user_id == 1
        assert target.market_access_token == "token"
        assert target.market_is_admin is True
        assert target.impersonating_username == "imp_user"
