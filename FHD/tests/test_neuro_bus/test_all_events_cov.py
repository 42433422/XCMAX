from __future__ import annotations

"""Branch coverage for all neuro_bus/events/* event modules."""

from unittest.mock import patch

import pytest

from app.neuro_bus.events.base import EventPriority, NeuroEvent


def _make(cls, payload: dict, **fields):
    ev = object.__new__(cls)
    ev.event_type = fields.get("event_type", getattr(cls, "event_type", "test.event"))
    ev.priority = fields.get("priority", EventPriority.NORMAL)
    ev.payload = payload
    return ev


def _call_post_init(ev):
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


class TestOrderEvents:
    def test_order_submitted_ok(self):
        ev = _make(OrderSubmittedEvent, {"order_id": "1", "customer_id": "c1", "items": []})
        _call_post_init(ev)
        assert ev.event_type == "order.submitted"

    def test_order_submitted_missing_field(self):
        ev = _make(OrderSubmittedEvent, {"customer_id": "c1", "items": []})
        with pytest.raises(ValueError, match="order_id"):
            _call_post_init(ev)

    def test_order_paid_ok(self):
        ev = _make(OrderPaidEvent, {"order_id": "1", "payment_id": "p1", "amount": 10})
        _call_post_init(ev)
        assert ev.event_type == "order.paid"

    def test_order_paid_missing(self):
        ev = _make(OrderPaidEvent, {"order_id": "1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_order_payment_failed_ok(self):
        ev = _make(OrderPaymentFailedEvent, {"order_id": "1"})
        _call_post_init(ev)
        assert ev.event_type == "order.payment_failed"

    def test_order_payment_failed_missing(self):
        ev = _make(OrderPaymentFailedEvent, {})
        with pytest.raises(ValueError, match="order_id"):
            _call_post_init(ev)

    def test_order_fulfilled_ok(self):
        ev = _make(OrderFulfilledEvent, {"order_id": "1"})
        _call_post_init(ev)
        assert ev.event_type == "order.fulfilled"

    def test_order_fulfilled_missing(self):
        ev = _make(OrderFulfilledEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_order_shipped_ok(self):
        ev = _make(OrderShippedEvent, {"order_id": "1", "shipment_id": "s1", "tracking_number": "T1"})
        _call_post_init(ev)
        assert ev.event_type == "order.shipped"

    def test_order_shipped_missing(self):
        ev = _make(OrderShippedEvent, {"order_id": "1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_order_cancelled_ok(self):
        ev = _make(OrderCancelledEvent, {"order_id": "1"})
        _call_post_init(ev)
        assert ev.event_type == "order.cancelled"

    def test_order_cancelled_missing(self):
        ev = _make(OrderCancelledEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_order_refunded_ok(self):
        ev = _make(OrderRefundedEvent, {"order_id": "1", "refund_id": "r1", "refund_amount": 5})
        _call_post_init(ev)
        assert ev.event_type == "order.refunded"

    def test_order_refunded_missing(self):
        ev = _make(OrderRefundedEvent, {"order_id": "1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_order_item_updated_ok(self):
        ev = _make(OrderItemUpdatedEvent, {"order_id": "1", "item_id": "i1", "changes": {}})
        _call_post_init(ev)
        assert ev.event_type == "order.item_updated"

    def test_order_item_updated_missing(self):
        ev = _make(OrderItemUpdatedEvent, {"order_id": "1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_order_status_changed_ok(self):
        ev = _make(OrderStatusChangedEvent, {"order_id": "1", "old_status": "pending", "new_status": "paid"})
        _call_post_init(ev)
        assert ev.event_type == "order.status_changed"

    def test_order_status_changed_missing(self):
        ev = _make(OrderStatusChangedEvent, {"order_id": "1"})
        with pytest.raises(ValueError):
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


class TestWechatEvents:
    def test_message_received_ok(self):
        ev = _make(WeChatMessageReceivedEvent, {
                "message_id": "m1",
                "from_user": "u1",
                "message_type": "text",
                "content": "hi",
            })
        _call_post_init(ev)
        assert ev.event_type == "wechat.message_received"

    def test_message_received_missing(self):
        ev = _make(WeChatMessageReceivedEvent, {"message_id": "m1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_message_sent_ok(self):
        ev = _make(WeChatMessageSentEvent, {
                "message_id": "m1",
                "to_user": "u1",
                "message_type": "text",
                "status": "ok",
            })
        _call_post_init(ev)
        assert ev.event_type == "wechat.message_sent"

    def test_message_sent_missing(self):
        ev = _make(WeChatMessageSentEvent, {"message_id": "m1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_contact_added_ok(self):
        ev = _make(WeChatContactAddedEvent, {"contact_id": "c1", "contact_name": "n1", "source": "s"})
        _call_post_init(ev)
        assert ev.event_type == "wechat.contact_added"

    def test_contact_added_missing(self):
        ev = _make(WeChatContactAddedEvent, {"contact_id": "c1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_contact_updated_ok(self):
        ev = _make(WeChatContactUpdatedEvent, {"contact_id": "c1"})
        _call_post_init(ev)
        assert ev.event_type == "wechat.contact_updated"

    def test_contact_updated_missing(self):
        ev = _make(WeChatContactUpdatedEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_task_created_ok(self):
        ev = _make(WeChatTaskCreatedEvent, {
                "task_id": "t1",
                "task_type": "send",
                "target_contacts": [],
                "content": "hi",
            })
        _call_post_init(ev)
        assert ev.event_type == "wechat.task_created"

    def test_task_created_missing(self):
        ev = _make(WeChatTaskCreatedEvent, {"task_id": "t1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_task_completed_ok(self):
        ev = _make(WeChatTaskCompletedEvent, {"task_id": "t1", "success_count": 1, "failed_count": 0})
        _call_post_init(ev)
        assert ev.event_type == "wechat.task_completed"

    def test_task_completed_missing(self):
        ev = _make(WeChatTaskCompletedEvent, {"task_id": "t1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_login_status_changed_ok(self):
        ev = _make(WeChatLoginStatusChangedEvent, {"account_id": "a1", "old_status": "offline", "new_status": "online"})
        _call_post_init(ev)
        assert ev.event_type == "wechat.login_status_changed"

    def test_login_status_changed_missing(self):
        ev = _make(WeChatLoginStatusChangedEvent, {"account_id": "a1"})
        with pytest.raises(ValueError):
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


class TestAuthEvents:
    def test_user_login_ok(self):
        ev = _make(UserLoginEvent, {"user_id": "1", "login_method": "password", "ip_address": "127.0.0.1"})
        _call_post_init(ev)
        assert ev.event_type == "auth.user_login"

    def test_user_login_missing(self):
        ev = _make(UserLoginEvent, {"user_id": "1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_user_logout_ok(self):
        ev = _make(UserLogoutEvent, {"user_id": "1"})
        _call_post_init(ev)
        assert ev.event_type == "auth.user_logout"

    def test_user_logout_missing(self):
        ev = _make(UserLogoutEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_user_registered_ok(self):
        ev = _make(UserRegisteredEvent, {"user_id": "1", "username": "u", "registration_source": "web"})
        _call_post_init(ev)
        assert ev.event_type == "auth.user_registered"

    def test_user_registered_missing(self):
        ev = _make(UserRegisteredEvent, {"user_id": "1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_password_changed_ok(self):
        ev = _make(UserPasswordChangedEvent, {"user_id": "1"})
        _call_post_init(ev)
        assert ev.event_type == "auth.password_changed"

    def test_password_changed_missing(self):
        ev = _make(UserPasswordChangedEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_permission_granted_ok(self):
        ev = _make(UserPermissionGrantedEvent, {"user_id": "1", "permission": "read", "granted_by": "admin"})
        _call_post_init(ev)
        assert ev.event_type == "auth.permission_granted"

    def test_permission_granted_missing(self):
        ev = _make(UserPermissionGrantedEvent, {"user_id": "1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_permission_revoked_ok(self):
        ev = _make(UserPermissionRevokedEvent, {"user_id": "1", "permission": "read", "revoked_by": "admin"})
        _call_post_init(ev)
        assert ev.event_type == "auth.permission_revoked"

    def test_permission_revoked_missing(self):
        ev = _make(UserPermissionRevokedEvent, {"user_id": "1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_login_failed_ok(self):
        ev = _make(LoginFailedEvent, {"username": "u", "reason": "bad_pass", "ip_address": "127.0.0.1"})
        _call_post_init(ev)
        assert ev.event_type == "auth.login_failed"

    def test_login_failed_missing(self):
        ev = _make(LoginFailedEvent, {"username": "u"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_token_refreshed_ok(self):
        ev = _make(TokenRefreshedEvent, {"user_id": "1"})
        _call_post_init(ev)
        assert ev.event_type == "auth.token_refreshed"

    def test_token_refreshed_missing(self):
        ev = _make(TokenRefreshedEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)


# ---------------------------------------------------------------------------
# payment_events
# ---------------------------------------------------------------------------
from app.neuro_bus.events.payment_events import (
    PaymentCompletedEvent,
    PaymentCreatedEvent,
    PaymentFailedEvent,
    PaymentMethodChangedEvent,
    PaymentNotificationSentEvent,
    PaymentRefundedEvent,
)


class TestPaymentEvents:
    def test_payment_created_ok(self):
        ev = _make(PaymentCreatedEvent, {
                "payment_id": "p1",
                "order_id": "o1",
                "amount": 100,
                "payment_method": "card",
            })
        _call_post_init(ev)
        assert ev.event_type == "payment.created"

    def test_payment_created_missing(self):
        ev = _make(PaymentCreatedEvent, {"payment_id": "p1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_payment_completed_ok(self):
        ev = _make(PaymentCompletedEvent, {"payment_id": "p1", "transaction_id": "t1", "paid_amount": 100})
        _call_post_init(ev)
        assert ev.event_type == "payment.completed"

    def test_payment_completed_missing(self):
        ev = _make(PaymentCompletedEvent, {"payment_id": "p1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_payment_failed_ok(self):
        ev = _make(PaymentFailedEvent, {"payment_id": "p1", "error_code": "E01", "error_message": "fail"})
        _call_post_init(ev)
        assert ev.event_type == "payment.failed"

    def test_payment_failed_missing(self):
        ev = _make(PaymentFailedEvent, {"payment_id": "p1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_payment_refunded_ok(self):
        ev = _make(PaymentRefundedEvent, {
                "payment_id": "p1",
                "refund_id": "r1",
                "refund_amount": 50,
                "reason": "customer",
            })
        _call_post_init(ev)
        assert ev.event_type == "payment.refunded"

    def test_payment_refunded_missing(self):
        ev = _make(PaymentRefundedEvent, {"payment_id": "p1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_payment_method_changed_ok(self):
        ev = _make(PaymentMethodChangedEvent, {"payment_id": "p1", "old_method": "card", "new_method": "cash"})
        _call_post_init(ev)
        assert ev.event_type == "payment.method_changed"

    def test_payment_method_changed_missing(self):
        ev = _make(PaymentMethodChangedEvent, {"payment_id": "p1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_payment_notification_sent_ok(self):
        ev = _make(PaymentNotificationSentEvent, {
                "payment_id": "p1",
                "notification_type": "email",
                "recipient": "a@b.com",
            })
        _call_post_init(ev)
        assert ev.event_type == "payment.notification_sent"

    def test_payment_notification_sent_missing(self):
        ev = _make(PaymentNotificationSentEvent, {"payment_id": "p1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)


# ---------------------------------------------------------------------------
# inventory_events
# ---------------------------------------------------------------------------
from app.neuro_bus.events.inventory_events import (
    InventoryCheckCompletedEvent,
    InventoryLowStockAlertEvent,
    InventoryStockChangedEvent,
    InventoryStockInEvent,
    InventoryStockOutEvent,
    InventoryTransferEvent,
)


class TestInventoryEvents:
    def test_stock_changed_ok(self):
        ev = _make(InventoryStockChangedEvent, {
                "product_id": "p1",
                "warehouse_id": "w1",
                "quantity_delta": -1,
                "reason": "sale",
            })
        _call_post_init(ev)
        assert ev.event_type == "inventory.stock_changed"

    def test_stock_changed_missing(self):
        ev = _make(InventoryStockChangedEvent, {"product_id": "p1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_low_stock_alert_ok(self):
        ev = _make(InventoryLowStockAlertEvent, {"product_id": "p1", "current_stock": 2, "threshold": 5})
        _call_post_init(ev)
        assert ev.event_type == "inventory.low_stock_alert"

    def test_low_stock_alert_missing(self):
        ev = _make(InventoryLowStockAlertEvent, {"product_id": "p1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_stock_in_ok(self):
        ev = _make(InventoryStockInEvent, {
                "product_id": "p1",
                "warehouse_id": "w1",
                "quantity": 10,
                "batch_no": "B001",
            })
        _call_post_init(ev)
        assert ev.event_type == "inventory.stock_in"

    def test_stock_in_missing(self):
        ev = _make(InventoryStockInEvent, {"product_id": "p1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_stock_out_ok(self):
        ev = _make(InventoryStockOutEvent, {
                "product_id": "p1",
                "warehouse_id": "w1",
                "quantity": 5,
                "reference_id": "ref1",
            })
        _call_post_init(ev)
        assert ev.event_type == "inventory.stock_out"

    def test_stock_out_missing(self):
        ev = _make(InventoryStockOutEvent, {"product_id": "p1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_transfer_ok(self):
        ev = _make(InventoryTransferEvent, {
                "product_id": "p1",
                "from_warehouse": "w1",
                "to_warehouse": "w2",
                "quantity": 3,
            })
        _call_post_init(ev)
        assert ev.event_type == "inventory.transfer"

    def test_transfer_missing(self):
        ev = _make(InventoryTransferEvent, {"product_id": "p1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_check_completed_ok(self):
        ev = _make(InventoryCheckCompletedEvent, {"warehouse_id": "w1", "check_date": "2026-01-01", "differences": []})
        _call_post_init(ev)
        assert ev.event_type == "inventory.check_completed"

    def test_check_completed_missing(self):
        ev = _make(InventoryCheckCompletedEvent, {"warehouse_id": "w1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)


# ---------------------------------------------------------------------------
# conversation_events
# ---------------------------------------------------------------------------
from app.neuro_bus.events.conversation_events import (
    ConversationAssignedEvent,
    ConversationCreatedEvent,
    ConversationEndedEvent,
    ConversationExportedEvent,
    ConversationMessageAddedEvent,
    ConversationTaggedEvent,
)


class TestConversationEvents:
    def test_created_ok(self):
        ev = _make(ConversationCreatedEvent, {"conversation_id": "c1", "user_id": "u1", "channel": "web"})
        _call_post_init(ev)
        assert ev.event_type == "conversation.created"

    def test_created_missing(self):
        ev = _make(ConversationCreatedEvent, {"conversation_id": "c1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_message_added_ok(self):
        ev = _make(ConversationMessageAddedEvent, {
                "conversation_id": "c1",
                "message_id": "m1",
                "sender_type": "user",
                "content": "hello",
            })
        _call_post_init(ev)
        assert ev.event_type == "conversation.message_added"

    def test_message_added_missing(self):
        ev = _make(ConversationMessageAddedEvent, {"conversation_id": "c1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_ended_ok(self):
        ev = _make(ConversationEndedEvent, {"conversation_id": "c1", "reason": "timeout", "duration_seconds": 30})
        _call_post_init(ev)
        assert ev.event_type == "conversation.ended"

    def test_ended_missing(self):
        ev = _make(ConversationEndedEvent, {"conversation_id": "c1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_assigned_ok(self):
        ev = _make(ConversationAssignedEvent, {"conversation_id": "c1", "assigned_to": "agent1", "assigned_by": "auto"})
        _call_post_init(ev)
        assert ev.event_type == "conversation.assigned"

    def test_assigned_missing(self):
        ev = _make(ConversationAssignedEvent, {"conversation_id": "c1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_tagged_ok(self):
        ev = _make(ConversationTaggedEvent, {"conversation_id": "c1", "tags": ["vip"], "tagged_by": "u1"})
        _call_post_init(ev)
        assert ev.event_type == "conversation.tagged"

    def test_tagged_missing(self):
        ev = _make(ConversationTaggedEvent, {"conversation_id": "c1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_exported_ok(self):
        ev = _make(ConversationExportedEvent, {
                "conversation_id": "c1",
                "export_format": "pdf",
                "file_path": "/tmp/out.pdf",
            })
        _call_post_init(ev)
        assert ev.event_type == "conversation.exported"

    def test_exported_missing(self):
        ev = _make(ConversationExportedEvent, {"conversation_id": "c1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)


# ---------------------------------------------------------------------------
# print_events
# ---------------------------------------------------------------------------
from app.neuro_bus.events.print_events import (
    LabelPrintRequestEvent,
    PrinterStatusChangedEvent,
    PrintJobCompletedEvent,
    PrintJobFailedEvent,
    PrintJobStartedEvent,
    PrintJobSubmittedEvent,
)


class TestPrintEvents:
    def test_job_submitted_ok(self):
        ev = _make(PrintJobSubmittedEvent, {
                "job_id": "j1",
                "document_id": "d1",
                "printer_id": "p1",
                "copies": 1,
            })
        _call_post_init(ev)
        assert ev.event_type == "print.job_submitted"

    def test_job_submitted_missing(self):
        ev = _make(PrintJobSubmittedEvent, {"job_id": "j1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_job_started_ok(self):
        ev = _make(PrintJobStartedEvent, {"job_id": "j1"})
        _call_post_init(ev)
        assert ev.event_type == "print.job_started"

    def test_job_started_missing(self):
        ev = _make(PrintJobStartedEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_job_completed_ok(self):
        ev = _make(PrintJobCompletedEvent, {"job_id": "j1", "pages_printed": 2, "print_time": 3})
        _call_post_init(ev)
        assert ev.event_type == "print.job_completed"

    def test_job_completed_missing(self):
        ev = _make(PrintJobCompletedEvent, {"job_id": "j1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_job_failed_ok(self):
        ev = _make(PrintJobFailedEvent, {"job_id": "j1", "error_code": "E01", "error_message": "fail"})
        _call_post_init(ev)
        assert ev.event_type == "print.job_failed"

    def test_job_failed_missing(self):
        ev = _make(PrintJobFailedEvent, {"job_id": "j1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_printer_status_changed_ok(self):
        ev = _make(PrinterStatusChangedEvent, {"printer_id": "p1", "old_status": "idle", "new_status": "busy"})
        _call_post_init(ev)
        assert ev.event_type == "print.printer_status_changed"

    def test_printer_status_changed_missing(self):
        ev = _make(PrinterStatusChangedEvent, {"printer_id": "p1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_label_print_request_ok(self):
        ev = _make(LabelPrintRequestEvent, {
                "label_id": "l1",
                "product_id": "p1",
                "quantity": 5,
                "printer_id": "pr1",
            })
        _call_post_init(ev)
        assert ev.event_type == "print.label_requested"

    def test_label_print_request_missing(self):
        ev = _make(LabelPrintRequestEvent, {"label_id": "l1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)


# ---------------------------------------------------------------------------
# ocr_events
# ---------------------------------------------------------------------------
from app.neuro_bus.events.ocr_events import (
    OCRBatchProcessingCompletedEvent,
    OCRResultValidatedEvent,
    OCRTaskCompletedEvent,
    OCRTaskFailedEvent,
    OCRTaskStartedEvent,
    OCRTaskSubmittedEvent,
)


class TestOcrEvents:
    def test_task_submitted_ok(self):
        ev = _make(OCRTaskSubmittedEvent, {"task_id": "t1", "image_url": "http://img.jpg", "ocr_type": "general"})
        _call_post_init(ev)
        assert ev.event_type == "ocr.task_submitted"

    def test_task_submitted_missing(self):
        ev = _make(OCRTaskSubmittedEvent, {"task_id": "t1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_task_started_ok(self):
        ev = _make(OCRTaskStartedEvent, {"task_id": "t1"})
        _call_post_init(ev)
        assert ev.event_type == "ocr.task_started"

    def test_task_started_missing(self):
        ev = _make(OCRTaskStartedEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_task_completed_ok(self):
        ev = _make(OCRTaskCompletedEvent, {"task_id": "t1", "result": "text", "confidence": 0.99})
        _call_post_init(ev)
        assert ev.event_type == "ocr.task_completed"

    def test_task_completed_missing(self):
        ev = _make(OCRTaskCompletedEvent, {"task_id": "t1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_task_failed_ok(self):
        ev = _make(OCRTaskFailedEvent, {"task_id": "t1", "error_code": "E01", "error_message": "fail"})
        _call_post_init(ev)
        assert ev.event_type == "ocr.task_failed"

    def test_task_failed_missing(self):
        ev = _make(OCRTaskFailedEvent, {"task_id": "t1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_result_validated_ok(self):
        ev = _make(OCRResultValidatedEvent, {
                "task_id": "t1",
                "validated_by": "u1",
                "is_correct": True,
                "corrections": [],
            })
        _call_post_init(ev)
        assert ev.event_type == "ocr.result_validated"

    def test_result_validated_missing(self):
        ev = _make(OCRResultValidatedEvent, {"task_id": "t1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_batch_completed_ok(self):
        ev = _make(OCRBatchProcessingCompletedEvent, {
                "batch_id": "b1",
                "total_count": 10,
                "success_count": 8,
                "failed_count": 2,
            })
        _call_post_init(ev)
        assert ev.event_type == "ocr.batch_completed"

    def test_batch_completed_missing(self):
        ev = _make(OCRBatchProcessingCompletedEvent, {"batch_id": "b1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)


# ---------------------------------------------------------------------------
# material_events
# ---------------------------------------------------------------------------
from app.neuro_bus.events.material_events import (
    MaterialCreatedEvent,
    MaterialLowStockAlertEvent,
    MaterialStockInEvent,
    MaterialStockOutEvent,
    MaterialSupplierChangedEvent,
    MaterialUpdatedEvent,
)


class TestMaterialEvents:
    def test_created_ok(self):
        ev = _make(MaterialCreatedEvent, {
                "material_id": "m1",
                "material_name": "钢板",
                "material_code": "MC001",
            })
        _call_post_init(ev)
        assert ev.event_type == "material.created"

    def test_created_missing(self):
        ev = _make(MaterialCreatedEvent, {"material_id": "m1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_updated_ok(self):
        ev = _make(MaterialUpdatedEvent, {"material_id": "m1"})
        _call_post_init(ev)
        assert ev.event_type == "material.updated"

    def test_updated_missing(self):
        ev = _make(MaterialUpdatedEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_stock_in_ok(self):
        ev = _make(MaterialStockInEvent, {
                "material_id": "m1",
                "warehouse_id": "w1",
                "quantity": 100,
                "batch_no": "B01",
            })
        _call_post_init(ev)
        assert ev.event_type == "material.stock_in"

    def test_stock_in_missing(self):
        ev = _make(MaterialStockInEvent, {"material_id": "m1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_stock_out_ok(self):
        ev = _make(MaterialStockOutEvent, {
                "material_id": "m1",
                "warehouse_id": "w1",
                "quantity": 10,
                "usage_purpose": "production",
            })
        _call_post_init(ev)
        assert ev.event_type == "material.stock_out"

    def test_stock_out_missing(self):
        ev = _make(MaterialStockOutEvent, {"material_id": "m1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_low_stock_alert_ok(self):
        ev = _make(MaterialLowStockAlertEvent, {"material_id": "m1", "current_stock": 2, "safety_stock": 10})
        _call_post_init(ev)
        assert ev.event_type == "material.low_stock_alert"

    def test_low_stock_alert_missing(self):
        ev = _make(MaterialLowStockAlertEvent, {"material_id": "m1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_supplier_changed_ok(self):
        ev = _make(MaterialSupplierChangedEvent, {"material_id": "m1", "old_supplier": "s1", "new_supplier": "s2"})
        _call_post_init(ev)
        assert ev.event_type == "material.supplier_changed"

    def test_supplier_changed_missing(self):
        ev = _make(MaterialSupplierChangedEvent, {"material_id": "m1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)


# ---------------------------------------------------------------------------
# ai_events
# ---------------------------------------------------------------------------
from app.neuro_bus.events.ai_events import (
    AIContextUpdatedEvent,
    AIConversationEndedEvent,
    AIConversationStartedEvent,
    AIFeedbackReceivedEvent,
    AIIntentRecognizedEvent,
    AIResponseGeneratedEvent,
)


class TestAIEvents:
    def test_intent_recognized_ok(self):
        ev = _make(AIIntentRecognizedEvent, {
                "session_id": "s1",
                "user_message": "hello",
                "intent": "greet",
                "confidence": 0.9,
            })
        _call_post_init(ev)
        assert ev.event_type == "ai.intent_recognized"

    def test_intent_recognized_missing(self):
        ev = _make(AIIntentRecognizedEvent, {"session_id": "s1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_response_generated_ok(self):
        ev = _make(AIResponseGeneratedEvent, {"session_id": "s1", "response": "hi", "generation_time_ms": 100})
        _call_post_init(ev)
        assert ev.event_type == "ai.response_generated"

    def test_response_generated_missing(self):
        ev = _make(AIResponseGeneratedEvent, {"session_id": "s1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_conversation_started_ok(self):
        ev = _make(AIConversationStartedEvent, {"session_id": "s1", "user_id": "u1", "channel": "web"})
        _call_post_init(ev)
        assert ev.event_type == "ai.conversation_started"

    def test_conversation_started_missing(self):
        ev = _make(AIConversationStartedEvent, {"session_id": "s1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_conversation_ended_ok(self):
        ev = _make(AIConversationEndedEvent, {"session_id": "s1", "total_messages": 5, "duration_seconds": 60})
        _call_post_init(ev)
        assert ev.event_type == "ai.conversation_ended"

    def test_conversation_ended_missing(self):
        ev = _make(AIConversationEndedEvent, {"session_id": "s1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_feedback_received_ok(self):
        ev = _make(AIFeedbackReceivedEvent, {
                "session_id": "s1",
                "message_id": "m1",
                "feedback_type": "like",
                "rating": 5,
            })
        _call_post_init(ev)
        assert ev.event_type == "ai.feedback_received"

    def test_feedback_received_missing(self):
        ev = _make(AIFeedbackReceivedEvent, {"session_id": "s1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_context_updated_ok(self):
        ev = _make(AIContextUpdatedEvent, {"session_id": "s1"})
        _call_post_init(ev)
        assert ev.event_type == "ai.context_updated"

    def test_context_updated_missing(self):
        ev = _make(AIContextUpdatedEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)


# ---------------------------------------------------------------------------
# shipment_events
# ---------------------------------------------------------------------------
from app.neuro_bus.events.shipment_events import (
    ShipmentCancelledEvent,
    ShipmentCreatedEvent,
    ShipmentDeletedEvent,
    ShipmentExportedEvent,
    ShipmentInventoryDeductedEvent,
    ShipmentItemAddedEvent,
    ShipmentPrintedEvent,
)


class TestShipmentEvents:
    def test_created_ok(self):
        ev = _make(ShipmentCreatedEvent, {"shipment_id": "s1", "unit_name": "公司A"})
        _call_post_init(ev)
        assert ev.event_type == "shipment.created"

    def test_created_missing(self):
        ev = _make(ShipmentCreatedEvent, {"shipment_id": "s1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_item_added_ok(self):
        ev = _make(ShipmentItemAddedEvent, {"shipment_id": "s1", "product_id": "p1", "quantity": 2})
        _call_post_init(ev)
        assert ev.event_type == "shipment.item_added"

    def test_item_added_missing(self):
        ev = _make(ShipmentItemAddedEvent, {"shipment_id": "s1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_printed_ok(self):
        ev = _make(ShipmentPrintedEvent, {"shipment_id": "s1"})
        _call_post_init(ev)
        assert ev.event_type == "shipment.printed"

    def test_printed_missing(self):
        ev = _make(ShipmentPrintedEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_cancelled_ok(self):
        ev = _make(ShipmentCancelledEvent, {"shipment_id": "s1"})
        _call_post_init(ev)
        assert ev.event_type == "shipment.cancelled"

    def test_cancelled_missing(self):
        ev = _make(ShipmentCancelledEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_deleted_ok(self):
        ev = _make(ShipmentDeletedEvent, {"shipment_id": "s1"})
        _call_post_init(ev)
        assert ev.event_type == "shipment.deleted"

    def test_deleted_missing(self):
        ev = _make(ShipmentDeletedEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_exported_ok(self):
        ev = _make(ShipmentExportedEvent, {"file_path": "/tmp/out.xlsx"})
        _call_post_init(ev)
        assert ev.event_type == "shipment.exported"

    def test_exported_missing(self):
        ev = _make(ShipmentExportedEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_inventory_deducted_ok(self):
        ev = _make(ShipmentInventoryDeductedEvent, {"shipment_id": "s1", "items": []})
        _call_post_init(ev)
        assert ev.event_type == "shipment.inventory_deducted"

    def test_inventory_deducted_missing(self):
        ev = _make(ShipmentInventoryDeductedEvent, {"shipment_id": "s1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)


# ---------------------------------------------------------------------------
# customer_events
# ---------------------------------------------------------------------------
from app.neuro_bus.events.customer_events import (
    CustomerCreditLimitChangedEvent,
    CustomerDeactivatedEvent,
    CustomerPreferenceUpdatedEvent,
    CustomerPurchaseUnitBoundEvent,
    CustomerRegisteredEvent,
    CustomerUpdatedEvent,
)


class TestCustomerEvents:
    def test_registered_ok(self):
        ev = _make(CustomerRegisteredEvent, {"customer_id": "c1", "contact_info": {"name": "Zhang"}})
        _call_post_init(ev)
        assert ev.event_type == "customer.registered"

    def test_registered_missing(self):
        ev = _make(CustomerRegisteredEvent, {"customer_id": "c1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_updated_ok(self):
        ev = _make(CustomerUpdatedEvent, {"customer_id": "c1"})
        _call_post_init(ev)
        assert ev.event_type == "customer.updated"

    def test_updated_missing(self):
        ev = _make(CustomerUpdatedEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_deactivated_ok(self):
        ev = _make(CustomerDeactivatedEvent, {"customer_id": "c1"})
        _call_post_init(ev)
        assert ev.event_type == "customer.deactivated"

    def test_deactivated_missing(self):
        ev = _make(CustomerDeactivatedEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_purchase_unit_bound_ok(self):
        ev = _make(CustomerPurchaseUnitBoundEvent, {"customer_id": "c1", "purchase_unit": "unit1"})
        _call_post_init(ev)
        assert ev.event_type == "customer.purchase_unit_bound"

    def test_purchase_unit_bound_missing(self):
        ev = _make(CustomerPurchaseUnitBoundEvent, {"customer_id": "c1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_preference_updated_ok(self):
        ev = _make(CustomerPreferenceUpdatedEvent, {"customer_id": "c1"})
        _call_post_init(ev)
        assert ev.event_type == "customer.preference_updated"

    def test_preference_updated_missing(self):
        ev = _make(CustomerPreferenceUpdatedEvent, {})
        with pytest.raises(ValueError):
            _call_post_init(ev)

    def test_credit_limit_changed_ok(self):
        ev = _make(CustomerCreditLimitChangedEvent, {"customer_id": "c1", "old_limit": 1000, "new_limit": 2000})
        _call_post_init(ev)
        assert ev.event_type == "customer.credit_limit_changed"

    def test_credit_limit_changed_missing(self):
        ev = _make(CustomerCreditLimitChangedEvent, {"customer_id": "c1"})
        with pytest.raises(ValueError):
            _call_post_init(ev)
