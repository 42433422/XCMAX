"""Python 路由 `POST /api/payment/notify/alipay` — 对齐 Java `AlipayNotifyIntegrationTest` 主路径。

仅在 ``PAYMENT_BACKEND`` 非 ``java`` 时由本路由处理；CI 默认覆盖此 fallback。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from modstore_server.api.app_factory import create_app, load_default_config


def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "pay_notify.sqlite"))
    orders_dir = tmp_path / "pay_orders"
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(orders_dir))
    orders_dir.mkdir(parents=True)

    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    models.init_db()

    app = create_app(load_default_config())
    return TestClient(app)


def _notify_plain_text(r):
    """兼容 JSON 字符串体与纯文本体（支付宝约定 success / fail）。"""
    try:
        return r.json()
    except Exception:
        return r.text


def _pending_order_json(out_trade_no: str, total: str) -> dict:
    return {
        "out_trade_no": out_trade_no,
        "subject": "wallet recharge",
        "total_amount": total,
        "user_id": 1,
        "order_kind": "wallet",
        "status": "pending",
        "paid_at": None,
        "created_at": "2026-05-08T10:00:00+00:00",
    }


@pytest.fixture
def alipay_verify_ok(monkeypatch: pytest.MonkeyPatch):
    def _verify(_data: dict, _sig: str) -> bool:
        return True

    monkeypatch.setattr("modstore_server.payment_api.alipay_service.verify_notify", _verify)


def test_notify_success_marks_order_paid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alipay_verify_ok,
):
    client = _make_client(tmp_path, monkeypatch)
    od = Path(os.environ["MODSTORE_PAYMENT_ORDERS_DIR"])
    ono = "MOD-NOTIFY-PY-1"
    (od / f"order_{ono}.json").write_text(
        json.dumps(_pending_order_json(ono, "19.90"), ensure_ascii=False),
        encoding="utf-8",
    )

    r = client.post(
        "/api/payment/notify/alipay",
        data={
            "sign": "x",
            "out_trade_no": ono,
            "trade_status": "TRADE_SUCCESS",
            "trade_no": "TN-1",
            "buyer_id": "B1",
            "total_amount": "19.90",
        },
    )
    assert r.status_code == 200
    assert _notify_plain_text(r) == "success"

    body = json.loads((od / f"order_{ono}.json").read_text(encoding="utf-8"))
    assert body["status"] == "paid"


def test_notify_duplicate_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alipay_verify_ok,
):
    client = _make_client(tmp_path, monkeypatch)
    od = Path(os.environ["MODSTORE_PAYMENT_ORDERS_DIR"])
    ono = "MOD-NOTIFY-PY-2"
    (od / f"order_{ono}.json").write_text(
        json.dumps(_pending_order_json(ono, "8.00"), ensure_ascii=False),
        encoding="utf-8",
    )

    form = {
        "sign": "x",
        "out_trade_no": ono,
        "trade_status": "TRADE_SUCCESS",
        "trade_no": "TN-2",
        "total_amount": "8.00",
    }
    assert _notify_plain_text(client.post("/api/payment/notify/alipay", data=form)) == "success"
    assert _notify_plain_text(client.post("/api/payment/notify/alipay", data=form)) == "success"

    data = json.loads((od / f"order_{ono}.json").read_text(encoding="utf-8"))
    assert data["status"] == "paid"


def test_notify_amount_mismatch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alipay_verify_ok,
):
    client = _make_client(tmp_path, monkeypatch)
    od = Path(os.environ["MODSTORE_PAYMENT_ORDERS_DIR"])
    ono = "MOD-NOTIFY-PY-3"
    (od / f"order_{ono}.json").write_text(
        json.dumps(_pending_order_json(ono, "9.90"), ensure_ascii=False),
        encoding="utf-8",
    )

    r = client.post(
        "/api/payment/notify/alipay",
        data={
            "sign": "x",
            "out_trade_no": ono,
            "trade_status": "TRADE_SUCCESS",
            "trade_no": "TN-3",
            "total_amount": "8.00",
        },
    )
    assert _notify_plain_text(r) == "fail"
    data = json.loads((od / f"order_{ono}.json").read_text(encoding="utf-8"))
    assert data["status"] == "pending"


def test_notify_missing_sign_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    client = _make_client(tmp_path, monkeypatch)
    od = Path(os.environ["MODSTORE_PAYMENT_ORDERS_DIR"])
    ono = "MOD-NOTIFY-PY-4"
    (od / f"order_{ono}.json").write_text(
        json.dumps(_pending_order_json(ono, "1.00"), ensure_ascii=False),
        encoding="utf-8",
    )

    r = client.post(
        "/api/payment/notify/alipay",
        data={
            "out_trade_no": ono,
            "trade_status": "TRADE_SUCCESS",
            "trade_no": "TN",
            "total_amount": "1.00",
        },
    )
    assert _notify_plain_text(r) == "fail"


def test_notify_verify_signature_false_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    client = _make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "modstore_server.payment_api.alipay_service.verify_notify",
        lambda _d, _s: False,
    )
    od = Path(os.environ["MODSTORE_PAYMENT_ORDERS_DIR"])
    ono = "MOD-NOTIFY-PY-5"
    (od / f"order_{ono}.json").write_text(
        json.dumps(_pending_order_json(ono, "1.00"), ensure_ascii=False),
        encoding="utf-8",
    )

    r = client.post(
        "/api/payment/notify/alipay",
        data={
            "sign": "bad",
            "out_trade_no": ono,
            "trade_status": "TRADE_SUCCESS",
            "total_amount": "1.00",
        },
    )
    assert _notify_plain_text(r) == "fail"


def test_notify_wait_buyer_pay_returns_success_without_pay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alipay_verify_ok,
):
    client = _make_client(tmp_path, monkeypatch)
    od = Path(os.environ["MODSTORE_PAYMENT_ORDERS_DIR"])
    ono = "MOD-NOTIFY-PY-6"
    (od / f"order_{ono}.json").write_text(
        json.dumps(_pending_order_json(ono, "5.00"), ensure_ascii=False),
        encoding="utf-8",
    )

    r = client.post(
        "/api/payment/notify/alipay",
        data={
            "sign": "x",
            "out_trade_no": ono,
            "trade_status": "WAIT_BUYER_PAY",
            "trade_no": "TN",
            "total_amount": "5.00",
        },
    )
    assert _notify_plain_text(r) == "success"
    data = json.loads((od / f"order_{ono}.json").read_text(encoding="utf-8"))
    assert data["status"] == "pending"


def test_notify_missing_order_returns_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alipay_verify_ok,
):
    client = _make_client(tmp_path, monkeypatch)
    r = client.post(
        "/api/payment/notify/alipay",
        data={
            "sign": "x",
            "out_trade_no": "MISSING",
            "trade_status": "TRADE_SUCCESS",
            "total_amount": "1.00",
        },
    )
    assert _notify_plain_text(r) == "fail"
