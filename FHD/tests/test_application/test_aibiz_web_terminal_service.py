"""Tests for app.application.aibiz_web_terminal_service — coverage ramp."""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.aibiz_web_terminal_service import (
    _LANE_BY_TERMINAL,
    _surface_cache_token,
    _surface_image_url,
    _unwrap,
)


# ========================= _LANE_BY_TERMINAL =============================


class TestLaneByTerminal:
    def test_web(self):
        assert _LANE_BY_TERMINAL["web"] == ("P-W", "SW")

    def test_software(self):
        assert _LANE_BY_TERMINAL["software"] == ("P-S", "SS")

    def test_app(self):
        assert _LANE_BY_TERMINAL["app"] == ("P-App", "SA")


# ========================= _unwrap =======================================


class TestUnwrap:
    def test_dict_passthrough(self):
        result = _unwrap({"key": "value"})
        assert result == {"key": "value"}

    def test_json_response_wrapped(self):
        from fastapi.responses import JSONResponse

        resp = JSONResponse(content={"error": "test"})
        result = _unwrap(resp)
        assert "_error_response" in result

    def test_non_dict_non_response(self):
        result = _unwrap("string")
        assert result == {}

    def test_none(self):
        result = _unwrap(None)
        assert result == {}

    def test_list(self):
        result = _unwrap([1, 2, 3])
        assert result == {}


# ========================= _surface_cache_token ==========================


class TestSurfaceCacheToken:
    def test_with_captured_at(self):
        surface = {"captured_at": "2026-06-14T10:30:00.000Z"}
        token = _surface_cache_token(surface)
        assert len(token) == 14
        assert "20260614" in token

    def test_with_cached_at(self):
        surface = {"cached_at": "2026-01-01T00:00:00.000Z"}
        token = _surface_cache_token(surface)
        assert len(token) == 14

    def test_no_timestamp(self):
        surface = {}
        token = _surface_cache_token(surface)
        assert token == date.today().isoformat().replace("-", "")

    def test_empty_captured_at(self):
        surface = {"captured_at": ""}
        token = _surface_cache_token(surface)
        assert token == date.today().isoformat().replace("-", "")


# ========================= _surface_image_url ============================


class TestSurfaceImageUrl:
    def test_basic(self):
        url = _surface_image_url("web", 0)
        assert "terminal=web" in url
        assert "index=0" in url

    def test_with_view(self):
        url = _surface_image_url("web", 1, view="full")
        assert "view=full" in url

    def test_with_v(self):
        url = _surface_image_url("web", 2, v="abc123")
        assert "v=abc123" in url

    def test_with_both(self):
        url = _surface_image_url("software", 3, view="thumb", v="def456")
        assert "terminal=software" in url
        assert "view=thumb" in url
        assert "v=def456" in url
