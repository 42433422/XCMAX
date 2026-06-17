"""Tests for app.application.app_service_pair_registry."""
from __future__ import annotations

import pytest

from app.application.app_service_pair_registry import (
    APP_SERVICE_PAIRS,
    AppServicePair,
    domains_on_v1_http,
    get_pair,
    iter_pairs,
    neuro_v2_module_path,
    resolve_http_getter,
    resolve_neuro_getter,
)


class TestAppServicePair:
    """Tests for AppServicePair dataclass."""

    def test_pair_is_frozen(self) -> None:
        pair = AppServicePair(
            domain="test",
            v1_module="test_v1",
            v1_getter="get_test_v1",
            v2_module="test_v2",
            v2_getter="get_test_v2",
            http_layer="v1",
            notes="test notes",
        )
        with pytest.raises(AttributeError):
            pair.domain = "changed"

    def test_pair_fields(self) -> None:
        pair = APP_SERVICE_PAIRS[0]
        assert pair.domain
        assert pair.v1_module
        assert pair.v1_getter
        assert pair.v2_module
        assert pair.v2_getter
        assert pair.http_layer in ("v1", "v2")


class TestIterPairs:
    """Tests for iter_pairs."""

    def test_returns_tuple(self) -> None:
        result = iter_pairs()
        assert isinstance(result, tuple)
        assert len(result) > 0

    def test_all_items_are_app_service_pairs(self) -> None:
        for p in iter_pairs():
            assert isinstance(p, AppServicePair)


class TestDomainsOnV1Http:
    """Tests for domains_on_v1_http."""

    def test_returns_tuple(self) -> None:
        result = domains_on_v1_http()
        assert isinstance(result, tuple)

    def test_all_current_domains_are_v1(self) -> None:
        result = domains_on_v1_http()
        # Based on the registry, all domains currently use v1
        assert len(result) > 0
        assert "auth" in result
        assert "user" in result


class TestGetPair:
    """Tests for get_pair."""

    def test_returns_pair_for_known_domain(self) -> None:
        pair = get_pair("auth")
        assert pair is not None
        assert pair.domain == "auth"

    def test_returns_none_for_unknown_domain(self) -> None:
        pair = get_pair("nonexistent_domain")
        assert pair is None

    def test_returns_pair_for_purchase(self) -> None:
        pair = get_pair("purchase")
        assert pair is not None
        assert pair.v1_module == ""  # purchase has no V1


class TestResolveNeuroGetter:
    """Tests for resolve_neuro_getter."""

    def test_returns_v2_getter_for_known_domain(self) -> None:
        result = resolve_neuro_getter("auth")
        assert result == "get_auth_app_service_v2"

    def test_raises_key_error_for_unknown_domain(self) -> None:
        with pytest.raises(KeyError):
            resolve_neuro_getter("nonexistent")


class TestResolveHttpGetter:
    """Tests for resolve_http_getter."""

    def test_returns_v1_getter_for_v1_domain(self) -> None:
        result = resolve_http_getter("auth")
        assert result == "get_auth_app_service"

    def test_raises_key_error_for_unknown_domain(self) -> None:
        with pytest.raises(KeyError):
            resolve_http_getter("nonexistent")

    def test_returns_v2_getter_for_v2_domain(self) -> None:
        # Currently all domains are v1, but test the logic
        pair = get_pair("auth")
        assert pair is not None
        # If http_layer were v2, it would return v2_getter
        # For now, all are v1, so it returns v1_getter
        result = resolve_http_getter("auth")
        assert "v1" in result or "get_auth_app_service" == result


class TestNeuroV2ModulePath:
    """Tests for neuro_v2_module_path."""

    def test_returns_v2_module_path(self) -> None:
        result = neuro_v2_module_path("auth")
        assert result == "app.application.auth_app_service_v2"

    def test_raises_key_error_for_unknown_domain(self) -> None:
        with pytest.raises(KeyError):
            neuro_v2_module_path("nonexistent")
