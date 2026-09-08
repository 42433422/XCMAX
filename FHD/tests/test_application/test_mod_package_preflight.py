"""Signed real ZIP preflight through logged-in HTTP, without installing code."""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.application import mod_package_preflight as preflight
from app.application.aiopen.service import AIOPEN_STATE, _tool_api_call
from app.infrastructure.mods import mod_manager, registry, trusted_keys
from app.infrastructure.mods.manifest import ModMetadata
from app.infrastructure.mods.package_signing import sign_members
from tests.test_application.test_aiopen_api_execution import application as application
from tests.test_application.test_aiopen_api_execution import caller
from tests.test_application.test_aiopen_api_execution import host as host


@pytest.fixture
def package_source(application, tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app.fastapi_routes.mod_store_routes import router

    app, _ = application
    app.include_router(router, prefix="/api/mod-store")
    key = Ed25519PrivateKey.generate()
    private = tmp_path / "test.pem"
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    monkeypatch.setattr(trusted_keys, "TRUSTED_MOD_PUBLIC_KEYS_PEM", (public,))
    monkeypatch.delenv("XCAGI_MOD_PUBLIC_KEY", raising=False)
    manager = mod_manager.ModManager(mods_root=str(tmp_path / "mods"))
    monkeypatch.setattr(mod_manager, "get_mod_manager", lambda: manager)
    local = registry.ModRegistry()
    local.register_mod(ModMetadata(id="mod-a", name="A", version="1.0.0.1"))
    local.register_mod(ModMetadata(id="mod-b", name="B", version="99.0"))
    monkeypatch.setattr(registry, "get_mod_registry", lambda: local)
    monkeypatch.setattr(
        "app.infrastructure.mods.install_receipts.read_verified_install", lambda *_: None
    )
    state = {
        "id": "candidate",
        "name": "Candidate",
        "version": "1.0.0",
        "dependencies": {"mod-a": ">=1.0.0.1"},
    }
    downloads = []

    async def download(path, dest, **kwargs):
        downloads.append(dest)
        assert path == "/packages/candidate/1.0.0/download"
        assert kwargs["max_bytes"] == 64 * 1024 * 1024
        manifest = {k: v for k, v in state.items() if not k.startswith("_")}
        members = [("manifest.json", json.dumps(manifest).encode())]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, value in members:
                archive.writestr(name, value)
            if not state.get("_unsigned"):
                archive.writestr(
                    "META-INF/signature.json", sign_members(members, manifest, private)
                )
        dest.write_bytes(buffer.getvalue())

    monkeypatch.setattr(preflight, "catalog_download_to", download)
    return app, state, downloads, local


def test_signed_dependency_preflight_uses_actual_account_entitlements(package_source):
    app, state, downloads, local = package_source
    with TestClient(app) as client:
        path = "/api/mod-store/dependencies?package_file=candidate:1.0.0"
        assert client.get(path).status_code == 401
        assert not downloads
        headers = {"X-Session-ID": "login-3"}
        result = client.get(path, headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["data"]["can_install"] is True
        state["dependencies"] = {"mod-a": ">=1.0.0.2", "mod-b": "*", "xcagi": ">=1.0.0.2"}
        rows = client.get(path, headers=headers).json()["data"]
        assert not rows["can_install"]
        assert [row["status"] for row in rows["missing"]] == [
            "incompatible",
            "missing",
            "incompatible",
        ]
        assert rows["missing"][1]["installed_version"] is None
        valid = client.get(path.replace("dependencies?", "validate?"), headers=headers)
        assert valid.json()["data"]["signature_verified"] is True
        assert valid.json()["data"]["installed"] is False
        assert not local.get_mod_metadata("candidate")
    assert all(not file.exists() and not file.parent.exists() for file in downloads)


@pytest.mark.parametrize(
    "change",
    [
        {"id": "different"},
        {"version": "2.0"},
        {"_unsigned": True},
        {"dependencies": "invalid"},
        {"dependencies": {"mod-a": 1}},
    ],
)
def test_invalid_or_wrong_identity_packages_are_rejected(package_source, change):
    app, state, downloads, _ = package_source
    state.update(change)
    with TestClient(app) as client:
        response = client.get(
            "/api/mod-store/validate?package_file=candidate:1.0.0",
            headers={"X-Session-ID": "login-3"},
        )
        assert response.status_code == 422, response.text
    assert all(not file.exists() for file in downloads)


@pytest.mark.parametrize(
    "value", ["", "candidate", "../candidate:1.0", "https://x:1.0", "candidate:latest"]
)
def test_preflight_does_not_accept_paths_or_unspecified_versions(package_source, value):
    app, _, downloads, _ = package_source
    with TestClient(app) as client:
        response = client.get(
            "/api/mod-store/dependencies",
            params={"package_file": value},
            headers={"X-Session-ID": "login-3"},
        )
        assert response.status_code == 400, response.text
    assert not downloads


def test_preflight_timeout_removes_partial_download(package_source, monkeypatch):
    app, _, downloads, _ = package_source

    async def timeout(path, dest, **kwargs):
        downloads.append(dest)
        dest.write_bytes(b"partial")
        raise TimeoutError("synthetic timeout")

    monkeypatch.setattr(preflight, "catalog_download_to", timeout)
    with TestClient(app) as client:
        response = client.get(
            "/api/mod-store/validate?package_file=candidate:1.0.0",
            headers={"X-Session-ID": "login-3"},
        )
        assert response.status_code == 504
    assert all(not file.parent.exists() for file in downloads)


@pytest.mark.asyncio
async def test_catalog_stream_download_enforces_limit(tmp_path, monkeypatch):
    import httpx
    from fastapi import HTTPException

    from app.infrastructure.mods import catalog_client

    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"abcdef"))
    monkeypatch.setattr(
        catalog_client.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    target = tmp_path / "bounded.zip"
    with pytest.raises(HTTPException) as error:
        await catalog_client.catalog_download_to("/packages/a/1/download", target, max_bytes=5)
    assert error.value.status_code == 413
    assert target.stat().st_size <= 5
    await catalog_client.catalog_download_to("/packages/a/1/download", target, max_bytes=6)
    assert target.read_bytes() == b"abcdef"


def test_ai_api_bridge_returns_verified_preflight_and_rejects_bad_package(
    package_source, monkeypatch
):
    app, state, _, _ = package_source
    monkeypatch.setitem(AIOPEN_STATE["whitelist"], "/api/mod-store", True)
    with caller({"X-Session-ID": "login-3"}):
        args = {"method": "GET", "path": "/api/mod-store/validate?package_file=candidate:1.0.0"}
        result = _tool_api_call(app, args)
        assert result["success"], result
        assert result["data"]["data"]["signature_verified"]
        state["id"] = "wrong-package"
        assert not _tool_api_call(app, args)["success"]


def test_download_returns_signed_zip_without_installing(package_source):
    app, state, downloads, local = package_source
    path = "/api/mod-store/package/candidate:1.0.0/download"
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        assert not downloads
        result = client.get(path, headers={"X-Session-ID": "login-3"})
        assert result.status_code == 200, result.text
        assert result.headers["content-type"] == "application/zip"
        assert result.headers["cache-control"] == "no-store"
        assert "candidate-1.0.0.zip" in result.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            assert json.loads(archive.read("manifest.json"))["id"] == "candidate"
            assert "META-INF/signature.json" in archive.namelist()
        assert local.get_mod_metadata("candidate") is None
        state["id"] = "wrong"
        assert client.get(path, headers={"X-Session-ID": "login-3"}).status_code == 422
        state["id"] = "candidate"
        state["_unsigned"] = True
        assert client.get(path, headers={"X-Session-ID": "login-3"}).status_code == 422
    assert all(not file.parent.exists() for file in downloads)


def test_ai_download_exports_verified_package_to_current_owner(package_source, monkeypatch):
    from app.application.aiopen import api_artifacts

    app, _, downloads, _ = package_source
    monkeypatch.setitem(AIOPEN_STATE["whitelist"], "/api/mod-store", True)
    with caller({"X-Session-ID": "login-3"}):
        result = _tool_api_call(
            app, {"method": "GET", "path": "/api/mod-store/package/candidate:1.0.0/download"}
        )
        assert result["success"], result
        content, _ = api_artifacts.read_api_export(result["artifacts"][0]["artifact_id"])
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert json.loads(archive.read("manifest.json"))["version"] == "1.0.0"
    with caller({"X-Session-ID": "login-4"}):
        with pytest.raises(api_artifacts.ApiArtifactError):
            api_artifacts.read_api_export(result["artifacts"][0]["artifact_id"])
    assert all(not file.parent.exists() for file in downloads)
