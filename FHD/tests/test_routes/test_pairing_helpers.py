"""pairing_helpers 单元测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.fastapi_routes.mobile_extensions import pairing_helpers as ph


def _mock_request(host_header: str = "127.0.0.1:5011") -> SimpleNamespace:
    return SimpleNamespace(headers={"host": host_header})


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
            port = ph._pairing_reachable_port(_mock_request("127.0.0.1:5011"), 17500)
        assert port == 17500

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
