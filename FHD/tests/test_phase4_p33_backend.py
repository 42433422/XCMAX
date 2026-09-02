"""COVERAGE_RAMP Phase 4 round 33: xcmax employee packs + client shell session."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

from app.infrastructure.auth.client_shell_session import (
    ADMIN_SHELL,
    attach_session_cookie,
    client_shell_from_request,
    resolve_session_id_from_request,
    session_cookie_name_for_request,
    session_cookie_name_for_shell,
)


def _make_request(*, shell: str = "enterprise", cookie_header: str = "") -> Request:
    hdrs: list[tuple[bytes, bytes]] = [(b"x-xcmax-client-shell", shell.encode())]
    if cookie_header:
        hdrs.append((b"cookie", cookie_header.encode()))
    scope = {
        "type": "http",
        "headers": hdrs,
        "method": "GET",
        "path": "/",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def test_collect_employee_pack_modules_reads_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.fastapi_routes import xcmax_admin as admin

    mods_root = Path("/tmp/mods")
    mgr = MagicMock()
    mgr.mods_root = mods_root

    class _Registry:
        def list_packs(self):
            return [{"id": "pack-a", "name": "Pack A", "version": "2.0.0"}]

    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: mgr,
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.employee_registry.EmployeeRegistry",
        lambda root: _Registry(),
    )
    rows = admin._collect_employee_pack_modules()
    assert any(r.get("module_id") == "pack-a" for r in rows)
    assert rows[0].get("source") == "employee"


def test_collect_employee_pack_modules_empty_when_no_mgr(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.fastapi_routes import xcmax_admin as admin

    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: None,
    )
    assert admin._collect_employee_pack_modules() == []


def test_client_shell_session_cookie_names() -> None:
    admin_req = _make_request(shell="admin")
    ent_req = _make_request(shell="enterprise")
    assert session_cookie_name_for_request(admin_req) == "admin_session_id"
    assert session_cookie_name_for_request(ent_req) == "session_id"
    assert session_cookie_name_for_shell(ADMIN_SHELL) == "admin_session_id"
    assert client_shell_from_request(admin_req) == ADMIN_SHELL


def test_resolve_session_id_from_split_cookies() -> None:
    req = _make_request(
        shell="admin",
        cookie_header="admin_session_id=adm123; session_id=ent456",
    )
    assert resolve_session_id_from_request(req) == "adm123"
    ent_req = _make_request(
        shell="enterprise",
        cookie_header="admin_session_id=adm123; session_id=ent456",
    )
    assert resolve_session_id_from_request(ent_req) == "ent456"


def test_attach_session_cookie_uses_shell_name() -> None:
    response = MagicMock()
    req = _make_request(shell="enterprise", cookie_header="")
    attach_session_cookie(response, "sid-ent", req)
    response.set_cookie.assert_called_once()
    kwargs = response.set_cookie.call_args.kwargs
    assert kwargs.get("key") == "session_id"
    assert kwargs.get("value") == "sid-ent"
