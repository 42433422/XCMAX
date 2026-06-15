"""Tests for app.fastapi_routes.model_payment — pure helper functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes.model_payment import (
    _DEMO_PLANS,
    _all_plans,
    _integration_flags,
    _plan_by_id,
)


# ========================= _DEMO_PLANS ===================================


class TestDemoPlans:
    def test_has_three_plans(self):
        assert len(_DEMO_PLANS) == 3

    def test_plan_structure(self):
        for plan in _DEMO_PLANS:
            assert "id" in plan
            assert "title" in plan
            assert "amount_cents" in plan
            assert "currency" in plan

    def test_starter_plan(self):
        starter = _DEMO_PLANS[0]
        assert starter["id"] == "demo-starter"
        assert starter["amount_cents"] == 990

    def test_pro_plan(self):
        pro = _DEMO_PLANS[2]
        assert pro["id"] == "demo-pro"
        assert pro["amount_cents"] == 19900


# ========================= _all_plans ====================================


class TestAllPlans:
    def test_includes_demo_plans(self):
        with patch("app.fastapi_routes.model_payment.list_saas_plans", return_value=[]):
            plans = _all_plans()
            assert len(plans) >= 3
            ids = [p["id"] for p in plans]
            assert "demo-starter" in ids

    def test_includes_saas_plans(self):
        saas_plan = {"id": "saas-1", "title": "SaaS Plan", "amount_cents": 9999, "currency": "CNY"}
        with patch("app.fastapi_routes.model_payment.list_saas_plans", return_value=[saas_plan]):
            plans = _all_plans()
            ids = [p["id"] for p in plans]
            assert "saas-1" in ids


# ========================= _plan_by_id ===================================


class TestPlanById:
    def test_found(self):
        with patch("app.fastapi_routes.model_payment.plan_by_id", return_value={"id": "demo-starter", "title": "体验档"}):
            plan = _plan_by_id("demo-starter")
            assert plan is not None
            assert plan["id"] == "demo-starter"

    def test_not_found(self):
        with patch("app.fastapi_routes.model_payment.plan_by_id", return_value=None):
            plan = _plan_by_id("nonexistent")
            assert plan is None


# ========================= _integration_flags ============================


class TestIntegrationFlags:
    def test_structure(self):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.is_fhd_postgres_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.model_payment_backend", return_value="json"):
            mock_ali.alipay_ui_ready.return_value = False
            flags = _integration_flags()
            assert "alipay_configured" in flags
            assert "market_sot" in flags
            assert "postgres_sot" in flags
            assert "backend" in flags

    def test_alipay_not_configured(self):
        with patch("app.fastapi_routes.model_payment.mp_ali") as mock_ali, \
             patch("app.fastapi_routes.model_payment.is_modstore_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.is_fhd_postgres_payment_sot", return_value=False), \
             patch("app.fastapi_routes.model_payment.model_payment_backend", return_value="json"):
            mock_ali.alipay_ui_ready.return_value = False
            flags = _integration_flags()
            assert flags["alipay_configured"] is False
