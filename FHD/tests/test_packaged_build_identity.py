"""Real package metadata → health and login receipt, using only isolated fixture paths."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.build_identity import build_identity

SHA = "70da5cdf6ca18abc44eb5370734314ca6663fb8f"
VERSION = "1.0.0.1"


@pytest.fixture
def packaged_identity(tmp_path, monkeypatch):
    for name in (
        "XCAGI_GIT_SHA",
        "FHD_GIT_SHA",
        "GIT_SHA",
        "XCAGI_BUILD_SHA",
        "XCMAX_PRODUCT_VERSION",
        "XCAGI_VERSION",
        "APP_VERSION",
        "XCAGI_RELEASE_ID",
        "XCAGI_DESKTOP_RESOURCES",
    ):
        monkeypatch.delenv(name, raising=False)
    resources = tmp_path / "XCAGI.app" / "Contents" / "Resources"
    internal = resources / "backend" / "_internal"
    internal.mkdir(parents=True)
    monkeypatch.setenv("FHD_DEPLOY_ROOT", str(internal))
    generator = (
        Path(__file__).resolve().parents[1] / "scripts/package/generate-desktop-build-info.py"
    )
    runpy.run_path(str(generator))["write_build_info"](
        version=VERSION, git_sha=SHA, output=resources / "build-info.json"
    )
    return resources


def test_electron_resources_metadata_appears_in_real_health_route(
    packaged_identity, tmp_path, monkeypatch
):
    from app.fastapi_routes.mounts.health import register_health_routes

    monkeypatch.setenv("XCAGI_DESKTOP_RESOURCES", str(packaged_identity))
    # A stale, user-writable metadata copy must not participate in release identity.
    user_data = tmp_path / "user-data"
    user_data.mkdir()
    (user_data / "build-info.json").write_text(json.dumps({"gitSha": "f" * 40, "version": "wrong"}))
    monkeypatch.setenv("XCAGI_DATA_DIR", str(user_data))
    monkeypatch.chdir(user_data)
    app = FastAPI()
    register_health_routes(app)
    with TestClient(app) as client:
        response = client.get("/api/health?lite=true")
    payload = response.json()
    metadata = json.loads((packaged_identity / "build-info.json").read_text())
    assert payload["git_sha"] == metadata["gitSha"] == SHA
    assert payload["release_id"] == metadata["releaseId"]
    assert payload["build"]["product_version"] == metadata["version"]
    assert payload["build"]["built_at"] == metadata["builtAt"]


@pytest.mark.asyncio
async def test_normal_login_receipt_and_health_share_packaged_identity(
    packaged_identity, tmp_path, monkeypatch
):
    from app.application.desktop_delivery_receipt import report_desktop_login_delivery_receipt

    monkeypatch.setenv("XCAGI_DESKTOP_RESOURCES", str(packaged_identity))
    user_data = tmp_path / "user-data"
    user_data.mkdir()
    (user_data / "installation-id").write_text("isolated-installation-00001")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(user_data))
    proxy = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr("app.fastapi_routes.market_account._proxy_json", proxy)
    result = await report_desktop_login_delivery_receipt("fixture-market-token")
    assert result["reported"] is True
    identity = build_identity()
    body = proxy.call_args.kwargs["json_body"]
    assert body["installed_build_sha"] == body["target_build_sha"] == identity["git_sha"] == SHA
    assert (
        body["installed_version"]
        == body["target_version"]
        == identity["product_version"]
        == VERSION
    )


@pytest.mark.parametrize("subdirectory", ["", "_internal", "xcagi-backend"])
@pytest.mark.parametrize("executable", ["xcagi-backend", "xcagi-backend.exe"])
def test_frozen_backend_without_electron_env_uses_adjacent_resources(
    packaged_identity, monkeypatch, subdirectory, executable
):
    binary = packaged_identity / "backend" / subdirectory / executable
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(binary))
    assert build_identity()["git_sha"] == SHA


def test_existing_server_stamp_and_environment_priority_remain(packaged_identity, monkeypatch):
    monkeypatch.setenv("XCAGI_DESKTOP_RESOURCES", str(packaged_identity))
    stamp = packaged_identity / "backend/_internal/.build-identity.json"
    stamp.write_text(
        json.dumps({"git_sha": "a" * 40, "version": "2.0.0.0", "built_at": "server-stamp"})
    )
    identity = build_identity()
    assert identity["git_sha"] == "a" * 40
    assert identity["built_at"] == "server-stamp"
    monkeypatch.setenv("GIT_SHA", "b" * 40)
    monkeypatch.setenv("FHD_GIT_SHA", "c" * 40)
    monkeypatch.setenv("XCAGI_GIT_SHA", "d" * 40)
    monkeypatch.setenv("XCMAX_PRODUCT_VERSION", "3.0.0.0")
    assert build_identity()["git_sha"] == "d" * 40
    assert build_identity()["product_version"] == "3.0.0.0"


def test_explicit_identity_override_keeps_desktop_release_id_consistent(
    packaged_identity, monkeypatch
):
    monkeypatch.setenv("XCAGI_DESKTOP_RESOURCES", str(packaged_identity))
    monkeypatch.setenv("XCAGI_GIT_SHA", "a" * 40)
    monkeypatch.setenv("XCMAX_PRODUCT_VERSION", "2.0.0.0")
    assert build_identity()["release_id"] == "xcagi-2.0.0.0-" + "a" * 40
    monkeypatch.setenv("XCAGI_RELEASE_ID", "explicit-release")
    assert build_identity()["release_id"] == "explicit-release"


def test_development_does_not_read_checked_in_desktop_metadata(packaged_identity, monkeypatch):
    monkeypatch.setattr("app.build_identity._local_git_sha", lambda: "e" * 40)
    monkeypatch.chdir(packaged_identity)
    assert build_identity()["git_sha"] == "e" * 40
    assert build_identity()["product_version"] == ""


@pytest.mark.parametrize(
    "contents",
    [
        "not-json",
        "[]",
        '{"gitSha":"short","version":"1.0.0.1"}',
        json.dumps({"gitSha": SHA, "version": VERSION, "releaseId": "different-sha"}),
        json.dumps({"gitSha": SHA, "version": {"invalid": True}}),
    ],
)
def test_invalid_packaged_metadata_cannot_fall_back_to_host_checkout(
    packaged_identity, monkeypatch, contents
):
    (packaged_identity / "build-info.json").write_text(contents)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(packaged_identity / "backend/xcagi-backend"))
    run = AsyncMock(side_effect=AssertionError("frozen identity must not call host git"))
    monkeypatch.setattr("app.build_identity.subprocess.run", run)
    assert build_identity()["git_sha"] == ""
    run.assert_not_called()


def test_legacy_backend_location_and_build_sha_alias(packaged_identity, monkeypatch):
    (packaged_identity / "build-info.json").unlink()
    (packaged_identity / "backend/build-info.json").write_text(
        json.dumps({"buildSha": SHA, "version": VERSION, "builtAt": "legacy-timestamp"})
    )
    monkeypatch.setenv("XCAGI_DESKTOP_RESOURCES", str(packaged_identity))
    identity = build_identity()
    assert identity["git_sha"] == SHA
    assert identity["built_at"] == "legacy-timestamp"
