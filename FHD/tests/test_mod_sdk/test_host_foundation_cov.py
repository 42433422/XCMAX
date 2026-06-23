from __future__ import annotations

"""Branch-coverage ramp for app.mod_sdk.host_foundation.

Targets 34 missing branches (54.1% → higher) from coverage_new.json.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.mod_sdk.host_foundation import (
    AUX_EMPLOYEE_PACK_MOD_IDS,
    HOST_FOUNDATION_BUNDLE_MOD_ID,
    HOST_FOUNDATION_EMPLOYEE_PACK_ID,
    STORE_COLLECTION_HOST_FOUNDATION,
    STORE_COLLECTION_INDUSTRY_MOD,
    STORE_COLLECTION_WORKFLOW_EMPLOYEE,
    aux_employee_pack_catalog_row,
    catalog_store_collection,
    inject_aux_employee_pack_rows,
    install_aux_employee_pack_from_repo_seed,
    is_aux_employee_pack_mod_id,
    is_host_bridge_mod_id,
    is_host_foundation_employee_pack,
    is_host_foundation_pack_installed,
    is_infrastructure_mod_hidden_from_store,
    is_workflow_employee_mod_id,
    read_aux_employee_pack_manifest,
    try_materialize_host_foundation_if_needed,
)

# ===========================================================================
# 1. is_host_bridge_mod_id (lines 40-46)
# ===========================================================================


class TestIsHostBridgeMod:
    def test_empty_string_returns_false(self):
        assert is_host_bridge_mod_id("") is False

    def test_none_returns_false(self):
        assert is_host_bridge_mod_id(None) is False  # type: ignore[arg-type]

    def test_generic_host_mod_ids(self):
        from app.mod_sdk.platform_shell import GENERIC_HOST_MOD_IDS

        for mid in list(GENERIC_HOST_MOD_IDS)[:2]:
            assert is_host_bridge_mod_id(mid) is True

    def test_xcagi_bridge_suffix(self):
        assert is_host_bridge_mod_id("xcagi-foo-bridge") is True

    def test_xcagi_not_bridge_suffix(self):
        assert is_host_bridge_mod_id("xcagi-foo-other") is False

    def test_non_xcagi_prefix(self):
        assert is_host_bridge_mod_id("third-party-bridge") is False


# ===========================================================================
# 2. is_workflow_employee_mod_id (line 49-50)
# ===========================================================================


class TestIsWorkflowEmployee:
    def test_starts_with_prefix(self):
        assert is_workflow_employee_mod_id("xcagi-workflow-employee-hr") is True

    def test_no_prefix_false(self):
        assert is_workflow_employee_mod_id("other-mod") is False

    def test_empty_false(self):
        assert is_workflow_employee_mod_id("") is False


# ===========================================================================
# 3. is_infrastructure_mod_hidden_from_store (lines 53-66)
# ===========================================================================


class TestIsInfraModHidden:
    def test_empty_not_hidden(self):
        assert is_infrastructure_mod_hidden_from_store("") is False

    def test_employee_pack_not_hidden(self):
        assert is_infrastructure_mod_hidden_from_store(HOST_FOUNDATION_EMPLOYEE_PACK_ID) is False

    def test_bundle_not_hidden(self):
        assert is_infrastructure_mod_hidden_from_store(HOST_FOUNDATION_BUNDLE_MOD_ID) is False

    def test_bridge_mod_is_hidden(self):
        assert is_infrastructure_mod_hidden_from_store("xcagi-foo-bridge") is True

    def test_workflow_employee_is_hidden(self):
        assert is_infrastructure_mod_hidden_from_store("xcagi-workflow-employee-sales") is True

    def test_infrastructure_prefix_is_hidden(self):
        assert is_infrastructure_mod_hidden_from_store("xcagi-planner-bridge") is True

    def test_regular_mod_not_hidden(self):
        assert is_infrastructure_mod_hidden_from_store("my-industry-mod") is False


# ===========================================================================
# 4. is_host_foundation_employee_pack (line 69-70)
# ===========================================================================


class TestIsHostFoundationEmployeePack:
    def test_exact_match(self):
        assert is_host_foundation_employee_pack(HOST_FOUNDATION_EMPLOYEE_PACK_ID) is True

    def test_other_id(self):
        assert is_host_foundation_employee_pack("other-mod") is False

    def test_empty(self):
        assert is_host_foundation_employee_pack("") is False


# ===========================================================================
# 5. is_aux_employee_pack_mod_id (lines 79-80)
# ===========================================================================


class TestIsAuxEmployeePack:
    def test_known_ids(self):
        for mid in AUX_EMPLOYEE_PACK_MOD_IDS:
            assert is_aux_employee_pack_mod_id(mid) is True

    def test_unknown(self):
        assert is_aux_employee_pack_mod_id("unknown-pack") is False

    def test_none(self):
        assert is_aux_employee_pack_mod_id(None) is False  # type: ignore[arg-type]


# ===========================================================================
# 6. _repo_mod_seed_dirs (lines 83-103): XCAGI_ROOT env var branch
# ===========================================================================


class TestRepoModSeedDirs:
    def test_xcagi_root_env_adds_path(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        with patch.dict(os.environ, {"XCAGI_ROOT": str(tmp_path)}):
            from app.mod_sdk.host_foundation import _repo_mod_seed_dirs

            dirs = _repo_mod_seed_dirs()
        assert any(str(mods_dir) in str(d) for d in dirs)

    def test_xcagi_root_nonexistent_dir_ignored(self, tmp_path):
        with patch.dict(os.environ, {"XCAGI_ROOT": str(tmp_path / "does_not_exist")}):
            from app.mod_sdk.host_foundation import _repo_mod_seed_dirs

            dirs = _repo_mod_seed_dirs()
        # Should not crash
        assert isinstance(dirs, list)


# ===========================================================================
# 7. read_aux_employee_pack_manifest (lines 106-119)
# ===========================================================================


class TestReadAuxEmployeePackManifest:
    def test_empty_id_returns_none(self):
        assert read_aux_employee_pack_manifest("") is None

    def test_unknown_id_returns_none(self):
        assert read_aux_employee_pack_manifest("not-an-aux-pack") is None

    def test_reads_manifest_from_dir(self, tmp_path):
        pid = AUX_EMPLOYEE_PACK_MOD_IDS[0]
        mod_dir = tmp_path / pid
        mod_dir.mkdir()
        manifest = {"id": pid, "name": "Test", "version": "2.0.0"}
        (mod_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        from app.mod_sdk.host_foundation import _repo_mod_seed_dirs

        with patch.object(
            __import__("app.mod_sdk.host_foundation", fromlist=["_repo_mod_seed_dirs"]),
            "_repo_mod_seed_dirs",
            return_value=[tmp_path],
        ):
            result = read_aux_employee_pack_manifest(pid)
        assert result is not None

    def test_corrupt_manifest_returns_none(self, tmp_path):
        pid = AUX_EMPLOYEE_PACK_MOD_IDS[0]
        mod_dir = tmp_path / pid
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("not json", encoding="utf-8")

        with patch("app.mod_sdk.host_foundation._repo_mod_seed_dirs", return_value=[tmp_path]):
            result = read_aux_employee_pack_manifest(pid)
        assert result is None

    def test_manifest_is_not_dict_returns_none(self, tmp_path):
        pid = AUX_EMPLOYEE_PACK_MOD_IDS[0]
        mod_dir = tmp_path / pid
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("[1, 2, 3]", encoding="utf-8")

        with patch("app.mod_sdk.host_foundation._repo_mod_seed_dirs", return_value=[tmp_path]):
            result = read_aux_employee_pack_manifest(pid)
        assert result is None


# ===========================================================================
# 8. aux_employee_pack_catalog_row (lines 122-147)
# ===========================================================================


class TestAuxEmployeePackCatalogRow:
    def test_row_with_no_manifest(self):
        pid = AUX_EMPLOYEE_PACK_MOD_IDS[0]
        with patch(
            "app.mod_sdk.host_foundation.read_aux_employee_pack_manifest", return_value=None
        ):
            row = aux_employee_pack_catalog_row(pack_id=pid, installed=False)
        assert row["id"] == pid
        assert row["is_installed"] is False
        assert row["version"] == "1.0.0"

    def test_row_with_manifest(self):
        pid = AUX_EMPLOYEE_PACK_MOD_IDS[0]
        manifest = {
            "id": "override-id",
            "name": "My Pack",
            "version": "3.0.0",
            "author": "me",
            "description": "desc",
            "dependencies": {"a": "1"},
        }
        with patch(
            "app.mod_sdk.host_foundation.read_aux_employee_pack_manifest", return_value=manifest
        ):
            row = aux_employee_pack_catalog_row(pack_id=pid, installed=True)
        assert row["is_installed"] is True
        assert row["version"] == "3.0.0"
        assert row["dependencies"] == {"a": "1"}

    def test_row_dependencies_non_dict_defaulted(self):
        pid = AUX_EMPLOYEE_PACK_MOD_IDS[0]
        manifest = {"id": pid, "dependencies": "bad"}
        with patch(
            "app.mod_sdk.host_foundation.read_aux_employee_pack_manifest", return_value=manifest
        ):
            row = aux_employee_pack_catalog_row(pack_id=pid, installed=False)
        assert row["dependencies"] == {}


# ===========================================================================
# 9. inject_aux_employee_pack_rows (lines 150-160)
# ===========================================================================


class TestInjectAuxEmployeePackRows:
    def test_already_present_not_duplicated(self):
        # All packs already in rows → inject should not add any
        rows = [{"id": pid} for pid in AUX_EMPLOYEE_PACK_MOD_IDS]
        initial_len = len(rows)
        # Even with a valid manifest, all packs are in `seen` so none appended
        with patch(
            "app.mod_sdk.host_foundation.read_aux_employee_pack_manifest", return_value={"id": "x"}
        ):
            inject_aux_employee_pack_rows(rows, set())
        assert len(rows) == initial_len

    def test_no_manifest_not_added(self):
        rows: list = []
        with patch(
            "app.mod_sdk.host_foundation.read_aux_employee_pack_manifest", return_value=None
        ):
            inject_aux_employee_pack_rows(rows, set())
        assert rows == []

    def test_new_pack_added(self):
        rows: list = []
        pid = AUX_EMPLOYEE_PACK_MOD_IDS[0]
        with patch(
            "app.mod_sdk.host_foundation.read_aux_employee_pack_manifest", return_value={"id": pid}
        ):
            inject_aux_employee_pack_rows(rows, {pid})
        assert any(r.get("id") == pid for r in rows)


# ===========================================================================
# 10. install_aux_employee_pack_from_repo_seed (lines 163-189)
# ===========================================================================


class TestInstallAuxEmployeePackFromRepoSeed:
    def test_not_aux_pack_returns_false(self):
        ok, msg = install_aux_employee_pack_from_repo_seed("not-aux-pack")
        assert ok is False
        assert "非触点" in msg

    def test_no_seed_dir_returns_false(self):
        pid = AUX_EMPLOYEE_PACK_MOD_IDS[0]
        with patch("app.mod_sdk.host_foundation._repo_mod_seed_dirs", return_value=[]):
            ok, msg = install_aux_employee_pack_from_repo_seed(pid)
        assert ok is False
        assert "未找到" in msg

    def test_install_success(self, tmp_path):
        pid = AUX_EMPLOYEE_PACK_MOD_IDS[0]
        src_dir = tmp_path / "mods" / pid
        src_dir.mkdir(parents=True)
        (src_dir / "manifest.json").write_text('{"id": "' + pid + '"}', encoding="utf-8")

        dest_root = tmp_path / "user_mods"
        dest_root.mkdir()

        mock_mm = MagicMock()
        mock_mm.mods_root = str(dest_root)

        import app.infrastructure.mods.mod_manager as _mm_mod

        with patch(
            "app.mod_sdk.host_foundation._repo_mod_seed_dirs", return_value=[tmp_path / "mods"]
        ):
            with patch.object(_mm_mod, "get_mod_manager", return_value=mock_mm):
                ok, msg = install_aux_employee_pack_from_repo_seed(pid)
        assert ok is True
        assert pid in msg

    def test_install_oserror(self, tmp_path):
        pid = AUX_EMPLOYEE_PACK_MOD_IDS[0]
        src_dir = tmp_path / "mods" / pid
        src_dir.mkdir(parents=True)
        (src_dir / "manifest.json").write_text('{"id": "' + pid + '"}', encoding="utf-8")

        mock_mm = MagicMock()
        mock_mm.mods_root = str(tmp_path / "dest")

        import shutil

        import app.infrastructure.mods.mod_manager as _mm_mod

        with patch(
            "app.mod_sdk.host_foundation._repo_mod_seed_dirs", return_value=[tmp_path / "mods"]
        ):
            with patch.object(_mm_mod, "get_mod_manager", return_value=mock_mm):
                with patch("shutil.copytree", side_effect=OSError("no space")):
                    ok, msg = install_aux_employee_pack_from_repo_seed(pid)
        assert ok is False
        assert "no space" in msg


# ===========================================================================
# 11. catalog_store_collection (lines 192-212)
# ===========================================================================


class TestCatalogStoreCollection:
    def test_non_dict_returns_industry(self):
        assert catalog_store_collection("not-a-dict") == STORE_COLLECTION_INDUSTRY_MOD  # type: ignore[arg-type]

    def test_store_collection_field_used(self):
        row = {"store_collection": "custom_col"}
        assert catalog_store_collection(row) == "custom_col"

    def test_employee_pack_with_host_foundation_cfg(self):
        row = {"artifact": "employee_pack", "config": {"host_foundation_pack": True}}
        assert catalog_store_collection(row) == STORE_COLLECTION_HOST_FOUNDATION

    def test_employee_pack_without_host_cfg(self):
        row = {"artifact": "employee_pack", "config": {}}
        assert catalog_store_collection(row) == STORE_COLLECTION_WORKFLOW_EMPLOYEE

    def test_host_foundation_employee_pack_by_id(self):
        row = {"id": HOST_FOUNDATION_EMPLOYEE_PACK_ID}
        assert catalog_store_collection(row) == STORE_COLLECTION_HOST_FOUNDATION

    def test_workflow_employee_id(self):
        row = {"id": "xcagi-workflow-employee-hr"}
        assert catalog_store_collection(row) == STORE_COLLECTION_WORKFLOW_EMPLOYEE

    def test_infrastructure_mod_returns_empty(self):
        row = {"id": "xcagi-planner-bridge"}
        assert catalog_store_collection(row) == ""

    def test_regular_mod_returns_industry(self):
        row = {"id": "my-cool-industry-mod"}
        assert catalog_store_collection(row) == STORE_COLLECTION_INDUSTRY_MOD

    def test_employee_pack_no_config_field(self):
        row = {"artifact": "employee_pack"}
        assert catalog_store_collection(row) == STORE_COLLECTION_WORKFLOW_EMPLOYEE


# ===========================================================================
# 12. try_materialize_host_foundation_if_needed (lines 280-284)
# ===========================================================================


class TestTryMaterializeIfNeeded:
    def test_employee_not_present_returns_none(self):
        with patch(
            "app.mod_sdk.host_foundation.host_foundation_employee_present", return_value=False
        ):
            assert try_materialize_host_foundation_if_needed() is None

    def test_bridges_ready_returns_none(self):
        with patch(
            "app.mod_sdk.host_foundation.host_foundation_employee_present", return_value=True
        ):
            with patch(
                "app.mod_sdk.host_foundation.host_foundation_bridges_ready", return_value=True
            ):
                assert try_materialize_host_foundation_if_needed() is None

    def test_materialize_called_when_needed(self):
        with patch(
            "app.mod_sdk.host_foundation.host_foundation_employee_present", return_value=True
        ):
            with patch(
                "app.mod_sdk.host_foundation.host_foundation_bridges_ready", return_value=False
            ):
                with patch(
                    "app.mod_sdk.host_foundation.materialize_host_foundation_bridges",
                    return_value={"ready": True},
                ) as mock_m:
                    result = try_materialize_host_foundation_if_needed("minimal")
        mock_m.assert_called_once_with("minimal")
        assert result == {"ready": True}
