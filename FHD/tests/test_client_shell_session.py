"""企业端 / 管理端分壳会话 Cookie 隔离。"""

from __future__ import annotations

from starlette.requests import Request

from app.infrastructure.auth.client_shell_session import (
    ADMIN_SHELL,
    attach_session_cookie,
    client_shell_from_request,
    resolve_session_id_from_request,
    session_cookie_name_for_request,
    session_cookie_name_for_shell,
)


def _make_request(
    *,
    shell: str = "enterprise",
    cookie_header: str = "",
) -> Request:
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


def test_session_cookie_name_by_shell_header() -> None:
    admin_req = _make_request(shell="admin")
    ent_req = _make_request(shell="enterprise")
    assert session_cookie_name_for_request(admin_req) == "admin_session_id"
    assert session_cookie_name_for_request(ent_req) == "session_id"
    assert client_shell_from_request(admin_req) == ADMIN_SHELL


def test_resolve_session_id_uses_shell_cookie() -> None:
    admin_req = _make_request(
        shell="admin",
        cookie_header="admin_session_id=adm-sid; session_id=ent-sid",
    )
    ent_req = _make_request(
        shell="enterprise",
        cookie_header="admin_session_id=adm-sid; session_id=ent-sid",
    )
    assert resolve_session_id_from_request(admin_req) == "adm-sid"
    assert resolve_session_id_from_request(ent_req) == "ent-sid"


def test_attach_session_cookie_writes_separate_names() -> None:
    from fastapi.responses import JSONResponse

    admin_req = _make_request(shell="admin")
    ent_req = _make_request(shell="enterprise")
    admin_resp = attach_session_cookie(JSONResponse({}), "sid-admin", admin_req)
    ent_resp = attach_session_cookie(JSONResponse({}), "sid-ent", ent_req)
    assert admin_resp.headers.get("set-cookie", "").startswith("admin_session_id=")
    assert ent_resp.headers.get("set-cookie", "").startswith("session_id=")
    assert session_cookie_name_for_shell(ADMIN_SHELL) == "admin_session_id"
