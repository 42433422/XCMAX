"""Tests for app.infrastructure.db.pool_sizing."""
from __future__ import annotations

import os

import pytest

from app.infrastructure.db.pool_sizing import (
    pool_config_from_env,
    estimate_total_connections,
    recommend_pool_for_pg,
)


class TestPoolConfigFromEnv:
    def test_default_values(self, monkeypatch):
        monkeypatch.delenv("XCAGI_DB_POOL_SIZE", raising=False)
        monkeypatch.delenv("XCAGI_DB_MAX_OVERFLOW", raising=False)
        result = pool_config_from_env()
        assert result["pool_size"] == 5
        assert result["max_overflow"] == 10

    def test_custom_values(self, monkeypatch):
        monkeypatch.setenv("XCAGI_DB_POOL_SIZE", "8")
        monkeypatch.setenv("XCAGI_DB_MAX_OVERFLOW", "15")
        result = pool_config_from_env()
        assert result["pool_size"] == 8
        assert result["max_overflow"] == 15


class TestEstimateTotalConnections:
    def test_basic_calculation(self):
        result = estimate_total_connections(
            pods=2, workers_per_pod=4, pool_size=5, max_overflow=10
        )
        assert result == 2 * 4 * (5 + 10)  # 120

    def test_single_pod_single_worker(self):
        result = estimate_total_connections(
            pods=1, workers_per_pod=1, pool_size=5, max_overflow=10
        )
        assert result == 15

    def test_zero_overflow(self):
        result = estimate_total_connections(
            pods=1, workers_per_pod=1, pool_size=5, max_overflow=0
        )
        assert result == 5


class TestRecommendPoolForPg:
    def test_basic_recommendation(self):
        result = recommend_pool_for_pg(
            pods=2, workers_per_pod=4, pg_max_connections=100, reserve=20
        )
        assert "pool_size" in result
        assert "max_overflow" in result
        assert result["pool_size"] >= 2
        assert result["max_overflow"] >= 2

    def test_small_pg_connections(self):
        result = recommend_pool_for_pg(
            pods=1, workers_per_pod=1, pg_max_connections=20, reserve=5
        )
        assert result["pool_size"] >= 2
        assert result["max_overflow"] >= 2

    def test_large_cluster(self):
        result = recommend_pool_for_pg(
            pods=10, workers_per_pod=8, pg_max_connections=200, reserve=30
        )
        assert result["pool_size"] >= 2
        assert result["max_overflow"] >= 2

    def test_reserve_equals_max(self):
        result = recommend_pool_for_pg(
            pods=1, workers_per_pod=1, pg_max_connections=20, reserve=20
        )
        # budget = max(1, 20-20) = 1
        assert "pool_size" in result
