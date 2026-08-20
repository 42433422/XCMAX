# mypy: disable-error-code="arg-type"
"""测试 MODstore 订单事件桥接（payment.paid → FHD NeuroBus + 回款核销）。"""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import MagicMock, patch

import pytest

from app.services.order_event_bridge import (
    PAID_EVENT_TYPE,
    event_dedup_key,
    ingest_paid_event,
    parse_paid_envelope,
    verify_signature,
)

_ENVELOPE = {
    "id": "payment.paid:MOD123",
    "type": "payment.paid",
    "version": 1,
    "source": "modstore-python",
    "aggregate_id": "MOD123",
    "created_at": 1710000000,
    "data": {
        "out_trade_no": "MOD123",
        "user_id": 42,
        "subject": "企业版月费",
        "total_amount": "99.00",
        "order_kind": "plan",
    },
}


def _clear_dedup():
    from app.services import order_event_bridge as m

    m._seen_dedup().clear()


@pytest.fixture(autouse=True)
def _reset_dedup():
    _clear_dedup()
    yield
    _clear_dedup()


class TestParsePaidEnvelope:
    def test_parses_valid(self):
        data = parse_paid_envelope(_ENVELOPE)
        assert data is not None
        assert data["out_trade_no"] == "MOD123"
        assert data["user_id"] == 42

    def test_rejects_wrong_type(self):
        env = dict(_ENVELOPE, type="refund.approved")
        assert parse_paid_envelope(env) is None

    def test_rejects_missing_field(self):
        env = dict(_ENVELOPE)
        env["data"] = {"out_trade_no": "MOD123"}  # 缺 user_id/total_amount
        assert parse_paid_envelope(env) is None

    def test_rejects_non_dict_body(self):
        assert parse_paid_envelope([]) is None
        assert parse_paid_envelope(None) is None

    def test_rejects_non_dict_data(self):
        env = dict(_ENVELOPE, data="not-a-dict")
        assert parse_paid_envelope(env) is None


class TestEventDedupKey:
    def test_uses_id(self):
        assert event_dedup_key(_ENVELOPE) == "payment.paid:MOD123"

    def test_fallback_aggregate_id(self):
        env = {"aggregate_id": "MOD9"}
        assert event_dedup_key(env) == "MOD9"

    def test_empty(self):
        assert event_dedup_key({}) == ""


class TestVerifySignature:
    def test_returns_true_when_no_secret(self):
        with patch("app.services.order_event_bridge.bridge_secret", return_value=""):
            assert verify_signature(b"{}", "sha256=abc") is True

    def test_valid_signature(self):
        secret = "s3cret"
        raw = b'{"type":"payment.paid"}'
        ts, eid = "1710000000", "payment.paid:MOD123"
        # 与 MODstore webhook_dispatcher._signature 一致：HMAC(secret, "{ts}.{id}.{body}")
        expected = hmac.new(
            secret.encode(), f"{ts}.{eid}.".encode() + raw, hashlib.sha256
        ).hexdigest()
        with patch("app.services.order_event_bridge.bridge_secret", return_value=secret):
            assert verify_signature(raw, f"sha256={expected}", timestamp=ts, event_id=eid) is True

    def test_invalid_signature(self):
        secret = "s3cret"
        with patch("app.services.order_event_bridge.bridge_secret", return_value=secret):
            assert verify_signature(b"{}", "sha256=deadbeef") is False

    def test_missing_signature_rejected(self):
        secret = "s3cret"
        with patch("app.services.order_event_bridge.bridge_secret", return_value=secret):
            assert verify_signature(b"{}", None) is False


class TestIngestPaidEvent:
    def test_accepts_and_dedups(self):
        with (
            patch("app.services.order_event_bridge.emit_paid_event", return_value=True) as emit,
            patch("app.services.order_event_bridge._record_reconciliation_if_user") as rec,
        ):
            first = ingest_paid_event(_ENVELOPE)
            second = ingest_paid_event(_ENVELOPE)
        assert first["accepted"] is True
        assert first["deduped"] is False
        assert second["accepted"] is True
        assert second["deduped"] is True
        assert emit.call_count == 1
        rec.assert_called_once()

    def test_rejects_invalid_envelope(self):
        with patch("app.services.order_event_bridge.emit_paid_event") as emit:
            result = ingest_paid_event({"type": "refund.approved"})
        assert result["accepted"] is False
        assert result["reason"] == "invalid_envelope"
        emit.assert_not_called()

    def test_rejects_bad_signature(self):
        secret = "s3cret"
        with (
            patch("app.services.order_event_bridge.bridge_secret", return_value=secret),
            patch("app.services.order_event_bridge.emit_paid_event") as emit,
        ):
            result = ingest_paid_event(
                _ENVELOPE,
                hmac_signature="sha256=bad",
                raw=b"{}",
                timestamp="1710000000",
                event_id="payment.paid:MOD123",
            )
        assert result["accepted"] is False
        assert result["reason"] == "invalid_signature"
        emit.assert_not_called()

    def test_returns_emitted_flag(self):
        with (
            patch("app.services.order_event_bridge.emit_paid_event", return_value=False),
            patch("app.services.order_event_bridge._record_reconciliation_if_user") as rec,
        ):
            result = ingest_paid_event(_ENVELOPE)
        assert result["emitted"] is False
        rec.assert_called_once()

    def test_ties_to_reconciliation(self):
        # 触发履约样板：应调用 record_reconciliation
        with (
            patch("app.services.order_event_bridge.emit_paid_event", return_value=True),
            patch("app.services.user_cs_pipeline.record_reconciliation") as rec,
        ):
            ingest_paid_event(_ENVELOPE)
        rec.assert_called_once()
        args = rec.call_args
        assert args[0][0] == 42  # user_id
        assert args[1]["amount_yuan"] == "99.00"
        assert args[1]["order_ref"] == "MOD123"


class TestBridgeSecretEnv:
    def test_reads_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("MODSTORE_ORDER_WEBHOOK_SECRET", "  env-secret  ")
        from app.services.order_event_bridge import bridge_secret

        assert bridge_secret() == "env-secret"

    def test_empty_when_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("MODSTORE_ORDER_WEBHOOK_SECRET", raising=False)
        from app.services.order_event_bridge import bridge_secret

        assert bridge_secret() == ""


class TestEmitPaidEvent:
    def test_publishes_to_neuro_bus(self) -> None:
        from app.services.order_event_bridge import emit_paid_event

        bus = MagicMock()
        bus.publish.return_value = True
        with patch("app.neuro_bus.bus.get_neuro_bus", return_value=bus):
            assert emit_paid_event(_ENVELOPE["data"]) is True
        bus.publish.assert_called_once()

    def test_false_when_publish_returns_false(self) -> None:
        from app.services.order_event_bridge import emit_paid_event

        bus = MagicMock()
        bus.publish.return_value = False
        with patch("app.neuro_bus.bus.get_neuro_bus", return_value=bus):
            assert emit_paid_event(_ENVELOPE["data"]) is False

    def test_false_on_exception(self) -> None:
        from app.services.order_event_bridge import emit_paid_event

        bus = MagicMock()
        bus.publish.side_effect = RuntimeError("bus down")
        with patch("app.neuro_bus.bus.get_neuro_bus", return_value=bus):
            assert emit_paid_event(_ENVELOPE["data"]) is False


class TestRecordReconciliation:
    def test_skips_when_no_user_id(self) -> None:
        from app.services.order_event_bridge import _record_reconciliation_if_user

        with patch("app.services.user_cs_pipeline.record_reconciliation") as rec:
            _record_reconciliation_if_user({"user_id": 0, "out_trade_no": "MOD0"})
        rec.assert_not_called()

    def test_records_reconciliation(self) -> None:
        from app.services.order_event_bridge import _record_reconciliation_if_user

        with patch("app.services.user_cs_pipeline.record_reconciliation") as rec:
            _record_reconciliation_if_user(_ENVELOPE["data"])
        rec.assert_called_once()

    def test_swallows_exception(self) -> None:
        from app.services.order_event_bridge import _record_reconciliation_if_user

        with patch(
            "app.services.user_cs_pipeline.record_reconciliation", side_effect=RuntimeError("x")
        ):
            _record_reconciliation_if_user(_ENVELOPE["data"])  # 不应抛异常
