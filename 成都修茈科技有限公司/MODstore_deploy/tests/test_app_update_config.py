import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server import app_config_api as api
from modstore_server.app_config_api import api_app_config


def test_enterprise_uses_published_combined_legal_document(monkeypatch):
    monkeypatch.setenv("XCAGI_PUBLIC_BASE_URL", "https://xiu-ci.com")
    enterprise = api_app_config("android", "enterprise", 0)
    assert enterprise["privacy_url"] == "https://xiu-ci.com/privacy.html"
    assert enterprise["terms_url"] == enterprise["privacy_url"]
    personal = api_app_config("android", "personal", 0)
    assert personal["privacy_url"].endswith("/legal/privacy")
    assert personal["terms_url"].endswith("/legal/terms")


def test_ios_update_requires_published_store_metadata(monkeypatch):
    monkeypatch.delenv("XCAGI_IOS_APP_STORE_ID", raising=False)
    monkeypatch.delenv("XCAGI_IOS_LATEST_VERSION_NAME", raising=False)
    unavailable = api_app_config("ios", "enterprise", 123)
    assert unavailable["app_store_url"] == ""
    assert unavailable["latest_ios_version_name"] == ""
    assert "apk_download_url" not in unavailable

    monkeypatch.setenv("XCAGI_IOS_APP_STORE_ID", "123456")
    monkeypatch.setenv("XCAGI_IOS_LATEST_VERSION_NAME", "1.0.10")
    available = api_app_config("ios", "enterprise", 123)
    assert available["app_store_url"] == "https://apps.apple.com/app/id123456"
    assert available["latest_ios_version_name"] == "1.0.10"
    assert api_app_config("ios", "personal", 123)["app_store_url"] == ""
    assert "apk_download_url" in api_app_config("android", "enterprise", 123)


@pytest.mark.parametrize("resolver", [api._delta_manifest_path, api._profile_page_path])
@pytest.mark.parametrize("sku", ["../outside", "enterprise/../../outside", "/tmp", "", "unknown"])
def test_sku_cannot_select_a_filesystem_path(monkeypatch, resolver, sku):
    monkeypatch.delenv("XCAGI_ANDROID_DELTA_MANIFEST", raising=False)
    monkeypatch.delenv("XCAGI_PROFILE_PAGE_CONFIG", raising=False)
    with pytest.raises(ValueError, match="SKU"):
        resolver(sku)


@pytest.mark.parametrize("sku", ["enterprise", "personal"])
def test_known_sku_paths_and_operator_overrides(monkeypatch, tmp_path, sku):
    for resolver, variable, name in (
        (api._delta_manifest_path, "XCAGI_ANDROID_DELTA_MANIFEST", "android_delta_manifest.json"),
        (api._profile_page_path, "XCAGI_PROFILE_PAGE_CONFIG", "profile_page.json"),
    ):
        monkeypatch.delenv(variable, raising=False)
        assert resolver(sku) == Path("/var/www/update/releases/stable") / sku / name
        configured = tmp_path / name
        monkeypatch.setenv(variable, str(configured))
        assert resolver(sku) == configured
        with pytest.raises(ValueError, match="SKU"):
            resolver("../outside")


def test_http_config_preserves_both_skus_and_rejects_traversal(monkeypatch, tmp_path):
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"headline": "operator profile"}))
    monkeypatch.setenv("XCAGI_PROFILE_PAGE_CONFIG", str(profile))
    manifest = tmp_path / "delta.json"
    manifest.write_text(
        json.dumps(
            {
                "target_version_code": api._ANDROID_LATEST_VERSION,
                "target_version_name": api._ANDROID_LATEST_NAME,
                "patches": [{"base_version_code": 1, "patch_url": "https://updates.invalid/patch"}],
            }
        )
    )
    monkeypatch.setenv("XCAGI_ANDROID_DELTA_MANIFEST", str(manifest))
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        for sku in ("enterprise", "personal"):
            result = client.get("/app/config", params={"sku": sku, "current_version_code": 1})
            assert result.status_code == 200
            assert result.json()["sku"] == sku
            assert result.json()["profile_page"]["headline"] == "operator profile"
            assert f"/download/{sku}/" in result.json()["apk_download_url"]
            assert result.json()["apk_delta"]["patch_url"] == "https://updates.invalid/patch"
            assert result.json()["apk_delta"]["available"] is True
        for sku in ("../outside", "personal/../../", "enterprise\\outside", "unknown"):
            assert client.get("/app/config", params={"sku": sku}).status_code == 422
