"""The relay URL normalizer is a domain utility with an injected topology default."""

from __future__ import annotations

import pytest

from app.domain.shared_services.mobile_relay_utils import _public_base_url
from app.domain.shared_services.mobile_relay_service import _public_base_url as legacy_url
from app.infrastructure.topology import FHD_API_BASE_URL


@pytest.mark.parametrize(
    ("raw", "default", "expected"),
    [
        ("https://relay.example.test/api", "https://fallback.test", "https://relay.example.test/api/"),
        ("relay.example.test/api", "https://fallback.test", "https://relay.example.test/api/"),
        ("", "https://fallback.test/base", "https://fallback.test/base/"),
        ("   ", "https://fallback.test/base/", "https://fallback.test/base/"),
        ("http://127.0.0.1:17500", "https://fallback.test", "http://127.0.0.1:17500/"),
    ],
)
def test_public_base_url_normalizes_explicit_and_injected_defaults(raw, default, expected):
    assert _public_base_url(raw, default_base_url=default) == expected


def test_public_base_url_requires_an_explicit_or_injected_address():
    with pytest.raises(ValueError, match="not configured"):
        _public_base_url("", default_base_url="")


def test_legacy_service_helper_uses_deployment_topology():
    assert legacy_url("") == FHD_API_BASE_URL.rstrip("/") + "/"
