"""Tests for app.application.app_service_pair_registry."""
from __future__ import annotations

import pytest

from app.application.app_service_pair_registry import (
    AppServicePair,
    APP_SERVICE_PAIRS,
    iter_pairs,
    domains_on_v1_http,
    get_pair,
    resolve_neuro_getter,
    resolve_http_getter,
    neuro_v2_module_path,
)


class TestAppServicePair:
    def test_frozen_dataclass(self):
        pair = AppServicePair(
            domain="test",
            v1_module="m1",
            v1_getter="g1",
            v2_module="m2",
            v2_getter="g2",
            http_layer="v1",
            notes="",
        )
        with pytest.raises(AttributeError):
            pair.domain = "changed"

    def test_fields(self):
        pair = APP_SERVICE_PAIRS[0]
        assert pair.domain
        assert pair.v1_module
        assert pair.v1_getter
        assert pair.v2_module
        assert pair.v2_getter
        assert pair.http_layer in ("v1", "v2")


class TestIterPairs:
    def test_returns_tuple(self):
        result = iter_pairs()
        assert isinstance(result, tuple)
        assert len(result) > 0

    def test_all_are_app_service_pairs(self):
        for pair in iter_pairs():
            assert isinstance(pair, AppServicePair)


class TestDomainsOnV1Http:
    def test_returns_tuple(self):
        result = domains_on_v1_http()
        assert isinstance(result, tuple)

    def test_all_domains_are_strings(self):
        for d in domains_on_v1_http():
            assert isinstance(d, str)

    def test_auth_is_v1(self):
        assert "auth" in domains_on_v1_http()


class TestGetPair:
    def test_existing_domain(self):
        pair = get_pair("auth")
        assert pair is not None
        assert pair.domain == "auth"

    def test_nonexistent_domain(self):
        assert get_pair("nonexistent_xyz") is None

    def test_purchase_domain(self):
        pair = get_pair("purchase")
        assert pair is not None
        assert pair.v1_module == ""


class TestResolveNeuroGetter:
    def test_existing_domain(self):
        result = resolve_neuro_getter("auth")
        assert result == "get_auth_app_service_v2"

    def test_nonexistent_domain_raises(self):
        with pytest.raises(KeyError):
            resolve_neuro_getter("nonexistent_xyz")


class TestResolveHttpGetter:
    def test_v1_domain_returns_v1_getter(self):
        result = resolve_http_getter("auth")
        assert "v1" in result or "auth" in result

    def test_nonexistent_domain_raises(self):
        with pytest.raises(KeyError):
            resolve_http_getter("nonexistent_xyz")


class TestNeuroV2ModulePath:
    def test_returns_module_path(self):
        result = neuro_v2_module_path("auth")
        assert result.startswith("app.application.")
        assert "auth" in result

    def test_nonexistent_domain_raises(self):
        with pytest.raises(KeyError):
            neuro_v2_module_path("nonexistent_xyz")
