"""AIOPEN 审批桥数据库集成测试：发起 → 审批 → 执行 → 防重放。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.aiopen import approval_bridge
from app.db.db_base import Base
from app.db.models.approval import (
    ApprovalFlow,
    ApprovalFlowNode,
    ApprovalRequest,
    ApprovalStatus,
)
from app.domain.aiopen.principal import ScreenPrincipal
from app.infrastructure.aiopen.principal_context import screen_principal_scope

_FLOW_KEY = "aiopen_danger_operation"


def _entry():
    return {
        "operation_id": "products.delete",
        "method": "DELETE",
        "path": "/api/products/{product_id}",
        "risk": "danger",
    }


@pytest.fixture()
def session_factory(monkeypatch):
    monkeypatch.setenv(approval_bridge.FLOW_KEY_ENV, _FLOW_KEY)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _disable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with patch("app.db.session.SessionLocal", testing_session):
        yield testing_session


def _seed_flow(factory) -> None:
    with factory() as db:
        flow = ApprovalFlow(
            flow_key=_FLOW_KEY, flow_name="AIOPEN 危险操作", is_active=True, is_deleted=False
        )
        db.add(flow)
        db.flush()
        db.add(
            ApprovalFlowNode(
                flow_id=flow.id,
                node_name="管理员审批",
                node_order=1,
                approver_type="user",
                is_active=True,
            )
        )
        db.commit()


def _approve(factory, approval_id: int) -> None:
    with factory() as db:
        request = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
        request.status = ApprovalStatus.APPROVED.value
        db.commit()


def test_missing_flow_fails_closed(session_factory):
    outcome = approval_bridge.submit(
        _entry(), {"params": {"product_id": "P-1"}}, ScreenPrincipal("7", "1")
    )
    assert outcome["code"] == "APPROVAL_FLOW_NOT_CONFIGURED"


def test_submit_creates_pending_request(session_factory):
    _seed_flow(session_factory)
    principal = ScreenPrincipal("7", "1")
    outcome = approval_bridge.submit(
        _entry(), {"params": {"product_id": "P-1"}}, principal
    )
    assert outcome["status"] == "pending"
    assert outcome["code"] == "APPROVAL_REQUIRED"
    with session_factory() as db:
        request = db.query(ApprovalRequest).filter(
            ApprovalRequest.id == outcome["approval_id"]
        ).first()
        assert request.status == ApprovalStatus.PENDING.value
        assert request.business_type == approval_bridge.BUSINESS_TYPE
        assert request.applicant_id == 7


def test_consume_requires_approval_then_executes_once(session_factory):
    _seed_flow(session_factory)
    principal = ScreenPrincipal("7", "1")
    args = {"params": {"product_id": "P-1"}}
    submitted = approval_bridge.submit(_entry(), args, principal)
    approval_id = submitted["approval_id"]

    pending = approval_bridge.consume(approval_id, _entry(), args, principal)
    assert pending["code"] == "APPROVAL_PENDING"

    _approve(session_factory, approval_id)
    approved = approval_bridge.consume(approval_id, _entry(), args, principal)
    assert approved["status"] == "approved"

    replay = approval_bridge.consume(approval_id, _entry(), args, principal)
    assert replay["code"] == "APPROVAL_CONSUMED"


def test_consume_rejects_argument_mismatch(session_factory):
    _seed_flow(session_factory)
    principal = ScreenPrincipal("7", "1")
    submitted = approval_bridge.submit(
        _entry(), {"params": {"product_id": "P-1"}}, principal
    )
    _approve(session_factory, submitted["approval_id"])
    mismatch = approval_bridge.consume(
        submitted["approval_id"], _entry(), {"params": {"product_id": "P-2"}}, principal
    )
    assert mismatch["code"] == "APPROVAL_MISMATCH"


def test_consume_rejects_other_applicant(session_factory):
    _seed_flow(session_factory)
    submitted = approval_bridge.submit(
        _entry(), {"params": {"product_id": "P-1"}}, ScreenPrincipal("7", "1")
    )
    _approve(session_factory, submitted["approval_id"])
    other = approval_bridge.consume(
        submitted["approval_id"],
        _entry(),
        {"params": {"product_id": "P-1"}},
        ScreenPrincipal("8", "1"),
    )
    assert other["code"] == "APPROVAL_MISMATCH"


def test_submit_uses_request_scoped_principal(session_factory):
    _seed_flow(session_factory)
    principal = ScreenPrincipal("7", "1")
    with screen_principal_scope(principal):
        outcome = approval_bridge.submit(_entry(), {"params": {"product_id": "P-1"}}, principal)
    assert outcome["status"] == "pending"
