"""测试 aux_employee_store 模块 - 触点/授权类 AI 员工商店。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.mod_sdk.aux_employee_store import (
    AUX_EMPLOYEE_PACK_MOD_IDS,
    STORE_COLLECTION_WORKFLOW_EMPLOYEE,
    aux_employee_pack_catalog_row,
    inject_aux_employee_pack_rows,
    is_aux_employee_pack_mod_id,
    read_aux_employee_pack_manifest,
)


class TestIsAuxEmployeePackModId:
    """测试 is_aux_employee_pack_mod_id 函数。"""

    def test_known_ids(self):
        for mid in AUX_EMPLOYEE_PACK_MOD_IDS:
            assert is_aux_employee_pack_mod_id(mid) is True

    def test_unknown_id(self):
        assert is_aux_employee_pack_mod_id("unknown-mod") is False

    def test_empty_string(self):
        assert is_aux_employee_pack_mod_id("") is False

    def test_none(self):
        assert is_aux_employee_pack_mod_id(None) is False

    def test_whitespace(self):
        assert is_aux_employee_pack_mod_id("  ") is False

    def test_strips_whitespace(self):
        mid = AUX_EMPLOYEE_PACK_MOD_IDS[0]
        assert is_aux_employee_pack_mod_id(f"  {mid}  ") is True


class TestReadAuxEmployeePackManifest:
    """测试 read_aux_employee_pack_manifest 函数。"""

    def test_unknown_mod_id_returns_none(self):
        assert read_aux_employee_pack_manifest("unknown-mod") is None

    def test_empty_id_returns_none(self):
        assert read_aux_employee_pack_manifest("") is None

    def test_reads_manifest(self, tmp_path):
        mod_dir = tmp_path / AUX_EMPLOYEE_PACK_MOD_IDS[0]
        mod_dir.mkdir()
        manifest = {"id": AUX_EMPLOYEE_PACK_MOD_IDS[0], "name": "Test", "version": "1.0.0"}
        (mod_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
            return_value=[tmp_path],
        ):
            result = read_aux_employee_pack_manifest(AUX_EMPLOYEE_PACK_MOD_IDS[0])
            assert result is not None
            assert result["id"] == AUX_EMPLOYEE_PACK_MOD_IDS[0]

    def test_corrupted_manifest_returns_none(self, tmp_path):
        mod_dir = tmp_path / AUX_EMPLOYEE_PACK_MOD_IDS[0]
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("not json{{{", encoding="utf-8")

        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
            return_value=[tmp_path],
        ):
            result = read_aux_employee_pack_manifest(AUX_EMPLOYEE_PACK_MOD_IDS[0])
            assert result is None

    def test_non_dict_manifest_returns_none(self, tmp_path):
        mod_dir = tmp_path / AUX_EMPLOYEE_PACK_MOD_IDS[0]
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text('["not", "dict"]', encoding="utf-8")

        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
            return_value=[tmp_path],
        ):
            result = read_aux_employee_pack_manifest(AUX_EMPLOYEE_PACK_MOD_IDS[0])
            assert result is None

    def test_no_manifest_file(self, tmp_path):
        mod_dir = tmp_path / AUX_EMPLOYEE_PACK_MOD_IDS[0]
        mod_dir.mkdir()

        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
            return_value=[tmp_path],
        ):
            result = read_aux_employee_pack_manifest(AUX_EMPLOYEE_PACK_MOD_IDS[0])
            assert result is None


class TestAuxEmployeePackCatalogRow:
    """测试 aux_employee_pack_catalog_row 函数。"""

    def test_basic_row(self):
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest",
            return_value={"id": "test-id", "name": "Test", "version": "2.0.0"},
        ):
            row = aux_employee_pack_catalog_row(pack_id="test-id", installed=True)
            assert row["id"] == "test-id"
            assert row["name"] == "Test"
            assert row["version"] == "2.0.0"
            assert row["is_installed"] is True
            assert row["artifact"] == "employee_pack"
            assert row["store_collection"] == STORE_COLLECTION_WORKFLOW_EMPLOYEE

    def test_no_manifest_defaults(self):
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest",
            return_value=None,
        ):
            row = aux_employee_pack_catalog_row(pack_id="test-id", installed=False)
            assert row["id"] == "test-id"
            assert row["version"] == "1.0.0"
            assert row["is_installed"] is False
            assert row["author"] == "成都修茈科技有限公司"

    def test_commerce_field(self):
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest",
            return_value=None,
        ):
            row = aux_employee_pack_catalog_row(pack_id="test-id", installed=False)
            assert row["commerce"]["price_label"] == "免费"
            assert row["commerce"]["collection"] == STORE_COLLECTION_WORKFLOW_EMPLOYEE


class TestInjectAuxEmployeePackRows:
    """测试 inject_aux_employee_pack_rows 函数。"""

    def test_injects_new_rows(self):
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest",
            return_value={"id": AUX_EMPLOYEE_PACK_MOD_IDS[0], "name": "Test"},
        ):
            available = []
            inject_aux_employee_pack_rows(available, set())
            assert len(available) >= 1

    def test_updates_existing_row(self):
        # Only return manifest for the first pack ID
        def mock_read(pack_id, **kw):
            if pack_id == AUX_EMPLOYEE_PACK_MOD_IDS[0]:
                return {"id": pack_id, "name": "Test"}
            return None

        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest",
            side_effect=mock_read,
        ):
            existing = {
                "id": AUX_EMPLOYEE_PACK_MOD_IDS[0],
                "pkg_id": AUX_EMPLOYEE_PACK_MOD_IDS[0],
                "is_installed": True,
            }
            available = [existing]
            inject_aux_employee_pack_rows(available, set())
            # Should have updated the existing row, not added a new one
            found = [r for r in available if r.get("id") == AUX_EMPLOYEE_PACK_MOD_IDS[0]]
            assert len(found) == 1
            assert found[0]["is_installed"] is True

    def test_no_manifest_skips(self):
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest",
            return_value=None,
        ):
            available = []
            inject_aux_employee_pack_rows(available, set())
            assert len(available) == 0

    def test_installed_ids_reflected(self):
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest",
            return_value={"id": AUX_EMPLOYEE_PACK_MOD_IDS[0], "name": "Test"},
        ):
            available = []
            inject_aux_employee_pack_rows(available, {AUX_EMPLOYEE_PACK_MOD_IDS[0]})
            assert len(available) >= 1
            assert available[0]["is_installed"] is True
