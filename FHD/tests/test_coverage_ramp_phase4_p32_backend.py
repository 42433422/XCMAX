"""COVERAGE_RAMP Phase 4 round 32: xcmax_admin _collect_mod_modules + im mark_read error."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infrastructure.auth.dependencies import CurrentUser, require_identified_user


def test_collect_mod_modules_reads_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.fastapi_routes import xcmax_admin as admin

    meta = MagicMock()
    meta.name = "Mod A"
    meta.version = "1.0.0"
    mgr = MagicMock()
    mgr._registry = {"mod-a": meta}
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: mgr,
    )
    rows = admin._collect_mod_modules()
    assert any(r.get("module_id") == "mod-a" for r in rows)
    assert rows[0].get("source") == "local"


def test_im_mark_read_permission_error() -> None:
    from app.fastapi_routes import im_routes

    app = FastAPI()
    app.include_router(im_routes.router)
    app.dependency_overrides[require_identified_user] = lambda: CurrentUser(1)

    mock_db = MagicMock()
    mock_svc = MagicMock()
    mock_svc.mark_read.side_effect = PermissionError("not a member")

    with (
        patch.object(im_routes, "_ensure_schema"),
        patch.object(im_routes, "HostSessionLocal", return_value=mock_db),
        patch.object(im_routes, "ImApplicationService", return_value=mock_svc),
        patch.object(im_routes.im_ws_hub, "send_to_user", new_callable=AsyncMock),
    ):
        client = TestClient(app)
        resp = client.post("/api/im/conversations/9/read", json={"last_message_id": 3})
    assert resp.status_code == 403
