"""Tests for app.application.impersonation_bridge."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.application.impersonation_bridge import (
    _BRIDGE_TTL_SEC,
    consume_impersonation_bridge_token,
    create_impersonation_bridge_token,
)


class TestCreateImpersonationBridgeToken:
    """Tests for create_impersonation_bridge_token."""

    def test_creates_token_and_stores_entry(self) -> None:
        token = create_impersonation_bridge_token("admin-session-123")
        assert isinstance(token, str)
        assert len(token) > 10

    def test_strips_admin_session_id(self) -> None:
        token = create_impersonation_bridge_token("  admin-sid  ")
        # Verify the stored entry has stripped value
        from app.application.impersonation_bridge import _BRIDGE
        entry = _BRIDGE.get(token)
        assert entry is not None
        assert entry["admin_sid"] == "admin-sid"

    def test_handles_empty_session_id(self) -> None:
        token = create_impersonation_bridge_token("")
        from app.application.impersonation_bridge import _BRIDGE
        entry = _BRIDGE.get(token)
        assert entry is not None
        assert entry["admin_sid"] == ""


class TestConsumeImpersonationBridgeToken:
    """Tests for consume_impersonation_bridge_token."""

    def test_consumes_valid_token(self) -> None:
        token = create_impersonation_bridge_token("admin-session-abc")
        result = consume_impersonation_bridge_token(token)
        assert result == "admin-session-abc"

    def test_token_is_consumed_once(self) -> None:
        token = create_impersonation_bridge_token("admin-session-once")
        result1 = consume_impersonation_bridge_token(token)
        assert result1 == "admin-session-once"
        result2 = consume_impersonation_bridge_token(token)
        assert result2 is None

    def test_invalid_token_returns_none(self) -> None:
        result = consume_impersonation_bridge_token("nonexistent-token")
        assert result is None

    def test_empty_token_returns_none(self) -> None:
        result = consume_impersonation_bridge_token("")
        assert result is None

    def test_none_token_returns_none(self) -> None:
        result = consume_impersonation_bridge_token(None)
        assert result is None

    def test_expired_token_returns_none(self) -> None:
        from app.application.impersonation_bridge import _BRIDGE
        token = create_impersonation_bridge_token("admin-expired")
        # Manually expire the entry
        _BRIDGE[token]["created_at"] = time.time() - _BRIDGE_TTL_SEC - 10
        result = consume_impersonation_bridge_token(token)
        assert result is None

    def test_strips_token_whitespace(self) -> None:
        token = create_impersonation_bridge_token("admin-whitespace")
        result = consume_impersonation_bridge_token(f"  {token}  ")
        assert result == "admin-whitespace"

    def test_empty_admin_sid_returns_none(self) -> None:
        from app.application.impersonation_bridge import _BRIDGE
        token = create_impersonation_bridge_token("")
        # Force admin_sid to empty
        _BRIDGE[token]["admin_sid"] = "   "
        result = consume_impersonation_bridge_token(token)
        assert result is None


class TestPurgeExpiredTokens:
    """Tests for expired token purge behavior."""

    def test_expired_tokens_are_purged_on_create(self) -> None:
        from app.application.impersonation_bridge import _BRIDGE
        # Create an old token
        old_token = create_impersonation_bridge_token("old-admin")
        _BRIDGE[old_token]["created_at"] = time.time() - _BRIDGE_TTL_SEC - 100
        # Creating a new token should purge the old one
        new_token = create_impersonation_bridge_token("new-admin")
        assert old_token not in _BRIDGE
        assert new_token in _BRIDGE
