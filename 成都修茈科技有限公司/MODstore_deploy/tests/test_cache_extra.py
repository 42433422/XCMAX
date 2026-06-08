"""Tests for modstore_server.cache module."""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from modstore_server.cache import delete, get_json, set_json


class TestInMemoryCache:
    def test_set_and_get(self):
        set_json("test_key_1", {"foo": "bar"}, ttl_seconds=60)
        result = get_json("test_key_1")
        assert result == {"foo": "bar"}

    def test_get_missing_key(self):
        result = get_json("nonexistent_key_xyz_123")
        assert result is None

    def test_set_overwrite(self):
        set_json("test_key_ow", "v1", ttl_seconds=60)
        set_json("test_key_ow", "v2", ttl_seconds=60)
        assert get_json("test_key_ow") == "v2"

    def test_delete_key(self):
        set_json("test_key_del", "value", ttl_seconds=60)
        delete("test_key_del")
        assert get_json("test_key_del") is None

    def test_delete_missing_key_no_error(self):
        delete("nonexistent_key_xyz_456")

    def test_ttl_expiry(self):
        set_json("test_key_ttl_exp", "expiring", ttl_seconds=1)
        time.sleep(1.1)
        assert get_json("test_key_ttl_exp") is None

    def test_complex_value(self):
        data = {"list": [1, 2, 3], "nested": {"a": True}, "null": None}
        set_json("test_key_complex", data, ttl_seconds=60)
        assert get_json("test_key_complex") == data

    def test_string_value(self):
        set_json("test_key_str", "hello", ttl_seconds=60)
        assert get_json("test_key_str") == "hello"

    def test_numeric_value(self):
        set_json("test_key_num", 42, ttl_seconds=60)
        assert get_json("test_key_num") == 42

    def test_default_ttl(self):
        set_json("test_key_default_ttl", "val")
        assert get_json("test_key_default_ttl") == "val"


class TestRedisFallback:
    def test_no_redis_url_uses_memory(self):
        os.environ.pop("REDIS_URL", None)
        set_json("test_mem_only_2", "val", ttl_seconds=60)
        assert get_json("test_mem_only_2") == "val"

    def test_redis_get_error_returns_none(self):
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("redis error")
        with patch("modstore_server.cache._redis_client", return_value=mock_client):
            result = get_json("any_key_redis_err")
            assert result is None
