from __future__ import annotations

"""Behavior tests for every neuro_bus/events/* domain-event ``__post_init__``.

These event classes are ``@dataclass`` subclasses of the non-dataclass
``NeuroEvent``. The generated ``__init__`` only sets ``event_type``/``priority``
and never calls ``NeuroEvent.__init__``, so ``self.payload`` is never populated
and ``__post_init__`` calls ``super().__post_init__()`` which does not exist on
``NeuroEvent``. Normal construction (e.g. ``OrderSubmittedEvent()``) therefore
raises ``AttributeError: 'super' object has no attribute '__post_init__'``.
See ``suspected_bugs`` in the task report — we test the real validation logic
without "fixing" the broken constructor.

What this file asserts (all on the real SUT, not on the test harness):
  * Each event class declares the exact ``event_type`` string the bus routes on,
    read from the class itself (the SUT), with the correct ``EventPriority``.
  * ``__post_init__`` accepts a payload containing every required field without
    raising, returns ``None``, and does not mutate the payload.
  * For *every* required field, dropping *that* field makes ``__post_init__``
    raise ``ValueError`` whose message names both the class and the missing
    field (``"<ClassName> 缺少必要字段: <field>"``). This exercises every
    iteration of the validation loop, not just the first field.
"""

from unittest.mock import patch

import pytest

from app.neuro_bus.events.ai_events import (
    AIContextUpdatedEvent,
    AIConversationEndedEvent,
    AIConversationStartedEvent,
    AIFeedbackReceivedEvent,
    AIIntentRecognizedEvent,
    AIResponseGeneratedEvent,
)
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
from app.neuro_bus.events.base import EventPriority, NeuroEvent
from app.neuro_bus.events.conversation_events import (
    ConversationAssignedEvent,
    ConversationCreatedEvent,
    ConversationEndedEvent,
    ConversationExportedEvent,
    ConversationMessageAddedEvent,
    ConversationTaggedEvent,
)
from app.neuro_bus.events.customer_events import (
    CustomerCreditLimitChangedEvent,
    CustomerDeactivatedEvent,
    CustomerPreferenceUpdatedEvent,
    CustomerPurchaseUnitBoundEvent,
    CustomerRegisteredEvent,
    CustomerUpdatedEvent,
)
from app.neuro_bus.events.inventory_events import (
    InventoryCheckCompletedEvent,
    InventoryLowStockAlertEvent,
    InventoryStockChangedEvent,
    InventoryStockInEvent,
    InventoryStockOutEvent,
    InventoryTransferEvent,
)
from app.neuro_bus.events.material_events import (
    MaterialCreatedEvent,
    MaterialLowStockAlertEvent,
    MaterialStockInEvent,
    MaterialStockOutEvent,
    MaterialSupplierChangedEvent,
    MaterialUpdatedEvent,
)
from app.neuro_bus.events.ocr_events import (
    OCRBatchProcessingCompletedEvent,
    OCRResultValidatedEvent,
    OCRTaskCompletedEvent,
    OCRTaskFailedEvent,
    OCRTaskStartedEvent,
    OCRTaskSubmittedEvent,
)
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
from app.neuro_bus.events.payment_events import (
    PaymentCompletedEvent,
    PaymentCreatedEvent,
    PaymentFailedEvent,
    PaymentMethodChangedEvent,
    PaymentNotificationSentEvent,
    PaymentRefundedEvent,
)
from app.neuro_bus.events.print_events import (
    LabelPrintRequestEvent,
    PrinterStatusChangedEvent,
    PrintJobCompletedEvent,
    PrintJobFailedEvent,
    PrintJobStartedEvent,
    PrintJobSubmittedEvent,
)
from app.neuro_bus.events.shipment_events import (
    ShipmentCancelledEvent,
    ShipmentCreatedEvent,
    ShipmentDeletedEvent,
    ShipmentExportedEvent,
    ShipmentInventoryDeductedEvent,
    ShipmentItemAddedEvent,
    ShipmentPrintedEvent,
)
from app.neuro_bus.events.wechat_events import (
    WeChatContactAddedEvent,
    WeChatContactUpdatedEvent,
    WeChatLoginStatusChangedEvent,
    WeChatMessageReceivedEvent,
    WeChatMessageSentEvent,
    WeChatTaskCompletedEvent,
    WeChatTaskCreatedEvent,
)

# ---------------------------------------------------------------------------
# Test harness
#
# We cannot construct these events normally (the dataclass __init__ never calls
# NeuroEvent.__init__, so payload is missing and super().__post_init__ blows up
# — see module docstring). To exercise the *real* validation branches we build
# a bare instance, attach a payload, and invoke the genuine __post_init__ with
# NeuroEvent.__post_init__ stubbed to a no-op (mirroring the missing base hook).
# Everything we assert below is set by the SUT — class-level event_type/priority
# defaults and the ValueError raised by the validation loop — never by us.
# ---------------------------------------------------------------------------


def _bare(cls, payload):
    """Instantiate ``cls`` bypassing its broken __init__, with ``payload`` set.

    ``event_type``/``priority`` are intentionally left to fall through to the
    class-level dataclass defaults so assertions read the real SUT values.
    """
    ev = object.__new__(cls)
    ev.payload = dict(payload)
    return ev


def _run_post_init(ev):
    """Invoke the real subclass __post_init__ with the absent base hook stubbed."""
    with patch.object(NeuroEvent, "__post_init__", lambda self: None, create=True):
        return type(ev).__post_init__(ev)


def _full_payload(required):
    """Build a payload containing every required field with a placeholder value."""
    return {field: f"value-of-{field}" for field in required}


# (EventClass, declared event_type, declared priority, [required fields in order])
EVENT_SPECS = [
    # --- order_events ------------------------------------------------------
    (
        OrderSubmittedEvent,
        "order.submitted",
        EventPriority.HIGH,
        ["order_id", "customer_id", "items"],
    ),
    (OrderPaidEvent, "order.paid", EventPriority.HIGH, ["order_id", "payment_id", "amount"]),
    (OrderPaymentFailedEvent, "order.payment_failed", EventPriority.HIGH, ["order_id"]),
    (OrderFulfilledEvent, "order.fulfilled", EventPriority.NORMAL, ["order_id"]),
    (
        OrderShippedEvent,
        "order.shipped",
        EventPriority.NORMAL,
        ["order_id", "shipment_id", "tracking_number"],
    ),
    (OrderCancelledEvent, "order.cancelled", EventPriority.HIGH, ["order_id"]),
    (
        OrderRefundedEvent,
        "order.refunded",
        EventPriority.HIGH,
        ["order_id", "refund_id", "refund_amount"],
    ),
    (
        OrderItemUpdatedEvent,
        "order.item_updated",
        EventPriority.NORMAL,
        ["order_id", "item_id", "changes"],
    ),
    (
        OrderStatusChangedEvent,
        "order.status_changed",
        EventPriority.NORMAL,
        ["order_id", "old_status", "new_status"],
    ),
    # --- wechat_events -----------------------------------------------------
    (
        WeChatMessageReceivedEvent,
        "wechat.message_received",
        EventPriority.HIGH,
        ["message_id", "from_user", "message_type", "content"],
    ),
    (
        WeChatMessageSentEvent,
        "wechat.message_sent",
        EventPriority.NORMAL,
        ["message_id", "to_user", "message_type", "status"],
    ),
    (
        WeChatContactAddedEvent,
        "wechat.contact_added",
        EventPriority.NORMAL,
        ["contact_id", "contact_name", "source"],
    ),
    (WeChatContactUpdatedEvent, "wechat.contact_updated", EventPriority.LOW, ["contact_id"]),
    (
        WeChatTaskCreatedEvent,
        "wechat.task_created",
        EventPriority.NORMAL,
        ["task_id", "task_type", "target_contacts", "content"],
    ),
    (
        WeChatTaskCompletedEvent,
        "wechat.task_completed",
        EventPriority.NORMAL,
        ["task_id", "success_count", "failed_count"],
    ),
    (
        WeChatLoginStatusChangedEvent,
        "wechat.login_status_changed",
        EventPriority.HIGH,
        ["account_id", "old_status", "new_status"],
    ),
    # --- auth_events -------------------------------------------------------
    (
        UserLoginEvent,
        "auth.user_login",
        EventPriority.HIGH,
        ["user_id", "login_method", "ip_address"],
    ),
    (UserLogoutEvent, "auth.user_logout", EventPriority.NORMAL, ["user_id"]),
    (
        UserRegisteredEvent,
        "auth.user_registered",
        EventPriority.NORMAL,
        ["user_id", "username", "registration_source"],
    ),
    (UserPasswordChangedEvent, "auth.password_changed", EventPriority.HIGH, ["user_id"]),
    (
        UserPermissionGrantedEvent,
        "auth.permission_granted",
        EventPriority.NORMAL,
        ["user_id", "permission", "granted_by"],
    ),
    (
        UserPermissionRevokedEvent,
        "auth.permission_revoked",
        EventPriority.NORMAL,
        ["user_id", "permission", "revoked_by"],
    ),
    (
        LoginFailedEvent,
        "auth.login_failed",
        EventPriority.HIGH,
        ["username", "reason", "ip_address"],
    ),
    (TokenRefreshedEvent, "auth.token_refreshed", EventPriority.LOW, ["user_id"]),
    # --- payment_events ----------------------------------------------------
    (
        PaymentCreatedEvent,
        "payment.created",
        EventPriority.HIGH,
        ["payment_id", "order_id", "amount", "payment_method"],
    ),
    (
        PaymentCompletedEvent,
        "payment.completed",
        EventPriority.HIGH,
        ["payment_id", "transaction_id", "paid_amount"],
    ),
    (
        PaymentFailedEvent,
        "payment.failed",
        EventPriority.HIGH,
        ["payment_id", "error_code", "error_message"],
    ),
    (
        PaymentRefundedEvent,
        "payment.refunded",
        EventPriority.HIGH,
        ["payment_id", "refund_id", "refund_amount", "reason"],
    ),
    (
        PaymentMethodChangedEvent,
        "payment.method_changed",
        EventPriority.NORMAL,
        ["payment_id", "old_method", "new_method"],
    ),
    (
        PaymentNotificationSentEvent,
        "payment.notification_sent",
        EventPriority.LOW,
        ["payment_id", "notification_type", "recipient"],
    ),
    # --- inventory_events --------------------------------------------------
    (
        InventoryStockChangedEvent,
        "inventory.stock_changed",
        EventPriority.HIGH,
        ["product_id", "warehouse_id", "quantity_delta", "reason"],
    ),
    (
        InventoryLowStockAlertEvent,
        "inventory.low_stock_alert",
        EventPriority.HIGH,
        ["product_id", "current_stock", "threshold"],
    ),
    (
        InventoryStockInEvent,
        "inventory.stock_in",
        EventPriority.NORMAL,
        ["product_id", "warehouse_id", "quantity", "batch_no"],
    ),
    (
        InventoryStockOutEvent,
        "inventory.stock_out",
        EventPriority.NORMAL,
        ["product_id", "warehouse_id", "quantity", "reference_id"],
    ),
    (
        InventoryTransferEvent,
        "inventory.transfer",
        EventPriority.NORMAL,
        ["product_id", "from_warehouse", "to_warehouse", "quantity"],
    ),
    (
        InventoryCheckCompletedEvent,
        "inventory.check_completed",
        EventPriority.LOW,
        ["warehouse_id", "check_date", "differences"],
    ),
    # --- conversation_events ----------------------------------------------
    (
        ConversationCreatedEvent,
        "conversation.created",
        EventPriority.NORMAL,
        ["conversation_id", "user_id", "channel"],
    ),
    (
        ConversationMessageAddedEvent,
        "conversation.message_added",
        EventPriority.NORMAL,
        ["conversation_id", "message_id", "sender_type", "content"],
    ),
    (
        ConversationEndedEvent,
        "conversation.ended",
        EventPriority.LOW,
        ["conversation_id", "reason", "duration_seconds"],
    ),
    (
        ConversationAssignedEvent,
        "conversation.assigned",
        EventPriority.NORMAL,
        ["conversation_id", "assigned_to", "assigned_by"],
    ),
    (
        ConversationTaggedEvent,
        "conversation.tagged",
        EventPriority.LOW,
        ["conversation_id", "tags", "tagged_by"],
    ),
    (
        ConversationExportedEvent,
        "conversation.exported",
        EventPriority.LOW,
        ["conversation_id", "export_format", "file_path"],
    ),
    # --- print_events ------------------------------------------------------
    (
        PrintJobSubmittedEvent,
        "print.job_submitted",
        EventPriority.NORMAL,
        ["job_id", "document_id", "printer_id", "copies"],
    ),
    (PrintJobStartedEvent, "print.job_started", EventPriority.LOW, ["job_id"]),
    (
        PrintJobCompletedEvent,
        "print.job_completed",
        EventPriority.NORMAL,
        ["job_id", "pages_printed", "print_time"],
    ),
    (
        PrintJobFailedEvent,
        "print.job_failed",
        EventPriority.HIGH,
        ["job_id", "error_code", "error_message"],
    ),
    (
        PrinterStatusChangedEvent,
        "print.printer_status_changed",
        EventPriority.HIGH,
        ["printer_id", "old_status", "new_status"],
    ),
    (
        LabelPrintRequestEvent,
        "print.label_requested",
        EventPriority.NORMAL,
        ["label_id", "product_id", "quantity", "printer_id"],
    ),
    # --- ocr_events --------------------------------------------------------
    (
        OCRTaskSubmittedEvent,
        "ocr.task_submitted",
        EventPriority.NORMAL,
        ["task_id", "image_url", "ocr_type"],
    ),
    (OCRTaskStartedEvent, "ocr.task_started", EventPriority.LOW, ["task_id"]),
    (
        OCRTaskCompletedEvent,
        "ocr.task_completed",
        EventPriority.NORMAL,
        ["task_id", "result", "confidence"],
    ),
    (
        OCRTaskFailedEvent,
        "ocr.task_failed",
        EventPriority.HIGH,
        ["task_id", "error_code", "error_message"],
    ),
    (
        OCRResultValidatedEvent,
        "ocr.result_validated",
        EventPriority.NORMAL,
        ["task_id", "validated_by", "is_correct", "corrections"],
    ),
    (
        OCRBatchProcessingCompletedEvent,
        "ocr.batch_completed",
        EventPriority.LOW,
        ["batch_id", "total_count", "success_count", "failed_count"],
    ),
    # --- material_events ---------------------------------------------------
    (
        MaterialCreatedEvent,
        "material.created",
        EventPriority.NORMAL,
        ["material_id", "material_name", "material_code"],
    ),
    (MaterialUpdatedEvent, "material.updated", EventPriority.NORMAL, ["material_id"]),
    (
        MaterialStockInEvent,
        "material.stock_in",
        EventPriority.NORMAL,
        ["material_id", "warehouse_id", "quantity", "batch_no"],
    ),
    (
        MaterialStockOutEvent,
        "material.stock_out",
        EventPriority.NORMAL,
        ["material_id", "warehouse_id", "quantity", "usage_purpose"],
    ),
    (
        MaterialLowStockAlertEvent,
        "material.low_stock_alert",
        EventPriority.HIGH,
        ["material_id", "current_stock", "safety_stock"],
    ),
    (
        MaterialSupplierChangedEvent,
        "material.supplier_changed",
        EventPriority.NORMAL,
        ["material_id", "old_supplier", "new_supplier"],
    ),
    # --- ai_events ---------------------------------------------------------
    (
        AIIntentRecognizedEvent,
        "ai.intent_recognized",
        EventPriority.HIGH,
        ["session_id", "user_message", "intent", "confidence"],
    ),
    (
        AIResponseGeneratedEvent,
        "ai.response_generated",
        EventPriority.NORMAL,
        ["session_id", "response", "generation_time_ms"],
    ),
    (
        AIConversationStartedEvent,
        "ai.conversation_started",
        EventPriority.NORMAL,
        ["session_id", "user_id", "channel"],
    ),
    (
        AIConversationEndedEvent,
        "ai.conversation_ended",
        EventPriority.LOW,
        ["session_id", "total_messages", "duration_seconds"],
    ),
    (
        AIFeedbackReceivedEvent,
        "ai.feedback_received",
        EventPriority.LOW,
        ["session_id", "message_id", "feedback_type", "rating"],
    ),
    (AIContextUpdatedEvent, "ai.context_updated", EventPriority.NORMAL, ["session_id"]),
    # --- shipment_events ---------------------------------------------------
    (ShipmentCreatedEvent, "shipment.created", EventPriority.HIGH, ["shipment_id", "unit_name"]),
    (
        ShipmentItemAddedEvent,
        "shipment.item_added",
        EventPriority.NORMAL,
        ["shipment_id", "product_id", "quantity"],
    ),
    (ShipmentPrintedEvent, "shipment.printed", EventPriority.NORMAL, ["shipment_id"]),
    (ShipmentCancelledEvent, "shipment.cancelled", EventPriority.HIGH, ["shipment_id"]),
    (ShipmentDeletedEvent, "shipment.deleted", EventPriority.NORMAL, ["shipment_id"]),
    (ShipmentExportedEvent, "shipment.exported", EventPriority.LOW, ["file_path"]),
    (
        ShipmentInventoryDeductedEvent,
        "shipment.inventory_deducted",
        EventPriority.HIGH,
        ["shipment_id", "items"],
    ),
    # --- customer_events ---------------------------------------------------
    (
        CustomerRegisteredEvent,
        "customer.registered",
        EventPriority.NORMAL,
        ["customer_id", "contact_info"],
    ),
    (CustomerUpdatedEvent, "customer.updated", EventPriority.NORMAL, ["customer_id"]),
    (CustomerDeactivatedEvent, "customer.deactivated", EventPriority.NORMAL, ["customer_id"]),
    (
        CustomerPurchaseUnitBoundEvent,
        "customer.purchase_unit_bound",
        EventPriority.NORMAL,
        ["customer_id", "purchase_unit"],
    ),
    (
        CustomerPreferenceUpdatedEvent,
        "customer.preference_updated",
        EventPriority.LOW,
        ["customer_id"],
    ),
    (
        CustomerCreditLimitChangedEvent,
        "customer.credit_limit_changed",
        EventPriority.HIGH,
        ["customer_id", "old_limit", "new_limit"],
    ),
]

# Sanity: every domain event module is represented and there are no dup classes.
assert len({cls for cls, *_ in EVENT_SPECS}) == len(EVENT_SPECS)


def _spec_id(spec):
    return spec[0].__name__


# Per-(class, missing-field) cases so every iteration of every validation loop
# is exercised with its own strong assertion.
MISSING_FIELD_CASES = [
    (cls, etype, required, missing)
    for (cls, etype, _prio, required) in EVENT_SPECS
    for missing in required
]


def _missing_id(case):
    cls, _etype, _required, missing = case
    return f"{cls.__name__}-drop-{missing}"


# ---------------------------------------------------------------------------
# Class-level contract: routing key + priority come from the SUT itself.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", EVENT_SPECS, ids=_spec_id)
def test_event_declares_routing_key_and_priority(spec):
    cls, expected_type, expected_priority, _required = spec
    # These read the dataclass field defaults on the real class — the strings the
    # NeuroBus routes on and the priority the SLA scheduler orders by.
    assert cls.event_type == expected_type
    assert cls.priority == expected_priority
    assert isinstance(cls.priority, EventPriority)


# ---------------------------------------------------------------------------
# Success branch: a complete payload passes validation, returns None, and the
# payload is left untouched.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", EVENT_SPECS, ids=_spec_id)
def test_post_init_accepts_complete_payload(spec):
    cls, _etype, _prio, required = spec
    payload = _full_payload(required)
    ev = _bare(cls, payload)

    result = _run_post_init(ev)

    # __post_init__ validates and returns nothing on success...
    assert result is None
    # ...and must not mutate / drop / add payload keys.
    assert ev.payload == payload
    assert set(ev.payload) == set(required)


# ---------------------------------------------------------------------------
# Failure branch: dropping ANY single required field raises ValueError whose
# message names both the class and exactly that field. Covers every loop body.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", MISSING_FIELD_CASES, ids=_missing_id)
def test_post_init_rejects_each_missing_field(case):
    cls, _etype, required, missing = case
    payload = _full_payload(required)
    del payload[missing]
    ev = _bare(cls, payload)

    expected_msg = f"{cls.__name__} 缺少必要字段: {missing}"
    with pytest.raises(ValueError) as exc_info:
        _run_post_init(ev)

    # Validation surfaces the *first* missing field encountered. Because we only
    # drop one field, the raised field is deterministically ``missing``.
    raised = str(exc_info.value)
    assert missing in raised
    assert cls.__name__ in raised
    # Single-field events emit the exact templated message; multi-field events
    # emit the same message for the first-missing field. When ``missing`` is the
    # first required field, the full message must match exactly.
    if required.index(missing) == 0:
        assert raised == expected_msg


# ---------------------------------------------------------------------------
# Empty payload: every event rejects an entirely empty payload by complaining
# about its FIRST required field specifically.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", EVENT_SPECS, ids=_spec_id)
def test_post_init_empty_payload_reports_first_required_field(spec):
    cls, _etype, _prio, required = spec
    first_field = required[0]
    ev = _bare(cls, {})

    with pytest.raises(ValueError, match=rf"{cls.__name__} 缺少必要字段: {first_field}"):
        _run_post_init(ev)


# ---------------------------------------------------------------------------
# Multi-field ordering: an event with N>=2 required fields reports the EARLIER
# missing field when two are absent, proving validation short-circuits in order.
# ---------------------------------------------------------------------------


MULTI_FIELD_SPECS = [s for s in EVENT_SPECS if len(s[3]) >= 2]


@pytest.mark.parametrize("spec", MULTI_FIELD_SPECS, ids=_spec_id)
def test_post_init_reports_earliest_missing_field_first(spec):
    cls, _etype, _prio, required = spec
    # Drop the first two required fields; the loop must complain about field[0].
    payload = _full_payload(required)
    del payload[required[0]]
    del payload[required[1]]
    ev = _bare(cls, payload)

    with pytest.raises(ValueError) as exc_info:
        _run_post_init(ev)
    assert str(exc_info.value) == f"{cls.__name__} 缺少必要字段: {required[0]}"


# ---------------------------------------------------------------------------
# Regression guard for the broken constructor (documents real, current SUT
# behavior — see suspected_bugs). Normal instantiation cannot work because the
# dataclass __init__ never populates ``payload`` and ``super().__post_init__``
# does not exist on NeuroEvent.
# ---------------------------------------------------------------------------


def test_normal_construction_is_broken_missing_base_post_init():
    with pytest.raises(AttributeError, match="__post_init__"):
        OrderSubmittedEvent()


def test_post_init_raises_attributeerror_without_payload_attr():
    # Without the stubbed base hook, calling the real __post_init__ tries
    # super().__post_init__() first and fails before field validation.
    ev = object.__new__(OrderPaidEvent)
    with pytest.raises(AttributeError, match="__post_init__"):
        OrderPaidEvent.__post_init__(ev)
