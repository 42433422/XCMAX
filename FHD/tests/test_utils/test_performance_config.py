"""测试 performance_config 模块 - 性能优化配置。"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.utils.performance_config import PerformanceConfig, get_performance_config


class TestPerformanceConfigDefaults:
    """测试默认配置值。"""

    def test_redis_cache_prefix(self):
        assert PerformanceConfig.REDIS_CACHE_PREFIX == "xcagi:"

    def test_default_cache_ttl(self):
        assert PerformanceConfig.DEFAULT_CACHE_TTL == 300

    def test_cache_null_ttl(self):
        assert PerformanceConfig.CACHE_NULL_TTL == 60

    def test_local_cache_size(self):
        assert PerformanceConfig.LOCAL_CACHE_SIZE == 1000

    def test_local_cache_ttl(self):
        assert PerformanceConfig.LOCAL_CACHE_TTL == 10

    def test_slow_query_threshold(self):
        assert PerformanceConfig.SLOW_QUERY_THRESHOLD == 0.5

    def test_max_batch_size(self):
        assert PerformanceConfig.MAX_BATCH_SIZE == 100

    def test_task_default_timeout(self):
        assert PerformanceConfig.TASK_DEFAULT_TIMEOUT == 300

    def test_task_max_retries(self):
        assert PerformanceConfig.TASK_MAX_RETRIES == 3

    def test_task_retry_delay(self):
        assert PerformanceConfig.TASK_RETRY_DELAY == 5

    def test_force_sync_tasks(self):
        assert PerformanceConfig.FORCE_SYNC_TASKS is False

    def test_dedup_window(self):
        assert PerformanceConfig.DEDUP_WINDOW == 60

    def test_dedup_max_keys(self):
        assert PerformanceConfig.DEDUP_MAX_KEYS == 10000

    def test_default_rate_limit(self):
        assert PerformanceConfig.DEFAULT_RATE_LIMIT == 100

    def test_ai_rate_limit(self):
        assert PerformanceConfig.AI_RATE_LIMIT == 30

    def test_circuit_failure_threshold(self):
        assert PerformanceConfig.CIRCUIT_FAILURE_THRESHOLD == 5

    def test_circuit_recovery_timeout(self):
        assert PerformanceConfig.CIRCUIT_RECOVERY_TIMEOUT == 60


class TestGetAllConfigs:
    """测试 get_all_configs 方法。"""

    def test_returns_dict(self):
        configs = PerformanceConfig.get_all_configs()
        assert isinstance(configs, dict)

    def test_includes_key_configs(self):
        configs = PerformanceConfig.get_all_configs()
        assert "DEFAULT_CACHE_TTL" in configs
        assert "SLOW_QUERY_THRESHOLD" in configs
        assert "MAX_BATCH_SIZE" in configs

    def test_excludes_private_attrs(self):
        configs = PerformanceConfig.get_all_configs()
        for key in configs:
            assert not key.startswith("_")

    def test_excludes_non_uppercase(self):
        configs = PerformanceConfig.get_all_configs()
        for key in configs:
            assert key.isupper()


class TestValidate:
    """测试 validate 方法。"""

    def test_valid_defaults(self):
        issues = PerformanceConfig.validate()
        assert issues == []

    def test_local_cache_size_too_small(self):
        original = PerformanceConfig.LOCAL_CACHE_SIZE
        try:
            PerformanceConfig.LOCAL_CACHE_SIZE = 5
            issues = PerformanceConfig.validate()
            assert any("LOCAL_CACHE_SIZE" in i for i in issues)
        finally:
            PerformanceConfig.LOCAL_CACHE_SIZE = original

    def test_default_cache_ttl_too_small(self):
        original = PerformanceConfig.DEFAULT_CACHE_TTL
        try:
            PerformanceConfig.DEFAULT_CACHE_TTL = 0
            issues = PerformanceConfig.validate()
            assert any("DEFAULT_CACHE_TTL" in i for i in issues)
        finally:
            PerformanceConfig.DEFAULT_CACHE_TTL = original

    def test_slow_query_threshold_negative(self):
        original = PerformanceConfig.SLOW_QUERY_THRESHOLD
        try:
            PerformanceConfig.SLOW_QUERY_THRESHOLD = -1
            issues = PerformanceConfig.validate()
            assert any("SLOW_QUERY_THRESHOLD" in i for i in issues)
        finally:
            PerformanceConfig.SLOW_QUERY_THRESHOLD = original

    def test_max_batch_size_zero(self):
        original = PerformanceConfig.MAX_BATCH_SIZE
        try:
            PerformanceConfig.MAX_BATCH_SIZE = 0
            issues = PerformanceConfig.validate()
            assert any("MAX_BATCH_SIZE" in i for i in issues)
        finally:
            PerformanceConfig.MAX_BATCH_SIZE = original


class TestPrintConfig:
    """测试 print_config 方法。"""

    def test_print_config_no_exception(self):
        import logging

        logger = logging.getLogger("test_print_config")
        with patch.object(logger, "info"):
            with patch.object(logger, "warning"):
                PerformanceConfig.print_config()


class TestGetPerformanceConfig:
    """测试工厂函数。"""

    def test_returns_instance(self):
        config = get_performance_config()
        assert isinstance(config, PerformanceConfig)
