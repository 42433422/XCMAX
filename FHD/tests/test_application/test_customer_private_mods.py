"""客户定制 Mod 只能对被授权账号可见、可调用。"""

from __future__ import annotations

import json
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.mod_sdk.client_private_mods import CUSTOMER_PRIVATE_MOD_IDS, is_customer_private_mod
from app.mod_sdk.runtime_frontend import visible_mod_rows

FHD_ROOT = Path(__file__).resolve().parents[2]


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/mods", "headers": []})


def test_customer_mod_hidden_even_when_manifest_claims_global():
    rows = [
        {"id": "sz-qsm-pro", "scope": "global", "primary": True},
        {"id": "attendance-industry", "scope": "global", "primary": True},
    ]

    visible = [row["id"] for row in visible_mod_rows(_request(), rows)]

    assert visible == ["attendance-industry"]


def test_unknown_customer_mod_id_is_not_private():
    assert is_customer_private_mod("taiyangniao-pro")
    assert not is_customer_private_mod("attendance-industry")
    assert not is_customer_private_mod("")


def test_customer_mods_declare_account_scope():
    for mod_id in CUSTOMER_PRIVATE_MOD_IDS:
        manifests = list(FHD_ROOT.glob(f"mods/*/{mod_id}/manifest.json"))
        if not manifests:
            continue
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        assert manifest.get("scope") == "account", mod_id


def test_packaging_exclusions_cover_customer_mods():
    script = (FHD_ROOT / "scripts/package/stage-bundled-mods.sh").read_text(encoding="utf-8")
    line = next((item for item in script.splitlines() if item.startswith("EXCLUDE_ALWAYS=(")), "")
    assert line, "打包脚本缺少 EXCLUDE_ALWAYS"
    for mod_id in CUSTOMER_PRIVATE_MOD_IDS:
        assert mod_id in line, f"{mod_id} 必须从发布包排除"


def test_customer_mod_api_is_blocked_without_entitlement():
    from app.middleware.customer_mod_scope import CustomerModScopeMiddleware

    async def handler(request: Request) -> JSONResponse:
        return JSONResponse({"success": True})

    app = Starlette(
        routes=[
            Route("/api/mod/{mod_id}/{rest:path}", handler, methods=["GET", "POST"]),
        ]
    )
    app.add_middleware(CustomerModScopeMiddleware)
    client = TestClient(app)

    blocked = client.get("/api/mod/sz-qsm-pro/phone-agent/status")
    assert blocked.status_code in {401, 403, 404, 409}
    assert blocked.json()["success"] is False

    allowed = client.get("/api/mod/xcagi-planner-bridge/chat")
    assert allowed.status_code == 200
