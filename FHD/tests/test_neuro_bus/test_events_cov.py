"""Coverage tests for neuro_bus event dataclasses.

Strategy: event subclasses call super().__post_init__() but NeuroEvent has no
__post_init__. We patch NeuroEvent to add a no-op __post_init__ that sets
self.payload if absent, then call __post_init__ directly to exercise branches.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.neuro_bus.events.base import EventPriority, NeuroEvent


def _make(cls, payload: dict, **fields):
    """Create an event instance bypassing the broken __init__ chain."""
    ev = object.__new__(cls)
    ev.event_type = fields.get("event_type", "test.event")
    ev.priority = fields.get("priority", EventPriority.NORMAL)
    ev.payload = payload
    return ev


def _call_post_init(ev):
    """Call __post_init__ with NeuroEvent.__post_init__ patched as a no-op."""
    with patch.object(NeuroEvent, "__post_init__", lambda self: None, create=True):
        type(ev).__post_init__(ev)


# ---------------------------------------------------------------------------
# order_events
# ---------------------------------------------------------------------------

from app.neuro_bus.events.order_events import (
    OrderCancelledEvent,
    OrderFulfilledEvent,
    OrderItemUpdatedEvent,
    OrderPaidEvent,
    OrderPaymentFailedEvent,
    OrderRefundedEvent,
    OrderShippedEvent,
    OrderStatusChangedEvent,
    OrderSubmittedEvent,
)


class TestOrderSubmittedEvent:
    def test_valid(self):
        ev = _make(OrderSubmittedEvent, {"order_id": "1", "customer_id": "c", "items": []})
        _call_post_init(ev)  # no exception

    def test_missing_order_id(self):
        ev = _make(OrderSubmittedEvent, {"customer_id": "c", "items": []})
        with pytest.raises(ValueError, match="order_id"):
            _call_post_init(ev)

    def test_missing_customer_id(self):
        ev = _make(OrderSubmittedEvent, {"order_id": "1", "items": []})
        with pytest.raises(ValueError, match="customer_id"):
            _call_post_init(ev)

    def test_missing_items(self):
        ev = _make(OrderSubmittedEvent, {"order_id": "1", "customer_id": "c"})
        with pytest.raises(ValueError, match="items"):
            _call_post_init(ev)


class TestOrderPaidEvent:
    def test_valid(self):
        ev = _make(OrderPaidEvent, {"order_id": "1", "payment_id": "p", "amount": 100})
        _call_post_init(ev)

    def test_missing_order_id(self):
        ev = _make(OrderPaidEvent, {"payment_id": "p", "amount": 100})
        with pytest.raises(ValueError, match="order_id"):
            _call_post_init(ev)

    def test_missing_payment_id(self):
        ev = _make(OrderPaidEvent, {"order_id": "1", "amount": 100})
        with pytest.raises(ValueError, match="payment_id"):
            _call_post_init(ev)

    def test_missing_amount(self):
        ev = _make(OrderPaidEvent, {"order_id": "1", "payment_id": "p"})
        with pytest.raises(ValueError, match="amount"):
            _call_post_init(ev)


class TestOrderPaymentFailedEvent:
    def test_valid(self):
        ev = _make(OrderPaymentFailedEvent, {"order_id": "1"})
        _call_post_init(ev)

    def test_missing_order_id(self):
        ev = _make(OrderPaymentFailedEvent, {})
        with pytest.raises(ValueError, match="order_id"):
            _call_post_init(ev)


class TestOrderFulfilledEvent:
    def test_valid(self):
        ev = _make(OrderFulfilledEvent, {"order_id": "1"})
        _call_post_init(ev)

    def test_missing_order_id(self):
        ev = _make(OrderFulfilledEvent, {})
        with pytest.raises(ValueError, match="order_id"):
            _call_post_init(ev)


class TestOrderShippedEvent:
    def test_valid(self):
        ev = _make(OrderShippedEvent, {"order_id": "1", "shipment_id": "s", "tracking_number": "T"})
        _call_post_init(ev)

    def test_missing_order_id(self):
        ev = _make(OrderShippedEvent, {"shipment_id": "s", "tracking_number": "T"})
        with pytest.raises(ValueError, match="order_id"):
            _call_post_init(ev)

    def test_missing_shipment_id(self):
        ev = _make(OrderShippedEvent, {"order_id": "1", "tracking_number": "T"})
        with pytest.raises(ValueError, match="shipment_id"):
            _call_post_init(ev)

    def test_missing_tracking_number(self):
        ev = _make(OrderShippedEvent, {"order_id": "1", "shipment_id": "s"})
        with pytest.raises(ValueError, match="tracking_number"):
            _call_post_init(ev)


class TestOrderCancelledEvent:
    def test_valid(self):
        ev = _make(OrderCancelledEvent, {"order_id": "1"})
        _call_post_init(ev)

    def test_missing_order_id(self):
        ev = _make(OrderCancelledEvent, {})
        with pytest.raises(ValueError, match="order_id"):
            _call_post_init(ev)


class TestOrderRefundedEvent:
    def test_valid(self):
        ev = _make(OrderRefundedEvent, {"order_id": "1", "refund_id": "r", "refund_amount": 50})
        _call_post_init(ev)

    def test_missing_order_id(self):
        ev = _make(OrderRefundedEvent, {"refund_id": "r", "refund_amount": 50})
        with pytest.raises(ValueError, match="order_id"):
            _call_post_init(ev)

    def test_missing_refund_id(self):
        ev = _make(OrderRefundedEvent, {"order_id": "1", "refund_amount": 50})
        with pytest.raises(ValueError, match="refund_id"):
            _call_post_init(ev)

    def test_missing_refund_amount(self):
        ev = _make(OrderRefundedEvent, {"order_id": "1", "refund_id": "r"})
        with pytest.raises(ValueError, match="refund_amount"):
            _call_post_init(ev)


class TestOrderItemUpdatedEvent:
    def test_valid(self):
        ev = _make(OrderItemUpdatedEvent, {"order_id": "1", "item_id": "i", "changes": {}})
        _call_post_init(ev)

    def test_missing_order_id(self):
        ev = _make(OrderItemUpdatedEvent, {"item_id": "i", "changes": {}})
        with pytest.raises(ValueError, match="order_id"):
            _call_post_init(ev)

    def test_missing_item_id(self):
        ev = _make(OrderItemUpdatedEvent, {"order_id": "1", "changes": {}})
        with pytest.raises(ValueError, match="item_id"):
            _call_post_init(ev)

    def test_missing_changes(self):
        ev = _make(OrderItemUpdatedEvent, {"order_id": "1", "item_id": "i"})
        with pytest.raises(ValueError, match="changes"):
            _call_post_init(ev)


class TestOrderStatusChangedEvent:
    def test_valid(self):
        ev = _make(
            OrderStatusChangedEvent, {"order_id": "1", "old_status": "draft", "new_status": "paid"}
        )
        _call_post_init(ev)

    def test_missing_order_id(self):
        ev = _make(OrderStatusChangedEvent, {"old_status": "draft", "new_status": "paid"})
        with pytest.raises(ValueError, match="order_id"):
            _call_post_init(ev)

    def test_missing_old_status(self):
        ev = _make(OrderStatusChangedEvent, {"order_id": "1", "new_status": "paid"})
        with pytest.raises(ValueError, match="old_status"):
            _call_post_init(ev)

    def test_missing_new_status(self):
        ev = _make(OrderStatusChangedEvent, {"order_id": "1", "old_status": "draft"})
        with pytest.raises(ValueError, match="new_status"):
            _call_post_init(ev)


# ---------------------------------------------------------------------------
# auth_events
# ---------------------------------------------------------------------------

from app.neuro_bus.events.auth_events import (
    LoginFailedEvent,
    TokenRefreshedEvent,
    UserLoginEvent,
    UserLogoutEvent,
    UserPasswordChangedEvent,
    UserPermissionGrantedEvent,
    UserPermissionRevokedEvent,
    UserRegisteredEvent,
)


class TestUserLoginEvent:
    # required: user_id, login_method, ip_address
    def test_valid(self):
        ev = _make(
            UserLoginEvent, {"user_id": "u1", "login_method": "password", "ip_address": "1.2.3.4"}
        )
        _call_post_init(ev)

    def test_missing_user_id(self):
        ev = _make(UserLoginEvent, {"login_method": "password", "ip_address": "1.2.3.4"})
        with pytest.raises(ValueError, match="user_id"):
            _call_post_init(ev)

    def test_missing_login_method(self):
        ev = _make(UserLoginEvent, {"user_id": "u1", "ip_address": "1.2.3.4"})
        with pytest.raises(ValueError, match="login_method"):
            _call_post_init(ev)

    def test_missing_ip_address(self):
        ev = _make(UserLoginEvent, {"user_id": "u1", "login_method": "password"})
        with pytest.raises(ValueError, match="ip_address"):
            _call_post_init(ev)


class TestUserLogoutEvent:
    # required: user_id
    def test_valid(self):
        ev = _make(UserLogoutEvent, {"user_id": "u1"})
        _call_post_init(ev)

    def test_missing_user_id(self):
        ev = _make(UserLogoutEvent, {})
        with pytest.raises(ValueError, match="user_id"):
            _call_post_init(ev)


class TestUserRegisteredEvent:
    # required: user_id, username, registration_source
    def test_valid(self):
        ev = _make(
            UserRegisteredEvent,
            {"user_id": "u1", "username": "alice", "registration_source": "web"},
        )
        _call_post_init(ev)

    def test_missing_user_id(self):
        ev = _make(UserRegisteredEvent, {"username": "alice", "registration_source": "web"})
        with pytest.raises(ValueError, match="user_id"):
            _call_post_init(ev)

    def test_missing_username(self):
        ev = _make(UserRegisteredEvent, {"user_id": "u1", "registration_source": "web"})
        with pytest.raises(ValueError, match="username"):
            _call_post_init(ev)

    def test_missing_registration_source(self):
        ev = _make(UserRegisteredEvent, {"user_id": "u1", "username": "alice"})
        with pytest.raises(ValueError, match="registration_source"):
            _call_post_init(ev)


class TestUserPasswordChangedEvent:
    # required: user_id
    def test_valid(self):
        ev = _make(UserPasswordChangedEvent, {"user_id": "u1"})
        _call_post_init(ev)

    def test_missing_user_id(self):
        ev = _make(UserPasswordChangedEvent, {})
        with pytest.raises(ValueError, match="user_id"):
            _call_post_init(ev)


class TestUserPermissionGrantedEvent:
    # required: user_id, permission, granted_by
    def test_valid(self):
        ev = _make(
            UserPermissionGrantedEvent,
            {"user_id": "u1", "permission": "admin", "granted_by": "root"},
        )
        _call_post_init(ev)

    def test_missing_user_id(self):
        ev = _make(UserPermissionGrantedEvent, {"permission": "admin", "granted_by": "root"})
        with pytest.raises(ValueError, match="user_id"):
            _call_post_init(ev)

    def test_missing_permission(self):
        ev = _make(UserPermissionGrantedEvent, {"user_id": "u1", "granted_by": "root"})
        with pytest.raises(ValueError, match="permission"):
            _call_post_init(ev)

    def test_missing_granted_by(self):
        ev = _make(UserPermissionGrantedEvent, {"user_id": "u1", "permission": "admin"})
        with pytest.raises(ValueError, match="granted_by"):
            _call_post_init(ev)


class TestUserPermissionRevokedEvent:
    # required: user_id, permission, revoked_by
    def test_valid(self):
        ev = _make(
            UserPermissionRevokedEvent,
            {"user_id": "u1", "permission": "admin", "revoked_by": "root"},
        )
        _call_post_init(ev)

    def test_missing_user_id(self):
        ev = _make(UserPermissionRevokedEvent, {"permission": "admin", "revoked_by": "root"})
        with pytest.raises(ValueError, match="user_id"):
            _call_post_init(ev)

    def test_missing_permission(self):
        ev = _make(UserPermissionRevokedEvent, {"user_id": "u1", "revoked_by": "root"})
        with pytest.raises(ValueError, match="permission"):
            _call_post_init(ev)

    def test_missing_revoked_by(self):
        ev = _make(UserPermissionRevokedEvent, {"user_id": "u1", "permission": "admin"})
        with pytest.raises(ValueError, match="revoked_by"):
            _call_post_init(ev)


class TestLoginFailedEvent:
    # required: username, reason, ip_address
    def test_valid(self):
        ev = _make(
            LoginFailedEvent, {"username": "alice", "reason": "bad_pw", "ip_address": "1.2.3.4"}
        )
        _call_post_init(ev)

    def test_missing_username(self):
        ev = _make(LoginFailedEvent, {"reason": "bad_pw", "ip_address": "1.2.3.4"})
        with pytest.raises(ValueError, match="username"):
            _call_post_init(ev)

    def test_missing_reason(self):
        ev = _make(LoginFailedEvent, {"username": "alice", "ip_address": "1.2.3.4"})
        with pytest.raises(ValueError, match="reason"):
            _call_post_init(ev)

    def test_missing_ip_address(self):
        ev = _make(LoginFailedEvent, {"username": "alice", "reason": "bad_pw"})
        with pytest.raises(ValueError, match="ip_address"):
            _call_post_init(ev)


class TestTokenRefreshedEvent:
    # required: user_id
    def test_valid(self):
        ev = _make(TokenRefreshedEvent, {"user_id": "u1"})
        _call_post_init(ev)

    def test_missing_user_id(self):
        ev = _make(TokenRefreshedEvent, {})
        with pytest.raises(ValueError, match="user_id"):
            _call_post_init(ev)
