"""Tests for app.fastapi_routes.xcmax_admin — pure helper functions."""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest


# ========================= REMOTE_HOST / REMOTE_PORT ====================


class TestRemoteConfig:
    def test_default_host(self):
        from app.fastapi_routes.xcmax_admin import REMOTE_HOST
        assert isinstance(REMOTE_HOST, str)

    def test_default_port(self):
        from app.fastapi_routes.xcmax_admin import REMOTE_PORT
        assert isinstance(REMOTE_PORT, int)


# ========================= _release_train_snapshot =======================


class TestReleaseTrainSnapshot:
    def test_fallback_when_no_file(self):
        from app.fastapi_routes.xcmax_admin import _release_train_snapshot
        # The function uses try/except for modstore_server import
        # and falls back to reading a file; if file doesn't exist, returns defaults
        with patch("pathlib.Path.is_file", return_value=False):
            result = _release_train_snapshot()
            assert "epoch" in result
            assert result["note"] == "ssot missing"

    def test_returns_dict(self):
        from app.fastapi_routes.xcmax_admin import _release_train_snapshot
        result = _release_train_snapshot()
        assert isinstance(result, dict)
        assert "epoch" in result
