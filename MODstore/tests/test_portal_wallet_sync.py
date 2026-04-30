"""portal_wallet_sync：HTTPS 校验与 JSON 解析。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from modman.constants import DEFAULT_PORTAL_PLANS_URL
from modman.repo_config import RepoConfig, resolved_portal_plans_url
from modstore_server.portal_wallet_sync import assert_safe_https_sync_url, fetch_wallet_secret


def test_repo_config_from_dict_omits_portal_fields():
    c = RepoConfig.from_dict({"library_root": "/x"})
    assert c.portal_plans_url == ""
    assert c.portal_wallet_sync_url == ""


def test_resolved_portal_plans_url_default():
    assert resolved_portal_plans_url(RepoConfig()) == DEFAULT_PORTAL_PLANS_URL


def test_resolved_portal_plans_url_custom():
    c = RepoConfig(portal_plans_url="https://staging.example/plans")
    assert resolved_portal_plans_url(c) == "https://staging.example/plans"


def test_assert_safe_rejects_http():
    with pytest.raises(ValueError, match="https"):
        assert_safe_https_sync_url("http://example.com/x")


def test_assert_safe_rejects_private_ip():
    with pytest.raises(ValueError, match="内网|loopback|链路"):
        assert_safe_https_sync_url("https://10.0.0.1/x")


def test_assert_safe_accepts_public_https():
    u = "https://example.com/path?x=1"
    assert assert_safe_https_sync_url(u) == u


def test_fetch_wallet_secret_uses_httpx_client(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"wallet_secret": "nested-secret"}}

    mock_instance = MagicMock()
    mock_instance.get.return_value = mock_resp
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_instance
    mock_cm.__exit__.return_value = None

    with patch("modstore_server.portal_wallet_sync.httpx.Client", return_value=mock_cm):
        out = fetch_wallet_secret("https://example.com/sync", "Bearer tokennnnn")

    assert out == {"ok": True, "wallet_secret": "nested-secret"}
    mock_instance.get.assert_called_once()
    _args, kwargs = mock_instance.get.call_args
    assert kwargs["headers"]["Authorization"].startswith("Bearer")
