"""Sandbox uploads must enforce ownership and server-configured destinations."""

from __future__ import annotations

import io
import zipfile
from email.parser import BytesParser
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modman.repo_config import RepoConfig
from modstore_server import sandbox_api
from modstore_server.api import auth_deps
from modstore_server.api.csrf import CSRFMiddleware
from modstore_server.application.auth import AuthApplicationService, AuthenticationError
from modstore_server.infrastructure import library_paths

BACKEND = "https://runner.example.test/base"
ORIGIN = "https://market.example.test"
OWNER = {"Authorization": "Bearer owner-test"}
ADMIN = {"Authorization": "Bearer admin-test"}


@pytest.fixture()
def sandbox(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "0")
    monkeypatch.setenv("MODSTORE_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("MODSTORE_SANDBOX_PUSH_BEARER", "synthetic-sandbox-bearer")
    monkeypatch.setattr(library_paths, "cfg", lambda: RepoConfig(xcagi_backend_url=BACKEND))
    users = {
        "Bearer owner-test": SimpleNamespace(id=8, is_admin=False),
        "Bearer admin-test": SimpleNamespace(id=7, is_admin=True),
    }

    def resolve(_self, authorization):
        if authorization not in users:
            raise AuthenticationError("invalid synthetic credential")
        return users[authorization]

    monkeypatch.setattr(AuthApplicationService, "current_user_from_authorization", resolve)
    monkeypatch.setattr(auth_deps, "user_owns_mod", lambda uid, mid: uid == 8 and mid == "owned")
    for mid in ("owned", "other"):
        folder = tmp_path / mid
        folder.mkdir()
        (folder / "fixture.txt").write_text(f"synthetic {mid}")
    lookup = Mock(side_effect=lambda mid: tmp_path / mid)
    monkeypatch.setattr(library_paths, "mod_dir", lookup)
    headers = Mock(wraps=sandbox_api._sandbox_install_headers)
    monkeypatch.setattr(sandbox_api, "_sandbox_install_headers", headers)
    calls, settings = [], []
    response = {"status": 200, "headers": {}}

    def transport(request):
        calls.append(request)
        return httpx.Response(
            response["status"], headers=response["headers"], json={"installed": True}
        )

    def client(**kwargs):
        settings.append(kwargs)
        return httpx.Client(transport=httpx.MockTransport(transport), **kwargs)

    monkeypatch.setattr(sandbox_api, "httpx", SimpleNamespace(Client=client))
    app = FastAPI()
    app.include_router(sandbox_api.router)
    app.add_middleware(CSRFMiddleware)
    with TestClient(app) as api:
        yield SimpleNamespace(
            api=api,
            calls=calls,
            settings=settings,
            lookup=lookup,
            headers=headers,
            response=response,
        )


def assert_no_effects(sandbox):
    sandbox.lookup.assert_not_called()
    sandbox.headers.assert_not_called()
    assert sandbox.calls == []
    assert sandbox.settings == []


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"Cookie": "csrf_token=test", "X-CSRF-Token": "test"}, 401),
        ({"Authorization": "Bearer forged"}, 401),
        ({"Authorization": "Bearer forged", "Cookie": "csrf_token=test"}, 403),
        (
            {
                "Authorization": "Bearer forged",
                "Cookie": "csrf_token=test",
                "X-CSRF-Token": "test",
            },
            401,
        ),
    ],
)
def test_auth_and_csrf_reject_before_any_effect(sandbox, headers, status):
    result = sandbox.api.post(
        "/api/sandbox/push-and-test",
        headers=headers,
        json={"host_url": BACKEND, "mod_id": "owned"},
    )
    assert result.status_code == status
    assert_no_effects(sandbox)


def test_nonowner_rejected_before_library_read(sandbox):
    result = sandbox.api.post(
        "/api/sandbox/push-and-test",
        headers=OWNER,
        json={"host_url": BACKEND, "mod_id": "other"},
    )
    assert result.status_code == 403
    assert_no_effects(sandbox)


@pytest.mark.parametrize("route", ["connect", "push-and-test"])
@pytest.mark.parametrize("auth", [OWNER, ADMIN])
@pytest.mark.parametrize(
    "target",
    [
        "https://attacker.invalid",
        "https://runner.example.test.attacker.invalid/base",
        "http://runner.example.test/base",
        "https://runner.example.test:444/base",
        "https://runner.example.test/sibling",
        ORIGIN + "/sandbox/evil",
        "https://user@runner.example.test/base",
        BACKEND + "?override=1",
        BACKEND + "#fragment",
        "//attacker.invalid",
        "file:///tmp/fixture",
        ORIGIN + "/sandbox\\evil",
    ],
)
def test_untrusted_destination_rejected_before_any_effect(sandbox, route, auth, target):
    result = sandbox.api.post(
        f"/api/sandbox/{route}",
        headers=auth,
        json={"host_url": target, "mod_id": "owned"},
    )
    assert result.status_code == 403
    assert_no_effects(sandbox)


@pytest.mark.parametrize("auth,mid", [(OWNER, "owned"), (ADMIN, "other")])
@pytest.mark.parametrize(
    "target,base",
    [
        (BACKEND, BACKEND),
        (BACKEND + "/", BACKEND),
        ("/sandbox", ORIGIN + "/sandbox"),
        (ORIGIN + "/sandbox/", ORIGIN + "/sandbox"),
    ],
)
def test_authorized_upload_preserves_package_contract(sandbox, auth, mid, target, base):
    result = sandbox.api.post(
        "/api/sandbox/push-and-test",
        headers=auth,
        json={"host_url": target, "mod_id": mid},
    )
    assert result.status_code == 200
    assert result.json() == {
        "ok": True,
        "mod_id": mid,
        "install": {"installed": True},
        "sandbox_url": base + "/?sandbox=1",
    }
    assert len(sandbox.calls) == 1
    request = sandbox.calls[0]
    assert str(request.url) == base + "/api/mod-store/install"
    assert request.headers["Authorization"] == "Bearer synthetic-sandbox-bearer"
    assert sandbox.settings[0]["follow_redirects"] is False
    multipart = BytesParser().parsebytes(
        b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content
    )
    upload = multipart.get_payload()[0]
    assert upload.get_filename() == mid + ".xcmod"
    with zipfile.ZipFile(io.BytesIO(upload.get_payload(decode=True))) as archive:
        assert archive.namelist() == ["fixture.txt"]
        assert archive.read("fixture.txt") == f"synthetic {mid}".encode()


@pytest.mark.parametrize("status", [307, 308])
def test_install_redirect_does_not_forward_package_or_credentials(sandbox, status):
    sandbox.response.update(status=status, headers={"Location": "https://attacker.invalid/install"})
    result = sandbox.api.post(
        "/api/sandbox/push-and-test",
        headers=OWNER,
        json={"host_url": BACKEND, "mod_id": "owned"},
    )
    assert result.json()["ok"] is False
    assert len(sandbox.calls) == 1
    assert sandbox.settings[0]["follow_redirects"] is False


def test_connect_and_host_status_use_configured_backend(sandbox):
    result = sandbox.api.post("/api/sandbox/connect", headers=OWNER, json={"host_url": BACKEND})
    assert result.json()["ok"] is True
    assert result.json()["host_url"] == BACKEND
    result = sandbox.api.get("/api/sandbox/host-status", headers=OWNER)
    assert result.json() == {"ok": True, "data": {"installed": True}}
    assert [str(r.url) for r in sandbox.calls] == [
        BACKEND + "/api/health",
        BACKEND + "/api/mods/loading-status",
        BACKEND + "/api/mods/loading-status",
    ]
    assert all(s["follow_redirects"] is False for s in sandbox.settings)


def test_unicode_configured_host_does_not_authorize_distinct_ascii_host(sandbox, monkeypatch):
    monkeypatch.setattr(
        library_paths,
        "cfg",
        lambda: RepoConfig(xcagi_backend_url="https://faß.example/base"),
    )
    result = sandbox.api.post(
        "/api/sandbox/push-and-test",
        headers=OWNER,
        json={"host_url": "https://fass.example/base", "mod_id": "owned"},
    )
    assert result.status_code == 403
    assert_no_effects(sandbox)


@pytest.mark.parametrize("target", ["https://faß.example/base", "https://xn--fa-hia.example/base"])
def test_unicode_configured_host_uses_httpx_idna_identity(sandbox, monkeypatch, target):
    monkeypatch.setattr(
        library_paths,
        "cfg",
        lambda: RepoConfig(xcagi_backend_url="https://faß.example/base"),
    )
    result = sandbox.api.post(
        "/api/sandbox/push-and-test",
        headers=OWNER,
        json={"host_url": target, "mod_id": "owned"},
    )
    assert result.json()["ok"] is True
    assert str(sandbox.calls[0].url) == "https://xn--fa-hia.example/base/api/mod-store/install"
