"""Tests for app.application.approval_workspace_app_service — coverage ramp."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.approval_workspace_app_service import (
    _FINAL_STATUSES,
    _allow_x_user_id_header,
    _generate_request_no,
    _next_node,
    _node_query_for_user,
    _normalize_statuses,
    _request_to_dict,
    _resolve_actor,
)

# ========================= _allow_x_user_id_header ======================


class TestAllowXUserIdHeader:
    def test_enabled(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
        assert _allow_x_user_id_header() is True

    def test_true(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "true")
        assert _allow_x_user_id_header() is True

    def test_disabled(self, monkeypatch):
        monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
        assert _allow_x_user_id_header() is False


# ========================= _generate_request_no ==========================


class TestGenerateRequestNo:
    def test_format(self):
        no = _generate_request_no()
        assert no.startswith("APR")
        assert "-" in no

    def test_uniqueness(self):
        nos = {_generate_request_no() for _ in range(20)}
        assert len(nos) == 20


# ========================= _node_query_for_user ==========================


class TestNodeQueryForUser:
    def test_user_in_list(self):
        node = Mock()
        node.approver_ids = json.dumps([1, 2, 3])
        assert _node_query_for_user(node, 2) is True

    def test_user_not_in_list(self):
        node = Mock()
        node.approver_ids = json.dumps([1, 3])
        assert _node_query_for_user(node, 2) is False

    def test_none_node(self):
        assert _node_query_for_user(None, 1) is False

    def test_empty_approver_ids(self):
        node = Mock()
        node.approver_ids = None
        assert _node_query_for_user(node, 1) is False

    def test_invalid_json(self):
        node = Mock()
        node.approver_ids = "not json"
        assert _node_query_for_user(node, 1) is False

    def test_list_approver_ids(self):
        node = Mock()
        node.approver_ids = [1, 2, 3]
        assert _node_query_for_user(node, 2) is True

    def test_non_list_json(self):
        node = Mock()
        node.approver_ids = json.dumps("string")
        assert _node_query_for_user(node, 1) is False


# ========================= _next_node ===================================


class TestNextNode:
    def test_finds_next(self):
        nodes = [Mock(node_order=1), Mock(node_order=3), Mock(node_order=5)]
        result = _next_node(nodes, 1)
        assert result.node_order == 3

    def test_no_next(self):
        nodes = [Mock(node_order=1), Mock(node_order=2)]
        result = _next_node(nodes, 2)
        assert result is None

    def test_empty_list(self):
        result = _next_node([], 0)
        assert result is None


# ========================= _normalize_statuses ==========================


class TestNormalizeStatuses:
    def test_none_returns_final(self):
        result = _normalize_statuses(None)
        assert result == list(_FINAL_STATUSES)

    def test_all_string(self):
        result = _normalize_statuses("all")
        assert result == list(_FINAL_STATUSES)

    def test_completed_string(self):
        result = _normalize_statuses("completed")
        assert result == list(_FINAL_STATUSES)

    def test_comma_separated(self):
        result = _normalize_statuses("approved,rejected")
        assert "approved" in result
        assert "rejected" in result

    def test_list_input(self):
        result = _normalize_statuses(["approved", "pending"])
        assert "approved" in result
        assert "pending" not in result

    def test_empty_list_returns_final(self):
        result = _normalize_statuses([])
        assert result == list(_FINAL_STATUSES)

    def test_invalid_type(self):
        result = _normalize_statuses(123)
        assert result == list(_FINAL_STATUSES)


# ========================= _request_to_dict ==============================


class TestRequestToDict:
    def test_without_records(self):
        mock_req = Mock()
        mock_req.to_dict.return_value = {"id": 1, "status": "pending"}
        mock_req.records = []
        result = _request_to_dict(mock_req, include_records=False)
        assert "records" not in result

    def test_with_records(self):
        mock_req = Mock()
        mock_req.to_dict.return_value = {"id": 1}
        mock_record = Mock()
        mock_record.action_time = None
        mock_record.to_dict.return_value = {"action": "approve"}
        mock_req.records = [mock_record]
        result = _request_to_dict(mock_req, include_records=True)
        assert "records" in result
        assert len(result["records"]) == 1


# ========================= _resolve_actor ================================


class TestResolveActor:
    def test_session_user_found(self):
        mock_request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user") as mock_resolve:
            mock_user = Mock()
            mock_user.id = 42
            mock_resolve.return_value = mock_user
            result = _resolve_actor(mock_request)
        assert result == 42

    def test_session_user_no_id(self):
        mock_request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user") as mock_resolve:
            mock_user = Mock(spec=[])
            mock_resolve.return_value = mock_user
            result = _resolve_actor(mock_request)
        assert result is None

    def test_x_user_id_header(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
        mock_request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=None):
            result = _resolve_actor(mock_request, x_user_id="99")
        assert result == 99

    def test_fallback(self):
        mock_request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=None):
            result = _resolve_actor(mock_request, fallback=7)
        assert result == 7

    def test_no_resolution(self):
        mock_request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=None):
            result = _resolve_actor(mock_request)
        assert result is None
