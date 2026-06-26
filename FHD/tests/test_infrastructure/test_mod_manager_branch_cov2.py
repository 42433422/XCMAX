"""测试 app.infrastructure.mods.mod_manager 的分支覆盖。

覆盖目标：
- is_mods_disabled（env var 多值）
- _short_exc_message（空 / 短 / 长 / 类型名回退）
- _invoke_mod_init_hook（无参 / app / mod_id / 必填不可满足 / signature 异常）
- ModManager.invalidate_scan_cache
- ModManager._record_load_failure / record_blueprint_failure / getters
- ModManager._metadata_to_api_dict（各字段分支）
- ModManager._mods_scan_fingerprint（目录不存在 / listdir 异常 / mtime 异常）
- ModManager._refresh_mods_root_if_needed（env 有效 / env 无效 / 当前路径不存在）
- mount_on_disk_primary_client_mods（返回空列表）
- _mod_allowed_for_api_load（空 / 过滤未激活 / 可见 / 异常）
- _backend_path_for_mod
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.mods.mod_manager import (
    ModManager,
    _all_mods_roots,
    _backend_path_for_mod,
    _invoke_mod_init_hook,
    _mod_allowed_for_api_load,
    _short_exc_message,
    is_mods_disabled,
    mount_on_disk_primary_client_mods,
)


class TestIsModsDisabled:
    """is_mods_disabled 分支覆盖。"""

    def test_not_set_returns_false(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert is_mods_disabled() is False

    def test_set_to_1_returns_true(self) -> None:
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "1"}):
            assert is_mods_disabled() is True

    def test_set_to_true_returns_true(self) -> None:
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "true"}):
            assert is_mods_disabled() is True

    def test_set_to_yes_returns_true(self) -> None:
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "yes"}):
            assert is_mods_disabled() is True

    def test_set_to_on_returns_true(self) -> None:
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "on"}):
            assert is_mods_disabled() is True

    def test_set_to_false_returns_false(self) -> None:
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "false"}):
            assert is_mods_disabled() is False

    def test_set_to_empty_returns_false(self) -> None:
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": ""}):
            assert is_mods_disabled() is False

    def test_case_insensitive(self) -> None:
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "TRUE"}):
            assert is_mods_disabled() is True

    def test_whitespace_stripped(self) -> None:
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "  true  "}):
            assert is_mods_disabled() is True


class TestShortExcMessage:
    """_short_exc_message 分支覆盖。"""

    def test_short_message_preserved(self) -> None:
        exc = ValueError("short error")
        assert _short_exc_message(exc) == "short error"

    def test_empty_message_uses_type_name(self) -> None:
        exc = ValueError()
        assert _short_exc_message(exc) == "ValueError"

    def test_whitespace_only_uses_type_name(self) -> None:
        exc = ValueError("   ")
        assert _short_exc_message(exc) == "ValueError"

    def test_long_message_truncated(self) -> None:
        exc = ValueError("x" * 600)
        result = _short_exc_message(exc, max_len=100)
        assert len(result) == 100
        assert result.endswith("...")

    def test_custom_max_len(self) -> None:
        exc = ValueError("x" * 200)
        result = _short_exc_message(exc, max_len=50)
        assert len(result) == 50
        assert result.endswith("...")

    def test_exact_max_len_not_truncated(self) -> None:
        exc = ValueError("x" * 47)
        result = _short_exc_message(exc, max_len=50)
        assert result == "x" * 47


class TestInvokeModInitHook:
    """_invoke_mod_init_hook 分支覆盖。"""

    def test_no_params_calls_directly(self) -> None:
        called = []

        def init_fn() -> None:
            called.append(True)

        _invoke_mod_init_hook(init_fn, mod_id="test")
        assert called == [True]

    def test_app_param_passed_as_none(self) -> None:
        received: list = []

        def init_fn(app=None) -> None:
            received.append(app)

        _invoke_mod_init_hook(init_fn, mod_id="test")
        assert received == [None]

    def test_mod_id_param_passed(self) -> None:
        received: list = []

        def init_fn(mod_id=None) -> None:
            received.append(mod_id)

        _invoke_mod_init_hook(init_fn, mod_id="my-mod")
        assert received == ["my-mod"]

    def test_app_and_mod_id_params(self) -> None:
        received: dict = {}

        def init_fn(app=None, mod_id=None) -> None:
            received["app"] = app
            received["mod_id"] = mod_id

        _invoke_mod_init_hook(init_fn, mod_id="my-mod")
        assert received == {"app": None, "mod_id": "my-mod"}

    def test_required_unsatisfiable_param_skips(self) -> None:
        called: list = []

        def init_fn(unknown_required) -> None:
            called.append(True)

        _invoke_mod_init_hook(init_fn, mod_id="test")
        assert called == []

    def test_optional_param_not_required(self) -> None:
        called: list = []

        def init_fn(optional_param="default") -> None:
            called.append(optional_param)

        _invoke_mod_init_hook(init_fn, mod_id="test")
        assert called == ["default"]

    def test_signature_exception_falls_back_to_direct_call(self) -> None:
        called: list = []

        # A builtin or C function that doesn't have a signature
        def init_fn(*args, **kwargs) -> None:
            called.append(True)

        _invoke_mod_init_hook(init_fn, mod_id="test")
        assert called == [True]

    def test_required_unknown_param_skips(self) -> None:
        called: list = []

        def init_fn(app=None, mod_id=None, *, extra) -> None:
            called.append(True)

        # extra is required (no default) and not app/mod_id → skip
        _invoke_mod_init_hook(init_fn, mod_id="test")
        assert called == []

    def test_bind_typeerror_falls_back_to_direct_call(self) -> None:
        called: list = []

        def init_fn(app=None, /) -> None:
            called.append(True)

        # app is positional-only with default; sig.bind(app=None) raises TypeError
        # → falls back to init_fn() which succeeds (app defaults to None)
        _invoke_mod_init_hook(init_fn, mod_id="test")
        assert called == [True]


class TestBackendPathForMod:
    """_backend_path_for_mod 分支覆盖。"""

    def test_returns_backend_subpath(self) -> None:
        assert _backend_path_for_mod("/mods/my-mod") == os.path.join("/mods/my-mod", "backend")

    def test_empty_path(self) -> None:
        assert _backend_path_for_mod("") == os.path.join("", "backend")


class TestModManagerScanFingerprint:
    """ModManager._mods_scan_fingerprint 分支覆盖。"""

    def test_empty_roots(self) -> None:
        mm = ModManager(mods_root="/nonexistent")
        with patch.object(mm, "all_mods_roots", return_value=[]):
            fp = mm._mods_scan_fingerprint()
            assert fp == ""

    def test_root_not_dir(self) -> None:
        mm = ModManager(mods_root="/nonexistent")
        with patch.object(mm, "all_mods_roots", return_value=["/nonexistent/path"]):
            fp = mm._mods_scan_fingerprint()
            assert "/nonexistent/path" in fp

    def test_root_with_manifest(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "my-mod"
        mod_dir.mkdir()
        manifest = mod_dir / "manifest.json"
        manifest.write_text('{"id": "my-mod"}')
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            fp = mm._mods_scan_fingerprint()
            assert "my-mod" in fp

    def test_skips_underscore_entries(self, tmp_path: Path) -> None:
        (tmp_path / "_internal").mkdir()
        (tmp_path / "_internal" / "manifest.json").write_text("{}")
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            fp = mm._mods_scan_fingerprint()
            assert "_internal" not in fp

    def test_listdir_oserror_handled(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]), \
             patch("os.listdir", side_effect=OSError("denied")):
            fp = mm._mods_scan_fingerprint()
            assert str(tmp_path) in fp

    def test_getmtime_oserror_handled(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "my-mod"
        mod_dir.mkdir()
        manifest = mod_dir / "manifest.json"
        manifest.write_text("{}")
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]), \
             patch("os.path.getmtime", side_effect=OSError("denied")):
            fp = mm._mods_scan_fingerprint()
            assert "my-mod" in fp


class TestModManagerInvalidateScanCache:
    """ModManager.invalidate_scan_cache 分支覆盖。"""

    def test_clears_cache(self) -> None:
        mm = ModManager(mods_root="/tmp")
        mm._scan_cache_fp = "old_fp"
        mm._scan_cache_mods = ["old"]
        mm.invalidate_scan_cache()
        assert mm._scan_cache_fp == ""
        assert mm._scan_cache_mods == []


class TestModManagerFailureRecording:
    """ModManager failure recording 分支覆盖。"""

    def test_record_load_failure(self) -> None:
        mm = ModManager(mods_root="/tmp")
        mm._record_load_failure("mod1", "fs", "dir not found")
        failures = mm.get_recent_load_failures()
        assert len(failures) == 1
        assert failures[0]["mod_id"] == "mod1"
        assert failures[0]["stage"] == "fs"
        assert failures[0]["message"] == "dir not found"

    def test_record_load_failure_truncates_long_message(self) -> None:
        mm = ModManager(mods_root="/tmp")
        long_msg = "x" * 600
        mm._record_load_failure("mod1", "fs", long_msg)
        failures = mm.get_recent_load_failures()
        assert len(failures[0]["message"]) == 500

    def test_record_blueprint_failure(self) -> None:
        mm = ModManager(mods_root="/tmp")
        mm.record_blueprint_failure("mod1", "blueprint error")
        failures = mm.get_blueprint_failures()
        assert len(failures) == 1
        assert failures[0]["mod_id"] == "mod1"
        assert failures[0]["message"] == "blueprint error"

    def test_record_blueprint_failure_truncates(self) -> None:
        mm = ModManager(mods_root="/tmp")
        mm.record_blueprint_failure("mod1", "x" * 600)
        failures = mm.get_blueprint_failures()
        assert len(failures[0]["message"]) == 500

    def test_get_scan_manifest_errors_initially_empty(self) -> None:
        mm = ModManager(mods_root="/tmp")
        assert mm.get_scan_manifest_errors() == []


class TestMetadataToApiDict:
    """ModManager._metadata_to_api_dict 分支覆盖。"""

    def test_basic_metadata(self) -> None:
        from app.infrastructure.mods.manifest import ModMetadata

        m = ModMetadata(
            id="test-mod",
            name="Test Mod",
            version="1.0.0",
            mod_path="/mods/test-mod",
        )
        row = ModManager._metadata_to_api_dict(m)
        assert row["id"] == "test-mod"
        assert row["name"] == "Test Mod"
        assert row["version"] == "1.0.0"
        assert row["author"] == ""
        assert row["description"] == ""
        assert row["primary"] is False
        assert row["industry"] == {}
        assert row["ui_labels"] == {}
        assert row["ui_starter_pack"] == []
        assert row["menu"] == []
        assert row["menu_overrides"] == []
        assert row["workflow_employees"] == []
        assert row["comms_exports"] == []

    def test_with_all_fields(self) -> None:
        from app.infrastructure.mods.manifest import ModMetadata

        m = ModMetadata(
            id="full-mod",
            name="Full Mod",
            version="2.0.0",
            author="Author",
            description="A full mod",
            primary=True,
            mod_path="/mods/full-mod",
            industry={"type": "retail"},
            ui_labels={"title": "Full"},
            ui_starter_pack=["pack1"],
            frontend_menu=[{"label": "Menu", "path": "/menu"}],
            frontend_menu_overrides=[{"key": "val"}],
            workflow_employees=["emp1"],
            comms_exports=["export1"],
        )
        row = ModManager._metadata_to_api_dict(m)
        assert row["author"] == "Author"
        assert row["description"] == "A full mod"
        assert row["primary"] is True
        assert row["industry"] == {"type": "retail"}
        assert row["ui_labels"] == {"title": "Full"}
        assert row["ui_starter_pack"] == ["pack1"]
        assert len(row["menu"]) == 1
        assert len(row["menu_overrides"]) == 1
        assert row["workflow_employees"] == ["emp1"]
        assert row["comms_exports"] == ["export1"]

    def test_bundle_artifact_adds_type(self) -> None:
        from app.infrastructure.mods.manifest import ModMetadata

        m = ModMetadata(
            id="bundle-mod",
            name="Bundle",
            version="1.0.0",
            mod_path="/mods/bundle-mod",
            artifact="bundle",
        )
        row = ModManager._metadata_to_api_dict(m)
        assert row.get("type") == "bundle"

    def test_non_bundle_no_type(self) -> None:
        from app.infrastructure.mods.manifest import ModMetadata

        m = ModMetadata(
            id="regular-mod",
            name="Regular",
            version="1.0.0",
            mod_path="/mods/regular-mod",
        )
        row = ModManager._metadata_to_api_dict(m)
        assert "type" not in row


class TestRefreshModsRootIfNeeded:
    """ModManager._refresh_mods_root_if_needed 分支覆盖。"""

    def test_env_valid_updates_root(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root="/old/path")
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": str(tmp_path)}):
            mm._refresh_mods_root_if_needed()
            assert mm.mods_root == str(tmp_path)

    def test_env_invalid_keeps_current(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": "/nonexistent/path"}):
            mm._refresh_mods_root_if_needed()
            assert mm.mods_root == str(tmp_path)

    def test_env_empty_and_current_missing_re_resolves(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root="/nonexistent/old")
        with patch.dict("os.environ", {}, clear=True), \
             patch("app.infrastructure.mods.mod_manager._default_mods_root", return_value=str(tmp_path)):
            mm._refresh_mods_root_if_needed()
            assert mm.mods_root == str(tmp_path)

    def test_env_empty_and_current_valid_keeps(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict("os.environ", {}, clear=True):
            mm._refresh_mods_root_if_needed()
            assert mm.mods_root == str(tmp_path)

    def test_env_xcagi_mods_dir_also_checked(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root="/old")
        with patch.dict("os.environ", {"XCAGI_MODS_DIR": str(tmp_path)}, clear=True):
            mm._refresh_mods_root_if_needed()
            assert mm.mods_root == str(tmp_path)


class TestMountOnDiskPrimaryClientMods:
    """mount_on_disk_primary_client_mods 分支覆盖。"""

    def test_returns_empty_list(self) -> None:
        result = mount_on_disk_primary_client_mods()
        assert result == []

    def test_with_mod_manager_arg(self) -> None:
        mm = ModManager(mods_root="/tmp")
        result = mount_on_disk_primary_client_mods(mm)
        assert result == []


class TestModAllowedForApiLoad:
    """_mod_allowed_for_api_load 分支覆盖。"""

    def test_empty_mod_id_returns_false(self) -> None:
        assert _mod_allowed_for_api_load("") is False
        assert _mod_allowed_for_api_load("   ") is False

    def test_filter_not_active_returns_true(self) -> None:
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=False):
            assert _mod_allowed_for_api_load("any-mod") is True

    def test_filter_active_and_visible_returns_true(self) -> None:
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True), \
             patch("app.enterprise.mod_entitlements.is_mod_visible_for_enterprise", return_value=True):
            assert _mod_allowed_for_api_load("visible-mod") is True

    def test_filter_active_and_not_visible_returns_false(self) -> None:
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True), \
             patch("app.enterprise.mod_entitlements.is_mod_visible_for_enterprise", return_value=False):
            assert _mod_allowed_for_api_load("hidden-mod") is False

    def test_import_error_returns_false(self) -> None:
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", side_effect=ImportError("no module")):
            assert _mod_allowed_for_api_load("any-mod") is False

    def test_runtime_error_returns_false(self) -> None:
        with patch("app.enterprise.mod_entitlements.enterprise_mod_filter_active", side_effect=RuntimeError("fail")):
            assert _mod_allowed_for_api_load("any-mod") is False


class TestAllModsRoots:
    """_all_mods_roots 分支覆盖。"""

    def test_primary_valid_added(self, tmp_path: Path) -> None:
        with patch("app.infrastructure.mods.mod_manager._repo_layout_mods_candidates", return_value=[]):
            result = _all_mods_roots(str(tmp_path))
            assert str(tmp_path) in result

    def test_primary_invalid_not_added(self) -> None:
        with patch("app.infrastructure.mods.mod_manager._repo_layout_mods_candidates", return_value=[]):
            result = _all_mods_roots("/nonexistent")
            assert "/nonexistent" not in result

    def test_env_root_added(self, tmp_path: Path) -> None:
        env_dir = tmp_path / "env-mods"
        env_dir.mkdir()
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": str(env_dir)}), \
             patch("app.infrastructure.mods.mod_manager._repo_layout_mods_candidates", return_value=[]):
            result = _all_mods_roots(str(tmp_path))
            assert str(env_dir) in result

    def test_dedup(self, tmp_path: Path) -> None:
        with patch("app.infrastructure.mods.mod_manager._repo_layout_mods_candidates", return_value=[str(tmp_path)]):
            result = _all_mods_roots(str(tmp_path))
            assert result.count(str(tmp_path)) == 1

    def test_repo_candidates_appended(self, tmp_path: Path) -> None:
        other = tmp_path / "other-mods"
        other.mkdir()
        with patch("app.infrastructure.mods.mod_manager._repo_layout_mods_candidates", return_value=[str(other)]):
            result = _all_mods_roots(str(tmp_path))
            assert str(other) in result
            assert str(tmp_path) in result


class TestModManagerResolveModDirectory:
    """ModManager.resolve_mod_directory 分支覆盖。"""

    def test_empty_mod_id_returns_none(self) -> None:
        mm = ModManager(mods_root="/tmp")
        assert mm.resolve_mod_directory("") is None

    def test_whitespace_mod_id_returns_none(self) -> None:
        mm = ModManager(mods_root="/tmp")
        assert mm.resolve_mod_directory("   ") is None

    def test_direct_hit(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "my-mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text('{"id": "my-mod"}')
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm.resolve_mod_directory("my-mod")
            assert result is not None
            assert "my-mod" in result

    def test_no_manifest_returns_none(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "no-manifest"
        mod_dir.mkdir()
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm.resolve_mod_directory("no-manifest")
            assert result is None

    def test_not_dir_returns_none(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm.resolve_mod_directory("nonexistent")
            assert result is None

    def test_canonical_alias_resolution(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "canonical-id"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text('{"id": "canonical-id"}')
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]), \
             patch("app.mod_sdk.industry_mod_aliases.canonical_mod_id", return_value="canonical-id"), \
             patch("app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for", return_value=[]):
            result = mm.resolve_mod_directory("legacy-id")
            assert result is not None
            assert "canonical-id" in result

    def test_legacy_id_resolution(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "legacy-mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text('{"id": "legacy-mod"}')
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]), \
             patch("app.mod_sdk.industry_mod_aliases.canonical_mod_id", return_value="some-id"), \
             patch("app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for", return_value=["legacy-mod"]):
            result = mm.resolve_mod_directory("some-id")
            assert result is not None
            assert "legacy-mod" in result


class TestModManagerListModsDisabled:
    """ModManager.list_all_mods / get_routes / list_mods 分支覆盖。"""

    def test_list_all_mods_disabled_returns_empty(self) -> None:
        mm = ModManager(mods_root="/tmp")
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            assert mm.list_all_mods() == []

    def test_get_routes_disabled_returns_empty(self) -> None:
        mm = ModManager(mods_root="/tmp")
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            assert mm.get_routes() == []

    def test_list_mods_delegates_to_list_all_mods(self) -> None:
        mm = ModManager(mods_root="/tmp")
        with patch.object(mm, "list_all_mods", return_value=[{"id": "x"}]) as mock:
            result = mm.list_mods()
            assert result == [{"id": "x"}]
            mock.assert_called_once()
