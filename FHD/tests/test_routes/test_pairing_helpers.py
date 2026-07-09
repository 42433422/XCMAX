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
        with (
            patch.object(ph, "_backend_listens_loopback_only", return_value=True),
            patch.object(ph, "_tcp_port_is_listening", return_value=True),
        ):
            port = ph._pairing_reachable_port(_mock_request("127.0.0.1:5011"), 17500)
        assert port == 5011

    def test_loopback_backend_keeps_api_port_when_vite_down(self):
        with (
            patch.object(ph, "_backend_listens_loopback_only", return_value=True),
            patch.object(ph, "_tcp_port_is_listening", return_value=False),
        ):
            port = ph._pairing_reachable_port(_mock_request("127.0.0.1:5011"), 17500)
        assert port == 17500

    def test_public_backend_keeps_api_port(self):
        with patch.object(ph, "_backend_listens_loopback_only", return_value=False):
            port = ph._pairing_reachable_port(_mock_request("127.0.0.1:5112"), 17500)
        assert port == 17500

    def test_public_backend_uses_vite_proxy_when_request_via_dev_port(self):
        with (
            patch.object(ph, "_backend_listens_loopback_only", return_value=False),
            patch.object(ph, "_tcp_port_is_listening", return_value=True),
        ):
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
        with (
            patch.object(ph, "_backend_listens_loopback_only", return_value=True),
            patch.object(ph, "_tcp_port_is_listening", return_value=True),
        ):
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
        with (
            patch.object(ph, "_backend_listens_loopback_only", return_value=False),
            patch.object(ph, "_tcp_port_is_listening", return_value=True),
        ):
            req = _mock_request("127.0.0.1:17500", forwarded_host="192.168.10.2:5011")
            port = ph._pairing_reachable_port(req, 17500)
        assert port == 5011


class TestPairingIssuePortEnvAndDefaults:
    def test_env_port_when_no_request_port(self, monkeypatch):
        monkeypatch.setenv("XCAGI_API_PORT", "17500")
        with patch.object(ph, "_read_runtime_api_port", return_value=0):
            assert ph._pairing_issue_port(_mock_request("localhost"), 0) == 17500

    def test_default_5000_when_nothing_else(self):
        with (
            patch.object(ph, "_read_runtime_api_port", return_value=0),
            patch.dict("os.environ", {}, clear=True),
        ):
            assert ph._pairing_issue_port(_mock_request("localhost"), 0) == 5000

    def test_reachable_defaults_invalid_api_port(self):
        with patch.object(ph, "_backend_listens_loopback_only", return_value=False):
            assert ph._pairing_reachable_port(None, 0) == 5000

    def test_host_is_private_or_loopback(self):
        assert ph._host_is_private_or_loopback("192.168.1.1") is True
        assert ph._host_is_private_or_loopback("127.0.0.1") is True
        assert ph._host_is_private_or_loopback("8.8.8.8") is False
        assert ph._host_is_private_or_loopback("localhost") is True

    def test_api_base_url_strips_scheme_and_path(self):
        assert ph._pairing_api_base_url("http://192.168.1.2/foo", 0) == "http://192.168.1.2:5000/"
        assert ph._pairing_api_base_url("192.168.1.2:9999", 17500) == "http://192.168.1.2:17500/"


class TestGuessLanAndRuntime:
    def test_guess_lan_ipv4_success(self):
        class _Sock:
            def connect(self, *_a):
                return None

            def getsockname(self):
                return ("10.0.0.8", 0)

            def close(self):
                return None

        with patch.object(ph.socket, "socket", return_value=_Sock()):
            assert ph._guess_lan_ipv4() == "10.0.0.8"

    def test_guess_lan_ipv4_oserror(self):
        with patch.object(ph.socket, "socket", side_effect=OSError("no net")):
            assert ph._guess_lan_ipv4() == "127.0.0.1"

    def test_read_runtime_api_port_file(self, tmp_path, monkeypatch):
        runtime = tmp_path / ".runtime"
        runtime.mkdir()
        (runtime / "api.port").write_text("17500\n", encoding="utf-8")
        monkeypatch.setattr(ph, "_REPO_ROOT", tmp_path)
        assert ph._read_runtime_api_port() == 17500

    def test_read_runtime_api_port_invalid(self, tmp_path, monkeypatch):
        runtime = tmp_path / ".runtime"
        runtime.mkdir()
        (runtime / "api.port").write_text("not-a-port\n", encoding="utf-8")
        monkeypatch.setattr(ph, "_REPO_ROOT", tmp_path)
        assert ph._read_runtime_api_port(default=9) == 9

    def test_backend_listens_loopback_env(self, monkeypatch):
        monkeypatch.setenv("XCAGI_API_HOST", "127.0.0.1")
        assert ph._backend_listens_loopback_only() is True
        monkeypatch.setenv("XCAGI_API_HOST", "0.0.0.0")
        assert ph._backend_listens_loopback_only() is False

    def test_enrich_without_code(self):
        with patch.object(ph, "_backend_listens_loopback_only", return_value=False):
            data = ph._enrich_pairing_payload(
                {"host": "10.1.2.3", "port": 17500, "nonce": "n"},
                _mock_request("10.1.2.3:17500"),
            )
        assert data["api_base_url"] == "http://10.1.2.3:17500/"
        assert "code" not in data or not data.get("code")
        assert data["qr_json"]["host"] == "10.1.2.3"

    def test_requested_5000_yields_to_request_port(self):
        assert ph._pairing_issue_port(_mock_request("127.0.0.1:17500"), 5000) == 17500
