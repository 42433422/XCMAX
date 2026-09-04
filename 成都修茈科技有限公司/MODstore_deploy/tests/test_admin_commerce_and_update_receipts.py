from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from starlette.requests import Request


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def _user(db, *, admin: bool):
    from modstore_server.models import User

    suffix = uuid.uuid4().hex[:12]
    row = User(
        username=f"commerce_{suffix}",
        email=f"commerce_{suffix}@pytest.local",
        password_hash="x",
        is_admin=admin,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_update_install_receipt_is_idempotent_and_summarizes_latest_device(client):
    from modstore_server.api.app_factory import _iter_route_method_signatures
    from modstore_server.app import app
    from modstore_server.models import get_session_factory
    from modstore_server.update_installation_api import (
        UpdateInstallationReceiptBody,
        list_update_installation_receipts,
        record_update_installation_receipt,
    )

    assert ("/api/update-installations/receipts", "POST") in set(
        _iter_route_method_signatures(app.routes)
    )
    sf = get_session_factory()
    with sf() as db:
        user = _user(db, admin=False)
        admin = _user(db, admin=True)
        installation_id = str(uuid.uuid4())
        target_sha = "a" * 40
        first = UpdateInstallationReceiptBody(
            installation_id=installation_id,
            idempotency_key=f"install-{uuid.uuid4().hex}",
            target_version="1.0.0.1",
            target_build_sha=target_sha,
            installed_version="1.0.0.1",
            installed_build_sha=target_sha,
            status="installed",
            reported_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        created = record_update_installation_receipt(first, db, user)
        assert created["ok"] is True
        assert created["duplicate"] is False
        replay = record_update_installation_receipt(first, db, user)
        assert replay["duplicate"] is True
        failed = UpdateInstallationReceiptBody(
            installation_id=installation_id,
            idempotency_key=f"install-{uuid.uuid4().hex}",
            target_version="1.0.0.1",
            target_build_sha=target_sha,
            installed_version="1.0.0.1",
            installed_build_sha="b" * 40,
            status="failed",
            error="build mismatch",
            reported_at=datetime.now(UTC),
        )
        record_update_installation_receipt(failed, db, user)
        listed = list_update_installation_receipts(target_sha, 200, db, admin)
        assert len(listed["items"]) == 2
        assert listed["summary"] == {
            "reported_devices": 1,
            "installed_devices": 0,
            "failed_devices": 1,
            "rolled_back_devices": 0,
        }


@pytest.mark.asyncio
async def test_admin_order_actions_are_safe_idempotent_and_audited(client, tmp_path, monkeypatch):
    from modstore_server import admin_commerce_api, payment_orders
    from modstore_server.db.delivery_commerce import CommerceAdminAction
    from modstore_server.models import RefundRequest, get_session_factory

    monkeypatch.setenv("PAYMENT_BACKEND", "python")
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.setattr(admin_commerce_api.alipay_service, "close_order", lambda **_: {"ok": True})
    sf = get_session_factory()
    with sf() as db:
        admin = _user(db, admin=True)
        order_no = f"PENDING-{uuid.uuid4().hex[:10]}"
        assert (
            payment_orders.create(
                out_trade_no=order_no,
                subject="pytest pending order",
                total_amount="100.00",
                user_id=admin.id,
                pay_type="alipay",
            )["ok"]
            is True
        )
        cancel_body = admin_commerce_api.AdminOrderActionBody(
            reason="客户确认取消",
            idempotency_key=f"cancel-{uuid.uuid4().hex}",
        )
        cancelled = await admin_commerce_api.cancel_admin_order(
            order_no, cancel_body, _request(), db, admin
        )
        assert cancelled["status"] == "closed"
        replay = await admin_commerce_api.cancel_admin_order(
            order_no, cancel_body, _request(), db, admin
        )
        assert replay["duplicate"] is True
        assert payment_orders.find(order_no)["status"] == "closed"

        reprice_no = f"REPRICE-{uuid.uuid4().hex[:10]}"
        assert (
            payment_orders.create(
                out_trade_no=reprice_no,
                subject="pytest reprice order",
                total_amount="100.00",
                user_id=admin.id,
                pay_type="alipay",
            )["ok"]
            is True
        )
        monkeypatch.setattr(
            admin_commerce_api.alipay_service,
            "create_pay_order",
            lambda **_: {"ok": False, "message": "provider unavailable"},
        )
        reprice_body = admin_commerce_api.AdminOrderRepriceBody(
            reason="合同金额调整",
            idempotency_key=f"reprice-{uuid.uuid4().hex}",
            new_amount=88,
        )
        partial = await admin_commerce_api.reprice_admin_order(
            reprice_no, reprice_body, _request(), db, admin
        )
        assert partial["ok"] is False
        assert partial["partial_success"] is True
        assert payment_orders.find(reprice_no)["status"] == "closed"
        audit = (
            db.query(CommerceAdminAction)
            .filter_by(idempotency_key=reprice_body.idempotency_key)
            .one()
        )
        assert audit.status == "partial"

        paid_no = f"PAID-{uuid.uuid4().hex[:10]}"
        assert (
            payment_orders.create(
                out_trade_no=paid_no,
                subject="pytest paid order",
                total_amount="66.00",
                user_id=admin.id,
            )["ok"]
            is True
        )
        assert payment_orders.update_status(out_trade_no=paid_no, status="paid") is True
        refund_body = admin_commerce_api.AdminOrderActionBody(
            reason="客户确认退款",
            idempotency_key=f"refund-{uuid.uuid4().hex}",
        )
        refund = await admin_commerce_api.create_admin_refund_request(
            paid_no, refund_body, _request(), db, admin
        )
        assert refund["status"] == "pending"
        assert db.query(RefundRequest).filter_by(order_no=paid_no, status="pending").one()
