"""测试 lan_ip 模块 - 客户端真实 IP 提取。"""

from __future__ import annotations

import pytest

from app.security.lan_ip import (
    _normalize,
    _peer_ip,
    _proxy_matches,
    _real_ip_header,
    _xff_chain,
    get_client_ip,
)


class TestPeerIp:
    """测试 _peer_ip 函数。"""

    def test_extracts_ip_from_tuple(self):
        scope = {"client": ("192.168.1.1", 8080)}
        assert _peer_ip(scope) == "192.168.1.1"

    def test_extracts_ip_from_list(self):
        scope = {"client": ["10.0.0.1", 80]}
        assert _peer_ip(scope) == "10.0.0.1"

    def test_none_scope(self):
        assert _peer_ip(None) is None

    def test_no_client(self):
        assert _peer_ip({}) is None

    def test_empty_tuple(self):
        assert _peer_ip({"client": ()}) is None


class TestNormalize:
    """测试 _normalize 函数。"""

    def test_ipv4(self):
        assert _normalize("192.168.1.1") == "192.168.1.1"

    def test_ipv6(self):
        assert _normalize("::1") == "::1"

    def test_ipv6_with_brackets(self):
        assert _normalize("[::1]") == "::1"

    def test_ip_with_port(self):
        assert _normalize("192.168.1.1:8080") == "192.168.1.1"

    def test_none(self):
        assert _normalize(None) is None

    def test_empty(self):
        assert _normalize("") is None

    def test_whitespace(self):
        assert _normalize("  192.168.1.1  ") == "192.168.1.1"

    def test_invalid_ip(self):
        assert _normalize("not_an_ip") is None

    def test_ipv6_full(self):
        assert _normalize("2001:db8::1") == "2001:db8::1"


class TestProxyMatches:
    """测试 _proxy_matches 函数。"""

    def test_exact_match(self):
        assert _proxy_matches("10.0.0.1", ["10.0.0.1"]) is True

    def test_no_match(self):
        assert _proxy_matches("10.0.0.1", ["10.0.0.2"]) is False

    def test_cidr_match(self):
        assert _proxy_matches("10.0.0.5", ["10.0.0.0/24"]) is True

    def test_cidr_no_match(self):
        assert _proxy_matches("10.0.1.5", ["10.0.0.0/24"]) is False

    def test_empty_peer(self):
        assert _proxy_matches("", ["10.0.0.1"]) is False

    def test_empty_trusted(self):
        assert _proxy_matches("10.0.0.1", []) is False

    def test_invalid_peer(self):
        assert _proxy_matches("not_an_ip", ["10.0.0.1"]) is False

    def test_invalid_trusted_entry(self):
        assert _proxy_matches("10.0.0.1", ["not_an_ip"]) is False

    def test_multiple_trusted(self):
        assert _proxy_matches("10.0.0.1", ["192.168.0.1", "10.0.0.1"]) is True


class TestXffChain:
    """测试 _xff_chain 函数。"""

    def test_extracts_xff(self):
        scope = {"headers": [(b"x-forwarded-for", b"1.1.1.1, 2.2.2.2")]}
        result = _xff_chain(scope)
        assert result == ["1.1.1.1", "2.2.2.2"]

    def test_no_xff_header(self):
        scope = {"headers": [(b"content-type", b"text/html")]}
        assert _xff_chain(scope) == []

    def test_empty_headers(self):
        assert _xff_chain({}) == []

    def test_single_ip(self):
        scope = {"headers": [(b"x-forwarded-for", b"1.1.1.1")]}
        assert _xff_chain(scope) == ["1.1.1.1"]

    def test_strips_whitespace(self):
        scope = {"headers": [(b"x-forwarded-for", b" 1.1.1.1 ,  2.2.2.2 ")]}
        result = _xff_chain(scope)
        assert result == ["1.1.1.1", "2.2.2.2"]


class TestRealIpHeader:
    """测试 _real_ip_header 函数。"""

    def test_extracts_real_ip(self):
        scope = {"headers": [(b"x-real-ip", b"1.1.1.1")]}
        assert _real_ip_header(scope) == "1.1.1.1"

    def test_no_real_ip(self):
        scope = {"headers": [(b"content-type", b"text/html")]}
        assert _real_ip_header(scope) is None

    def test_empty_headers(self):
        assert _real_ip_header({}) is None


class TestGetClientIp:
    """测试 get_client_ip 主函数。"""

    def test_direct_connection(self):
        scope = {"client": ("192.168.1.1", 8080)}
        assert get_client_ip(scope) == "192.168.1.1"

    def test_no_client(self):
        assert get_client_ip({}) is None

    def test_with_untrusted_proxy(self):
        scope = {
            "client": ("10.0.0.1", 8080),
            "headers": [(b"x-forwarded-for", b"1.1.1.1")],
        }
        # 10.0.0.1 is not in trusted_proxies, so XFF is ignored
        assert get_client_ip(scope, trusted_proxies=["172.16.0.1"]) == "10.0.0.1"

    def test_with_trusted_proxy(self):
        scope = {
            "client": ("10.0.0.1", 8080),
            "headers": [(b"x-forwarded-for", b"1.1.1.1")],
        }
        result = get_client_ip(scope, trusted_proxies=["10.0.0.1"])
        assert result == "1.1.1.1"

    def test_with_trusted_proxy_cidr(self):
        scope = {
            "client": ("10.0.0.5", 8080),
            "headers": [(b"x-forwarded-for", b"1.1.1.1")],
        }
        result = get_client_ip(scope, trusted_proxies=["10.0.0.0/24"])
        assert result == "1.1.1.1"

    def test_xff_chain_with_trusted_proxy(self):
        scope = {
            "client": ("10.0.0.1", 8080),
            "headers": [(b"x-forwarded-for", b"1.1.1.1, 10.0.0.1")],
        }
        result = get_client_ip(scope, trusted_proxies=["10.0.0.1"])
        # Should return the first non-trusted IP from the right
        assert result == "1.1.1.1"

    def test_fallback_to_real_ip_header(self):
        scope = {
            "client": ("10.0.0.1", 8080),
            "headers": [(b"x-real-ip", b"1.1.1.1")],
        }
        result = get_client_ip(scope, trusted_proxies=["10.0.0.1"])
        assert result == "1.1.1.1"

    def test_no_trusted_proxies_ignores_xff(self):
        scope = {
            "client": ("192.168.1.1", 8080),
            "headers": [(b"x-forwarded-for", b"1.1.1.1")],
        }
        result = get_client_ip(scope, trusted_proxies=[])
        assert result == "192.168.1.1"
