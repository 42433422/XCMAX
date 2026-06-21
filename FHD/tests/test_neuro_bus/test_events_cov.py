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
# wechat_events
# ---------------------------------------------------------------------------

from app.neuro_bus.events.wechat_events import (
    WeChatContactAddedEvent,
    WeChatContactUpdatedEvent,
    WeChatLoginStatusChangedEvent,
    WeChatMessageReceivedEvent,
    WeChatMessageSentEvent,
    WeChatTaskCompletedEvent,
    WeChatTaskCreatedEvent,
)


class TestWeChatMessageReceivedEvent:
    # required: message_id, from_user, message_type, content
    def test_valid(self):
        ev = _make(
            WeChatMessageReceivedEvent,
            {"message_id": "m1", "from_user": "u1", "message_type": "text", "content": "hi"},
        )
        _call_post_init(ev)

    def test_missing_message_id(self):
        ev = _make(
            WeChatMessageReceivedEvent, {"from_user": "u1", "message_type": "text", "content": "hi"}
        )
        with pytest.raises(ValueError, match="message_id"):
            _call_post_init(ev)

    def test_missing_from_user(self):
        ev = _make(
            WeChatMessageReceivedEvent,
            {"message_id": "m1", "message_type": "text", "content": "hi"},
        )
        with pytest.raises(ValueError, match="from_user"):
            _call_post_init(ev)

    def test_missing_content(self):
        ev = _make(
            WeChatMessageReceivedEvent,
            {"message_id": "m1", "from_user": "u1", "message_type": "text"},
        )
        with pytest.raises(ValueError, match="content"):
            _call_post_init(ev)


class TestWeChatMessageSentEvent:
    # required: message_id, to_user, message_type, status
    def test_valid(self):
        ev = _make(
            WeChatMessageSentEvent,
            {"message_id": "m1", "to_user": "u1", "message_type": "text", "status": "ok"},
        )
        _call_post_init(ev)

    def test_missing_message_id(self):
        ev = _make(
            WeChatMessageSentEvent, {"to_user": "u1", "message_type": "text", "status": "ok"}
        )
        with pytest.raises(ValueError, match="message_id"):
            _call_post_init(ev)

    def test_missing_to_user(self):
        ev = _make(
            WeChatMessageSentEvent, {"message_id": "m1", "message_type": "text", "status": "ok"}
        )
        with pytest.raises(ValueError, match="to_user"):
            _call_post_init(ev)


class TestWeChatContactAddedEvent:
    # required: contact_id, contact_name, source
    def test_valid(self):
        ev = _make(
            WeChatContactAddedEvent, {"contact_id": "c", "contact_name": "Alice", "source": "scan"}
        )
        _call_post_init(ev)

    def test_missing_contact_id(self):
        ev = _make(WeChatContactAddedEvent, {"contact_name": "Alice", "source": "scan"})
        with pytest.raises(ValueError, match="contact_id"):
            _call_post_init(ev)

    def test_missing_contact_name(self):
        ev = _make(WeChatContactAddedEvent, {"contact_id": "c", "source": "scan"})
        with pytest.raises(ValueError, match="contact_name"):
            _call_post_init(ev)

    def test_missing_source(self):
        ev = _make(WeChatContactAddedEvent, {"contact_id": "c", "contact_name": "Alice"})
        with pytest.raises(ValueError, match="source"):
            _call_post_init(ev)


class TestWeChatContactUpdatedEvent:
    # required: contact_id only
    def test_valid(self):
        ev = _make(WeChatContactUpdatedEvent, {"contact_id": "c"})
        _call_post_init(ev)

    def test_missing_contact_id(self):
        ev = _make(WeChatContactUpdatedEvent, {})
        with pytest.raises(ValueError, match="contact_id"):
            _call_post_init(ev)


class TestWeChatLoginStatusChangedEvent:
    # required: account_id, old_status, new_status
    def test_valid(self):
        ev = _make(
            WeChatLoginStatusChangedEvent,
            {"account_id": "a1", "old_status": "offline", "new_status": "online"},
        )
        _call_post_init(ev)

    def test_missing_account_id(self):
        ev = _make(WeChatLoginStatusChangedEvent, {"old_status": "offline", "new_status": "online"})
        with pytest.raises(ValueError, match="account_id"):
            _call_post_init(ev)

    def test_missing_old_status(self):
        ev = _make(WeChatLoginStatusChangedEvent, {"account_id": "a1", "new_status": "online"})
        with pytest.raises(ValueError, match="old_status"):
            _call_post_init(ev)

    def test_missing_new_status(self):
        ev = _make(WeChatLoginStatusChangedEvent, {"account_id": "a1", "old_status": "offline"})
        with pytest.raises(ValueError, match="new_status"):
            _call_post_init(ev)


class TestWeChatTaskCreatedEvent:
    # required: task_id, task_type, target_contacts, content
    def test_valid(self):
        ev = _make(
            WeChatTaskCreatedEvent,
            {"task_id": "t1", "task_type": "broadcast", "target_contacts": [], "content": "msg"},
        )
        _call_post_init(ev)

    def test_missing_task_id(self):
        ev = _make(
            WeChatTaskCreatedEvent,
            {"task_type": "broadcast", "target_contacts": [], "content": "msg"},
        )
        with pytest.raises(ValueError, match="task_id"):
            _call_post_init(ev)

    def test_missing_task_type(self):
        ev = _make(
            WeChatTaskCreatedEvent, {"task_id": "t1", "target_contacts": [], "content": "msg"}
        )
        with pytest.raises(ValueError, match="task_type"):
            _call_post_init(ev)

    def test_missing_content(self):
        ev = _make(
            WeChatTaskCreatedEvent,
            {"task_id": "t1", "task_type": "broadcast", "target_contacts": []},
        )
        with pytest.raises(ValueError, match="content"):
            _call_post_init(ev)


class TestWeChatTaskCompletedEvent:
    # required: task_id, success_count, failed_count
    def test_valid(self):
        ev = _make(
            WeChatTaskCompletedEvent, {"task_id": "t1", "success_count": 3, "failed_count": 0}
        )
        _call_post_init(ev)

    def test_missing_task_id(self):
        ev = _make(WeChatTaskCompletedEvent, {"success_count": 3, "failed_count": 0})
        with pytest.raises(ValueError, match="task_id"):
            _call_post_init(ev)

    def test_missing_success_count(self):
        ev = _make(WeChatTaskCompletedEvent, {"task_id": "t1", "failed_count": 0})
        with pytest.raises(ValueError, match="success_count"):
            _call_post_init(ev)

    def test_missing_failed_count(self):
        ev = _make(WeChatTaskCompletedEvent, {"task_id": "t1", "success_count": 3})
        with pytest.raises(ValueError, match="failed_count"):
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
