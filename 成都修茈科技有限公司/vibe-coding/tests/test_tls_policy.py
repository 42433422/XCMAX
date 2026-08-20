from __future__ import annotations

import ssl

import pytest

from vibe_coding._internals.tls import ssl_context_for_endpoint


def test_default_tls_uses_urllib_platform_context() -> None:
    assert ssl_context_for_endpoint("https://api.example.com", verify_ssl=True) is None


def test_unverified_tls_is_rejected_for_remote_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        ssl_context_for_endpoint("https://api.example.com", verify_ssl=False)


def test_unverified_tls_is_confined_to_loopback_https() -> None:
    context = ssl_context_for_endpoint("https://127.0.0.1:8443", verify_ssl=False)
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_NONE
