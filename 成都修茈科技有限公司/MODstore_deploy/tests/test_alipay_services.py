"""Gateway outcomes and checkout selection for the Python payment fallback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("user_agent", ["desktop", "Android mobile"])
def test_unusable_checkout_response_falls_back_to_verified_qr(monkeypatch, user_agent):
    from modstore_server import alipay_service as payments

    calls = []

    def page(**kwargs):
        calls.append(("page", kwargs))
        return ""

    def wap(**kwargs):
        calls.append(("wap", kwargs))
        return None

    def precreate(**kwargs):
        calls.append(("precreate", kwargs))
        return {
            "code": "10000",
            "qr_code": "fixture://checkout",
            "trade_no": "fixture-trade",
        }

    client = SimpleNamespace(
        api_alipay_trade_page_pay=page,
        api_alipay_trade_wap_pay=wap,
        api_alipay_trade_precreate=precreate,
    )
    monkeypatch.setattr(payments, "credentials_ready", lambda: True)
    monkeypatch.setattr(payments, "build_client", lambda: client)
    result = payments.create_pay_order(
        out_trade_no="order-one",
        subject="fixture",
        total_amount="1.23",
        user_agent=user_agent,
        notify_url="https://example.invalid/api/payment/notify/alipay",
    )
    assert result["ok"] is True
    assert result["type"] == "precreate"
    assert result["qr_code"] == "fixture://checkout"
    assert result["redirect_url"] is None
    assert calls[-1][0] == "precreate"
    assert all(call[1]["total_amount"] == "1.23" for call in calls)


@pytest.mark.parametrize("signature_result", [False, True])
def test_notification_verification_delegates_exact_payload(monkeypatch, signature_result):
    from modstore_server import alipay_service as payments

    observed = []

    def verify(data, signature):
        observed.append((dict(data), signature))
        return signature_result

    monkeypatch.setattr(payments, "build_client", lambda: SimpleNamespace(verify=verify))
    payload = {
        "out_trade_no": "order-one",
        "total_amount": "1.23",
        "trade_status": "TRADE_SUCCESS",
    }
    assert payments.verify_notify(payload, "fixture-signature") is signature_result
    assert observed == [(payload, "fixture-signature")]


def test_refund_requires_an_order_identifier_before_constructing_client(monkeypatch):
    from modstore_server import alipay_service as payments

    def forbidden():
        pytest.fail("missing order identifiers must never call the gateway")

    monkeypatch.setattr(payments, "build_client", forbidden)
    assert payments.refund_order(refund_amount="1.00")["ok"] is False
    assert payments.query_order()["ok"] is False
    assert payments.close_order()["ok"] is False
