"""Tests for app.infrastructure.db.pool_sizing."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.infrastructure.db.pool_sizing import (
    estimate_total_connections,
    pool_config_from_env,
    recommend_pool_for_pg,
)


class TestPoolConfigFromEnv:
    """Tests for pool_config_from_env."""

    def test_default_values(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = pool_config_from_env()
            assert result["pool_size"] == 5
            assert result["max_overflow"] == 10

    def test_custom_values(self) -> None:
        with patch.dict("os.environ", {"XCAGI_DB_POOL_SIZE": "8", "XCAGI_DB_MAX_OVERFLOW": "15"}):
            result = pool_config_from_env()
            assert result["pool_size"] == 8
            assert result["max_overflow"] == 15


class TestEstimateTotalConnections:
    """Tests for estimate_total_connections."""

    def test_basic_calculation(self) -> None:
        result = estimate_total_connections(pods=2, workers_per_pod=4, pool_size=5, max_overflow=10)
        # 2 * 4 * (5 + 10) = 120
        assert result == 120

    def test_single_pod(self) -> None:
        result = estimate_total_connections(pods=1, workers_per_pod=1, pool_size=5, max_overflow=5)
        assert result == 10

    def test_large_deployment(self) -> None:
        result = estimate_total_connections(
            pods=10, workers_per_pod=8, pool_size=10, max_overflow=20
        )
        # 10 * 8 * 30 = 2400
        assert result == 2400


class TestRecommendPoolForPg:
    """Tests for recommend_pool_for_pg."""

    def test_basic_recommendation(self) -> None:
        result = recommend_pool_for_pg(pods=2, workers_per_pod=4)
        assert "pool_size" in result
        assert "max_overflow" in result
        assert result["pool_size"] >= 2
        assert result["max_overflow"] >= 2

    def test_custom_pg_max_connections(self) -> None:
        result = recommend_pool_for_pg(pods=1, workers_per_pod=1, pg_max_connections=50, reserve=10)
        # budget = 40, per_pod = 40, per_worker = 40
        assert result["pool_size"] >= 2

    def test_minimum_pool_size(self) -> None:
        result = recommend_pool_for_pg(
            pods=100, workers_per_pod=100, pg_max_connections=100, reserve=20
        )
        # Very constrained, should still return minimum values
        assert result["pool_size"] >= 2
        assert result["max_overflow"] >= 2

    def test_pool_size_capped_at_10(self) -> None:
        result = recommend_pool_for_pg(
            pods=1, workers_per_pod=1, pg_max_connections=1000, reserve=20
        )
        assert result["pool_size"] <= 10

    def test_reserve_reduces_budget(self) -> None:
        result_low_reserve = recommend_pool_for_pg(
            pods=1, workers_per_pod=1, pg_max_connections=100, reserve=5
        )
        result_high_reserve = recommend_pool_for_pg(
            pods=1, workers_per_pod=1, pg_max_connections=100, reserve=80
        )
        # Higher reserve means less budget, potentially smaller pool
        assert result_low_reserve["pool_size"] >= result_high_reserve["pool_size"]
