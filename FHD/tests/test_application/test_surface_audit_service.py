"""Comprehensive tests for app.application.surface_audit_service — coverage ramp.

Extends the existing basic tests with full coverage of all public functions,
internal helpers, cache operations, lane execution, and edge cases.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.surface_audit_service import (
    _adb_has_device,
    _cache_file,
    _lane_cache_dir,
    _lane_png_day_dirs,
    _lane_png_root,
    _load_config,
    _most_recent_prior_cache,
    _node_env,
    _page_png_slug,
    _playwright_available,
    _read_cache,
    _read_cache_path,
    _today_key,
    _write_cache,
    get_surface_audit_lane,
    list_configured_lanes,
    resolve_lane_page_png_path,
    run_surface_audit_lane,
)

# ========================= _today_key ====================================


class TestTodayKey:
    def test_format(self):
        result = _today_key()
        assert result == date.today().isoformat()
        assert len(result) == 10


# ========================= _lane_cache_dir ===============================


class TestLaneCacheDir:
    def test_basic(self):
        result = _lane_cache_dir("P-W/SW")
        assert isinstance(result, Path)
        assert "P-W_SW" in str(result)

    def test_simple_lane(self):
        result = _lane_cache_dir("test")
        assert "test" in str(result)

    def test_empty_lane(self):
        result = _lane_cache_dir("")
        assert isinstance(result, Path)


# ========================= _lane_png_root ================================


class TestLanePngRoot:
    def test_basic(self):
        result = _lane_png_root("P-W/SW")
        assert isinstance(result, Path)
        assert "P-W_SW" in str(result)

    def test_simple_lane(self):
        result = _lane_png_root("P-App")
        assert "P-App" in str(result)


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

    def test_whitespace_id(self):
        result = _page_png_slug(6, {"id": "  "})
        assert "006" in result


# ========================= _lane_png_day_dirs ============================


class TestLanePngDayDirs:
    def test_nonexistent_root(self, tmp_path):
        with patch(
            "app.application.surface_audit_service._lane_png_root",
            return_value=tmp_path / "nonexistent",
        ):
            result = _lane_png_day_dirs("test")
            assert result == []

    def test_empty_root(self, tmp_path):
        png_root = tmp_path / "png" / "test"
        png_root.mkdir(parents=True)
        with patch("app.application.surface_audit_service._lane_png_root", return_value=png_root):
            result = _lane_png_day_dirs("test")
            assert result == []

    def test_with_day_dirs(self, tmp_path):
        png_root = tmp_path / "png" / "test"
        today = date.today()
        day1 = png_root / today.isoformat()
        day1.mkdir(parents=True)
        with (
            patch("app.application.surface_audit_service._lane_png_root", return_value=png_root),
            patch(
                "app.application.surface_audit_service._today_key", return_value=today.isoformat()
            ),
        ):
            result = _lane_png_day_dirs("test")
            assert len(result) >= 1

    def test_future_day_excluded(self, tmp_path):
        png_root = tmp_path / "png" / "test"
        future = date.today() + timedelta(days=5)
        future_dir = png_root / future.isoformat()
        future_dir.mkdir(parents=True)
        with (
            patch("app.application.surface_audit_service._lane_png_root", return_value=png_root),
            patch(
                "app.application.surface_audit_service._today_key",
                return_value=date.today().isoformat(),
            ),
        ):
            result = _lane_png_day_dirs("test")
            # Future dirs should not be included
            for p in result:
                assert future.isoformat() not in str(p)


# ========================= resolve_lane_page_png_path ====================


class TestResolveLanePagePngPath:
    def test_saved_path_exists(self, tmp_path):
        png = tmp_path / "test.png"
        png.write_bytes(b"fake png")
        result = resolve_lane_page_png_path("P-W", 0, {"screenshot_saved": str(png)})
        assert result == png

    def test_saved_path_not_exists(self, tmp_path):
        with patch("app.application.surface_audit_service._lane_png_day_dirs", return_value=[]):
            result = resolve_lane_page_png_path(
                "P-W", 0, {"screenshot_saved": "/nonexistent/file.png"}
            )
            assert result is None

    def test_none_page(self, tmp_path):
        with patch("app.application.surface_audit_service._lane_png_day_dirs", return_value=[]):
            result = resolve_lane_page_png_path("P-W", 0, None)
            assert result is None

    def test_slug_match_in_day_dir(self, tmp_path):
        day_dir = tmp_path / "2026-01-01"
        day_dir.mkdir()
        png_file = day_dir / "000_dashboard.png"
        png_file.write_bytes(b"fake png")

        with patch(
            "app.application.surface_audit_service._lane_png_day_dirs", return_value=[day_dir]
        ):
            result = resolve_lane_page_png_path("P-W", 0, {"id": "dashboard"})
            assert result == png_file

    def test_index_fallback(self, tmp_path):
        day_dir = tmp_path / "2026-01-01"
        day_dir.mkdir()
        png_file = day_dir / "some_other_name.png"
        png_file.write_bytes(b"fake png")

        with patch(
            "app.application.surface_audit_service._lane_png_day_dirs", return_value=[day_dir]
        ):
            result = resolve_lane_page_png_path("P-W", 0, {"id": "nonexistent"})
            assert result == png_file


# ========================= _cache_file ===================================


class TestCacheFile:
    def test_path_format(self):
        result = _cache_file("P-W")
        assert isinstance(result, Path)
        assert str(result).endswith(".json")
        assert "P-W" in str(result)


# ========================= _load_config ==================================


class TestLoadConfig:
    def test_config_exists(self, tmp_path):
        config = tmp_path / "surface_audit_pages.json"
        config.write_text(json.dumps({"lanes": {"P-W": {}, "P-App": {}}}))
        with patch("app.application.surface_audit_service._CONFIG_PATH", config):
            result = _load_config()
            assert "lanes" in result
            assert "P-W" in result["lanes"]

    def test_config_missing(self, tmp_path):
        config = tmp_path / "nonexistent.json"
        with patch("app.application.surface_audit_service._CONFIG_PATH", config):
            result = _load_config()
            assert result == {"lanes": {}}


# ========================= _read_cache_path ==============================


class TestReadCachePath:
    def test_valid_cache(self, tmp_path):
        cache = tmp_path / "2026-01-01.json"
        cache.write_text(json.dumps({"success": True, "data": "test"}))
        result = _read_cache_path(cache)
        assert result is not None
        assert result["success"] is True

    def test_invalid_cache_no_success(self, tmp_path):
        cache = tmp_path / "2026-01-01.json"
        cache.write_text(json.dumps({"success": False}))
        result = _read_cache_path(cache)
        assert result is None

    def test_nonexistent_file(self, tmp_path):
        result = _read_cache_path(tmp_path / "missing.json")
        assert result is None

    def test_invalid_json(self, tmp_path):
        cache = tmp_path / "2026-01-01.json"
        cache.write_text("not json")
        result = _read_cache_path(cache)
        assert result is None

    def test_non_dict_json(self, tmp_path):
        cache = tmp_path / "2026-01-01.json"
        cache.write_text(json.dumps([1, 2, 3]))
        result = _read_cache_path(cache)
        assert result is None


# ========================= _read_cache ===================================


class TestReadCache:
    def test_reads_today_cache(self, tmp_path):
        cache_file = tmp_path / "P-W" / f"{_today_key()}.json"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text(json.dumps({"success": True, "data": "cached"}))
        with patch("app.application.surface_audit_service._cache_file", return_value=cache_file):
            result = _read_cache("P-W")
            assert result is not None
            assert result["success"] is True


# ========================= _write_cache ==================================


class TestWriteCache:
    def test_writes_cache(self, tmp_path):
        cache_file = tmp_path / "P-W" / f"{_today_key()}.json"
        with patch("app.application.surface_audit_service._cache_file", return_value=cache_file):
            _write_cache("P-W", {"success": True, "data": "test"})
            assert cache_file.exists()
            data = json.loads(cache_file.read_text())
            assert data["success"] is True


# ========================= _most_recent_prior_cache ======================


class TestMostRecentPriorCache:
    def test_no_cache_dir(self, tmp_path):
        with patch(
            "app.application.surface_audit_service._lane_cache_dir",
            return_value=tmp_path / "nonexistent",
        ):
            result = _most_recent_prior_cache("P-W")
            assert result is None

    def test_empty_cache_dir(self, tmp_path):
        cache_dir = tmp_path / "P-W"
        cache_dir.mkdir()
        with patch("app.application.surface_audit_service._lane_cache_dir", return_value=cache_dir):
            result = _most_recent_prior_cache("P-W")
            assert result is None

    def test_finds_prior_cache(self, tmp_path):
        cache_dir = tmp_path / "P-W"
        cache_dir.mkdir()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        cache_file = cache_dir / f"{yesterday}.json"
        cache_file.write_text(json.dumps({"success": True}))
        with patch("app.application.surface_audit_service._lane_cache_dir", return_value=cache_dir):
            result = _most_recent_prior_cache("P-W")
            assert result is not None
            assert result == cache_file

    def test_today_cache_not_returned(self, tmp_path):
        cache_dir = tmp_path / "P-W"
        cache_dir.mkdir()
        today_file = cache_dir / f"{_today_key()}.json"
        today_file.write_text(json.dumps({"success": True}))
        with patch("app.application.surface_audit_service._lane_cache_dir", return_value=cache_dir):
            result = _most_recent_prior_cache("P-W")
            assert result is None

    def test_too_old_cache_excluded(self, tmp_path):
        cache_dir = tmp_path / "P-W"
        cache_dir.mkdir()
        old = (date.today() - timedelta(days=30)).isoformat()
        old_file = cache_dir / f"{old}.json"
        old_file.write_text(json.dumps({"success": True}))
        with (
            patch("app.application.surface_audit_service._lane_cache_dir", return_value=cache_dir),
            patch("app.application.surface_audit_service._CACHE_FALLBACK_MAX_AGE_DAYS", 14),
        ):
            result = _most_recent_prior_cache("P-W")
            assert result is None


# ========================= _adb_has_device ===============================


class TestAdbHasDevice:
    def test_adb_not_found(self, tmp_path):
        with patch("app.application.surface_audit_service._FHD_ROOT", tmp_path):
            result = _adb_has_device()
            assert result is False

    def test_adb_device_connected(self, tmp_path):
        with (
            patch("app.application.surface_audit_service._FHD_ROOT", tmp_path),
            patch("subprocess.run") as mock_run,
        ):
            # Create the adb path so is_file() returns True
            adb_path = (
                tmp_path
                / "mobile-android"
                / ".toolchain"
                / "android-sdk"
                / "platform-tools"
                / "adb"
            )
            adb_path.parent.mkdir(parents=True)
            adb_path.write_text("fake adb")

            mock_run.return_value = Mock(stdout="List of devices attached\nemulator-5554\tdevice\n")
            result = _adb_has_device()
            assert result is True

    def test_adb_no_device(self, tmp_path):
        with (
            patch("app.application.surface_audit_service._FHD_ROOT", tmp_path),
            patch("subprocess.run") as mock_run,
        ):
            adb_path = (
                tmp_path
                / "mobile-android"
                / ".toolchain"
                / "android-sdk"
                / "platform-tools"
                / "adb"
            )
            adb_path.parent.mkdir(parents=True)
            adb_path.write_text("fake adb")

            mock_run.return_value = Mock(stdout="List of devices attached\n")
            result = _adb_has_device()
            assert result is False

    def test_adb_error(self, tmp_path):
        with (
            patch("app.application.surface_audit_service._FHD_ROOT", tmp_path),
            patch("subprocess.run") as mock_run,
        ):
            adb_path = (
                tmp_path
                / "mobile-android"
                / ".toolchain"
                / "android-sdk"
                / "platform-tools"
                / "adb"
            )
            adb_path.parent.mkdir(parents=True)
            adb_path.write_text("fake adb")

            mock_run.side_effect = OSError("adb error")
            result = _adb_has_device()
            assert result is False


# ========================= _node_env =====================================


class TestNodeEnv:
    def test_default_env(self, monkeypatch):
        monkeypatch.delenv("SURFACE_AUDIT_BASE_URL", raising=False)
        monkeypatch.delenv("SURFACE_AUDIT_API_URL", raising=False)
        env = _node_env()
        assert env["SURFACE_AUDIT_BASE_URL"] == "http://127.0.0.1:5001"
        assert env["SURFACE_AUDIT_API_URL"] == "http://127.0.0.1:5000"

    def test_p_w_lane_env(self, monkeypatch):
        monkeypatch.delenv("SURFACE_AUDIT_ADMIN_BASE_URL", raising=False)
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.delenv("SURFACE_AUDIT_API_URL", raising=False)
        env = _node_env("P-W")
        # P-W should set marketing URLs
        assert "SURFACE_AUDIT_MARKETING_BASE_URL" in env

    def test_p_s_lane_env(self, monkeypatch):
        monkeypatch.delenv("SURFACE_AUDIT_USER", raising=False)
        monkeypatch.delenv("SURFACE_AUDIT_PASSWORD", raising=False)
        env = _node_env("P-S")
        assert env.get("SURFACE_AUDIT_PRODUCT_SKU") == "enterprise"
        assert env.get("SURFACE_AUDIT_INCLUDE_ENTERPRISE") == "1"

    def test_p_app_lane_env(self, monkeypatch):
        monkeypatch.delenv("SURFACE_AUDIT_USER", raising=False)
        monkeypatch.delenv("SURFACE_AUDIT_PASSWORD", raising=False)
        env = _node_env("P-App")
        assert env.get("SURFACE_AUDIT_PRODUCT_SKU") == "enterprise"
        assert "SURFACE_AUDIT_ANDROID_PACKAGE" in env

    def test_other_lane_env(self, monkeypatch):
        env = _node_env("P-Dashboard")
        assert env.get("SURFACE_AUDIT_PRODUCT_SKU") == "personal"

    def test_adb_detection(self, monkeypatch):
        monkeypatch.delenv("SURFACE_AUDIT_ANDROID", raising=False)
        monkeypatch.delenv("XCAGI_SURFACE_AUDIT_ANDROID", raising=False)
        with patch("app.application.surface_audit_service._adb_has_device", return_value=True):
            env = _node_env("P-App")
            assert env.get("SURFACE_AUDIT_ANDROID") == "1"

    def test_existing_android_env(self, monkeypatch):
        monkeypatch.setenv("SURFACE_AUDIT_ANDROID", "1")
        env = _node_env()
        assert env.get("SURFACE_AUDIT_ANDROID") == "1"


# ========================= _playwright_available =========================


class TestPlaywrightAvailable:
    def test_both_exist(self, tmp_path):
        script = tmp_path / "scripts" / "ci" / "run_surface_audit.mjs"
        script.parent.mkdir(parents=True)
        script.write_text("// script")
        pw = tmp_path / "frontend" / "node_modules" / "@playwright" / "test"
        pw.mkdir(parents=True)

        with (
            patch("app.application.surface_audit_service._SCRIPT_PATH", script),
            patch(
                "app.application.surface_audit_service._NODE_MODULES",
                tmp_path / "frontend" / "node_modules",
            ),
        ):
            result = _playwright_available()
            assert result is True

    def test_script_missing(self, tmp_path):
        pw = tmp_path / "frontend" / "node_modules" / "@playwright" / "test"
        pw.mkdir(parents=True)
        with (
            patch("app.application.surface_audit_service._SCRIPT_PATH", tmp_path / "missing.mjs"),
            patch(
                "app.application.surface_audit_service._NODE_MODULES",
                tmp_path / "frontend" / "node_modules",
            ),
        ):
            result = _playwright_available()
            assert result is False


# ========================= run_surface_audit_lane ========================


class TestRunSurfaceAuditLane:
    def test_empty_lane(self):
        result = run_surface_audit_lane("")
        assert result["success"] is False
        assert "lane 必填" in result["message"]

    def test_unknown_lane(self):
        with patch(
            "app.application.surface_audit_service._load_config",
            return_value={"lanes": {"P-W": {}}},
        ):
            result = run_surface_audit_lane("P-Unknown")
            assert result["success"] is False
            assert "未知 lane" in result["message"]

    def test_cached_result(self):
        with (
            patch(
                "app.application.surface_audit_service._load_config",
                return_value={"lanes": {"P-W": {}}},
            ),
            patch(
                "app.application.surface_audit_service._read_cache",
                return_value={"success": True, "data": "cached"},
            ),
        ):
            result = run_surface_audit_lane("P-W", refresh=False)
            assert result["success"] is True
            assert result["from_cache"] is True

    def test_playwright_not_available(self):
        with (
            patch(
                "app.application.surface_audit_service._load_config",
                return_value={"lanes": {"P-W": {}}},
            ),
            patch("app.application.surface_audit_service._read_cache", return_value=None),
            patch(
                "app.application.surface_audit_service._playwright_available", return_value=False
            ),
        ):
            result = run_surface_audit_lane("P-W", refresh=True)
            assert result["success"] is False
            assert "Playwright" in result["message"]

    def test_run_timeout(self, monkeypatch):
        monkeypatch.setenv("SURFACE_AUDIT_TIMEOUT_SEC", "1")
        with (
            patch(
                "app.application.surface_audit_service._load_config",
                return_value={"lanes": {"P-W": {}}},
            ),
            patch("app.application.surface_audit_service._read_cache", return_value=None),
            patch("app.application.surface_audit_service._playwright_available", return_value=True),
            patch("app.application.surface_audit_service._node_env", return_value={}),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="node", timeout=1)),
        ):
            result = run_surface_audit_lane("P-W", refresh=True)
            assert result["success"] is False
            assert "超时" in result["message"]

    def test_run_node_not_found(self):
        with (
            patch(
                "app.application.surface_audit_service._load_config",
                return_value={"lanes": {"P-W": {}}},
            ),
            patch("app.application.surface_audit_service._read_cache", return_value=None),
            patch("app.application.surface_audit_service._playwright_available", return_value=True),
            patch("app.application.surface_audit_service._node_env", return_value={}),
            patch("subprocess.run", side_effect=FileNotFoundError("node not found")),
        ):
            result = run_surface_audit_lane("P-W", refresh=True)
            assert result["success"] is False
            assert "node" in result["message"]

    def test_run_nonzero_exit(self):
        with (
            patch(
                "app.application.surface_audit_service._load_config",
                return_value={"lanes": {"P-W": {}}},
            ),
            patch("app.application.surface_audit_service._read_cache", return_value=None),
            patch("app.application.surface_audit_service._playwright_available", return_value=True),
            patch("app.application.surface_audit_service._node_env", return_value={}),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = Mock(returncode=1, stderr="error output", stdout="")
            result = run_surface_audit_lane("P-W", refresh=True)
            assert result["success"] is False

    def test_run_success_json_stdout(self):
        payload = {"success": True, "pages": []}
        with (
            patch(
                "app.application.surface_audit_service._load_config",
                return_value={"lanes": {"P-W": {}}},
            ),
            patch("app.application.surface_audit_service._read_cache", return_value=None),
            patch("app.application.surface_audit_service._playwright_available", return_value=True),
            patch("app.application.surface_audit_service._node_env", return_value={}),
            patch("subprocess.run") as mock_run,
            patch("app.application.surface_audit_service._write_cache") as mock_write,
        ):
            mock_run.return_value = Mock(returncode=0, stdout=json.dumps(payload), stderr="")
            result = run_surface_audit_lane("P-W", refresh=True)
            assert result["success"] is True
            assert result["from_cache"] is False
            mock_write.assert_called_once()

    def test_run_success_json_file(self, tmp_path):
        """When stdout is not valid JSON, fall back to reading the output file."""
        out_path = tmp_path / "P-W" / f"{_today_key()}.json"
        out_path.parent.mkdir(parents=True)
        out_path.write_text(json.dumps({"success": True, "pages": []}))

        with (
            patch(
                "app.application.surface_audit_service._load_config",
                return_value={"lanes": {"P-W": {}}},
            ),
            patch("app.application.surface_audit_service._read_cache", return_value=None),
            patch("app.application.surface_audit_service._playwright_available", return_value=True),
            patch("app.application.surface_audit_service._node_env", return_value={}),
            patch("app.application.surface_audit_service._cache_file", return_value=out_path),
            patch("subprocess.run") as mock_run,
            patch("app.application.surface_audit_service._write_cache"),
        ):
            mock_run.return_value = Mock(returncode=0, stdout="not json", stderr="")
            result = run_surface_audit_lane("P-W", refresh=True)
            assert result["success"] is True

    def test_run_no_json_output(self, tmp_path):
        out_path = tmp_path / "missing.json"
        with (
            patch(
                "app.application.surface_audit_service._load_config",
                return_value={"lanes": {"P-W": {}}},
            ),
            patch("app.application.surface_audit_service._read_cache", return_value=None),
            patch("app.application.surface_audit_service._playwright_available", return_value=True),
            patch("app.application.surface_audit_service._node_env", return_value={}),
            patch("app.application.surface_audit_service._cache_file", return_value=out_path),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = Mock(returncode=0, stdout="not json", stderr="")
            result = run_surface_audit_lane("P-W", refresh=True)
            assert result["success"] is False
            assert "非 JSON" in result["message"]


# ========================= get_surface_audit_lane ========================


class TestGetSurfaceAuditLane:
    def test_success_wraps_data(self):
        with patch("app.application.surface_audit_service.run_surface_audit_lane") as mock_run:
            mock_run.return_value = {"success": True, "pages": [], "from_cache": True}
            result = get_surface_audit_lane("P-W")
            assert result["success"] is True
            assert "data" in result
            assert "success" not in result.get("data", {})

    def test_failure_passthrough(self):
        with patch("app.application.surface_audit_service.run_surface_audit_lane") as mock_run:
            mock_run.return_value = {"success": False, "message": "error"}
            result = get_surface_audit_lane("P-W")
            assert result["success"] is False
            assert "message" in result


# ========================= list_configured_lanes =========================


class TestListConfiguredLanes:
    def test_with_lanes(self):
        with patch(
            "app.application.surface_audit_service._load_config",
            return_value={"lanes": {"P-W": {}, "P-App": {}}},
        ):
            result = list_configured_lanes()
            assert set(result) == {"P-W", "P-App"}

    def test_empty(self):
        with patch(
            "app.application.surface_audit_service._load_config", return_value={"lanes": {}}
        ):
            result = list_configured_lanes()
            assert result == []
