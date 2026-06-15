"""Tests for app.fastapi_routes.service_bridge — pure helper functions."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes.service_bridge import _get_instance_name


# ========================= _get_instance_name ============================


class TestGetInstanceName:
    def test_default(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SERVICE_BRIDGE_INSTANCE_NAME", None)
            result = _get_instance_name()
            assert result == "XCAGI 宿主"

    def test_custom(self):
        with patch.dict(os.environ, {"SERVICE_BRIDGE_INSTANCE_NAME": "My Instance"}):
            result = _get_instance_name()
            assert result == "My Instance"

    def test_empty_env(self):
        with patch.dict(os.environ, {"SERVICE_BRIDGE_INSTANCE_NAME": ""}):
            result = _get_instance_name()
            assert result == ""


# ========================= _get_or_create_instance_id ====================


class TestGetOrCreateInstanceId:
    def test_format(self):
        with patch("os.path.exists", return_value=False), \
             patch("os.makedirs"):
            from app.fastapi_routes.service_bridge import _get_or_create_instance_id
            result = _get_or_create_instance_id()
            assert result.startswith("xcagi-host-")

    def test_reads_cached(self):
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()):
            # Mock the file read
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_file.read.return_value = "xcagi-host-cached123"
            with patch("builtins.open", return_value=mock_file):
                from app.fastapi_routes.service_bridge import _get_or_create_instance_id
                result = _get_or_create_instance_id()
                assert result == "xcagi-host-cached123"
