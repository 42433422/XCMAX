"""测试 app.mod_sdk.aux_employee_store 的分支覆盖。

覆盖目标：
- is_aux_employee_pack_mod_id（空 / 非 mod id / 命中）
- _repo_mod_seed_dirs（mods 存在 / XCAGI_MODS_ROOT / XCAGI_ROOT / 去重）
- read_aux_employee_pack_manifest（空 pid / 非 mod id / 文件不存在 / JSON 错误 / 正常）
- aux_employee_pack_catalog_row（manifest None / 默认值 / dependencies 非 dict）
- inject_aux_employee_pack_rows（已存在替换 / 新增 / 无 manifest 跳过）
- install_aux_employee_pack_from_repo_seed（非 mod id / 未找到 / 已存在 dest / OSError）
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.mod_sdk import aux_employee_store


class TestIsAuxEmployeePackModId:
    """is_aux_employee_pack_mod_id 分支覆盖。"""

    def test_returns_true_for_known_mod_ids(self) -> None:
        assert aux_employee_store.is_aux_employee_pack_mod_id("wechat-contacts-ai-employee") is True
        assert aux_employee_store.is_aux_employee_pack_mod_id("lan-gate-ai-employee") is True

    def test_returns_false_for_unknown_mod_id(self) -> None:
        assert aux_employee_store.is_aux_employee_pack_mod_id("unknown-mod") is False

    def test_returns_false_for_empty_string(self) -> None:
        assert aux_employee_store.is_aux_employee_pack_mod_id("") is False

    def test_returns_false_for_none(self) -> None:
        assert aux_employee_store.is_aux_employee_pack_mod_id(None) is False

    def test_strips_whitespace(self) -> None:
        assert aux_employee_store.is_aux_employee_pack_mod_id("  wechat-contacts-ai-employee  ") is True


class TestRepoModSeedDirs:
    """_repo_mod_seed_dirs 分支覆盖。"""

    def test_returns_list_without_env_vars(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = aux_employee_store._repo_mod_seed_dirs()
            assert isinstance(result, list)

    def test_includes_xcagi_mods_root_when_set(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": str(tmp_path)}):
            result = aux_employee_store._repo_mod_seed_dirs()
            assert any(str(tmp_path) in str(p) for p in result)

    def test_includes_xcagi_root_mods_when_set(self, tmp_path: Path) -> None:
        # XCAGI_ROOT 需要指向一个包含 mods 子目录的路径
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        with patch.dict("os.environ", {"XCAGI_ROOT": str(tmp_path)}):
            result = aux_employee_store._repo_mod_seed_dirs()
            assert any(str(tmp_path) in str(p) for p in result)

    def test_skips_nonexistent_dirs(self) -> None:
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": "/nonexistent/path/xyz"}):
            result = aux_employee_store._repo_mod_seed_dirs()
            for p in result:
                assert "/nonexistent/path/xyz" not in str(p)

    def test_dedupes_paths(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": str(tmp_path)}):
            result = aux_employee_store._repo_mod_seed_dirs()
            resolved = [str(p.resolve()) for p in result]
            assert len(resolved) == len(set(resolved))


class TestReadAuxEmployeePackManifest:
    """read_aux_employee_pack_manifest 分支覆盖。"""

    def test_returns_none_for_empty_pid(self) -> None:
        assert aux_employee_store.read_aux_employee_pack_manifest("") is None

    def test_returns_none_for_none_pid(self) -> None:
        assert aux_employee_store.read_aux_employee_pack_manifest(None) is None

    def test_returns_none_for_unknown_mod_id(self) -> None:
        assert aux_employee_store.read_aux_employee_pack_manifest("unknown-mod") is None

    def test_returns_none_when_no_manifest_found(self) -> None:
        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs", return_value=[Path("/nonexistent")]
        ):
            assert (
                aux_employee_store.read_aux_employee_pack_manifest("wechat-contacts-ai-employee")
                is None
            )

    def test_returns_manifest_when_valid(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "wechat-contacts-ai-employee"
        mod_dir.mkdir()
        manifest = {"id": "wechat-contacts-ai-employee", "version": "1.0.0"}
        (mod_dir / "manifest.json").write_text(json.dumps(manifest))
        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs", return_value=[tmp_path]
        ):
            result = aux_employee_store.read_aux_employee_pack_manifest("wechat-contacts-ai-employee")
            assert result == manifest

    def test_returns_none_when_manifest_not_dict(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "wechat-contacts-ai-employee"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps(["not a dict"]))
        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs", return_value=[tmp_path]
        ):
            assert (
                aux_employee_store.read_aux_employee_pack_manifest("wechat-contacts-ai-employee")
                is None
            )

    def test_returns_none_on_json_error(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "wechat-contacts-ai-employee"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("invalid json {")
        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs", return_value=[tmp_path]
        ):
            assert (
                aux_employee_store.read_aux_employee_pack_manifest("wechat-contacts-ai-employee")
                is None
            )

    def test_skips_missing_manifest_in_first_root(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "second" / "wechat-contacts-ai-employee"
        mod_dir.mkdir(parents=True)
        manifest = {"id": "wechat-contacts-ai-employee"}
        (mod_dir / "manifest.json").write_text(json.dumps(manifest))
        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
            return_value=[tmp_path / "first", tmp_path / "second"],
        ):
            result = aux_employee_store.read_aux_employee_pack_manifest("wechat-contacts-ai-employee")
            assert result == manifest


class TestAuxEmployeePackCatalogRow:
    """aux_employee_pack_catalog_row 分支覆盖。"""

    def test_uses_manifest_values_when_present(self) -> None:
        manifest = {
            "id": "wechat-contacts-ai-employee",
            "name": "WeChat Contacts",
            "version": "2.0.0",
            "author": "Custom Author",
            "description": "A pack",
            "dependencies": {"dep1": "1.0"},
        }
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest", return_value=manifest
        ):
            row = aux_employee_store.aux_employee_pack_catalog_row(
                pack_id="wechat-contacts-ai-employee", installed=True
            )
            assert row["id"] == "wechat-contacts-ai-employee"
            assert row["name"] == "WeChat Contacts"
            assert row["version"] == "2.0.0"
            assert row["author"] == "Custom Author"
            assert row["description"] == "A pack"
            assert row["is_installed"] is True
            assert row["dependencies"] == {"dep1": "1.0"}

    def test_uses_defaults_when_manifest_none(self) -> None:
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest", return_value=None
        ):
            row = aux_employee_store.aux_employee_pack_catalog_row(
                pack_id="wechat-contacts-ai-employee", installed=False
            )
            assert row["id"] == "wechat-contacts-ai-employee"
            assert row["name"] == "wechat-contacts-ai-employee"
            assert row["version"] == "1.0.0"
            assert row["author"] == "成都修茈科技有限公司"
            assert row["description"] == ""
            assert row["is_installed"] is False
            assert row["dependencies"] == {}

    def test_dependencies_defaults_to_empty_when_not_dict(self) -> None:
        manifest = {"id": "x", "dependencies": "not a dict"}
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest", return_value=manifest
        ):
            row = aux_employee_store.aux_employee_pack_catalog_row(
                pack_id="wechat-contacts-ai-employee", installed=True
            )
            assert row["dependencies"] == {}

    def test_falls_back_to_pack_id_when_manifest_id_empty(self) -> None:
        manifest = {"id": "", "version": ""}
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest", return_value=manifest
        ):
            row = aux_employee_store.aux_employee_pack_catalog_row(
                pack_id="wechat-contacts-ai-employee", installed=True
            )
            assert row["id"] == "wechat-contacts-ai-employee"
            assert row["version"] == "1.0.0"


class TestInjectAuxEmployeePackRows:
    """inject_aux_employee_pack_rows 分支覆盖。"""

    def test_appends_new_row_when_not_present(self) -> None:
        # 两个 pack_id 都需要返回 manifest
        manifest = {"id": "wechat-contacts-ai-employee", "name": "WeChat"}
        manifest2 = {"id": "lan-gate-ai-employee", "name": "LanGate"}
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest",
            side_effect=lambda pid: manifest if pid == "wechat-contacts-ai-employee" else manifest2,
        ):
            available: list[dict] = []
            aux_employee_store.inject_aux_employee_pack_rows(available, set())
            assert len(available) == 2
            ids = {r["id"] for r in available}
            assert "wechat-contacts-ai-employee" in ids
            assert "lan-gate-ai-employee" in ids

    def test_replaces_existing_row_preserving_is_installed(self) -> None:
        manifest = {"id": "wechat-contacts-ai-employee", "name": "WeChat"}
        existing = {
            "id": "wechat-contacts-ai-employee",
            "name": "Old Name",
            "is_installed": True,
            "extra_field": "keep",
        }
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest", return_value=manifest
        ):
            available = [existing]
            aux_employee_store.inject_aux_employee_pack_rows(available, set())
            assert len(available) == 2
            row = next(r for r in available if r["id"] == "wechat-contacts-ai-employee")
            assert row["name"] == "WeChat"
            assert row["is_installed"] is True

    def test_skips_when_no_manifest(self) -> None:
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest", return_value=None
        ):
            available: list[dict] = []
            aux_employee_store.inject_aux_employee_pack_rows(available, set())
            assert available == []

    def test_marks_installed_when_in_installed_ids(self) -> None:
        manifest = {"id": "wechat-contacts-ai-employee"}
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest", return_value=manifest
        ):
            available: list[dict] = []
            aux_employee_store.inject_aux_employee_pack_rows(
                available, {"wechat-contacts-ai-employee"}
            )
            row = next(r for r in available if r["id"] == "wechat-contacts-ai-employee")
            assert row["is_installed"] is True

    def test_handles_existing_row_not_dict(self) -> None:
        manifest = {"id": "wechat-contacts-ai-employee"}
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest", return_value=manifest
        ):
            available: list[dict] = [{"id": "wechat-contacts-ai-employee"}]  # type: ignore[list-item]
            aux_employee_store.inject_aux_employee_pack_rows(available, set())
            assert len(available) == 2

    def test_uses_pkg_id_when_id_missing(self) -> None:
        manifest = {"id": "wechat-contacts-ai-employee"}
        with patch(
            "app.mod_sdk.aux_employee_store.read_aux_employee_pack_manifest", return_value=manifest
        ):
            available = [{"pkg_id": "wechat-contacts-ai-employee", "is_installed": False}]
            aux_employee_store.inject_aux_employee_pack_rows(available, set())
            assert len(available) == 2


class TestInstallAuxEmployeePackFromRepoSeed:
    """install_aux_employee_pack_from_repo_seed 分支覆盖。"""

    def test_returns_false_for_non_mod_id(self) -> None:
        ok, msg = aux_employee_store.install_aux_employee_pack_from_repo_seed("unknown-mod")
        assert ok is False
        assert "非触点员工包" in msg

    def test_returns_false_for_empty_pid(self) -> None:
        ok, msg = aux_employee_store.install_aux_employee_pack_from_repo_seed("")
        assert ok is False
        assert "非触点员工包" in msg

    def test_returns_false_when_seed_not_found(self) -> None:
        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
            return_value=[Path("/nonexistent")],
        ):
            ok, msg = aux_employee_store.install_aux_employee_pack_from_repo_seed(
                "wechat-contacts-ai-employee"
            )
            assert ok is False
            assert "未找到" in msg

    def test_install_success(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "mods" / "wechat-contacts-ai-employee"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "wechat-contacts-ai-employee"}))
        (mod_dir / "code.py").write_text("x = 1")

        dest_dir = tmp_path / "dest" / "wechat-contacts-ai-employee"
        mock_mm = MagicMock()
        mock_mm.mods_root = str(tmp_path / "dest")

        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
            return_value=[tmp_path / "mods"],
        ), patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mock_mm
        ):
            ok, msg = aux_employee_store.install_aux_employee_pack_from_repo_seed(
                "wechat-contacts-ai-employee"
            )
            assert ok is True
            assert "已从内置种子安装" in msg
            assert dest_dir.exists()
            mock_mm.load_all_mods.assert_called_once()

    def test_install_overwrites_existing_dest(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "mods" / "wechat-contacts-ai-employee"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "wechat-contacts-ai-employee"}))

        dest_dir = tmp_path / "dest" / "wechat-contacts-ai-employee"
        dest_dir.mkdir(parents=True)
        (dest_dir / "old.txt").write_text("old")

        mock_mm = MagicMock()
        mock_mm.mods_root = str(tmp_path / "dest")

        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
            return_value=[tmp_path / "mods"],
        ), patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mock_mm
        ):
            ok, msg = aux_employee_store.install_aux_employee_pack_from_repo_seed(
                "wechat-contacts-ai-employee"
            )
            assert ok is True
            assert not (dest_dir / "old.txt").exists()

    def test_install_handles_os_error(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "mods" / "wechat-contacts-ai-employee"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "wechat-contacts-ai-employee"}))

        mock_mm = MagicMock()
        mock_mm.mods_root = str(tmp_path / "dest")

        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
            return_value=[tmp_path / "mods"],
        ), patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mock_mm
        ), patch("app.mod_sdk.aux_employee_store.shutil.copytree", side_effect=OSError("copy failed")):
            ok, msg = aux_employee_store.install_aux_employee_pack_from_repo_seed(
                "wechat-contacts-ai-employee"
            )
            assert ok is False
            assert "copy failed" in msg
