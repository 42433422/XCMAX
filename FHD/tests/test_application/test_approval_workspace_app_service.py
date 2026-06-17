"""Tests for app.application.approval_workspace_app_service — coverage ramp."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.approval_workspace_app_service import (
    _allow_x_user_id_header,
    _generate_request_no,
    _node_query_for_user,
)

# ========================= _allow_x_user_id_header =======================


class TestAllowXUserIdHeader:
    def test_default_false(self, monkeypatch):
        monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
        assert _allow_x_user_id_header() is False

    def test_1(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
        assert _allow_x_user_id_header() is True

    def test_true(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "true")
        assert _allow_x_user_id_header() is True

    def test_yes(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "yes")
        assert _allow_x_user_id_header() is True

    def test_false(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "false")
        assert _allow_x_user_id_header() is False

    def test_empty(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "")
        assert _allow_x_user_id_header() is False


# ========================= _generate_request_no ==========================


class TestGenerateRequestNo:
    def test_format(self):
        no = _generate_request_no()
        assert no.startswith("APR")
        assert len(no) > 10
        assert "-" in no

    def test_unique(self):
        nos = {_generate_request_no() for _ in range(20)}
        assert len(nos) == 20


# ========================= _node_query_for_user ==========================


class TestNodeQueryForUser:
    def test_none_node(self):
        assert _node_query_for_user(None, 1) is False

    def test_no_approver_ids(self):
        node = Mock()
        node.approver_ids = None
        assert _node_query_for_user(node, 1) is False

    def test_empty_approver_ids(self):
        node = Mock()
        node.approver_ids = []
        assert _node_query_for_user(node, 1) is False

    def test_user_in_approver_ids(self):
        node = Mock()
        node.approver_ids = [1, 2, 3]
        assert _node_query_for_user(node, 2) is True

    def test_user_not_in_approver_ids(self):
        node = Mock()
        node.approver_ids = [1, 2, 3]
        assert _node_query_for_user(node, 4) is False

    def test_string_approver_ids(self):
        node = Mock()
        node.approver_ids = "[1, 2, 3]"
        assert _node_query_for_user(node, 1) is True
        assert _node_query_for_user(node, 4) is False
