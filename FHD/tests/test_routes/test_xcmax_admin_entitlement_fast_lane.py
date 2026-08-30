from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.fastapi_routes.xcmax_admin as admin_routes


def test_entitlement_fast_lane_routes_proxy_exact_admin_contracts():
    app = FastAPI()
    app.include_router(admin_routes.router)
    client = TestClient(app)
    proxied = AsyncMock(return_value={"ok": True})

    with patch("app.fastapi_routes.xcmax_admin._market_admin_proxy", new=proxied):
        response = client.get("/api/xcmax/admin/market/entitlement-fast-lane/plans")
        assert response.status_code == 200
        assert proxied.await_args.args[1:] == (
            "GET",
            "/api/admin/entitlement-fast-lane/plans",
        )

        response = client.get(
            "/api/xcmax/admin/market/entitlement-fast-lane/accounts/name%2Btag%40example.com"
        )
        assert response.status_code == 200
        assert proxied.await_args.args[1:] == (
            "GET",
            "/api/admin/entitlement-fast-lane/accounts/name%2Btag%40example.com",
        )

        payload = {
            "account": "SUNBIRD",
            "action": "assign",
            "plan_id": "saas-permanent-max",
            "reason": "创始人确认集团协同版",
            "idempotency_key": "test-fast-lane-123456",
        }
        response = client.post(
            "/api/xcmax/admin/market/entitlement-fast-lane/actions",
            json=payload,
        )
        assert response.status_code == 200
        assert proxied.await_args.args[1:] == (
            "POST",
            "/api/admin/entitlement-fast-lane/actions",
        )
        assert proxied.await_args.kwargs == {"json_body": payload}
