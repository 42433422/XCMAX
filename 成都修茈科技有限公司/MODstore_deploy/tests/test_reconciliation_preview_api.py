"""管理员只读对账预览 API：`POST /api/admin/reconciliation/preview`（不落库）。"""

from __future__ import annotations

import json
import types
from pathlib import Path

from fastapi.testclient import TestClient

from modstore_server.api.app_factory import create_app, load_default_config
from modstore_server.api.auth_deps import require_user


def test_preview_requires_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "recv_prev.sqlite"))
    monkeypatch.setenv(
        "MODSTORE_PAYMENT_ORDERS_DIR",
        str(tmp_path / "orders"),
    )
    (tmp_path / "orders").mkdir(parents=True)

    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    models.init_db()

    app = create_app(load_default_config())
    client = TestClient(app)

    user = types.SimpleNamespace(id=1, username="u", is_admin=False, email="u@u")
    app.dependency_overrides[require_user] = lambda: user
    try:
        r = client.post(
            "/api/admin/reconciliation/preview",
            json={
                "period_start": "2026-01-01T00:00:00",
                "period_end": "2026-02-01T00:00:00",
            },
        )
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(require_user, None)


def test_preview_read_only_skill_shape_and_alipay_diff(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "recv_prev2.sqlite"))
    orders_dir = tmp_path / "orders"
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(orders_dir))
    orders_dir.mkdir(parents=True)

    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    models.init_db()

    # 一笔已支付订单落在区间内
    paid_at = "2026-01-15T12:00:00+00:00"
    order_path = orders_dir / "order_MOD-PREV-1.json"
    order_path.write_text(
        json.dumps(
            {
                "out_trade_no": "MOD-PREV-1",
                "subject": "t",
                "total_amount": "10.00",
                "user_id": 1,
                "status": "paid",
                "paid_at": paid_at,
                "created_at": paid_at,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    app = create_app(load_default_config())
    client = TestClient(app)

    admin = types.SimpleNamespace(id=99, username="admin", is_admin=True, email="a@a")
    app.dependency_overrides[require_user] = lambda: admin
    try:
        r = client.post(
            "/api/admin/reconciliation/preview",
            json={
                "period_start": "2026-01-01T00:00:00",
                "period_end": "2026-02-01T00:00:00",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["read_only"] is True
        pr = body["payment_reconcile"]
        assert pr["status"] == "ok"
        assert pr["total_orders"] == 1
        assert pr["diff_count"] == 0
        assert pr["diff_amount_cny"] == 0.0
        assert "支付对账预览" in pr["report_md"]
        assert pr["platform_snapshot"]["total_gmv"] == 10.0

        r2 = client.post(
            "/api/admin/reconciliation/preview",
            json={
                "period_start": "2026-01-01T00:00:00",
                "period_end": "2026-02-01T00:00:00",
                "alipay_statement_total_cny": 5.0,
            },
        )
        assert r2.status_code == 200
        pr2 = r2.json()["payment_reconcile"]
        assert pr2["status"] == "warning"
        assert pr2["diff_count"] == 1
        assert abs(pr2["diff_amount_cny"] - 5.0) < 0.001
    finally:
        app.dependency_overrides.pop(require_user, None)


def test_preview_includes_history_vs_previous_confirmed_report(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "recv_prev3.sqlite"))
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders3"))
    (tmp_path / "orders3").mkdir(parents=True)

    import modstore_server.models as models
    from modstore_server.models import ReconciliationReport

    models._engine = None
    models._SessionFactory = None
    models.init_db()

    from datetime import datetime

    sf = models.get_session_factory()
    with sf() as session:
        prev = ReconciliationReport(
            period_start=datetime(2025, 11, 1),
            period_end=datetime(2025, 12, 1),
            total_orders=2,
            total_gmv=20.0,
            platform_revenue=0,
            author_payable=0,
            refunds_count=0,
            refunds_amount=0,
            wallet_top_ups=0,
            alipay_income=20.0,
            status="confirmed",
            generated_at=datetime(2025, 12, 2),
            confirmed_at=datetime(2025, 12, 2),
        )
        session.add(prev)
        session.commit()

    app = create_app(load_default_config())
    client = TestClient(app)

    admin = types.SimpleNamespace(id=99, username="admin", is_admin=True, email="a@a")
    app.dependency_overrides[require_user] = lambda: admin
    try:
        r = client.post(
            "/api/admin/reconciliation/preview",
            json={
                "period_start": "2026-01-01T00:00:00",
                "period_end": "2026-02-01T00:00:00",
            },
        )
        assert r.status_code == 200
        hist = r.json()["payment_reconcile"]["history_vs_previous_period"]
        assert hist is not None
        assert hist["previous_report_id"] is not None
        assert hist["total_gmv_delta_cny"] == -20.0
    finally:
        app.dependency_overrides.pop(require_user, None)
