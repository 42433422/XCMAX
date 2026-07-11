"""pairing_helpers 单元测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.fastapi_routes.mobile_extensions import pairing_helpers as ph


def _mock_request(
    host_header: str = "127.0.0.1:5011",
    forwarded_host: str = "",
) -> SimpleNamespace:
    headers: dict[str, str] = {"host": host_header}
    if forwarded_host:
        headers["x-forwarded-host"] = forwarded_host
    return SimpleNamespace(headers=headers)


class TestPairingIssuePort:
    def test_requested_port_wins_over_vite_proxy(self):
        assert ph._pairing_issue_port(_mock_request("127.0.0.1:5011"), 17500) == 17500

    def test_skips_vite_dev_port_for_runtime_api_port(self):
        with patch.object(ph, "_read_runtime_api_port", return_value=17500):
            assert ph._pairing_issue_port(_mock_request("127.0.0.1:5011"), 0) == 17500

    def test_infers_non_vite_request_port(self):
        assert ph._pairing_issue_port(_mock_request("127.0.0.1:5112"), 0) == 5112


class TestPairingReachablePort:
    def test_loopback_backend_uses_vite_proxy_port(self):
        with patch.object(ph, "_backend_listens_loopback_only", return_value=True):
            port = ph._pairing_reachable_port(_mock_request("127.0.0.1:5011"), 17500)
        assert port == 5011

    def test_public_backend_keeps_api_port(self):
        with patch.object(ph, "_backend_listens_loopback_only", return_value=False):
            port = ph._pairing_reachable_port(_mock_request("127.0.0.1:5112"), 17500)
        assert port == 17500

    def test_public_backend_uses_vite_proxy_when_request_via_dev_port(self):
        with patch.object(ph, "_backend_listens_loopback_only", return_value=False):
            port = ph._pairing_reachable_port(_mock_request("127.0.0.1:5011"), 17500)
        assert port == 5011

    def test_enrich_payload_uses_reachable_port(self):
        payload = {
            "host": "192.168.10.2",
            "port": 17500,
            "nonce": "abc",
            "shortCode": "123456",
            "exp": 1,
        }
        with patch.object(ph, "_backend_listens_loopback_only", return_value=True):
            data = ph._enrich_pairing_payload(payload, _mock_request("127.0.0.1:5011"))
        assert data["port"] == 5011
        assert data["api_base_url"] == "http://192.168.10.2:5011/"
        assert data["qr_json"]["port"] == 5011
        assert data["qr_json"]["api_base_url"] == "http://192.168.10.2:5011/"


class TestRequestHostPortForwarded:
    def test_prefers_x_forwarded_host_over_host(self):
        # Vite changeOrigin 改写 Host 为后端地址，X-Forwarded-Host 保留手机真实访问端口
        req = _mock_request("127.0.0.1:17500", forwarded_host="192.168.10.2:5011")
        assert ph._request_host_port(req) == 5011

    def test_falls_back_to_host_when_no_forwarded(self):
        req = _mock_request("127.0.0.1:5011")
        assert ph._request_host_port(req) == 5011

    def test_reachable_port_uses_forwarded_host(self):
        # 模拟 vite 代理：Host=后端:17500，X-Forwarded-Host=手机访问的:5011
        with patch.object(ph, "_backend_listens_loopback_only", return_value=False):
            req = _mock_request("127.0.0.1:17500", forwarded_host="192.168.10.2:5011")
            port = ph._pairing_reachable_port(req, 17500)
        assert port == 5011
