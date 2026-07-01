"""Tests for app.fastapi_routes.xcmax_admin — pure helper functions."""

from __future__ import annotations

import builtins
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

        original_import = builtins.__import__

        def fail_release_train_import(name, *args, **kwargs):
            if name == "modstore_server.release_train" or name.startswith(
                "modstore_server.release_train.",
            ):
                raise ImportError("force file fallback")
            return original_import(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=fail_release_train_import),
            patch("pathlib.Path.is_file", return_value=False),
        ):
            result = _release_train_snapshot()
            assert "epoch" in result
            assert result["note"] == "ssot missing"

    def test_returns_dict(self):
        from app.fastapi_routes.xcmax_admin import _release_train_snapshot

        result = _release_train_snapshot()
        assert isinstance(result, dict)
        assert "epoch" in result
