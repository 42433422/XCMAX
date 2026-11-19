from modstore_server.app_config_api import api_app_config


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
