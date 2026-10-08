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


@pytest.mark.parametrize(
    "snapshot_has_request,case",
    [
        (False, "success"),
        (True, "success"),
        (False, "denied"),
        (False, "intermediate"),
        (False, "invalid-backup"),
        (False, "multi"),
    ],
)
def test_configured_restore_approval_restores_wal_and_retains_audit(
    tmp_path, snapshot_has_request, case
):
    import sqlite3
    from contextlib import contextmanager

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from app.application import approval_workspace_app_service as service
    from app.db.base import Base
    from app.db.models import User
    from app.db.models.approval import (
        ApprovalFlow,
        ApprovalFlowNode,
        ApprovalRecord,
        ApprovalRequest,
    )
    from app.services.database_service import DatabaseService

    live, backup = tmp_path / "live.db", tmp_path / "snapshot.bak"
    engine = create_engine(f"sqlite:///{live}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("pragma journal_mode=wal")
            connection.exec_driver_sql("create table restore_probe(price real)")
            connection.exec_driver_sql("insert into restore_probe values(12.50)")
            connection.exec_driver_sql(
                "create table ai_action_audit(actor text, action text, payload text)"
            )
        with sessions() as db:
            db.add(User(id=41, username="configured-restore", password="test"))
            db.add(
                ApprovalFlow(id=1, flow_key="configured-restore", flow_name="Configured restore")
            )
            db.commit()
            db.add(
                ApprovalFlowNode(
                    id=1,
                    flow_id=1,
                    node_name="Manager approval",
                    node_order=1,
                    approver_type="user",
                    approver_ids="[77]" if case == "denied" else "[41]",
                )
            )
            if case in {"intermediate", "multi"}:
                db.add(
                    ApprovalFlowNode(
                        id=2,
                        flow_id=1,
                        node_name="Final approval",
                        node_order=2,
                        approver_type="user",
                        approver_ids="[41]",
                    )
                )
            db.commit()
        with sqlite3.connect(live) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        with sessions() as db:
            db.add(
                ApprovalRequest(
                    id=4,
                    tenant_id=1,
                    request_no="APR-configured-restore",
                    flow_id=1,
                    business_type="workflow_tool",
                    business_data=json.dumps(
                        {"tool_id": "system_maintenance", "action": "restore_database"}
                    ),
                    applicant_id=41,
                    title="Configured restore",
                    status="pending",
                    current_node_id=1,
                    current_node_order=1,
                )
            )
            db.commit()
            if snapshot_has_request:
                with sqlite3.connect(live) as source, sqlite3.connect(backup) as target:
                    source.backup(target)
            db.execute(text("update restore_probe set price=13.50"))
            db.commit()
        if case == "invalid-backup":
            backup.write_bytes(b"INVALID SYNTHETIC BACKUP")

        @contextmanager
        def database_context():
            with sessions() as db:
                yield db

        def resume(**kwargs):
            database = DatabaseService()
            with patch.object(database, "_get_db_path", return_value=str(live)):
                outcome = database.restore_database(str(backup))
            return {
                "success": outcome["success"],
                "workflow_executed": outcome["success"],
                "nodes_executed": 1,
                "nodes_total": 1,
            }

        with (
            patch.object(service, "get_db", side_effect=database_context),
            patch.object(service, "_resolve_actor", return_value=41),
            patch.object(
                service, "_resume_pending_ai_workflow_after_approval", side_effect=resume
            ) as execution,
            patch.object(service, "notify_mobile_user"),
        ):
            response = service.approve_request(4, Mock(), body={"opinion": "restore authorized"})
            if case == "denied":
                assert response.status_code == 403
                execution.assert_not_called()
                with sessions() as db:
                    assert db.get(ApprovalRequest, 4).status == "pending"
                    assert db.query(ApprovalRecord).count() == 0
                    assert db.execute(text("select price from restore_probe")).scalar() == 13.50
                return
            if case == "intermediate":
                assert response["success"] is True
                execution.assert_not_called()
                with sessions() as db:
                    assert db.get(ApprovalRequest, 4).status == "in_progress"
                    assert db.execute(text("select price from restore_probe")).scalar() == 13.50
                return
            if case == "multi":
                execution.assert_not_called()
                response = service.approve_request(
                    4, Mock(), body={"opinion": "final restore authorized"}
                )
            assert execution.call_count == 1
        if case == "invalid-backup":
            assert response["success"] is False
            with sessions() as db:
                assert db.get(ApprovalRequest, 4).status == "cancelled"
                assert db.execute(text("select price from restore_probe")).scalar() == 13.50
                assert (
                    db.query(ApprovalRecord).filter_by(request_id=4, action="approve").count() == 1
                )
                assert db.execute(text("select count(*) from ai_action_audit")).scalar() == 2
            with sqlite3.connect(live) as reopened:
                assert reopened.execute("pragma integrity_check").fetchall() == [("ok",)]
            return
        assert response["success"] is True
        with sessions() as db:
            assert db.execute(text("select price from restore_probe")).scalar() == 12.50
            assert db.get(ApprovalRequest, 4).status == "approved"
            assert db.query(ApprovalRecord).filter_by(request_id=4, action="approve").count() == (
                2 if case == "multi" else 1
            )
            records = (
                db.query(ApprovalRecord)
                .filter_by(request_id=4)
                .order_by(ApprovalRecord.node_order)
                .all()
            )
            assert [record.opinion for record in records] == (
                ["restore authorized", "final restore authorized"]
                if case == "multi"
                else ["restore authorized"]
            )
            assert all(record.approver_id == 41 for record in records)
            assert db.execute(text("select count(*) from ai_action_audit")).scalar() == 1
        with sqlite3.connect(live) as reopened:
            assert reopened.execute("pragma integrity_check").fetchall() == [("ok",)]
    finally:
        engine.dispose()


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
