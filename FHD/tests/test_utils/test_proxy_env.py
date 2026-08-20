from __future__ import annotations

import os

from app.utils.security.proxy_env import sanitize_socks_all_proxy


def test_sanitize_clears_socks_all_proxy_without_socksio(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7890")
    monkeypatch.setenv("all_proxy", "socks5://127.0.0.1:7890")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setattr("app.utils.security.proxy_env._socksio_available", lambda: False)

    cleared = sanitize_socks_all_proxy()

    assert set(cleared) == {"ALL_PROXY", "all_proxy"}
    assert "ALL_PROXY" not in os.environ
    assert "all_proxy" not in os.environ
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7890"


def test_sanitize_keeps_socks_when_socksio_present(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7890")
    monkeypatch.setattr("app.utils.security.proxy_env._socksio_available", lambda: True)

    cleared = sanitize_socks_all_proxy()

    assert cleared == []
    assert os.environ["ALL_PROXY"] == "socks5://127.0.0.1:7890"


def test_sanitize_ignores_http_all_proxy(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("all_proxy", "http://127.0.0.1:7890")
    monkeypatch.setattr("app.utils.security.proxy_env._socksio_available", lambda: False)

    cleared = sanitize_socks_all_proxy()

    assert cleared == []
    assert os.environ["ALL_PROXY"] == "http://127.0.0.1:7890"
    assert os.environ["all_proxy"] == "http://127.0.0.1:7890"  # noqa: SIM112
