"""Tests for app.application.purchase_app_service — coverage ramp C3.2-b.

Covers:
* ``PurchaseApplicationService.__init__`` creates a ``PurchaseService``.
* ``__getattr__`` delegates unknown methods to inner service.
* ``get_purchase_app_service`` singleton.
* Fallback / mocked ``PurchaseService`` behaviour.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from app.application.purchase_app_service import (
    PurchaseApplicationService,
    get_purchase_app_service,
)


class TestInit:
    def test_creates_inner_service(self) -> None:
        with patch("app.infrastructure.gateways.purchase_legacy.PurchaseService") as PS:
            PS.return_value = MagicMock(name="inner")
            svc = PurchaseApplicationService()
        assert svc._inner is PS.return_value
        PS.assert_called_once_with()


class TestDelegation:
    def test_unknown_method_delegates(self) -> None:
        with patch("app.infrastructure.gateways.purchase_legacy.PurchaseService") as PS:
            inner = MagicMock()
            inner.some_method.return_value = "delegated"
            PS.return_value = inner
            svc = PurchaseApplicationService()
        # __getattr__ on the service forwards to inner
        out = svc.some_method(1, 2, key="v")
        inner.some_method.assert_called_once_with(1, 2, key="v")
        assert out == "delegated"

    def test_attribute_access_for_known_returns(self) -> None:
        svc = PurchaseApplicationService()
        # _inner is a real attribute, not delegated
        assert hasattr(svc, "_inner")


class TestSingleton:
    def test_singleton_returns_same(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.application.purchase_app_service as mod

        monkeypatch.setattr(mod, "_purchase_app_service", None)
        with patch("app.infrastructure.gateways.purchase_legacy.PurchaseService"):
            a = get_purchase_app_service()
            b = get_purchase_app_service()
        assert a is b

    def test_singleton_returns_existing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.application.purchase_app_service as mod

        existing = MagicMock()
        monkeypatch.setattr(mod, "_purchase_app_service", existing)
        assert get_purchase_app_service() is existing
