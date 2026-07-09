"""企业端 / 管理端分壳会话 Cookie 隔离。"""

from __future__ import annotations

from starlette.requests import Request

from app.infrastructure.auth.client_shell_session import (
    ADMIN_SHELL,
    ENTERPRISE_SHELL,
    attach_session_cookie,
    client_shell_from_headers,
    client_shell_from_request,
    resolve_session_id_from_request,
    session_cookie_name_for_request,
    session_cookie_name_for_shell,
)
from app.infrastructure.auth.dependencies import session_id_from_request as dep_session_id


def _make_request(
    *,
    shell: str | None = "enterprise",
    cookie_header: str = "",
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    hdrs: list[tuple[bytes, bytes]] = []
    if shell is not None:
        hdrs.append((b"x-xcmax-client-shell", shell.encode()))
    if cookie_header:
        hdrs.append((b"cookie", cookie_header.encode()))
    if extra_headers:
        hdrs.extend(extra_headers)
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
    # 主读路径 dependencies 与 resolve 一致，双壳互不串
    assert dep_session_id(admin_req) == "adm-sid"
    assert dep_session_id(ent_req) == "ent-sid"


def test_attach_session_cookie_writes_separate_names() -> None:
    from fastapi.responses import JSONResponse

    admin_req = _make_request(shell="admin")
    ent_req = _make_request(shell="enterprise")
    admin_resp = attach_session_cookie(JSONResponse({}), "sid-admin", admin_req)
    ent_resp = attach_session_cookie(JSONResponse({}), "sid-ent", ent_req)
    assert admin_resp.headers.get("set-cookie", "").startswith("admin_session_id=")
    assert ent_resp.headers.get("set-cookie", "").startswith("session_id=")
    assert session_cookie_name_for_shell(ADMIN_SHELL) == "admin_session_id"


def test_shell_from_forwarded_host_5011() -> None:
    req = _make_request(
        shell=None,
        extra_headers=[(b"x-forwarded-host", b"127.0.0.1:5011")],
    )
    assert client_shell_from_request(req) == ADMIN_SHELL


def test_shell_from_admin_path_referer() -> None:
    req = _make_request(
        shell=None,
        extra_headers=[(b"referer", b"http://127.0.0.1:17500/admin/xcmax-admin")],
    )
    assert client_shell_from_request(req) == ADMIN_SHELL


def test_shell_headers_helper_matches_request() -> None:
    assert client_shell_from_headers({"X-XCMAX-Client-Shell": "admin"}) == ADMIN_SHELL
    assert client_shell_from_headers({"origin": "http://127.0.0.1:5011"}) == ADMIN_SHELL
    assert client_shell_from_headers({}) == ENTERPRISE_SHELL


def test_shell_aliases_desktop_web() -> None:
    assert client_shell_from_headers({"X-XCMAX-Client-Shell": "desktop"}) == ENTERPRISE_SHELL
    assert client_shell_from_headers({"X-XCMAX-Client-Shell": "web"}) == ENTERPRISE_SHELL


def test_header_get_tolerates_broken_mapping() -> None:
    class BrokenHeaders:
        def get(self, *_args, **_kwargs):
            raise TypeError("no get")

        def items(self):
            raise AttributeError("no items")

    assert client_shell_from_headers(BrokenHeaders()) == ENTERPRISE_SHELL
    assert client_shell_from_headers(None) == ENTERPRISE_SHELL


def test_attach_empty_sid_unchanged() -> None:
    from fastapi.responses import JSONResponse

    req = _make_request(shell="enterprise")
    resp = JSONResponse({"ok": True})
    assert attach_session_cookie(resp, "", req) is resp
    assert attach_session_cookie(resp, None, req) is resp


def test_clear_session_cookie_by_shell() -> None:
    from fastapi.responses import JSONResponse

    from app.infrastructure.auth.client_shell_session import clear_session_cookie

    admin_req = _make_request(shell="admin")
    resp = clear_session_cookie(JSONResponse({}), admin_req)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "admin_session_id=" in set_cookie


def test_resolve_session_id_bearer_when_allowed(monkeypatch) -> None:
    monkeypatch.setenv("FHD_ALLOW_BEARER_AS_SESSION_ID", "1")
    req = _make_request(
        shell="enterprise",
        extra_headers=[(b"authorization", b"Bearer bearer-sid")],
    )
    assert resolve_session_id_from_request(req) == "bearer-sid"


def test_resolve_session_id_x_session_header() -> None:
    req = _make_request(
        shell="enterprise",
        extra_headers=[(b"x-session-id", b"hdr-only")],
    )
    assert resolve_session_id_from_request(req) == "hdr-only"


def test_session_cookie_name_from_headers() -> None:
    from app.infrastructure.auth.client_shell_session import session_cookie_name_from_headers

    assert session_cookie_name_from_headers({"X-XCMAX-Client-Shell": "admin"}) == "admin_session_id"
    assert session_cookie_name_from_headers({}) == "session_id"
