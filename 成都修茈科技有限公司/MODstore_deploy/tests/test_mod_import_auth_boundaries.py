"""An entitlement is not permission to replace the shared executable Mod library."""

from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server.api import auth_deps, catalog
from modstore_server.api.csrf import CSRFMiddleware
from modstore_server.application.auth import AuthApplicationService, AuthenticationError


@pytest.fixture
def importer(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "0")
    users = {
        "Bearer member": SimpleNamespace(id=8, is_admin=False),
        "Bearer admin": SimpleNamespace(id=7, is_admin=True),
    }

    def resolve(_self, token):
        if token not in users:
            raise AuthenticationError("synthetic invalid credential")
        return users[token]

    monkeypatch.setattr(AuthApplicationService, "current_user_from_authorization", resolve)
    monkeypatch.setattr(auth_deps, "user_owns_mod", lambda *_: True)
    library = tmp_path / "library"
    monkeypatch.setattr(catalog.library_paths, "lib", lambda: library)
    publish = Mock(wraps=catalog.import_zip)
    register = Mock()
    monkeypatch.setattr(catalog, "import_zip", publish)
    monkeypatch.setattr(catalog, "add_user_mod", register)
    app = FastAPI()
    app.include_router(catalog.router)
    app.add_middleware(CSRFMiddleware)
    payload = io.BytesIO()
    manifest = {
        "id": "synthetic",
        "name": "Synthetic",
        "version": "1",
        "backend": {"entry": "blueprints", "init": "mod_init"},
        "frontend": {"routes": "frontend/routes.js"},
    }
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("synthetic/manifest.json", json.dumps(manifest))
    with TestClient(app) as client:
        yield client, payload.getvalue(), publish, register, library


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"Cookie": "csrf_token=t", "X-CSRF-Token": "t"}, 401),
        (
            {
                "Authorization": "Bearer forged",
                "Cookie": "csrf_token=t",
                "X-CSRF-Token": "t",
            },
            401,
        ),
        ({"Authorization": "Bearer member"}, 403),
        ({"Cookie": "is_admin=true; csrf_token=t"}, 403),
    ],
)
def test_untrusted_or_entitled_member_cannot_import(importer, headers, expected):
    client, payload, publish, register, library = importer
    response = client.post(
        "/api/mods/import?replace=true&is_admin=true&user_id=7",
        files={"file": ("synthetic.zip", payload, "application/zip")},
        headers=headers,
    )
    assert response.status_code == expected
    publish.assert_not_called()
    register.assert_not_called()
    assert not library.exists()


def test_admin_can_import_valid_synthetic_mod(importer):
    client, payload, publish, register, library = importer
    response = client.post(
        "/api/mods/import",
        headers={"Authorization": "Bearer admin"},
        files={"file": ("synthetic.zip", payload, "application/zip")},
    )
    assert response.status_code == 200, response.text
    assert (library / "synthetic/manifest.json").is_file()
    register.assert_called_once_with(7, "synthetic")
