"""Tests for app.infrastructure.mods.catalog_remote."""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock

from app.infrastructure.mods.catalog_remote import (
    catalog_base_url,
    fetch_remote_package_list,
    merge_catalog_rows,
)


class TestCatalogBaseUrl:
    def test_default_empty(self, monkeypatch):
        monkeypatch.delenv("XCAGI_MOD_CATALOG_URL", raising=False)
        assert catalog_base_url() == ""

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MOD_CATALOG_URL", "  https://catalog.example.com/  ")
        assert catalog_base_url() == "https://catalog.example.com"

    def test_trailing_slash_stripped(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MOD_CATALOG_URL", "https://catalog.example.com///")
        assert catalog_base_url() == "https://catalog.example.com"


class TestFetchRemotePackageList:
    def test_empty_base_url_returns_empty(self, monkeypatch):
        monkeypatch.delenv("XCAGI_MOD_CATALOG_URL", raising=False)
        assert fetch_remote_package_list() == []

    @patch("app.infrastructure.mods.catalog_remote.urllib.request.urlopen")
    def test_successful_fetch(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("XCAGI_MOD_CATALOG_URL", "https://catalog.example.com")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"packages": [{"id": "mod1", "version": "1.0"}]}
        ).encode("utf-8")
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_remote_package_list()
        assert len(result) == 1
        assert result[0]["id"] == "mod1"

    @patch("app.infrastructure.mods.catalog_remote.urllib.request.urlopen")
    def test_invalid_json_returns_empty(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("XCAGI_MOD_CATALOG_URL", "https://catalog.example.com")
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_remote_package_list()
        assert result == []

    @patch("app.infrastructure.mods.catalog_remote.urllib.request.urlopen")
    def test_network_error_returns_empty(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("XCAGI_MOD_CATALOG_URL", "https://catalog.example.com")
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("network error")
        result = fetch_remote_package_list()
        assert result == []


class TestMergeCatalogRows:
    def test_empty_both(self):
        assert merge_catalog_rows([], []) == []

    def test_local_only(self):
        local = [{"id": "mod1", "version": "1.0", "package_file": "mod1.zip"}]
        result = merge_catalog_rows(local, [])
        assert len(result) == 1
        assert result[0]["id"] == "mod1"

    def test_remote_only(self):
        remote = [{"id": "mod2", "version": "2.0", "download_url": "https://..."}]
        result = merge_catalog_rows([], remote)
        assert len(result) == 1
        assert result[0]["source"] == "remote"

    def test_merge_dedup_by_id_version(self):
        local = [{"id": "mod1", "version": "1.0", "package_file": "mod1.zip"}]
        remote = [{"id": "mod1", "version": "1.0", "download_url": "https://..."}]
        result = merge_catalog_rows(local, remote)
        assert len(result) == 1
        assert result[0]["package_file"] == "mod1.zip"
        assert result[0]["download_url"] == "https://..."
        assert result[0]["source"] == "remote+local"

    def test_different_versions_not_deduped(self):
        local = [{"id": "mod1", "version": "1.0"}]
        remote = [{"id": "mod1", "version": "2.0"}]
        result = merge_catalog_rows(local, remote)
        assert len(result) == 2

    def test_prefer_remote_fields_false(self):
        local = [{"id": "mod1", "version": "1.0", "download_url": "local-url"}]
        remote = [{"id": "mod1", "version": "1.0", "download_url": "remote-url"}]
        result = merge_catalog_rows(local, remote, prefer_remote_fields=False)
        assert len(result) == 1
        assert result[0]["download_url"] == "local-url"

    def test_non_dict_entries_skipped(self):
        local = ["not a dict", {"id": "mod1", "version": "1.0"}]
        remote = [42, {"id": "mod2", "version": "1.0"}]
        result = merge_catalog_rows(local, remote)
        assert len(result) == 2

    def test_remote_fields_preferred(self):
        local = [{"id": "mod1", "version": "1.0", "sha256": "local_hash"}]
        remote = [{"id": "mod1", "version": "1.0", "sha256": "remote_hash", "tags": ["new"]}]
        result = merge_catalog_rows(local, remote, prefer_remote_fields=True)
        assert result[0]["sha256"] == "remote_hash"
        assert result[0]["tags"] == ["new"]
