from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.fastapi_routes.xcmax_admin as admin_routes


def test_diagnostic_terminal_routes_proxy_the_exact_read_only_contracts():
    app = FastAPI()
    app.include_router(admin_routes.router)
    client = TestClient(app)
    proxied = AsyncMock(return_value={"ok": True, "read_only": True})

    with patch("app.fastapi_routes.xcmax_admin._market_admin_proxy", new=proxied):
        commands = client.get("/api/xcmax/admin/market/diagnostic-terminal/commands")
        assert commands.status_code == 200
        assert proxied.await_args.args[1:] == (
            "GET",
            "/api/admin/diagnostic-terminal/commands",
        )

        payload = {"command": "find 登录 --limit 20"}
        execute = client.post(
            "/api/xcmax/admin/market/diagnostic-terminal/execute",
            json=payload,
        )
        assert execute.status_code == 200
        assert proxied.await_args.args[1:] == (
            "POST",
            "/api/admin/diagnostic-terminal/execute",
        )
        assert proxied.await_args.kwargs == {"json_body": payload}
