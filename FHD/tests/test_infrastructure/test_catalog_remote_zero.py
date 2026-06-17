"""Tests for app.infrastructure.mods.catalog_remote."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.mods.catalog_remote import (
    catalog_base_url,
    fetch_remote_package_list,
    merge_catalog_rows,
)


class TestCatalogBaseUrl:
    """Tests for catalog_base_url."""

    def test_returns_env_value(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MOD_CATALOG_URL": "https://catalog.example.com/"}):
            result = catalog_base_url()
            assert result == "https://catalog.example.com"

    def test_returns_empty_when_not_set(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = catalog_base_url()
            assert result == ""

    def test_strips_trailing_slash(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MOD_CATALOG_URL": "https://example.com///"}):
            result = catalog_base_url()
            assert result == "https://example.com"


class TestFetchRemotePackageList:
    """Tests for fetch_remote_package_list."""

    def test_returns_empty_when_no_base_url(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = fetch_remote_package_list()
            assert result == []

    def test_returns_packages_on_success(self) -> None:
        response_data = json.dumps({"packages": [{"id": "mod1", "version": "1.0"}]}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict("os.environ", {"XCAGI_MOD_CATALOG_URL": "https://catalog.test"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = fetch_remote_package_list()
                assert len(result) == 1
                assert result[0]["id"] == "mod1"

    def test_returns_empty_on_url_error(self) -> None:
        import urllib.error

        with patch.dict("os.environ", {"XCAGI_MOD_CATALOG_URL": "https://catalog.test"}):
            with patch(
                "urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")
            ):
                result = fetch_remote_package_list()
                assert result == []

    def test_returns_empty_on_json_error(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict("os.environ", {"XCAGI_MOD_CATALOG_URL": "https://catalog.test"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = fetch_remote_package_list()
                assert result == []

    def test_filters_non_dict_packages(self) -> None:
        response_data = json.dumps({"packages": [{"id": "ok"}, "bad", 42]}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict("os.environ", {"XCAGI_MOD_CATALOG_URL": "https://catalog.test"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = fetch_remote_package_list()
                assert len(result) == 1
                assert result[0]["id"] == "ok"

    def test_returns_empty_when_packages_not_list(self) -> None:
        response_data = json.dumps({"packages": "not a list"}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict("os.environ", {"XCAGI_MOD_CATALOG_URL": "https://catalog.test"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = fetch_remote_package_list()
                assert result == []


class TestMergeCatalogRows:
    """Tests for merge_catalog_rows."""

    def test_merge_empty_lists(self) -> None:
        result = merge_catalog_rows([], [])
        assert result == []

    def test_merge_local_only(self) -> None:
        local = [{"id": "mod1", "version": "1.0", "name": "Local Mod"}]
        result = merge_catalog_rows(local, [])
        assert len(result) == 1
        assert result[0]["name"] == "Local Mod"

    def test_merge_remote_only(self) -> None:
        remote = [{"id": "mod2", "version": "2.0", "name": "Remote Mod"}]
        result = merge_catalog_rows([], remote)
        assert len(result) == 1
        assert result[0]["source"] == "remote"
        assert result[0]["package_file"] == ""

    def test_merge_both_with_no_overlap(self) -> None:
        local = [{"id": "mod1", "version": "1.0"}]
        remote = [{"id": "mod2", "version": "2.0"}]
        result = merge_catalog_rows(local, remote)
        assert len(result) == 2

    def test_merge_overlapping_keeps_local_base(self) -> None:
        local = [{"id": "mod1", "version": "1.0", "package_file": "/local/path"}]
        remote = [{"id": "mod1", "version": "1.0", "download_url": "https://dl", "sha256": "abc"}]
        result = merge_catalog_rows(local, remote)
        assert len(result) == 1
        assert result[0]["package_file"] == "/local/path"
        assert result[0]["download_url"] == "https://dl"
        assert result[0]["sha256"] == "abc"
        assert result[0]["source"] == "remote+local"

    def test_merge_without_prefer_remote_fields(self) -> None:
        local = [{"id": "mod1", "version": "1.0", "download_url": "local_url"}]
        remote = [{"id": "mod1", "version": "1.0", "download_url": "remote_url"}]
        result = merge_catalog_rows(local, remote, prefer_remote_fields=False)
        assert len(result) == 1
        assert result[0]["download_url"] == "local_url"

    def test_merge_filters_non_dict_entries(self) -> None:
        local = [{"id": "mod1", "version": "1.0"}, "bad"]
        remote = [{"id": "mod2", "version": "2.0"}, 42]
        result = merge_catalog_rows(local, remote)
        assert len(result) == 2
