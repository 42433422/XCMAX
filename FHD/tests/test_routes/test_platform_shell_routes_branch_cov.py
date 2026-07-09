"""platform_shell_routes 异常/空列表分支。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes import platform_shell_routes as ps


@pytest.mark.asyncio
async def test_capabilities_list_mods_failure():
    with (
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=RuntimeError("boom"),
        ),
        patch.object(ps, "RECOVERABLE_ERRORS", (RuntimeError,)),
        patch(
            "app.mod_sdk.platform_shell.build_platform_shell_payload",
            return_value={"ok": True},
        ) as build,
    ):
        out = await ps.platform_shell_capabilities()
    assert out["success"] is True
    build.assert_called_once_with([])


@pytest.mark.asyncio
async def test_decoupling_progress_list_mods_failure():
    with (
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=RuntimeError("boom"),
        ),
        patch.object(ps, "RECOVERABLE_ERRORS", (RuntimeError,)),
        patch(
            "app.mod_sdk.decoupling_progress.build_decoupling_progress_payload",
            return_value={"ok": True},
        ) as build,
    ):
        out = await ps.decoupling_progress()
    assert out["success"] is True
    build.assert_called_once_with([])


@pytest.mark.asyncio
async def test_deliverable_status_uses_request_app():
    req = MagicMock()
    req.app = MagicMock(name="app")
    with patch(
        "app.mod_sdk.deliverable_status.build_deliverable_status",
        return_value={"deliverable": True},
    ) as build:
        out = await ps.platform_shell_deliverable_status(req)
    assert out["data"]["deliverable"] is True
    build.assert_called_once_with(app=req.app)


@pytest.mark.asyncio
async def test_employee_ssot_installed_failure():
    with (
        patch(
            "app.application.ops_closure_status._installed_employee_pack_ids",
            side_effect=RuntimeError("x"),
        ),
        patch.object(ps, "RECOVERABLE_ERRORS", (RuntimeError,)),
        patch(
            "app.mod_sdk.employee_ssot.derive_employee_ssot",
            return_value={"admin": {}},
        ) as derive,
    ):
        out = await ps.platform_shell_employee_ssot()
    assert out["success"] is True
    derive.assert_called_once_with(installed_ids=set())


@pytest.mark.asyncio
async def test_capabilities_with_mods():
    mm = MagicMock()
    mm.list_all_mods.return_value = [{"id": "a"}, {"id": ""}, {"id": "b"}]
    with (
        patch("app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mm),
        patch(
            "app.mod_sdk.platform_shell.build_platform_shell_payload",
            return_value={"mods": 2},
        ) as build,
    ):
        out = await ps.platform_shell_capabilities()
    assert out["success"] is True
    build.assert_called_once_with(["a", "b"])
