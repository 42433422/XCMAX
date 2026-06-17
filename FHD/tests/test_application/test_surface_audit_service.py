"""Tests for app.application.surface_audit_service — coverage ramp."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.surface_audit_service import (
    _lane_cache_dir,
    _lane_png_root,
    _page_png_slug,
    _today_key,
)

# ========================= _today_key ====================================


class TestTodayKey:
    def test_format(self):
        result = _today_key()
        assert result == date.today().isoformat()
        assert len(result) == 10  # YYYY-MM-DD


# ========================= _lane_cache_dir ===============================


class TestLaneCacheDir:
    def test_basic(self):
        result = _lane_cache_dir("P-W/SW")
        assert isinstance(result, Path)
        assert "P-W_SW" in str(result)

    def test_simple_lane(self):
        result = _lane_cache_dir("test")
        assert "test" in str(result)


# ========================= _lane_png_root ================================


class TestLanePngRoot:
    def test_basic(self):
        result = _lane_png_root("P-W/SW")
        assert isinstance(result, Path)
        assert "P-W_SW" in str(result)


# ========================= _page_png_slug ================================


class TestPagePngSlug:
    def test_with_id(self):
        result = _page_png_slug(0, {"id": "dashboard"})
        assert result == "000_dashboard"

    def test_with_name(self):
        result = _page_png_slug(1, {"name": "settings"})
        assert result == "001_settings"

    def test_no_id_or_name(self):
        result = _page_png_slug(2, {})
        assert result == "002_page"

    def test_special_chars(self):
        result = _page_png_slug(3, {"id": "test page/section"})
        assert "/" not in result
        assert "003" in result

    def test_empty_page(self):
        result = _page_png_slug(4, {})
        assert result == "004_page"
