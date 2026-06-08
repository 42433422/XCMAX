"""支付核心函数单元测试：签名、防重放、金额校验、下单字段解析。"""

from __future__ import annotations

import hashlib
import time

import pytest

from modstore_server.payment_common import (
    MEMBERSHIP_TIER_ORDER,
    SVIP_LOCKED_PLAN_IDS,
    SVIP_TIER_PLAN_IDS,
    CheckoutDTO,
    SignCheckoutBody,
    _amount_sign_str,
    _amounts_match,
    _membership_meta,
    _parse_money,
    _plan_required_predecessor,
    canonical_checkout_sign_data,
    check_replay_attack,
    generate_signature,
    verify_signature,
)


class TestGenerateAndVerifySignature:
    def test_sign_and_verify_roundtrip(self):
        data = {"item_id": "0", "plan_id": "pro", "total_amount": "199", "wallet_recharge": "false"}
        secret = "test-secret"
        sig = generate_signature(data, secret)
        assert verify_signature(data, secret, sig)

    def test_tampered_data_fails(self):
        data = {"amount": "100"}
        secret = "s"
        sig = generate_signature(data, secret)
        assert not verify_signature({"amount": "200"}, secret, sig)

    def test_wrong_secret_fails(self):
        data = {"a": "1"}
        sig = generate_signature(data, "secret-a")
        assert not verify_signature(data, "secret-b", sig)

    def test_empty_data(self):
        sig = generate_signature({}, "s")
        assert verify_signature({}, "s", sig)


class TestCheckReplayAttack:
    def test_fresh_request_is_not_replay(self):
        assert not check_replay_attack("unique-req-1", int(time.time()))

    def test_stale_timestamp_is_replay(self):
        old_ts = int(time.time()) - 600
        assert check_replay_attack("unique-req-2", old_ts)

    def test_blank_request_id_is_replay(self):
        assert check_replay_attack("", int(time.time()))
        assert check_replay_attack("   ", int(time.time()))

    def test_duplicate_request_id_is_replay(self):
        ts = int(time.time())
        assert not check_replay_attack("dup-req", ts)
        assert check_replay_attack("dup-req", ts)


class TestParseMoney:
    def test_int(self):
        assert _parse_money(42) == 42.0

    def test_float(self):
        assert _parse_money(9.90) == pytest.approx(9.90)

    def test_string(self):
        assert _parse_money("199.00") == pytest.approx(199.0)

    def test_comma_separated(self):
        assert _parse_money("1,000.50") == pytest.approx(1000.5)

    def test_none(self):
        assert _parse_money(None) is None

    def test_empty(self):
        assert _parse_money("") is None

    def test_invalid(self):
        assert _parse_money("abc") is None


class TestAmountsMatch:
    def test_exact_match(self):
        assert _amounts_match(99.00, "99.00")

    def test_within_tolerance(self):
        assert _amounts_match(99.00, "99.009")

    def test_outside_tolerance(self):
        assert not _amounts_match(99.00, "99.02")

    def test_none_amounts(self):
        assert not _amounts_match(None, "99")
        assert not _amounts_match("99", None)


class TestAmountSignStr:
    def test_integer(self):
        assert _amount_sign_str(10) == "10"

    def test_decimal(self):
        assert _amount_sign_str(9.9) == "9.9"

    def test_zero(self):
        assert _amount_sign_str(0) == "0"

    def test_none(self):
        assert _amount_sign_str(None) == "0"

    def test_string_input(self):
        assert _amount_sign_str("199.00") == "199"


class TestCanonicalCheckoutSignData:
    def test_all_fields(self):
        dto = CheckoutDTO(
            plan_id="pro",
            item_id=42,
            total_amount=199.0,
            subject="Test",
            wallet_recharge=False,
            pay_channel="alipay",
            request_id="req-1",
            timestamp=1710000000,
            signature="-",
        )
        result = canonical_checkout_sign_data(dto)
        assert result["item_id"] == "42"
        assert result["plan_id"] == "pro"
        assert result["request_id"] == "req-1"
        assert result["timestamp"] == "1710000000"
        assert result["wallet_recharge"] == "false"

    def test_wallet_recharge_true(self):
        dto = CheckoutDTO(
            plan_id="",
            item_id=0,
            total_amount=50.0,
            subject="",
            wallet_recharge=True,
            pay_channel="alipay",
            request_id="req-2",
            timestamp=1710000000,
            signature="-",
        )
        result = canonical_checkout_sign_data(dto)
        assert result["wallet_recharge"] == "true"


class TestMembershipMeta:
    def test_basic_plan(self):
        meta = _membership_meta("plan_basic")
        assert meta["tier"] == "vip"
        assert meta["is_member"] is True
        assert meta["can_byok"] is False

    def test_pro_plan(self):
        meta = _membership_meta("plan_pro")
        assert meta["tier"] == "vip_plus"
        assert meta["can_byok"] is True

    def test_enterprise_plan(self):
        meta = _membership_meta("plan_enterprise")
        assert meta["tier"] == "svip1"
        assert meta["is_member"] is True

    def test_svip_plans(self):
        for i in range(2, 9):
            meta = _membership_meta(f"plan_svip{i}")
            assert meta["tier"] == f"svip{i}"
            assert meta["is_member"] is True

    def test_unknown_plan(self):
        meta = _membership_meta("plan_nonexistent")
        assert meta["tier"] == "free"
        assert meta["is_member"] is False

    def test_none_plan(self):
        meta = _membership_meta(None)
        assert meta["tier"] == "free"


class TestPlanRequiredPredecessor:
    def test_svip2_requires_enterprise(self):
        assert _plan_required_predecessor("plan_svip2") == "plan_enterprise"

    def test_svip8_requires_enterprise(self):
        assert _plan_required_predecessor("plan_svip8") == "plan_enterprise"

    def test_basic_no_predecessor(self):
        assert _plan_required_predecessor("plan_basic") is None

    def test_pro_no_predecessor(self):
        assert _plan_required_predecessor("plan_pro") is None

    def test_enterprise_no_predecessor(self):
        assert _plan_required_predecessor("plan_enterprise") is None

    def test_none_no_predecessor(self):
        assert _plan_required_predecessor(None) is None


class TestMembershipTierOrder:
    def test_tier_ordering(self):
        assert MEMBERSHIP_TIER_ORDER["plan_basic"] < MEMBERSHIP_TIER_ORDER["plan_pro"]
        assert MEMBERSHIP_TIER_ORDER["plan_pro"] < MEMBERSHIP_TIER_ORDER["plan_enterprise"]
        assert MEMBERSHIP_TIER_ORDER["plan_enterprise"] < MEMBERSHIP_TIER_ORDER["plan_svip2"]

    def test_svip_locked_are_higher_than_enterprise(self):
        for pid in SVIP_LOCKED_PLAN_IDS:
            assert MEMBERSHIP_TIER_ORDER[pid] > MEMBERSHIP_TIER_ORDER["plan_enterprise"]

    def test_all_svip_tiers_in_tier_plan_ids(self):
        for pid in SVIP_LOCKED_PLAN_IDS:
            assert pid in SVIP_TIER_PLAN_IDS
