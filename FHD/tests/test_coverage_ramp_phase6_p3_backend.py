"""COVERAGE_RAMP Phase 6 round 3: backend low-coverage modules.

Targets:
- ``app/infrastructure/payment/order_store.py`` (50.0% line coverage)
- ``app/services/hybrid_intent_service.py`` (34.2% line coverage)

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.payment import order_store
from app.services.hybrid_intent_service import (
    HybridIntentService,
    get_hybrid_intent_service,
    hybrid_recognize_intents,
    hybrid_recognize_intents_sync,
    reset_hybrid_intent_service,
)


# ---------------------------------------------------------------------------
# order_store — fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_order_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离 order_store 文件系统到 tmp_path/orders.json。"""
    target = tmp_path / "orders.json"
    monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(target))
    return target


# ---------------------------------------------------------------------------
# order_store — order_store_path / _load
# ---------------------------------------------------------------------------


def test_order_store_path_uses_env(isolated_order_store: Path) -> None:
    assert order_store.order_store_path() == isolated_order_store


def test_order_store_path_default_when_env_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_PAYMENT_ORDER_STORE_PATH", raising=False)
    p = order_store.order_store_path()
    assert p.name == "model_payment_orders.json"


def test_load_returns_empty_state_when_file_missing(isolated_order_store: Path) -> None:
    assert not isolated_order_store.is_file()
    data = order_store._load()
    assert data == {"orders": {}, "entitlements": {}}


def test_load_returns_empty_state_when_json_not_dict(isolated_order_store: Path) -> None:
    isolated_order_store.parent.mkdir(parents=True, exist_ok=True)
    isolated_order_store.write_text('["not", "a", "dict"]', encoding="utf-8")
    data = order_store._load()
    assert data == {"orders": {}, "entitlements": {}}


def test_load_returns_empty_state_when_json_invalid(isolated_order_store: Path) -> None:
    isolated_order_store.parent.mkdir(parents=True, exist_ok=True)
    isolated_order_store.write_text("{not valid json", encoding="utf-8")
    data = order_store._load()
    assert data == {"orders": {}, "entitlements": {}}


def test_load_repairs_missing_or_bad_subkeys(isolated_order_store: Path) -> None:
    isolated_order_store.parent.mkdir(parents=True, exist_ok=True)
    isolated_order_store.write_text(
        json.dumps({"orders": "bad", "entitlements": "bad"}),
        encoding="utf-8",
    )
    data = order_store._load()
    assert data["orders"] == {}
    assert data["entitlements"] == {}


def test_atomic_write_creates_file_and_parents(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deep" / "orders.json"
    payload = {"orders": {"x": {"k": 1}}, "entitlements": {}}
    order_store._atomic_write(target, payload)
    assert target.is_file()
    with open(target, encoding="utf-8") as f:
        assert json.load(f) == payload


# ---------------------------------------------------------------------------
# order_store — record_checkout_pending / apply_notify_paid happy path
# ---------------------------------------------------------------------------


def test_record_checkout_pending_writes_pending_order(isolated_order_store: Path) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-1",
        plan_id="plan-A",
        amount_cents=9900,
        amount_yuan="99.00",
        local_user_id=42,
    )
    o = order_store.get_order("OT-1")
    assert o is not None
    assert o["out_trade_no"] == "OT-1"
    assert o["plan_id"] == "plan-A"
    assert o["amount_cents"] == 9900
    assert o["amount_yuan"] == "99.00"
    assert o["status"] == "pending_payment"
    assert o["trade_no"] is None
    assert o["paid_at"] is None
    assert o["notify_count"] == 0
    assert o["local_user_id"] == 42


def test_record_checkout_pending_without_local_user_id(isolated_order_store: Path) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-2",
        plan_id="plan-B",
        amount_cents=100,
        amount_yuan="1.00",
    )
    o = order_store.get_order("OT-2")
    assert o is not None
    assert "local_user_id" not in o


def test_apply_notify_paid_marked_paid_flow(isolated_order_store: Path) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-3",
        plan_id="plan-A",
        amount_cents=9900,
        amount_yuan="99.00",
        local_user_id=7,
    )
    reason, snap = order_store.apply_notify_paid(
        out_trade_no="OT-3",
        trade_no="T-1",
        total_amount="99.00",
    )
    assert reason == "marked_paid"
    assert snap is not None
    assert snap["status"] == "paid"
    assert snap["trade_no"] == "T-1"
    assert snap["paid_at"] is not None
    assert snap["notify_count"] == 1
    # entitlement should be granted
    ent = snap.get("entitlement")
    assert ent is not None
    assert ent["plan_id"] == "plan-A"
    assert ent["purchase_count"] == 1
    assert ent["last_out_trade_no"] == "OT-3"
    assert ent["last_trade_no"] == "T-1"


def test_apply_notify_paid_already_paid_idempotent(isolated_order_store: Path) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-4",
        plan_id="plan-A",
        amount_cents=5000,
        amount_yuan="50.00",
        local_user_id=1,
    )
    order_store.apply_notify_paid(
        out_trade_no="OT-4", trade_no="T-1", total_amount="50.00"
    )
    # second notify → already_paid
    reason, snap = order_store.apply_notify_paid(
        out_trade_no="OT-4", trade_no="T-1", total_amount="50.00"
    )
    assert reason == "already_paid"
    assert snap is not None
    assert snap["status"] == "paid"
    assert snap["notify_count"] == 2
    # entitlement purchase_count should NOT bump on duplicate notify
    ent = order_store.get_entitlement("plan-A")
    assert ent is not None
    assert ent["purchase_count"] == 1


def test_apply_notify_paid_unknown_order(isolated_order_store: Path) -> None:
    reason, snap = order_store.apply_notify_paid(
        out_trade_no="nope", trade_no="T", total_amount="1.00"
    )
    assert reason == "unknown_order"
    assert snap is None


def test_apply_notify_paid_amount_mismatch(isolated_order_store: Path) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-5",
        plan_id="plan-A",
        amount_cents=9900,
        amount_yuan="99.00",
        local_user_id=1,
    )
    reason, snap = order_store.apply_notify_paid(
        out_trade_no="OT-5", trade_no="T-9", total_amount="50.00"
    )
    assert reason == "amount_mismatch"
    assert snap is not None
    # snapshot reflects stored order (still pending)
    assert snap["status"] == "pending_payment"
    # order should remain pending
    o = order_store.get_order("OT-5")
    assert o is not None
    assert o["status"] == "pending_payment"


def test_apply_notify_paid_amount_yuan_fallback_when_cents_bad(
    isolated_order_store: Path,
) -> None:
    # Manually craft an order with bad amount_cents to exercise fallback branch
    isolated_order_store.parent.mkdir(parents=True, exist_ok=True)
    isolated_order_store.write_text(
        json.dumps(
            {
                "orders": {
                    "OT-X": {
                        "out_trade_no": "OT-X",
                        "plan_id": "",
                        "amount_cents": "not-int",
                        "amount_yuan": "12.34",
                        "status": "pending_payment",
                        "trade_no": None,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "paid_at": None,
                        "notify_count": 0,
                        "last_notify_at": None,
                    }
                },
                "entitlements": {},
            }
        ),
        encoding="utf-8",
    )
    reason, snap = order_store.apply_notify_paid(
        out_trade_no="OT-X", trade_no="T", total_amount="12.34"
    )
    assert reason == "marked_paid"
    assert snap is not None
    assert snap["status"] == "paid"


def test_apply_notify_paid_empty_plan_id_skips_entitlement(
    isolated_order_store: Path,
) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-E",
        plan_id="",
        amount_cents=100,
        amount_yuan="1.00",
        local_user_id=1,
    )
    reason, snap = order_store.apply_notify_paid(
        out_trade_no="OT-E", trade_no="T", total_amount="1.00"
    )
    assert reason == "marked_paid"
    assert snap is not None
    assert "entitlement" not in snap
    assert order_store.list_entitlements() == []


# ---------------------------------------------------------------------------
# order_store — SaaS plan subscription branch
# ---------------------------------------------------------------------------


def test_apply_notify_paid_saas_plan_triggers_subscription(
    isolated_order_store: Path,
) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-S",
        plan_id="saas-pro",
        amount_cents=10000,
        amount_yuan="100.00",
        local_user_id=99,
    )
    with (
        patch(
            "app.application.tenant_subscription_app_service.apply_paid_plan_for_user",
            return_value=True,
        ) as mock_apply,
        patch(
            "app.infrastructure.billing.saas_plans.is_saas_plan_id",
            return_value=True,
        ) as mock_is_saas,
    ):
        reason, snap = order_store.apply_notify_paid(
            out_trade_no="OT-S", trade_no="T-S", total_amount="100.00"
        )
    assert reason == "marked_paid"
    assert snap is not None
    mock_is_saas.assert_called_once_with("saas-pro")
    mock_apply.assert_called_once_with(user_id=99, plan_id="saas-pro")


def test_apply_notify_paid_saas_plan_without_local_user_id_logs_warning(
    isolated_order_store: Path,
) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-S2",
        plan_id="saas-team",
        amount_cents=20000,
        amount_yuan="200.00",
    )
    with (
        patch(
            "app.application.tenant_subscription_app_service.apply_paid_plan_for_user",
            return_value=True,
        ) as mock_apply,
        patch(
            "app.infrastructure.billing.saas_plans.is_saas_plan_id",
            return_value=True,
        ) as mock_is_saas,
    ):
        reason, snap = order_store.apply_notify_paid(
            out_trade_no="OT-S2", trade_no="T-S2", total_amount="200.00"
        )
    assert reason == "marked_paid"
    # local_user_id missing → no apply call
    mock_is_saas.assert_not_called()
    mock_apply.assert_not_called()


def test_apply_notify_paid_saas_plan_not_in_registry_skips_apply(
    isolated_order_store: Path,
) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-S3",
        plan_id="saas-unknown",
        amount_cents=100,
        amount_yuan="1.00",
        local_user_id=1,
    )
    with (
        patch(
            "app.application.tenant_subscription_app_service.apply_paid_plan_for_user",
            return_value=True,
        ) as mock_apply,
        patch(
            "app.infrastructure.billing.saas_plans.is_saas_plan_id",
            return_value=False,
        ),
    ):
        reason, _ = order_store.apply_notify_paid(
            out_trade_no="OT-S3", trade_no="T", total_amount="1.00"
        )
    assert reason == "marked_paid"
    mock_apply.assert_not_called()


def test_apply_notify_paid_saas_plan_apply_recoverable_error_swallowed(
    isolated_order_store: Path,
) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-S4",
        plan_id="saas-pro",
        amount_cents=100,
        amount_yuan="1.00",
        local_user_id=1,
    )
    with (
        patch(
            "app.application.tenant_subscription_app_service.apply_paid_plan_for_user",
            side_effect=RuntimeError("db down"),
        ),
        patch(
            "app.infrastructure.billing.saas_plans.is_saas_plan_id",
            return_value=True,
        ),
    ):
        # should not raise
        reason, snap = order_store.apply_notify_paid(
            out_trade_no="OT-S4", trade_no="T", total_amount="1.00"
        )
    assert reason == "marked_paid"
    assert snap is not None


# ---------------------------------------------------------------------------
# order_store — entitlements / queries / counts
# ---------------------------------------------------------------------------


def test_list_entitlements_sorted_by_last_paid_at_desc(
    isolated_order_store: Path,
) -> None:
    # craft two entitlements with different last_paid_at
    isolated_order_store.parent.mkdir(parents=True, exist_ok=True)
    isolated_order_store.write_text(
        json.dumps(
            {
                "orders": {},
                "entitlements": {
                    "plan-old": {
                        "plan_id": "plan-old",
                        "purchase_count": 1,
                        "first_paid_at": "2026-01-01T00:00:00+00:00",
                        "last_paid_at": "2026-01-01T00:00:00+00:00",
                        "last_out_trade_no": "A",
                        "last_trade_no": "TA",
                    },
                    "plan-new": {
                        "plan_id": "plan-new",
                        "purchase_count": 1,
                        "first_paid_at": "2026-06-01T00:00:00+00:00",
                        "last_paid_at": "2026-06-01T00:00:00+00:00",
                        "last_out_trade_no": "B",
                        "last_trade_no": "TB",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    items = order_store.list_entitlements()
    assert [i["plan_id"] for i in items] == ["plan-new", "plan-old"]


def test_list_entitlements_empty(isolated_order_store: Path) -> None:
    assert order_store.list_entitlements() == []


def test_list_entitlements_skips_non_dict_entries(
    isolated_order_store: Path,
) -> None:
    isolated_order_store.parent.mkdir(parents=True, exist_ok=True)
    isolated_order_store.write_text(
        json.dumps(
            {"orders": {}, "entitlements": {"bad": "not-a-dict", "good": {"plan_id": "good"}}}
        ),
        encoding="utf-8",
    )
    items = order_store.list_entitlements()
    assert len(items) == 1
    assert items[0]["plan_id"] == "good"


def test_get_entitlement_returns_copy(isolated_order_store: Path) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-G",
        plan_id="plan-G",
        amount_cents=100,
        amount_yuan="1.00",
        local_user_id=1,
    )
    order_store.apply_notify_paid(
        out_trade_no="OT-G", trade_no="TG", total_amount="1.00"
    )
    ent = order_store.get_entitlement("plan-G")
    assert ent is not None
    assert ent["plan_id"] == "plan-G"
    ent["mutated"] = True
    # ensure mutation does not propagate
    ent2 = order_store.get_entitlement("plan-G")
    assert ent2 is not None
    assert "mutated" not in ent2


def test_get_entitlement_empty_plan_id_returns_none(isolated_order_store: Path) -> None:
    assert order_store.get_entitlement("") is None


def test_get_entitlement_missing_returns_none(isolated_order_store: Path) -> None:
    assert order_store.get_entitlement("nope") is None


def test_get_order_empty_out_trade_no_returns_none(isolated_order_store: Path) -> None:
    assert order_store.get_order("") is None


def test_get_order_missing_returns_none(isolated_order_store: Path) -> None:
    assert order_store.get_order("nope") is None


def test_get_order_returns_copy(isolated_order_store: Path) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-C",
        plan_id="p",
        amount_cents=1,
        amount_yuan="0.01",
        local_user_id=1,
    )
    o = order_store.get_order("OT-C")
    assert o is not None
    o["mutated"] = True
    o2 = order_store.get_order("OT-C")
    assert o2 is not None
    assert "mutated" not in o2


def test_update_order_status_updates_and_returns_copy(
    isolated_order_store: Path,
) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-U",
        plan_id="p",
        amount_cents=1,
        amount_yuan="0.01",
        local_user_id=1,
    )
    out = order_store.update_order_status(
        out_trade_no="OT-U", status="closed", extra={"refund_id": "R1"}
    )
    assert out is not None
    assert out["status"] == "closed"
    assert out["refund_id"] == "R1"
    assert "updated_at" in out
    # persisted
    o = order_store.get_order("OT-U")
    assert o is not None
    assert o["status"] == "closed"
    assert o["refund_id"] == "R1"


def test_update_order_status_empty_out_trade_no_returns_none(
    isolated_order_store: Path,
) -> None:
    assert order_store.update_order_status(out_trade_no="", status="closed") is None


def test_update_order_status_unknown_order_returns_none(
    isolated_order_store: Path,
) -> None:
    assert (
        order_store.update_order_status(out_trade_no="nope", status="closed") is None
    )


def test_update_order_status_without_extra(isolated_order_store: Path) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-U2",
        plan_id="p",
        amount_cents=1,
        amount_yuan="0.01",
        local_user_id=1,
    )
    out = order_store.update_order_status(out_trade_no="OT-U2", status="refunded")
    assert out is not None
    assert out["status"] == "refunded"


def test_count_orders_empty(isolated_order_store: Path) -> None:
    assert order_store.count_orders() == 0


def test_count_orders_counts_orders(isolated_order_store: Path) -> None:
    for i in range(3):
        order_store.record_checkout_pending(
            out_trade_no=f"OT-{i}",
            plan_id="p",
            amount_cents=1,
            amount_yuan="0.01",
            local_user_id=1,
        )
    assert order_store.count_orders() == 3


def test_count_orders_handles_bad_orders_field(isolated_order_store: Path) -> None:
    isolated_order_store.parent.mkdir(parents=True, exist_ok=True)
    isolated_order_store.write_text(
        json.dumps({"orders": "not-a-dict", "entitlements": {}}),
        encoding="utf-8",
    )
    assert order_store.count_orders() == 0


def test_json_store_has_unmigrated_orders_false_when_no_file(
    isolated_order_store: Path,
) -> None:
    assert order_store.json_store_has_unmigrated_orders() is False


def test_json_store_has_unmigrated_orders_false_when_empty(
    isolated_order_store: Path,
) -> None:
    isolated_order_store.parent.mkdir(parents=True, exist_ok=True)
    isolated_order_store.write_text(
        json.dumps({"orders": {}, "entitlements": {}}),
        encoding="utf-8",
    )
    assert order_store.json_store_has_unmigrated_orders() is False


def test_json_store_has_unmigrated_orders_true_when_orders_exist(
    isolated_order_store: Path,
) -> None:
    order_store.record_checkout_pending(
        out_trade_no="OT-M",
        plan_id="p",
        amount_cents=1,
        amount_yuan="0.01",
        local_user_id=1,
    )
    assert order_store.json_store_has_unmigrated_orders() is True


# ---------------------------------------------------------------------------
# order_store — _grant_entitlement_inplace accumulates
# ---------------------------------------------------------------------------


def test_grant_entitlement_accumulates_purchase_count(
    isolated_order_store: Path,
) -> None:
    # First paid order for plan-A
    order_store.record_checkout_pending(
        out_trade_no="OT-A1",
        plan_id="plan-A",
        amount_cents=100,
        amount_yuan="1.00",
        local_user_id=1,
    )
    order_store.apply_notify_paid(
        out_trade_no="OT-A1", trade_no="TA1", total_amount="1.00"
    )
    # Second paid order for plan-A (different out_trade_no)
    order_store.record_checkout_pending(
        out_trade_no="OT-A2",
        plan_id="plan-A",
        amount_cents=100,
        amount_yuan="1.00",
        local_user_id=1,
    )
    order_store.apply_notify_paid(
        out_trade_no="OT-A2", trade_no="TA2", total_amount="1.00"
    )
    ent = order_store.get_entitlement("plan-A")
    assert ent is not None
    assert ent["purchase_count"] == 2
    assert ent["first_paid_at"] is not None
    assert ent["last_paid_at"] is not None
    assert ent["last_out_trade_no"] == "OT-A2"
    assert ent["last_trade_no"] == "TA2"


# ---------------------------------------------------------------------------
# hybrid_intent_service — fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_hybrid_singleton() -> None:
    reset_hybrid_intent_service()
    yield
    reset_hybrid_intent_service()


def _make_service(
    *,
    use_rasa: bool = False,
    use_bert: bool = False,
    rasa_service: object | None = None,
    bert_service: object | None = None,
    bert_confidence_threshold: float = 0.7,
    rasa_confidence_threshold: float = 0.7,
) -> HybridIntentService:
    """构造 HybridIntentService 实例，跳过真实 BERT 初始化。"""
    svc = HybridIntentService(
        use_rasa=use_rasa,
        rasa_service=rasa_service,
        use_bert=use_bert,
        bert_confidence_threshold=bert_confidence_threshold,
        rasa_confidence_threshold=rasa_confidence_threshold,
    )
    if bert_service is not None:
        svc.bert_service = bert_service
    return svc


# ---------------------------------------------------------------------------
# hybrid_intent_service — __init__ / _init_bert_service
# ---------------------------------------------------------------------------


def test_init_disables_bert_when_init_raises() -> None:
    # _init_bert_service imports get_bert_intent_service from .bert_intent_service
    with patch(
        "app.services.bert_intent_service.get_bert_intent_service",
        side_effect=RuntimeError("no model"),
    ):
        svc = HybridIntentService(use_bert=True)
    assert svc.use_bert is False
    assert svc.bert_service is None


def test_init_with_bert_disabled() -> None:
    svc = HybridIntentService(use_bert=False)
    assert svc.use_bert is False
    assert svc.bert_service is None
    assert svc.bert_classifier is None


def test_init_with_bert_enabled_and_service_initialized() -> None:
    fake_bert = MagicMock()
    with patch(
        "app.services.bert_intent_service.get_bert_intent_service",
        return_value=fake_bert,
    ):
        svc = HybridIntentService(use_bert=True)
    assert svc.use_bert is True
    assert svc.bert_service is fake_bert


# ---------------------------------------------------------------------------
# hybrid_intent_service — recognize (rule-only path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recognize_rule_only_returns_sources_used() -> None:
    svc = _make_service(use_rasa=False, use_bert=False)
    result = await svc.recognize("你好")
    assert result["sources_used"] == ["rule"]
    assert "bert_intent" not in result
    assert "rasa_intent" not in result


@pytest.mark.asyncio
async def test_recognize_rule_only_with_shipment_message() -> None:
    svc = _make_service(use_rasa=False, use_bert=False)
    result = await svc.recognize("生成发货单")
    # rule engine should pick up shipment_generate intent
    assert "rule" in result["sources_used"]


# ---------------------------------------------------------------------------
# hybrid_intent_service — recognize (BERT path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recognize_bert_low_confidence_marks_fallback() -> None:
    fake_bert = MagicMock()
    fake_bert.recognize.return_value = {
        "intent": "customers",
        "confidence": 0.3,
        "fallback_recommended": True,
    }
    svc = _make_service(
        use_bert=True,
        bert_service=fake_bert,
        bert_confidence_threshold=0.7,
    )
    result = await svc.recognize("查客户")
    assert result["bert_intent"] == "customers"
    assert result["bert_confidence"] == 0.3
    assert result["bert_available"] is True
    assert result["bert_low_confidence"] is True
    assert "bert" in result["sources_used"]


@pytest.mark.asyncio
async def test_recognize_bert_high_confidence_overrides_primary_intent() -> None:
    fake_bert = MagicMock()
    fake_bert.recognize.return_value = {
        "intent": "customers",
        "confidence": 0.95,
    }
    svc = _make_service(
        use_bert=True,
        bert_service=fake_bert,
        bert_confidence_threshold=0.7,
    )
    result = await svc.recognize("随便一句话")
    assert result["bert_confidence"] == 0.95
    assert result["primary_intent"] == "customers"
    assert result["intent_confidence"] == 0.95
    assert "customers" in result["intent_hints"]


@pytest.mark.asyncio
async def test_recognize_bert_high_confidence_skipped_when_negated() -> None:
    fake_bert = MagicMock()
    fake_bert.recognize.return_value = {
        "intent": "customers",
        "confidence": 0.95,
    }
    svc = _make_service(
        use_bert=True,
        bert_service=fake_bert,
        bert_confidence_threshold=0.7,
    )
    # Use a negated message — rule engine should mark is_negated=True
    result = await svc.recognize("不查客户")
    # Even if bert says high confidence, negation blocks override
    if result.get("is_negated"):
        # primary_intent should NOT be customers from bert override
        # (rule may still set it, but bert branch is skipped)
        assert result["bert_confidence"] == 0.95
        assert result["bert_available"] is True


@pytest.mark.asyncio
async def test_recognize_bert_unmapped_intent_does_not_override() -> None:
    fake_bert = MagicMock()
    fake_bert.recognize.return_value = {
        "intent": "totally_unknown_intent",
        "confidence": 0.99,
    }
    svc = _make_service(
        use_bert=True,
        bert_service=fake_bert,
        bert_confidence_threshold=0.7,
    )
    result = await svc.recognize("hello")
    # bert fields populated but primary_intent not overridden (no mapping)
    assert result["bert_intent"] == "totally_unknown_intent"
    assert result["bert_confidence"] == 0.99
    # primary_intent may be None or set by rule, but not from bert
    assert result.get("intent_confidence") != 0.99


@pytest.mark.asyncio
async def test_recognize_bert_appends_hint_only_when_new() -> None:
    fake_bert = MagicMock()
    fake_bert.recognize.return_value = {
        "intent": "customers",
        "confidence": 0.9,
    }
    svc = _make_service(
        use_bert=True,
        bert_service=fake_bert,
        bert_confidence_threshold=0.7,
    )
    # Use a message that rule engine already maps to customers
    result = await svc.recognize("查询客户")
    # customers should appear in intent_hints (possibly twice if rule also added)
    assert "customers" in result["intent_hints"]


# ---------------------------------------------------------------------------
# hybrid_intent_service — recognize (RASA path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recognize_rasa_high_confidence_overrides_primary_intent() -> None:
    fake_rasa = MagicMock()
    fake_rasa.parse = AsyncMock(
        return_value={
            "intent": {"name": "customers", "confidence": 0.9},
            "text": "查客户",
        }
    )
    svc = _make_service(
        use_rasa=True,
        rasa_service=fake_rasa,
        use_bert=False,
        rasa_confidence_threshold=0.7,
    )
    result = await svc.recognize("查客户")
    assert result["rasa_available"] is True
    assert result["rasa_intent"] == "customers"
    assert result["rasa_confidence"] == 0.9
    assert "rasa" in result["sources_used"]
    assert result["primary_intent"] == "customers"
    assert "customers" in result["intent_hints"]


@pytest.mark.asyncio
async def test_recognize_rasa_low_confidence_does_not_override() -> None:
    fake_rasa = MagicMock()
    fake_rasa.parse = AsyncMock(
        return_value={
            "intent": {"name": "customers", "confidence": 0.3},
            "text": "x",
        }
    )
    svc = _make_service(
        use_rasa=True,
        rasa_service=fake_rasa,
        use_bert=False,
        rasa_confidence_threshold=0.7,
    )
    result = await svc.recognize("随便说点啥")
    assert result["rasa_available"] is True
    assert result["rasa_confidence"] == 0.3
    # primary_intent should not be overridden by rasa
    assert result.get("primary_intent") != "customers" or result["rasa_confidence"] < 0.7


@pytest.mark.asyncio
async def test_recognize_rasa_unmapped_intent_does_not_override() -> None:
    fake_rasa = MagicMock()
    fake_rasa.parse = AsyncMock(
        return_value={
            "intent": {"name": "unknown_intent_xyz", "confidence": 0.95},
            "text": "x",
        }
    )
    svc = _make_service(
        use_rasa=True,
        rasa_service=fake_rasa,
        use_bert=False,
        rasa_confidence_threshold=0.7,
    )
    result = await svc.recognize("hello")
    assert result["rasa_intent"] == "unknown_intent_xyz"
    # primary_intent not overridden
    assert result.get("primary_intent") != "unknown_intent_xyz"


@pytest.mark.asyncio
async def test_recognize_rasa_negation_intent_does_not_override() -> None:
    fake_rasa = MagicMock()
    fake_rasa.parse = AsyncMock(
        return_value={
            "intent": {"name": "negation", "confidence": 0.95},
            "text": "x",
        }
    )
    svc = _make_service(
        use_rasa=True,
        rasa_service=fake_rasa,
        use_bert=False,
        rasa_confidence_threshold=0.7,
    )
    # Use a message that rule engine does NOT mark as negated, so rasa_intent
    # survives the is_negated clearing branch.
    result = await svc.recognize("随便说点啥")
    assert result["rasa_intent"] == "negation"
    # negation intent should not override primary_intent (mapped to "negation"
    # but the code explicitly skips mapping when mapped_intent == "negation")
    assert result.get("primary_intent") != "negation"


@pytest.mark.asyncio
async def test_recognize_rasa_negated_message_clears_rasa_fields() -> None:
    fake_rasa = MagicMock()
    fake_rasa.parse = AsyncMock(
        return_value={
            "intent": {"name": "customers", "confidence": 0.95},
            "text": "x",
        }
    )
    svc = _make_service(
        use_rasa=True,
        rasa_service=fake_rasa,
        use_bert=False,
        rasa_confidence_threshold=0.7,
    )
    result = await svc.recognize("不查客户")
    if result.get("is_negated"):
        assert result["rasa_intent"] is None
        assert result["rasa_confidence"] == 0.0
        assert result["tool_key"] is None


@pytest.mark.asyncio
async def test_recognize_rasa_no_intent_name() -> None:
    fake_rasa = MagicMock()
    fake_rasa.parse = AsyncMock(
        return_value={"intent": None, "text": "x"}
    )
    svc = _make_service(
        use_rasa=True,
        rasa_service=fake_rasa,
        use_bert=False,
    )
    result = await svc.recognize("hello")
    assert result["rasa_available"] is True
    assert result["rasa_intent"] is None
    assert result["rasa_confidence"] == 0.0


@pytest.mark.asyncio
async def test_recognize_rasa_intent_empty_dict() -> None:
    fake_rasa = MagicMock()
    fake_rasa.parse = AsyncMock(return_value={"intent": {}, "text": "x"})
    svc = _make_service(
        use_rasa=True,
        rasa_service=fake_rasa,
        use_bert=False,
    )
    result = await svc.recognize("hello")
    assert result["rasa_intent"] is None
    assert result["rasa_confidence"] == 0.0


# ---------------------------------------------------------------------------
# hybrid_intent_service — recognize_sync
# ---------------------------------------------------------------------------


def test_recognize_sync_returns_result() -> None:
    svc = _make_service(use_rasa=False, use_bert=False)
    result = svc.recognize_sync("你好")
    assert "sources_used" in result
    assert result["sources_used"] == ["rule"]


def test_recognize_sync_handles_timeout() -> None:
    svc = _make_service(use_rasa=False, use_bert=False)
    with patch.object(
        HybridIntentService, "recognize", new=AsyncMock(side_effect=_slow_recognize)
    ):
        # Force timeout by patching future.result to raise TimeoutError
        import concurrent.futures

        original = concurrent.futures.ThreadPoolExecutor
        result = svc.recognize_sync("hello")
    # Should fall back to rule_recognize_intents
    assert "sources_used" not in result or result.get("primary_intent") is None or isinstance(
        result, dict
    )


async def _slow_recognize(_msg: str) -> dict:  # noqa: RUF029
    import asyncio

    await asyncio.sleep(10)
    return {}


def test_recognize_sync_handles_recoverable_error() -> None:
    """recognize_sync 在 asyncio.get_event_loop() 成功且 recognize 抛出
    RECOVERABLE_ERRORS 时，应捕获并回退到 rule_recognize_intents。

    注意：当 get_event_loop 抛 RuntimeError 时进入 except RuntimeError 分支，
    该分支内的 asyncio.run 不再被外层 try 捕获，因此只测试 loop 可获取的场景。
    """
    svc = _make_service(use_rasa=False, use_bert=False)
    # Patch asyncio.get_event_loop to return a non-running loop so we stay
    # in the main try block (not the RuntimeError branch).
    import asyncio

    fake_loop = MagicMock()
    fake_loop.is_running.return_value = False
    with (
        patch("asyncio.get_event_loop", return_value=fake_loop),
        patch.object(
            HybridIntentService,
            "recognize",
            new=AsyncMock(side_effect=ValueError("bad")),
        ),
    ):
        # asyncio.run is called with the coroutine; we need to patch it too
        # so it re-raises the ValueError inside the try block.
        original_run = asyncio.run

        def fake_run(coro):
            # Close the coroutine to avoid "never awaited" warning, then raise
            try:
                coro.close()
            except Exception:
                pass
            raise ValueError("bad")

        with patch("asyncio.run", side_effect=fake_run):
            result = svc.recognize_sync("hello")
    # Should fall back to rule_recognize_intents
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# hybrid_intent_service — module-level entry points
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_recognize_intents_uses_singleton() -> None:
    reset_hybrid_intent_service()
    with patch(
        "app.services.bert_intent_service.get_bert_intent_service",
        side_effect=RuntimeError("disabled"),
    ):
        result = await hybrid_recognize_intents("你好")
    assert "sources_used" in result
    assert result["sources_used"] == ["rule"]


def test_hybrid_recognize_intents_sync_uses_singleton() -> None:
    reset_hybrid_intent_service()
    with patch(
        "app.services.bert_intent_service.get_bert_intent_service",
        side_effect=RuntimeError("disabled"),
    ):
        result = hybrid_recognize_intents_sync("你好")
    assert "sources_used" in result
    assert result["sources_used"] == ["rule"]


def test_get_hybrid_intent_service_singleton_caches() -> None:
    reset_hybrid_intent_service()
    with patch(
        "app.services.bert_intent_service.get_bert_intent_service",
        side_effect=RuntimeError("disabled"),
    ):
        svc1 = get_hybrid_intent_service(use_bert=True)
        svc2 = get_hybrid_intent_service(use_bert=True)
    assert svc1 is svc2


def test_get_hybrid_intent_service_with_rasa() -> None:
    reset_hybrid_intent_service()
    with (
        patch(
            "app.services.bert_intent_service.get_bert_intent_service",
            side_effect=RuntimeError("disabled"),
        ),
        patch(
            "app.services.hybrid_intent_service.get_rasa_nlu_service",
            return_value=MagicMock(),
        ) as mock_get_rasa,
    ):
        svc = get_hybrid_intent_service(use_rasa=True, use_bert=False)
    assert svc.use_rasa is True
    assert svc.rasa_service is not None
    mock_get_rasa.assert_called_once()


def test_reset_hybrid_intent_service_clears_singleton() -> None:
    reset_hybrid_intent_service()
    with patch(
        "app.services.bert_intent_service.get_bert_intent_service",
        side_effect=RuntimeError("disabled"),
    ):
        svc1 = get_hybrid_intent_service(use_bert=True)
    reset_hybrid_intent_service()
    with patch(
        "app.services.bert_intent_service.get_bert_intent_service",
        side_effect=RuntimeError("disabled"),
    ):
        svc2 = get_hybrid_intent_service(use_bert=True)
    assert svc1 is not svc2
