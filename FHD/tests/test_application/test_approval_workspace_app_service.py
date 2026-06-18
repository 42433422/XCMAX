"""Tests for app.application.approval_workspace_app_service — comprehensive coverage ramp."""

from __future__ import annotations

import json
import os
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.approval_workspace_app_service import (
    _allow_x_user_id_header,
    _audit,
    _close_request_if_needed,
    _generate_request_no,
    _next_node,
    _node_query_for_user,
    _normalize_statuses,
    _ordered_nodes,
    _request_to_dict,
    _resolve_actor,
    approve_request,
    check_approver_orphan,
    cleanup_requests,
    create_flow,
    delete_flow,
    delete_request,
    get_approval_users,
    get_flow_detail,
    get_request_detail,
    list_flows,
    list_requests,
    process_approval_timeouts_endpoint,
    reject_request,
    submit_request,
    toggle_flow_active,
    update_flow,
    withdraw_request,
)
from app.db.models.approval import (
    ApprovalAction,
    ApprovalFlow,
    ApprovalFlowNode,
    ApprovalRecord,
    ApprovalRequest,
    ApprovalStatus,
)


def _make_db_ctx(mock_db):
    """Create a context manager mock that yields mock_db for ``with get_db() as db:``."""
    ctx = MagicMock()
    ctx.__enter__ = Mock(return_value=mock_db)
    ctx.__exit__ = Mock(return_value=False)
    return ctx


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

    def test_whitespace_true(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "  true  ")
        assert _allow_x_user_id_header() is True

    def test_uppercase_TRUE(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "TRUE")
        # .lower() makes "TRUE" → "true" which IS in the set
        assert _allow_x_user_id_header() is True


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

    def test_date_component(self):
        no = _generate_request_no()
        today_str = datetime.now().strftime("%Y%m%d")
        assert today_str in no


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

    def test_invalid_json_approver_ids(self):
        node = Mock()
        node.approver_ids = "not-json"
        assert _node_query_for_user(node, 1) is False

    def test_non_list_json_approver_ids(self):
        node = Mock()
        node.approver_ids = '{"key": "val"}'
        assert _node_query_for_user(node, 1) is False

    def test_approver_ids_with_none_entries(self):
        node = Mock()
        node.approver_ids = [1, None, 3]
        assert _node_query_for_user(node, 1) is True
        assert _node_query_for_user(node, 3) is True

    def test_string_user_id_in_list(self):
        node = Mock()
        node.approver_ids = ["1", "2", "3"]
        assert _node_query_for_user(node, 1) is True

    def test_empty_string_approver_ids(self):
        node = Mock()
        node.approver_ids = ""
        assert _node_query_for_user(node, 1) is False


# ========================= _resolve_actor ================================


class TestResolveActor:
    def test_session_user_found(self):
        request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user") as mock_resolve:
            user = Mock()
            user.id = 42
            mock_resolve.return_value = user
            result = _resolve_actor(request)
            assert result == 42

    def test_session_user_no_id(self):
        request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user") as mock_resolve:
            user = Mock()
            user.id = None
            mock_resolve.return_value = user
            # Falls through to x_user_id / fallback
            result = _resolve_actor(request, x_user_id="10")
            # _allow_x_user_id_header defaults to False in test env unless set
            assert result is None or result == 10

    def test_session_user_none(self):
        request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user") as mock_resolve:
            mock_resolve.return_value = None
            result = _resolve_actor(request)
            assert result is None

    def test_x_user_id_header_allowed(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
        request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user") as mock_resolve:
            mock_resolve.return_value = None
            result = _resolve_actor(request, x_user_id="5")
            assert result == 5

    def test_x_user_id_header_not_allowed(self, monkeypatch):
        monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
        request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user") as mock_resolve:
            mock_resolve.return_value = None
            result = _resolve_actor(request, x_user_id="5")
            assert result is None

    def test_x_user_id_non_digit(self, monkeypatch):
        monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
        request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user") as mock_resolve:
            mock_resolve.return_value = None
            result = _resolve_actor(request, x_user_id="abc")
            assert result is None

    def test_fallback_used(self):
        request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user") as mock_resolve:
            mock_resolve.return_value = None
            result = _resolve_actor(request, fallback=99)
            assert result == 99

    def test_fallback_invalid(self):
        request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user") as mock_resolve:
            mock_resolve.return_value = None
            result = _resolve_actor(request, fallback="not_a_number")
            assert result is None

    def test_fallback_none(self):
        request = Mock()
        with patch("app.infrastructure.auth.dependencies.resolve_session_user") as mock_resolve:
            mock_resolve.return_value = None
            result = _resolve_actor(request, fallback=None)
            assert result is None


# ========================= _audit ========================================


class TestAudit:
    def test_audit_writes_to_db(self):
        db = MagicMock()
        _audit(db, actor=1, action="test.action", payload={"key": "val"})
        db.execute.assert_called_once()
        call_args = db.execute.call_args
        # db.execute called with positional args: (text_clause, params_dict)
        params = call_args[0][1]
        assert params["actor"] == "1"
        assert params["action"] == "test.action"

    def test_audit_actor_none(self):
        db = MagicMock()
        _audit(db, actor=None, action="test.action", payload={})
        db.execute.assert_called_once()
        call_args = db.execute.call_args
        params = call_args[0][1]
        assert params["actor"] is None

    def test_audit_db_error_does_not_raise(self):
        db = MagicMock()
        db.execute.side_effect = OSError("DB connection lost")
        # Should not raise
        _audit(db, actor=1, action="test.action", payload={"k": "v"})


# ========================= _next_node ====================================


class TestNextNode:
    def test_finds_next(self):
        n1 = Mock(node_order=1)
        n2 = Mock(node_order=2)
        n3 = Mock(node_order=3)
        assert _next_node([n1, n2, n3], 1) is n2

    def test_no_next(self):
        n1 = Mock(node_order=1)
        assert _next_node([n1], 1) is None

    def test_empty_list(self):
        assert _next_node([], 1) is None

    def test_current_order_zero(self):
        n1 = Mock(node_order=1)
        n2 = Mock(node_order=2)
        assert _next_node([n1, n2], 0) is n1


# ========================= _ordered_nodes ================================


class TestOrderedNodes:
    def test_ordered_nodes_query(self):
        db = MagicMock()
        mock_query = MagicMock()
        db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []
        result = _ordered_nodes(db, flow_id=1)
        assert result == []
        db.query.assert_called_once_with(ApprovalFlowNode)


# ========================= _request_to_dict ==============================


class TestRequestToDict:
    def test_without_records(self):
        req = Mock()
        req.to_dict.return_value = {"id": 1, "title": "test"}
        req.records = None
        result = _request_to_dict(req, include_records=False)
        assert result == {"id": 1, "title": "test"}

    def test_with_records(self):
        req = Mock()
        req.to_dict.return_value = {"id": 1, "title": "test"}
        rec1 = Mock()
        rec1.action_time = datetime(2026, 1, 2)
        rec1.to_dict.return_value = {"id": 10, "action": "approve"}
        rec2 = Mock()
        rec2.action_time = datetime(2026, 1, 1)
        rec2.to_dict.return_value = {"id": 11, "action": "reject"}
        req.records = [rec1, rec2]
        result = _request_to_dict(req, include_records=True)
        assert "records" in result
        # Records should be sorted by action_time
        assert result["records"][0]["id"] == 11
        assert result["records"][1]["id"] == 10

    def test_with_empty_records(self):
        req = Mock()
        req.to_dict.return_value = {"id": 1}
        req.records = []
        result = _request_to_dict(req, include_records=True)
        assert result["records"] == []

    def test_with_none_records(self):
        req = Mock()
        req.to_dict.return_value = {"id": 1}
        req.records = None
        result = _request_to_dict(req, include_records=True)
        assert result["records"] == []


# ========================= _normalize_statuses ===========================


class TestNormalizeStatuses:
    def test_none_returns_final(self):
        result = _normalize_statuses(None)
        assert set(result) == {
            ApprovalStatus.APPROVED.value,
            ApprovalStatus.REJECTED.value,
            ApprovalStatus.WITHDRAWN.value,
            ApprovalStatus.CANCELLED.value,
        }

    def test_string_all(self):
        result = _normalize_statuses("all")
        assert len(result) == 4

    def test_string_completed(self):
        result = _normalize_statuses("completed")
        assert len(result) == 4

    def test_string_final(self):
        result = _normalize_statuses("final")
        assert len(result) == 4

    def test_string_empty(self):
        result = _normalize_statuses("")
        assert len(result) == 4

    def test_string_comma_separated(self):
        result = _normalize_statuses("approved,rejected")
        assert set(result) == {"approved", "rejected"}

    def test_string_with_spaces(self):
        result = _normalize_statuses(" approved , rejected ")
        assert set(result) == {"approved", "rejected"}

    def test_list_input(self):
        result = _normalize_statuses(["approved", "rejected"])
        assert set(result) == {"approved", "rejected"}

    def test_list_with_invalid(self):
        result = _normalize_statuses(["approved", "invalid_status"])
        assert result == ["approved"]

    def test_list_all_invalid_returns_final(self):
        result = _normalize_statuses(["invalid1", "invalid2"])
        assert len(result) == 4

    def test_non_list_non_string(self):
        result = _normalize_statuses(123)
        assert len(result) == 4

    def test_empty_list(self):
        result = _normalize_statuses([])
        assert len(result) == 4


# ========================= _close_request_if_needed ======================


class TestCloseRequestIfNeeded:
    def test_last_node_approves(self):
        req = Mock()
        req.current_node_order = 3
        nodes = [Mock(node_order=1), Mock(node_order=2), Mock(node_order=3)]
        status, next_node_id = _close_request_if_needed(
            Mock(), req=req, nodes=nodes, approver_id=1, approver_name="Admin"
        )
        assert status == ApprovalStatus.APPROVED.value
        assert next_node_id is None
        assert req.status == ApprovalStatus.APPROVED.value
        assert req.approved_by == 1

    def test_has_next_node(self):
        req = Mock()
        req.current_node_order = 1
        n2 = Mock(node_order=2)
        nodes = [Mock(node_order=1), n2]
        status, next_node_id = _close_request_if_needed(
            Mock(), req=req, nodes=nodes, approver_id=1, approver_name="Admin"
        )
        assert status == ApprovalStatus.IN_PROGRESS.value
        assert next_node_id == n2.id
        assert req.current_node_id == n2.id

    def test_current_node_order_none(self):
        req = Mock()
        req.current_node_order = None
        n1 = Mock(node_order=1)
        nodes = [n1]
        status, next_node_id = _close_request_if_needed(
            Mock(), req=req, nodes=nodes, approver_id=1, approver_name="Admin"
        )
        # None treated as 0, so n1 (order=1) is next
        assert status == ApprovalStatus.IN_PROGRESS.value


# ========================= list_requests =================================


class TestListRequests:
    def test_list_requests_basic(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        with patch(
            "app.application.approval_workspace_app_service.get_db",
            return_value=_make_db_ctx(mock_db),
        ):
            result = list_requests(page=1, page_size=50)
            assert result["success"] is True
            assert result["data"] == []

    def test_list_requests_with_applicant_id(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        with patch(
            "app.application.approval_workspace_app_service.get_db",
            return_value=_make_db_ctx(mock_db),
        ):
            result = list_requests(applicant_id=1, page=1, page_size=50)
            assert result["success"] is True

    def test_list_requests_with_status(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        with patch(
            "app.application.approval_workspace_app_service.get_db",
            return_value=_make_db_ctx(mock_db),
        ):
            result = list_requests(status="pending", page=1, page_size=50)
            assert result["success"] is True

    def test_list_requests_with_approver_id_filter(self):
        """When approver_id is set, items are filtered by node membership."""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query

        req = Mock()
        req.to_dict.return_value = {"id": 1, "status": "pending"}
        req.current_node = None
        req.status = "pending"
        mock_query.all.return_value = [req]

        with patch(
            "app.application.approval_workspace_app_service.get_db",
            return_value=_make_db_ctx(mock_db),
        ):
            result = list_requests(approver_id=1, page=1, page_size=50)
            # current_node is None so the request is filtered out
            assert result["pagination"]["returned"] == 0

    def test_list_requests_with_business_type(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        with patch(
            "app.application.approval_workspace_app_service.get_db",
            return_value=_make_db_ctx(mock_db),
        ):
            result = list_requests(business_type="general", page=1, page_size=50)
            assert result["success"] is True


# ========================= cleanup_requests ==============================


class TestCleanupRequests:
    def test_cleanup_no_actor_raises_401(self):
        request = Mock()
        with patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve:
            mock_resolve.return_value = None
            with pytest.raises(Exception) as exc_info:
                cleanup_requests(request, body={})
            assert exc_info.value.status_code == 401

    def test_cleanup_unsupported_scope_returns_400(self):
        request = Mock()
        with patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve:
            mock_resolve.return_value = 1
            result = cleanup_requests(request, body={"scope": "all_users"})
            assert result.status_code == 400

    def test_cleanup_dry_run(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = cleanup_requests(request, body={"dry_run": True})
            assert result["success"] is True
            assert result["data"]["dry_run"] is True

    def test_cleanup_with_before_days(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = cleanup_requests(request, body={"before_days": 30})
            assert result["success"] is True

    def test_cleanup_before_days_negative_treated_as_none(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = cleanup_requests(request, body={"before_days": -5})
            assert result["success"] is True
            assert result["data"]["before_days"] is None

    def test_cleanup_before_days_invalid_treated_as_none(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = cleanup_requests(request, body={"before_days": "abc"})
            assert result["success"] is True
            assert result["data"]["before_days"] is None

    def test_cleanup_actually_deletes(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query

        req1 = Mock()
        req1.id = 1
        req1.request_no = "APR20260101-ABC"
        mock_query.all.return_value = [req1]

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch("app.application.approval_workspace_app_service._audit"),
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = cleanup_requests(request, body={})
            assert result["success"] is True
            assert result["data"]["deleted"] == 1
            mock_db.delete.assert_called_once_with(req1)
            mock_db.commit.assert_called_once()

    def test_cleanup_zero_matched(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = cleanup_requests(request, body={})
            assert result["success"] is True
            assert result["data"]["matched"] == 0
            assert result["data"]["deleted"] == 0


# ========================= get_request_detail ============================


class TestGetRequestDetail:
    def test_found(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.to_dict.return_value = {"id": 1}
        req.records = []
        mock_query.first.return_value = req

        with patch("app.application.approval_workspace_app_service.get_db") as mock_get_db:
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = get_request_detail(1)
            assert result["success"] is True

    def test_not_found(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        with patch("app.application.approval_workspace_app_service.get_db") as mock_get_db:
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = get_request_detail(999)
            assert result.status_code == 404


# ========================= submit_request ================================


class TestSubmitRequest:
    def test_missing_flow_key_raises_400(self):
        request = Mock()
        with pytest.raises(Exception) as exc_info:
            submit_request(request, body={"title": "test"})
        assert exc_info.value.status_code == 400

    def test_missing_title_raises_400(self):
        request = Mock()
        with pytest.raises(Exception) as exc_info:
            submit_request(request, body={"flow_key": "test_flow"})
        assert exc_info.value.status_code == 400

    def test_no_actor_raises_401(self):
        request = Mock()
        with patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve:
            mock_resolve.return_value = None
            with pytest.raises(Exception) as exc_info:
                submit_request(request, body={"flow_key": "fk", "title": "t"})
            assert exc_info.value.status_code == 401

    def test_flow_not_found(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = submit_request(request, body={"flow_key": "missing", "title": "test"})
            assert result.status_code == 404

    def test_flow_no_nodes(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        flow = Mock()
        flow.id = 1
        flow.flow_key = "fk"
        mock_query.first.return_value = flow

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch("app.application.approval_workspace_app_service._ordered_nodes") as mock_nodes,
            patch("app.application.approval_workspace_app_service._audit"),
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            mock_nodes.return_value = []
            result = submit_request(request, body={"flow_key": "fk", "title": "test"})
            assert result.status_code == 400

    def test_submit_success(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        flow = Mock()
        flow.id = 1
        flow.flow_key = "fk"
        mock_query.first.return_value = flow

        first_node = Mock()
        first_node.id = 10
        first_node.node_order = 1

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch("app.application.approval_workspace_app_service._ordered_nodes") as mock_nodes,
            patch("app.application.approval_workspace_app_service._audit"),
            patch(
                "app.application.approval_workspace_app_service._generate_request_no"
            ) as mock_gen,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            mock_nodes.return_value = [first_node]
            mock_gen.return_value = "APR20260101-TEST1"
            result = submit_request(
                request,
                body={
                    "flow_key": "fk",
                    "title": "test request",
                    "business_id": 42,
                    "business_data": {"key": "val"},
                },
            )
            assert result["success"] is True
            mock_db.add.assert_called()
            mock_db.commit.assert_called()

    def test_submit_with_empty_flow_key(self):
        request = Mock()
        with pytest.raises(Exception) as exc_info:
            submit_request(request, body={"flow_key": "  ", "title": "t"})
        assert exc_info.value.status_code == 400


# ========================= approve_request ===============================


class TestApproveRequest:
    def test_no_actor_raises_401(self):
        request = Mock()
        with patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve:
            mock_resolve.return_value = None
            with pytest.raises(Exception) as exc_info:
                approve_request(1, request, body={})
            assert exc_info.value.status_code == 401

    def test_request_not_found(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = approve_request(999, request, body={})
            assert result.status_code == 404

    def test_wrong_status_returns_400(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.status = ApprovalStatus.APPROVED.value
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = approve_request(1, request, body={})
            assert result.status_code == 400

    def test_no_current_node_returns_400(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.status = ApprovalStatus.PENDING.value
        req.current_node = None
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = approve_request(1, request, body={})
            assert result.status_code == 400

    def test_user_not_in_approver_list_returns_403(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.status = ApprovalStatus.PENDING.value
        node = Mock()
        node.id = 10
        node.approver_ids = "[2, 3]"
        req.current_node = node
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch(
                "app.application.approval_workspace_app_service._node_query_for_user"
            ) as mock_nqf,
        ):
            mock_resolve.return_value = 1
            mock_nqf.return_value = False
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = approve_request(1, request, body={})
            assert result.status_code == 403

    def test_approve_success(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.status = ApprovalStatus.PENDING.value
        req.id = 1
        req.request_no = "APR001"
        req.flow_id = 1
        req.title = "Test"
        req.applicant_id = 5
        node = Mock()
        node.id = 10
        node.node_name = "Node1"
        node.node_order = 1
        node.approver_ids = "[1]"
        req.current_node = node
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch(
                "app.application.approval_workspace_app_service._node_query_for_user"
            ) as mock_nqf,
            patch("app.application.approval_workspace_app_service._ordered_nodes") as mock_on,
            patch(
                "app.application.approval_workspace_app_service._close_request_if_needed"
            ) as mock_close,
            patch("app.application.approval_workspace_app_service._audit"),
            patch("app.application.approval_workspace_app_service.notify_mobile_user"),
            patch("app.application.approval_workspace_app_service._request_to_dict") as mock_rtd,
        ):
            mock_resolve.return_value = 1
            mock_nqf.return_value = True
            mock_on.return_value = [node]
            mock_close.return_value = (ApprovalStatus.APPROVED.value, None)
            mock_rtd.return_value = {"id": 1, "status": "approved"}
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = approve_request(1, request, body={})
            assert result["success"] is True
            mock_db.add.assert_called()


# ========================= reject_request ================================


class TestRejectRequest:
    def test_no_actor_raises_401(self):
        request = Mock()
        with patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve:
            mock_resolve.return_value = None
            with pytest.raises(Exception) as exc_info:
                reject_request(1, request, body={})
            assert exc_info.value.status_code == 401

    def test_empty_reason_raises_400(self):
        request = Mock()
        with patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve:
            mock_resolve.return_value = 1
            with pytest.raises(Exception) as exc_info:
                reject_request(1, request, body={})
            assert exc_info.value.status_code == 400

    def test_request_not_found(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = reject_request(999, request, body={"reason": "bad"})
            assert result.status_code == 404

    def test_wrong_status_returns_400(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.status = ApprovalStatus.APPROVED.value
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = reject_request(1, request, body={"reason": "bad"})
            assert result.status_code == 400

    def test_no_current_node_returns_400(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.status = ApprovalStatus.PENDING.value
        req.current_node = None
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = reject_request(1, request, body={"reason": "bad"})
            assert result.status_code == 400

    def test_user_not_approver_returns_403(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.status = ApprovalStatus.PENDING.value
        node = Mock()
        node.id = 10
        node.approver_ids = "[2]"
        req.current_node = node
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch(
                "app.application.approval_workspace_app_service._node_query_for_user"
            ) as mock_nqf,
        ):
            mock_resolve.return_value = 1
            mock_nqf.return_value = False
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = reject_request(1, request, body={"reason": "bad"})
            assert result.status_code == 403

    def test_reject_success(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.status = ApprovalStatus.PENDING.value
        req.id = 1
        req.request_no = "APR001"
        req.flow_id = 1
        node = Mock()
        node.id = 10
        node.node_name = "Node1"
        node.node_order = 1
        node.approver_ids = "[1]"
        req.current_node = node
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch(
                "app.application.approval_workspace_app_service._node_query_for_user"
            ) as mock_nqf,
            patch("app.application.approval_workspace_app_service._audit"),
            patch("app.application.approval_workspace_app_service._request_to_dict") as mock_rtd,
        ):
            mock_resolve.return_value = 1
            mock_nqf.return_value = True
            mock_rtd.return_value = {"id": 1, "status": "rejected"}
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = reject_request(1, request, body={"reason": "不符合要求"})
            assert result["success"] is True
            assert req.status == ApprovalStatus.REJECTED.value
            mock_db.add.assert_called()

    def test_reject_with_opinion_field(self):
        """Reject uses 'opinion' field as reason when 'reason' is absent."""
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.status = ApprovalStatus.PENDING.value
        req.id = 1
        req.request_no = "APR001"
        req.flow_id = 1
        node = Mock()
        node.id = 10
        node.node_name = "Node1"
        node.node_order = 1
        node.approver_ids = "[1]"
        req.current_node = node
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch(
                "app.application.approval_workspace_app_service._node_query_for_user"
            ) as mock_nqf,
            patch("app.application.approval_workspace_app_service._audit"),
            patch("app.application.approval_workspace_app_service._request_to_dict") as mock_rtd,
        ):
            mock_resolve.return_value = 1
            mock_nqf.return_value = True
            mock_rtd.return_value = {"id": 1, "status": "rejected"}
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = reject_request(1, request, body={"opinion": "不同意"})
            assert result["success"] is True


# ========================= withdraw_request ==============================


class TestWithdrawRequest:
    def test_no_actor_raises_401(self):
        request = Mock()
        with patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve:
            mock_resolve.return_value = None
            with pytest.raises(Exception) as exc_info:
                withdraw_request(1, request, body={})
            assert exc_info.value.status_code == 401

    def test_request_not_found(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = withdraw_request(999, request, body={})
            assert result.status_code == 404

    def test_not_applicant_returns_403(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.applicant_id = 2
        req.status = ApprovalStatus.PENDING.value
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = withdraw_request(1, request, body={})
            assert result.status_code == 403

    def test_wrong_status_returns_400(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.applicant_id = 1
        req.status = ApprovalStatus.APPROVED.value
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = withdraw_request(1, request, body={})
            assert result.status_code == 400

    def test_flow_disallows_withdraw_returns_400(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.applicant_id = 1
        req.status = ApprovalStatus.PENDING.value
        req.flow_id = 1
        flow = Mock()
        flow.allow_withdraw = False
        req.flow = flow
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = withdraw_request(1, request, body={})
            assert result.status_code == 400

    def test_withdraw_success(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        node = Mock()
        node.id = 10
        node.node_name = "Node1"
        node.node_order = 1
        req = Mock()
        req.applicant_id = 1
        req.status = ApprovalStatus.PENDING.value
        req.flow_id = 1
        req.id = 1
        req.request_no = "APR001"
        flow = Mock()
        flow.allow_withdraw = True
        req.flow = flow
        req.current_node = node
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch("app.application.approval_workspace_app_service._audit"),
            patch("app.application.approval_workspace_app_service._request_to_dict") as mock_rtd,
        ):
            mock_resolve.return_value = 1
            mock_rtd.return_value = {"id": 1, "status": "withdrawn"}
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = withdraw_request(1, request, body={})
            assert result["success"] is True
            assert req.status == ApprovalStatus.WITHDRAWN.value

    def test_withdraw_flow_none_allowed(self):
        """When flow is None, withdraw should succeed (no restriction)."""
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        node = Mock()
        node.id = 10
        node.node_name = "Node1"
        node.node_order = 1
        req = Mock()
        req.applicant_id = 1
        req.status = ApprovalStatus.PENDING.value
        req.flow_id = 1
        req.id = 1
        req.request_no = "APR001"
        req.flow = None
        req.current_node = node
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch("app.application.approval_workspace_app_service._audit"),
            patch("app.application.approval_workspace_app_service._request_to_dict") as mock_rtd,
        ):
            mock_resolve.return_value = 1
            mock_rtd.return_value = {"id": 1, "status": "withdrawn"}
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = withdraw_request(1, request, body={})
            assert result["success"] is True


# ========================= delete_request ================================


class TestDeleteRequest:
    def test_no_actor_raises_401(self):
        request = Mock()
        with patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve:
            mock_resolve.return_value = None
            with pytest.raises(Exception) as exc_info:
                delete_request(1, request)
            assert exc_info.value.status_code == 401

    def test_not_found(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = delete_request(999, request)
            assert result.status_code == 404

    def test_not_applicant_returns_403(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.applicant_id = 2
        req.status = ApprovalStatus.APPROVED.value
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = delete_request(1, request)
            assert result.status_code == 403

    def test_non_final_status_returns_400(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.applicant_id = 1
        req.status = ApprovalStatus.PENDING.value
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = delete_request(1, request)
            assert result.status_code == 400

    def test_delete_success(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        req = Mock()
        req.applicant_id = 1
        req.status = ApprovalStatus.APPROVED.value
        req.id = 1
        req.request_no = "APR001"
        req.flow_id = 1
        req.business_type = "general"
        req.business_id = None
        req.title = "Test"
        mock_query.first.return_value = req

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch("app.application.approval_workspace_app_service._audit"),
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = delete_request(1, request)
            assert result["success"] is True
            assert result["data"]["deleted"] == 1
            mock_db.delete.assert_called_once_with(req)


# ========================= get_approval_users ============================


class TestGetApprovalUsers:
    def test_with_user_model(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        user = Mock()
        user.id = 1
        user.name = "Admin"
        user.username = "admin"
        user.email = "admin@test.com"
        user.department = "IT"
        mock_query.all.return_value = [user]

        # Create a mock User class with is_active attribute
        MockUser = Mock()
        MockUser.is_active = Mock()

        with (
            patch(
                "app.application.approval_workspace_app_service.get_db",
                return_value=_make_db_ctx(mock_db),
            ),
            patch("app.db.models.User", MockUser, create=True),
        ):
            result = get_approval_users()
            assert result["success"] is True
            assert len(result["data"]) == 1
            assert result["data"][0]["id"] == 1

    def test_fallback_to_product_roster(self):
        # When User query fails, fallback to product roster
        mock_product_svc = MagicMock()
        mock_product_svc.get_all_products.return_value = [
            {"id": 1, "name": "产品A", "product_name": "产品A"},
        ]

        with (
            patch(
                "app.application.approval_workspace_app_service.get_db",
                side_effect=ImportError("no User"),
            ),
            patch(
                "app.application.approval_workspace_app_service.RECOVERABLE_ERRORS", (ImportError,)
            ),
            patch("app.application.get_product_app_service", return_value=mock_product_svc),
        ):
            result = get_approval_users()
            assert result["success"] is True
            assert "data" in result


# ========================= check_approver_orphan =========================


class TestCheckApproverOrphan:
    def test_no_orphan(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        flow = Mock()
        flow.id = 1
        flow.flow_name = "TestFlow"
        flow.nodes = []
        mock_query.all.return_value = [flow]

        with patch("app.application.approval_workspace_app_service.get_db") as mock_get_db:
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = check_approver_orphan(99)
            assert result["success"] is True
            assert result["is_orphan_in_active_flows"] is False

    def test_orphan_found(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        node = Mock()
        node.id = 10
        node.approver_ids = json.dumps([1, 2, 99])
        flow = Mock()
        flow.id = 1
        flow.flow_name = "TestFlow"
        flow.nodes = [node]
        mock_query.all.return_value = [flow]

        with patch("app.application.approval_workspace_app_service.get_db") as mock_get_db:
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = check_approver_orphan(99)
            assert result["success"] is True
            assert result["is_orphan_in_active_flows"] is True
            assert len(result["orphan_flows"]) == 1


# ========================= process_approval_timeouts_endpoint ============


class TestProcessApprovalTimeoutsEndpoint:
    def test_success(self):
        with patch(
            "app.application.workflow.approval_service.process_approval_timeouts"
        ) as mock_pt:
            mock_pt.return_value = {"success": True, "timed_out": 0}
            result = process_approval_timeouts_endpoint()
            assert result.status_code == 200

    def test_failure(self):
        with patch(
            "app.application.workflow.approval_service.process_approval_timeouts"
        ) as mock_pt:
            mock_pt.return_value = {"success": False, "message": "error"}
            result = process_approval_timeouts_endpoint()
            assert result.status_code == 500


# ========================= list_flows ====================================


class TestListFlows:
    def test_list_flows_basic(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        flow = Mock()
        flow.to_dict.return_value = {"id": 1, "flow_key": "fk"}
        mock_query.all.return_value = [flow]

        with patch("app.application.approval_workspace_app_service.get_db") as mock_get_db:
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = list_flows()
            assert result["success"] is True
            assert len(result["data"]) == 1

    def test_list_flows_with_filters(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []

        with patch("app.application.approval_workspace_app_service.get_db") as mock_get_db:
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = list_flows(is_active=True, business_type="general")
            assert result["success"] is True


# ========================= get_flow_detail ===============================


class TestGetFlowDetail:
    def test_found(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        flow = Mock()
        flow.to_dict.return_value = {"id": 1}
        mock_query.first.return_value = flow

        with patch("app.application.approval_workspace_app_service.get_db") as mock_get_db:
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = get_flow_detail(1)
            assert result["success"] is True

    def test_not_found(self):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        with patch("app.application.approval_workspace_app_service.get_db") as mock_get_db:
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = get_flow_detail(999)
            assert result.status_code == 404


# ========================= create_flow ===================================


class TestCreateFlow:
    def test_invalid_flow_payload_raises_400(self):
        request = Mock()
        with pytest.raises(Exception) as exc_info:
            create_flow(request, body={"flow": "not_dict", "nodes": []})
        assert exc_info.value.status_code == 400

    def test_invalid_nodes_payload_raises_400(self):
        request = Mock()
        with pytest.raises(Exception) as exc_info:
            create_flow(request, body={"flow": {}, "nodes": "not_list"})
        assert exc_info.value.status_code == 400

    def test_missing_flow_name_raises_400(self):
        request = Mock()
        with pytest.raises(Exception) as exc_info:
            create_flow(
                request,
                body={"flow": {"flow_key": "fk"}, "nodes": [{"node_name": "n1"}]},
            )
        assert exc_info.value.status_code == 400

    def test_missing_flow_key_raises_400(self):
        request = Mock()
        with pytest.raises(Exception) as exc_info:
            create_flow(
                request,
                body={"flow": {"flow_name": "fn"}, "nodes": [{"node_name": "n1"}]},
            )
        assert exc_info.value.status_code == 400

    def test_no_nodes_raises_400(self):
        request = Mock()
        with pytest.raises(Exception) as exc_info:
            create_flow(
                request,
                body={"flow": {"flow_name": "fn", "flow_key": "fk"}, "nodes": []},
            )
        assert exc_info.value.status_code == 400

    def test_duplicate_flow_key_returns_409(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = Mock()  # existing flow

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = create_flow(
                request,
                body={
                    "flow": {"flow_name": "fn", "flow_key": "fk"},
                    "nodes": [{"node_name": "n1"}],
                },
            )
            assert result.status_code == 409

    def test_create_flow_success(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None  # no existing flow

        flow = Mock()
        flow.id = 1
        flow.to_dict.return_value = {"id": 1, "flow_key": "fk"}
        # Make db.add set the flow id
        mock_db.add.side_effect = lambda obj: None
        mock_db.flush.side_effect = lambda: setattr(flow, "id", 1) if hasattr(flow, "id") else None

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch("app.application.approval_workspace_app_service._audit"),
            patch("app.application.approval_workspace_app_service.ApprovalFlow") as MockFlow,
            patch("app.application.approval_workspace_app_service.ApprovalFlowNode") as MockNode,
        ):
            mock_resolve.return_value = 1
            MockFlow.return_value = flow
            mock_node = Mock()
            MockNode.return_value = mock_node
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = create_flow(
                request,
                body={
                    "flow": {
                        "flow_name": "Test Flow",
                        "flow_key": "test_flow",
                        "business_type": "general",
                    },
                    "nodes": [
                        {
                            "node_name": "Node1",
                            "approver_ids": [1, 2],
                            "node_order": 1,
                        }
                    ],
                },
            )
            assert result["success"] is True

    def test_create_flow_non_dict_node_skipped(self):
        """Non-dict entries in nodes list are silently skipped."""
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        flow = Mock()
        flow.id = 1
        flow.to_dict.return_value = {"id": 1}

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch("app.application.approval_workspace_app_service._audit"),
            patch("app.application.approval_workspace_app_service.ApprovalFlow") as MockFlow,
            patch("app.application.approval_workspace_app_service.ApprovalFlowNode") as MockNode,
        ):
            mock_resolve.return_value = 1
            MockFlow.return_value = flow
            MockNode.return_value = Mock()
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = create_flow(
                request,
                body={
                    "flow": {"flow_name": "fn", "flow_key": "fk"},
                    "nodes": ["not_a_dict", {"node_name": "n1", "approver_ids": [1]}],
                },
            )
            assert result["success"] is True


# ========================= update_flow ===================================


class TestUpdateFlow:
    def test_not_found(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = update_flow(999, request, body={"flow_name": "new"})
            assert result.status_code == 404

    def test_update_success(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        flow = Mock()
        flow.to_dict.return_value = {"id": 1, "flow_name": "Updated"}
        mock_query.first.return_value = flow

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch("app.application.approval_workspace_app_service._audit"),
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = update_flow(1, request, body={"flow_name": "Updated"})
            assert result["success"] is True
            mock_db.commit.assert_called()


# ========================= toggle_flow_active ============================


class TestToggleFlowActive:
    def test_not_found(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = toggle_flow_active(999, request, body={"is_active": True})
            assert result.status_code == 404

    def test_activate(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        flow = Mock()
        flow.is_active = False
        mock_query.first.return_value = flow

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch("app.application.approval_workspace_app_service._audit"),
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = toggle_flow_active(1, request, body={"is_active": True})
            assert result["success"] is True
            assert result["is_active"] is True

    def test_deactivate(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        flow = Mock()
        flow.is_active = True
        mock_query.first.return_value = flow

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch("app.application.approval_workspace_app_service._audit"),
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = toggle_flow_active(1, request, body={"is_active": False})
            assert result["success"] is True
            assert result["is_active"] is False


# ========================= delete_flow ===================================


class TestDeleteFlow:
    def test_not_found(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = delete_flow(999, request)
            assert result.status_code == 404

    def test_pending_requests_returns_409(self):
        request = Mock()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        flow = Mock()
        mock_query.first.return_value = flow

        # Second query for pending count
        mock_count_query = MagicMock()
        mock_db.query.return_value = mock_count_query
        mock_count_query.filter.return_value = mock_count_query
        mock_count_query.count.return_value = 3

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = delete_flow(1, request)
            assert result.status_code == 409

    def test_delete_success(self):
        request = Mock()
        mock_db = MagicMock()
        # First query: find the flow
        flow_query = MagicMock()
        # Second query: count pending
        count_query = MagicMock()

        call_count = [0]

        def query_side_effect(model):
            call_count[0] += 1
            if call_count[0] == 1:
                return flow_query
            return count_query

        mock_db.query.side_effect = query_side_effect
        flow_query.filter.return_value = flow_query
        flow = Mock()
        flow_query.first.return_value = flow

        count_query.filter.return_value = count_query
        count_query.count.return_value = 0

        with (
            patch("app.application.approval_workspace_app_service._resolve_actor") as mock_resolve,
            patch("app.application.approval_workspace_app_service.get_db") as mock_get_db,
            patch("app.application.approval_workspace_app_service._audit"),
        ):
            mock_resolve.return_value = 1
            mock_get_db.return_value = _make_db_ctx(mock_db)
            result = delete_flow(1, request)
            assert result["success"] is True
            assert flow.is_deleted is True
            assert flow.is_active is False
