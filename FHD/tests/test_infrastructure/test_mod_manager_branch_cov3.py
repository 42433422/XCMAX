"""测试 app.infrastructure.mods.mod_manager 的分支覆盖（第 3 轮）。

覆盖目标（未在 cov2 / cov / ext* 中覆盖的分支）：
- _default_mods_root（env 无效 / 包相对路径 / cwd mods / 向上查找 / 兜底）
- _repo_layout_mods_candidates（多候选 / 去重）
- import_mod_backend_py（文件缺失 / spec None / loader None / 已缓存模块）
- _register_mod_hooks（无 hooks / 无 mod_path / backend. 前缀 / 无效 spec / 不可调用 / 成功 / 异常）
- ModManager.ensure_mods_loaded（disabled / 已加载 / 无 discovered / 节流 / 最大尝试 / 异常）
- ModManager._scan_mods_from_build_index（无索引 / JSON 错 / 指纹不匹配 / rows 非 list / row 非 dict / mod_path 缺 / manifest 缺 / 重复 id / 命中）
- ModManager.scan_mods（缓存命中 / build index 命中 / 根不存在 / _ 前缀 / 非 dir / manifest 解析失败）
- ModManager.load_mod（SKU 阻断 / 已加载同步 / 路径缺失 / manifest 无效 / bundle 已注册 / bundle 注册成功 / bundle 注册 False / 依赖未满足 / 后端错误）
- ModManager._load_mod_backend（无 backend 目录 / entry 加载 / init TypeError / RECOVERABLE 重抛）
- ModManager.unload_mod（instance cleanup / cleanup 异常 / comms 异常）
- ModManager.install_mod_package（签名错 / 包错 / 缺 id / SKU 阻断 / 已存在更新 / 激活加载成功 / 激活加载失败 / 不激活 / RECOVERABLE）
- ModManager.uninstall_mod（未加载 employee_pack / employee_pack 卸载 / 已加载 unload / remove_files / RECOVERABLE）
- ModManager.update_mod（未安装 / 已加载 / 解压失败重载 / 加载成功 / 加载失败 / 未加载 / RECOVERABLE）
- ModManager.validate_mod_package（非文件 / 非 zip / 缺 id / 缺字段 / bundle / employee_pack / 后端入口缺失 / 前端路由缺失 / 通过 / ModPackageError / RECOVERABLE）
- ModManager.list_all_mods（disabled / employee registry 异常 / enterprise filter 异常）
- ModManager.get_routes（disabled / enterprise filter 异常 / routes 空 / 命中）
- ModManager.load_all_mods（enterprise 跳过 / 依赖未满足 / 加载失败 / 排序）
- register_employee_pack_routes（空 pid / disabled / 无 manifest / JSON 错 / 非 employee_pack / 无 entry / 无 resolved_id / import 错 / 无 register_fastapi_routes / 成功）
- load_employee_pack_routes（disabled / 无 emp_root / 非 dir / 无 manifest / JSON 错 / 非 employee_pack / 无 pack_id / 注册）
- _register_single_mod_http_routes（空 mid / 已注册 / 无 metadata / 无 backend_entry / 无 mod_path / module None / register_fastapi_routes / register_websocket_routes / ws False / ws True / registered / 无 registrar / RECOVERABLE）
- _restore_entitlements_from_session_id（空 sid / restore 异常 / cached 空 / cached 命中）
- ensure_mod_api_ready（空 mid / disabled / 不允许 / 加载失败 / 已注册 / 获取 app 失败 / 注册路由）
- load_mod_routes（无 mod_manager / 注册路由 / 加载 employee pack）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.mods.manifest import ModMetadata
from app.infrastructure.mods.mod_manager import (
    ModManager,
    _default_mods_root,
    _register_mod_hooks,
    _repo_layout_mods_candidates,
    _restore_entitlements_from_session_id,
    ensure_mod_api_ready,
    import_mod_backend_py,
    load_employee_pack_routes,
    load_mod_routes,
    register_employee_pack_routes,
)
from app.infrastructure.mods.package import ModPackageError, ModSignatureError

# ---------------------------------------------------------------------------
# _default_mods_root
# ---------------------------------------------------------------------------


class TestDefaultModsRoot:
    """_default_mods_root 分支覆盖。"""

    def test_env_set_but_not_directory_falls_through(self, tmp_path: Path) -> None:
        """env 设置但非目录 → 走包相对路径。"""
        # Create a mods dir at the package-relative location so the function returns it
        fake_file = tmp_path / "app" / "infrastructure" / "mods" / "mod_manager.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_text("")
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()

        with (
            patch.dict("os.environ", {"XCAGI_MODS_ROOT": "/nonexistent/xyz"}, clear=False),
            patch("app.infrastructure.mods.mod_manager.__file__", str(fake_file)),
        ):
            result = _default_mods_root()
            assert isinstance(result, str)
            # Should fall through env (invalid) and find package-relative mods
            assert result.endswith("mods")

    def test_env_valid_directory_returned(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": str(tmp_path)}, clear=False):
            result = _default_mods_root()
            assert os.path.abspath(str(tmp_path)) == result

    def test_env_xcagi_mods_dir_valid(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {"XCAGI_MODS_DIR": str(tmp_path)}, clear=False),
            patch.dict("os.environ", {"XCAGI_MODS_ROOT": ""}, clear=False),
        ):
            result = _default_mods_root()
            assert os.path.abspath(str(tmp_path)) == result

    def test_package_relative_path_exists(self, tmp_path: Path) -> None:
        """包相对路径存在时返回它。"""
        # 构造一个 fake __file__ 路径，使包相对路径指向 tmp_path/mods
        fake_file = tmp_path / "app" / "infrastructure" / "mods" / "mod_manager.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_text("")
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("app.infrastructure.mods.mod_manager.__file__", str(fake_file)),
        ):
            result = _default_mods_root()
            assert mods_dir.exists()
            # 应返回包相对路径
            assert result.endswith("mods")

    def test_cwd_mods_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """包相对路径不存在，但 cwd/mods 存在。"""
        fake_file = tmp_path / "deep" / "app" / "infrastructure" / "mods" / "mod_manager.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_text("")

        cwd_mods = tmp_path / "mods"
        cwd_mods.mkdir()

        monkeypatch.chdir(tmp_path)
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("app.infrastructure.mods.mod_manager.__file__", str(fake_file)),
        ):
            result = _default_mods_root()
            assert "mods" in result

    def test_walk_up_finds_mods(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """向上 8 级查找 mods 目录。"""
        fake_file = (
            tmp_path / "a" / "b" / "c" / "d" / "app" / "infrastructure" / "mods" / "mod_manager.py"
        )
        fake_file.parent.mkdir(parents=True)
        fake_file.write_text("")

        deep_cwd = tmp_path / "a" / "b" / "c" / "d" / "e" / "f"
        deep_cwd.mkdir(parents=True)
        # 在 tmp_path/a/b 创建 mods
        walk_mods = tmp_path / "a" / "b" / "mods"
        walk_mods.mkdir()

        monkeypatch.chdir(deep_cwd)
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("app.infrastructure.mods.mod_manager.__file__", str(fake_file)),
        ):
            result = _default_mods_root()
            assert "mods" in result

    def test_walk_up_reaches_root_returns_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """向上查找到达根目录仍无 mods → 返回包相对路径（兜底）。"""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        fake_file = sandbox / "app" / "infrastructure" / "mods" / "mod_manager.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_text("")

        empty_dir = sandbox / "empty"
        empty_dir.mkdir()
        monkeypatch.chdir(empty_dir)

        # Patch os.path.isdir to return False for any "mods" path, forcing fallback
        real_isdir = os.path.isdir

        def _fake_isdir(p: str) -> bool:
            if isinstance(p, str) and p.endswith("mods"):
                return False
            return real_isdir(p)

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("app.infrastructure.mods.mod_manager.__file__", str(fake_file)),
            patch("os.path.isdir", side_effect=_fake_isdir),
        ):
            result = _default_mods_root()
            assert isinstance(result, str)
            assert result.endswith("mods")


# ---------------------------------------------------------------------------
# _repo_layout_mods_candidates
# ---------------------------------------------------------------------------


class TestRepoLayoutModsCandidates:
    """_repo_layout_mods_candidates 分支覆盖。"""

    def test_returns_list(self) -> None:
        result = _repo_layout_mods_candidates()
        assert isinstance(result, list)

    def test_includes_existing_mods_dirs(self, tmp_path: Path) -> None:
        fake_file = tmp_path / "app" / "infrastructure" / "mods" / "mod_manager.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_text("")
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()

        with patch("app.infrastructure.mods.mod_manager.__file__", str(fake_file)):
            result = _repo_layout_mods_candidates()
            assert any("mods" in p for p in result)

    def test_dedupes_candidates(self, tmp_path: Path) -> None:
        fake_file = tmp_path / "app" / "infrastructure" / "mods" / "mod_manager.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_text("")
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()

        with patch("app.infrastructure.mods.mod_manager.__file__", str(fake_file)):
            result = _repo_layout_mods_candidates()
            # 无重复
            assert len(result) == len(set(result))


# ---------------------------------------------------------------------------
# import_mod_backend_py
# ---------------------------------------------------------------------------


class TestImportModBackendPy:
    """import_mod_backend_py 分支覆盖。"""

    def test_file_missing_raises_filenotfound(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="backend file missing"):
            import_mod_backend_py(str(tmp_path), "my-mod", "nonexistent")

    def test_spec_none_raises_importerror(self, tmp_path: Path) -> None:
        """spec_from_file_location 返回 None → ImportError。"""
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        entry_file = backend_dir / "entry.py"
        entry_file.write_text("# empty")

        with patch("importlib.util.spec_from_file_location", return_value=None):
            with pytest.raises(ImportError, match="Cannot load spec"):
                import_mod_backend_py(str(tmp_path), "my-mod", "entry")

    def test_loader_none_raises_importerror(self, tmp_path: Path) -> None:
        """spec.loader 为 None → ImportError。"""
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        entry_file = backend_dir / "entry.py"
        entry_file.write_text("# empty")

        fake_spec = MagicMock()
        fake_spec.loader = None
        with patch("importlib.util.spec_from_file_location", return_value=fake_spec):
            with pytest.raises(ImportError, match="Cannot load spec"):
                import_mod_backend_py(str(tmp_path), "my-mod", "entry")

    def test_existing_module_returned_from_cache(self, tmp_path: Path) -> None:
        """sys.modules 已有同名模块 → 直接返回，不重新 exec。"""
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        entry_file = backend_dir / "entry.py"
        entry_file.write_text("VALUE = 42\n")

        # 首次加载
        mod1 = import_mod_backend_py(str(tmp_path), "cached-mod", "entry")
        assert mod1.VALUE == 42

        # 修改文件内容，再次加载应返回缓存（不重新 exec）
        entry_file.write_text("VALUE = 99\n")
        mod2 = import_mod_backend_py(str(tmp_path), "cached-mod", "entry")
        assert mod2 is mod1
        assert mod2.VALUE == 42  # 仍是旧值

    def test_successful_load_executes_module(self, tmp_path: Path) -> None:
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        entry_file = backend_dir / "myentry.py"
        entry_file.write_text("CONSTANT = 'hello'\n\ndef my_func():\n    return 'world'\n")

        mod = import_mod_backend_py(str(tmp_path), "test-mod", "myentry")
        assert mod.CONSTANT == "hello"
        assert mod.my_func() == "world"

    def test_special_chars_in_mod_id_sanitized(self, tmp_path: Path) -> None:
        """mod_id 含特殊字符 → 安全化为下划线。"""
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        entry_file = backend_dir / "entry.py"
        entry_file.write_text("X = 1\n")

        mod = import_mod_backend_py(str(tmp_path), "my.mod-id@v1", "entry")
        assert mod.X == 1


# ---------------------------------------------------------------------------
# _register_mod_hooks
# ---------------------------------------------------------------------------


class TestRegisterModHooks:
    """_register_mod_hooks 分支覆盖。"""

    def test_no_hooks_returns_early(self) -> None:
        m = ModMetadata(id="m", name="M", version="1.0.0", mod_path="/mods/m")
        # hooks 为空 dict → 直接返回
        _register_mod_hooks("m", m)  # 不应抛异常

    def test_no_mod_path_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        m = ModMetadata(
            id="m",
            name="M",
            version="1.0.0",
            mod_path="",
            hooks={"event": "handler.fn"},
        )
        with caplog.at_level("ERROR"):
            _register_mod_hooks("m", m)
        assert any("no mod_path" in r.message for r in caplog.records)

    def test_backend_prefix_stripped(self, tmp_path: Path) -> None:
        """spec 以 backend. 开头 → 去除前缀后仍能正确解析。"""
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        entry_file = backend_dir / "hooks.py"
        entry_file.write_text("def on_event():\n    return 'ok'\n")

        m = ModMetadata(
            id="m",
            name="M",
            version="1.0.0",
            mod_path=str(tmp_path),
            hooks={"event": "backend.hooks.on_event"},
        )

        with patch("app.infrastructure.mods.hooks.subscribe") as mock_sub:
            _register_mod_hooks("m", m)
            mock_sub.assert_called_once()
            args = mock_sub.call_args[0]
            assert args[0] == "event"
            assert callable(args[1])
            assert args[1]() == "ok"

    def test_invalid_spec_no_module_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """spec 无点号 → module_name 为空 → 记录错误。"""
        m = ModMetadata(
            id="m",
            name="M",
            version="1.0.0",
            mod_path="/mods/m",
            hooks={"event": "no_dot_spec"},
        )
        with caplog.at_level("ERROR"):
            _register_mod_hooks("m", m)
        assert any("Invalid hook handler spec" in r.message for r in caplog.records)

    def test_handler_not_callable_logs_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        entry_file = backend_dir / "hooks.py"
        entry_file.write_text("not_callable = 42\n")

        m = ModMetadata(
            id="m",
            name="M",
            version="1.0.0",
            mod_path=str(tmp_path),
            hooks={"event": "hooks.not_callable"},
        )

        with caplog.at_level("ERROR"):
            _register_mod_hooks("m", m)
        assert any("not callable" in r.message for r in caplog.records)

    def test_successful_subscription(self, tmp_path: Path) -> None:
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        entry_file = backend_dir / "hooks.py"
        entry_file.write_text("def on_event():\n    return 'handled'\n")

        m = ModMetadata(
            id="m",
            name="M",
            version="1.0.0",
            mod_path=str(tmp_path),
            hooks={"event": "hooks.on_event"},
        )

        with patch("app.infrastructure.mods.hooks.subscribe") as mock_sub:
            _register_mod_hooks("m", m)
            mock_sub.assert_called_once()
            args = mock_sub.call_args[0]
            assert args[0] == "event"
            assert callable(args[1])

    def test_recoverable_error_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """import_mod_backend_py 抛 RECOVERABLE_ERRORS → 记录错误。"""
        m = ModMetadata(
            id="m",
            name="M",
            version="1.0.0",
            mod_path=str(tmp_path),
            hooks={"event": "hooks.on_event"},
        )

        with (
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                side_effect=OSError("disk error"),
            ),
            caplog.at_level("ERROR"),
        ):
            _register_mod_hooks("m", m)
        assert any("Failed to register hook" in r.message for r in caplog.records)

    def test_empty_spec_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        """spec 为空字符串 → strip 后为空 → 触发 invalid spec 分支。"""
        m = ModMetadata(
            id="m",
            name="M",
            version="1.0.0",
            mod_path="/mods/m",
            hooks={"event": "   "},
        )
        with caplog.at_level("ERROR"):
            _register_mod_hooks("m", m)
        assert any("Invalid hook handler spec" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# ModManager.ensure_mods_loaded
# ---------------------------------------------------------------------------


class TestEnsureModsLoaded:
    """ModManager.ensure_mods_loaded 分支覆盖。"""

    def test_disabled_returns_early(self) -> None:
        mm = ModManager(mods_root="/tmp")
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            with patch.object(mm, "_refresh_mods_root_if_needed") as ref:
                mm.ensure_mods_loaded(app=None)
                ref.assert_not_called()

    def test_already_loaded_returns_early(self) -> None:
        mm = ModManager(mods_root="/tmp")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "list_loaded_mods", return_value=[MagicMock()]) as llm,
            patch.object(mm, "scan_mods") as sm,
        ):
            mm.ensure_mods_loaded(app=None)
            llm.assert_called_once()
            sm.assert_not_called()

    def test_no_discovered_returns(self) -> None:
        mm = ModManager(mods_root="/tmp")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[]),
            patch.object(mm, "load_all_mods") as lam,
        ):
            mm.ensure_mods_loaded(app=None)
            lam.assert_not_called()

    def test_throttle_within_window_returns(self) -> None:
        """上次尝试在 1.5s 内 → 节流返回。"""
        import time

        mm = ModManager(mods_root="/tmp")
        mm._last_ensure_at = time.monotonic()  # 刚刚
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[MagicMock()]),
            patch.object(mm, "load_all_mods") as lam,
        ):
            mm.ensure_mods_loaded(app=None)
            lam.assert_not_called()

    def test_max_attempts_reached_returns(self) -> None:
        mm = ModManager(mods_root="/tmp")
        mm._ensure_attempts = 20
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[MagicMock()]),
            patch.object(mm, "load_all_mods") as lam,
        ):
            mm.ensure_mods_loaded(app=None)
            lam.assert_not_called()

    def test_successful_load_calls_load_all_and_routes(self) -> None:
        mm = ModManager(mods_root="/tmp")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[MagicMock()]),
            patch.object(mm, "load_all_mods") as lam,
            patch("app.infrastructure.mods.mod_manager.load_mod_routes") as lmr,
        ):
            mm.ensure_mods_loaded(app="myapp")
            lam.assert_called_once()
            lmr.assert_called_once_with("myapp", mm)

    def test_recoverable_error_swallowed(self) -> None:
        mm = ModManager(mods_root="/tmp")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed", side_effect=OSError("boom")),
        ):
            # 不应抛异常
            mm.ensure_mods_loaded(app=None)


# ---------------------------------------------------------------------------
# ModManager._scan_mods_from_build_index
# ---------------------------------------------------------------------------


class TestScanModsFromBuildIndex:
    """ModManager._scan_mods_from_build_index 分支覆盖。"""

    def test_no_index_file_returns_none(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            assert mm._scan_mods_from_build_index("fp1") is None

    def test_index_json_parse_error_returns_none(self, tmp_path: Path) -> None:
        index_path = tmp_path / "mods-index.json"
        index_path.write_text("not json {{{")
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            assert mm._scan_mods_from_build_index("fp1") is None

    def test_fingerprint_mismatch_returns_none(self, tmp_path: Path) -> None:
        index_path = tmp_path / "mods-index.json"
        index_path.write_text(json.dumps({"fingerprint": "other_fp", "mods": []}))
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            assert mm._scan_mods_from_build_index("fp1") is None

    def test_rows_not_list_returns_none(self, tmp_path: Path) -> None:
        index_path = tmp_path / "mods-index.json"
        index_path.write_text(json.dumps({"fingerprint": "fp1", "mods": "not_list"}))
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            assert mm._scan_mods_from_build_index("fp1") is None

    def test_row_not_dict_skipped(self, tmp_path: Path) -> None:
        index_path = tmp_path / "mods-index.json"
        index_path.write_text(
            json.dumps({"fingerprint": "fp1", "mods": ["not_dict", {"mod_path": ""}]})
        )
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            assert mm._scan_mods_from_build_index("fp1") is None

    def test_mod_path_missing_manifest_skipped(self, tmp_path: Path) -> None:
        index_path = tmp_path / "mods-index.json"
        index_path.write_text(
            json.dumps(
                {"fingerprint": "fp1", "mods": [{"mod_path": str(tmp_path / "no_manifest")}]}
            )
        )
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            assert mm._scan_mods_from_build_index("fp1") is None

    def test_successful_index_hit(self, tmp_path: Path) -> None:
        # 创建一个真实的 mod 目录
        mod_dir = tmp_path / "indexed-mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "indexed-mod", "name": "Indexed"}))

        index_path = tmp_path / "mods-index.json"
        index_path.write_text(
            json.dumps({"fingerprint": "fp1", "mods": [{"mod_path": str(mod_dir)}]})
        )
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm._scan_mods_from_build_index("fp1")
            assert result is not None
            assert len(result) == 1
            assert result[0].id == "indexed-mod"

    def test_duplicate_id_deduped(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "dup-mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "dup-mod", "name": "Dup"}))

        index_path = tmp_path / "mods-index.json"
        index_path.write_text(
            json.dumps(
                {
                    "fingerprint": "fp1",
                    "mods": [
                        {"mod_path": str(mod_dir)},
                        {"mod_path": str(mod_dir)},  # 重复
                    ],
                }
            )
        )
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm._scan_mods_from_build_index("fp1")
            assert result is not None
            assert len(result) == 1


# ---------------------------------------------------------------------------
# ModManager.scan_mods
# ---------------------------------------------------------------------------


class TestScanModsCacheAndIndex:
    """ModManager.scan_mods 缓存与索引分支覆盖。"""

    def test_cache_hit_returns_cached(self) -> None:
        mm = ModManager(mods_root="/tmp")
        mm._scan_cache_fp = "cached_fp"
        cached_mod = MagicMock()
        mm._scan_cache_mods = [cached_mod]
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_mods_scan_fingerprint", return_value="cached_fp"),
        ):
            result = mm.scan_mods(use_cache=True)
            assert len(result) == 1
            assert result[0] is cached_mod

    def test_build_index_hit(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "idx-mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "idx-mod", "name": "Idx"}))

        index_path = tmp_path / "mods-index.json"
        index_path.write_text(
            json.dumps({"fingerprint": "fp1", "mods": [{"mod_path": str(mod_dir)}]})
        )

        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_mods_scan_fingerprint", return_value="fp1"),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
        ):
            result = mm.scan_mods(use_cache=True)
            assert len(result) == 1
            assert result[0].id == "idx-mod"
            # 缓存被写入
            assert mm._scan_cache_fp == "fp1"

    def test_use_cache_false_skips_index(self, tmp_path: Path) -> None:
        """use_cache=False → 不查 build index。"""
        mod_dir = tmp_path / "live-mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "live-mod", "name": "Live"}))

        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_mods_scan_fingerprint", return_value="fp1"),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
            patch.object(mm, "_scan_mods_from_build_index") as sbi,
        ):
            result = mm.scan_mods(use_cache=False)
            sbi.assert_not_called()
            assert len(result) == 1
            assert result[0].id == "live-mod"

    def test_root_not_dir_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_mods_scan_fingerprint", return_value="fp1"),
            patch.object(mm, "all_mods_roots", return_value=["/nonexistent/xyz"]),
            patch.object(mm, "_scan_mods_from_build_index", return_value=None),
        ):
            with caplog.at_level("WARNING"):
                result = mm.scan_mods()
            assert result == []
            assert any("does not exist" in r.message for r in caplog.records)

    def test_underscore_entry_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "_internal").mkdir()
        (tmp_path / "_internal" / "manifest.json").write_text(json.dumps({"id": "internal"}))
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_mods_scan_fingerprint", return_value="fp1"),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
            patch.object(mm, "_scan_mods_from_build_index", return_value=None),
        ):
            result = mm.scan_mods()
            assert result == []

    def test_non_dir_entry_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_text("not a dir")
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_mods_scan_fingerprint", return_value="fp1"),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
            patch.object(mm, "_scan_mods_from_build_index", return_value=None),
        ):
            result = mm.scan_mods()
            assert result == []

    def test_manifest_parse_failed_records_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        mod_dir = tmp_path / "broken-mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("not json {{{")
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_mods_scan_fingerprint", return_value="fp1"),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
            patch.object(mm, "_scan_mods_from_build_index", return_value=None),
        ):
            with caplog.at_level("WARNING"):
                result = mm.scan_mods()
            assert result == []
            errors = mm.get_scan_manifest_errors()
            assert len(errors) == 1
            assert errors[0]["entry"] == "broken-mod"

    def test_duplicate_id_across_roots_skipped(self, tmp_path: Path) -> None:
        root1 = tmp_path / "root1"
        root2 = tmp_path / "root2"
        root1.mkdir()
        root2.mkdir()
        for root in (root1, root2):
            mod_dir = root / "same-mod"
            mod_dir.mkdir()
            (mod_dir / "manifest.json").write_text(json.dumps({"id": "same-mod", "name": "Same"}))

        mm = ModManager(mods_root=str(root1))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_mods_scan_fingerprint", return_value="fp1"),
            patch.object(mm, "all_mods_roots", return_value=[str(root1), str(root2)]),
            patch.object(mm, "_scan_mods_from_build_index", return_value=None),
        ):
            result = mm.scan_mods()
            assert len(result) == 1
            assert result[0].id == "same-mod"


# ---------------------------------------------------------------------------
# ModManager.load_mod
# ---------------------------------------------------------------------------


class TestLoadModBranches:
    """ModManager.load_mod 分支覆盖。"""

    def test_sku_blocked_returns_false(self) -> None:
        mm = ModManager(mods_root="/tmp")
        with patch(
            "app.mod_sdk.product_skus.assert_mod_allowed_for_sku",
            side_effect=PermissionError("not allowed"),
        ):
            assert mm.load_mod("blocked-mod") is False
            failures = mm.get_recent_load_failures()
            assert any(f["stage"] == "sku_policy" for f in failures)

    def test_already_loaded_syncs_loaded_list(self) -> None:
        """注册表已有 metadata 但 _loaded_mods 漏记 → 同步列表。"""
        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(id="loaded-mod", name="Loaded", version="1.0.0")
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = meta
            gr.return_value = reg
            assert mm.load_mod("loaded-mod") is True
            assert "loaded-mod" in mm._loaded_mods

    def test_mod_path_not_found_returns_false(self) -> None:
        mm = ModManager(mods_root="/tmp")
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = None
            gr.return_value = reg
            with patch.object(mm, "resolve_mod_directory", return_value=None):
                assert mm.load_mod("missing-mod") is False
                failures = mm.get_recent_load_failures()
                assert any(f["stage"] == "fs" for f in failures)

    def test_manifest_invalid_returns_false(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / "bad-manifest"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("not json {{{")
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = None
            gr.return_value = reg
            with patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)):
                assert mm.load_mod("bad-mod") is False
                failures = mm.get_recent_load_failures()
                assert any(f["stage"] == "manifest" for f in failures)

    def test_bundle_already_registered_returns_true(self) -> None:
        """bundle artifact 且注册表已有 → 返回 True。"""
        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(
            id="bundle-mod",
            name="Bundle",
            version="1.0.0",
            mod_path="/mods/bundle",
            artifact="bundle",
        )
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="bundle"),
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = meta  # 已注册
            gr.return_value = reg
            with patch.object(mm, "resolve_mod_directory", return_value="/mods/bundle"):
                assert mm.load_mod("bundle-mod") is True

    def test_bundle_register_success(self) -> None:
        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(
            id="bundle-mod",
            name="Bundle",
            version="1.0.0",
            mod_path="/mods/bundle",
            artifact="bundle",
        )
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="bundle"),
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = None  # 未注册
            reg.register_mod.return_value = True
            gr.return_value = reg
            with patch.object(mm, "resolve_mod_directory", return_value="/mods/bundle"):
                assert mm.load_mod("bundle-mod") is True
                assert "bundle-mod" in mm._loaded_mods
                reg.register_mod.assert_called_once_with(meta)

    def test_bundle_register_false_still_returns_true(self) -> None:
        """bundle register_mod 返回 False → 仍返回 True（兼容历史）。"""
        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(
            id="bundle-mod",
            name="Bundle",
            version="1.0.0",
            mod_path="/mods/bundle",
            artifact="bundle",
        )
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="bundle"),
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = None
            reg.register_mod.return_value = False  # 注册失败
            gr.return_value = reg
            with patch.object(mm, "resolve_mod_directory", return_value="/mods/bundle"):
                assert mm.load_mod("bundle-mod") is True

    def test_dependencies_not_satisfied_returns_false(self) -> None:
        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(
            id="dep-mod",
            name="Dep",
            version="1.0.0",
            mod_path="/mods/dep",
            dependencies={"other-mod": ">=1.0.0"},
        )
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="mod"),
            patch("app.infrastructure.mods.mod_manager.validate_dependencies", return_value=False),
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = None
            reg.list_mod_ids.return_value = []
            gr.return_value = reg
            with patch.object(mm, "resolve_mod_directory", return_value="/mods/dep"):
                assert mm.load_mod("dep-mod") is False
                failures = mm.get_recent_load_failures()
                assert any(f["stage"] == "dependencies" for f in failures)

    def test_backend_error_returns_false(self) -> None:
        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(
            id="backend-mod",
            name="Backend",
            version="1.0.0",
            mod_path="/mods/backend",
        )
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="mod"),
            patch("app.infrastructure.mods.mod_manager.validate_dependencies", return_value=True),
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = None
            reg.list_mod_ids.return_value = []
            gr.return_value = reg
            with (
                patch.object(mm, "_load_mod_backend", side_effect=OSError("backend boom")),
                patch.object(mm, "resolve_mod_directory", return_value="/mods/backend"),
            ):
                assert mm.load_mod("backend-mod") is False
                failures = mm.get_recent_load_failures()
                assert any(f["stage"] == "backend" for f in failures)

    def test_successful_load_with_effective_id(self) -> None:
        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(
            id="real-id",
            name="Real",
            version="1.0.0",
            mod_path="/mods/real",
        )
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="mod"),
            patch("app.infrastructure.mods.mod_manager.validate_dependencies", return_value=True),
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = None
            reg.list_mod_ids.return_value = []
            gr.return_value = reg
            with (
                patch.object(mm, "_load_mod_backend") as lb,
                patch.object(mm, "resolve_mod_directory", return_value="/mods/real"),
            ):
                assert mm.load_mod("requested-id") is True
                lb.assert_called_once()
                # effective_id 是 meta.id 而非 mod_id
                assert "real-id" in mm._loaded_mods


# ---------------------------------------------------------------------------
# ModManager._load_mod_backend
# ---------------------------------------------------------------------------


class TestLoadModBackendBranches:
    """ModManager._load_mod_backend 分支覆盖。"""

    def test_no_backend_dir_returns_early(self, tmp_path: Path) -> None:
        """mod_path 下无 backend 目录 → 直接返回。"""
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="m", name="M", version="1.0.0", mod_path=str(tmp_path))
        # 不创建 backend 目录
        mm._load_mod_backend("m", str(tmp_path), meta)
        # 无异常即通过

    def test_backend_entry_loads_and_inits(self, tmp_path: Path) -> None:
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        entry_file = backend_dir / "entry.py"
        entry_file.write_text("def init():\n    return 'inited'\n")

        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(
            id="m",
            name="M",
            version="1.0.0",
            mod_path=str(tmp_path),
            backend_entry="entry",
            backend_init="init",
        )
        mm._load_mod_backend("m", str(tmp_path), meta)
        assert "m" in mm._backend_entry_modules
        assert mm._backend_entry_modules["m"].init() == "inited"

    def test_init_typeerror_logged(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        entry_file = backend_dir / "entry.py"
        entry_file.write_text(
            "def init(app, mod_id, extra):\n    return 'inited'\n"  # extra 必填不可满足
        )

        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(
            id="m",
            name="M",
            version="1.0.0",
            mod_path=str(tmp_path),
            backend_entry="entry",
            backend_init="init",
        )
        with caplog.at_level("WARNING"):
            mm._load_mod_backend("m", str(tmp_path), meta)
        # init 因不可满足参数被跳过，但不应抛异常

    def test_recoverable_error_reraises(self, tmp_path: Path) -> None:
        """backend_entry 加载抛 RECOVERABLE_ERRORS → 重新抛出。"""
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(
            id="m",
            name="M",
            version="1.0.0",
            mod_path=str(tmp_path),
            backend_entry="entry",
            backend_init="init",
        )
        with patch(
            "app.infrastructure.mods.mod_manager.import_mod_backend_py",
            side_effect=OSError("load boom"),
        ):
            with pytest.raises(OSError, match="load boom"):
                mm._load_mod_backend("m", str(tmp_path), meta)

    def test_no_backend_entry_skips_load(self, tmp_path: Path) -> None:
        """backend 目录存在但 metadata.backend_entry 为空 → 跳过加载。"""
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir()
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(
            id="m",
            name="M",
            version="1.0.0",
            mod_path=str(tmp_path),
            backend_entry="",
        )
        mm._load_mod_backend("m", str(tmp_path), meta)
        assert "m" not in mm._backend_entry_modules


# ---------------------------------------------------------------------------
# ModManager.unload_mod
# ---------------------------------------------------------------------------


class TestUnloadModBranches:
    """ModManager.unload_mod 分支覆盖。"""

    def test_instance_cleanup_called(self) -> None:
        mm = ModManager(mods_root="/tmp")
        mm._loaded_mods.append("m")
        instance = MagicMock()
        instance.cleanup = MagicMock()
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_instance.return_value = instance
            gr.return_value = reg
            with patch("app.infrastructure.mods.comms.get_mod_comms") as gc:
                comms = MagicMock()
                gc.return_value = comms
                assert mm.unload_mod("m") is True
                instance.cleanup.assert_called_once()
                comms.unregister_all.assert_called_once_with("m")
        assert "m" not in mm._loaded_mods

    def test_cleanup_error_swallowed(self, caplog: pytest.LogCaptureFixture) -> None:
        mm = ModManager(mods_root="/tmp")
        mm._loaded_mods.append("m")
        instance = MagicMock()
        instance.cleanup = MagicMock(side_effect=OSError("cleanup boom"))
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_instance.return_value = instance
            gr.return_value = reg
            with patch("app.infrastructure.mods.comms.get_mod_comms"):
                with caplog.at_level("ERROR"):
                    assert mm.unload_mod("m") is True
                assert any("Error cleaning up" in r.message for r in caplog.records)

    def test_no_instance_skips_cleanup(self) -> None:
        mm = ModManager(mods_root="/tmp")
        mm._loaded_mods.append("m")
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_instance.return_value = None
            gr.return_value = reg
            with patch("app.infrastructure.mods.comms.get_mod_comms"):
                assert mm.unload_mod("m") is True

    def test_comms_cleanup_error_swallowed(self, caplog: pytest.LogCaptureFixture) -> None:
        mm = ModManager(mods_root="/tmp")
        mm._loaded_mods.append("m")
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_instance.return_value = None
            gr.return_value = reg
            with patch(
                "app.infrastructure.mods.comms.get_mod_comms",
                side_effect=RuntimeError("comms boom"),
            ):
                with caplog.at_level("WARNING"):
                    assert mm.unload_mod("m") is True
                assert any("comms cleanup failed" in r.message.lower() for r in caplog.records)

    def test_mod_not_in_loaded_list_still_succeeds(self) -> None:
        """mod_id 不在 _loaded_mods → 仍返回 True。"""
        mm = ModManager(mods_root="/tmp")
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_instance.return_value = None
            gr.return_value = reg
            with patch("app.infrastructure.mods.comms.get_mod_comms"):
                assert mm.unload_mod("not-loaded") is True


# ---------------------------------------------------------------------------
# ModManager.install_mod_package
# ---------------------------------------------------------------------------


class TestInstallModPackage:
    """ModManager.install_mod_package 分支覆盖。"""

    def test_signature_error_returns_false(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            side_effect=ModSignatureError("bad sig"),
        ):
            ok, msg, meta = mm.install_mod_package("/pkg.xcmod", verify_signature=True)
            assert ok is False
            assert "签名验证失败" in msg
            assert meta is None

    def test_package_error_returns_false(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            side_effect=ModPackageError("bad pkg"),
        ):
            ok, msg, meta = mm.install_mod_package("/pkg.xcmod")
            assert ok is False
            assert "MOD 包无效" in msg
            assert meta is None

    def test_missing_id_returns_false(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            return_value=(str(tmp_path / "extracted"), {"version": "1.0.0"}),  # 无 id
        ):
            ok, msg, meta = mm.install_mod_package("/pkg.xcmod")
            assert ok is False
            assert "缺少 id" in msg
            assert meta is None

    def test_sku_blocked_returns_false(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(
                    str(tmp_path / "extracted"),
                    {"id": "blocked-mod", "version": "1.0.0"},
                ),
            ),
            patch(
                "app.mod_sdk.product_skus.assert_mod_allowed_for_sku",
                side_effect=PermissionError("sku blocked"),
            ),
        ):
            ok, msg, meta = mm.install_mod_package("/pkg.xcmod")
            assert ok is False
            assert "sku blocked" in msg

    def test_existing_mod_updated(self, tmp_path: Path) -> None:
        """已存在的 mod → 删除旧目录 → 复制新内容。"""
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        existing = mods_root / "existing-mod"
        existing.mkdir()
        (existing / "manifest.json").write_text(
            json.dumps({"id": "existing-mod", "version": "1.0.0"})
        )

        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        (extract_dir / "manifest.json").write_text(
            json.dumps({"id": "existing-mod", "name": "Existing", "version": "2.0.0"})
        )

        mm = ModManager(mods_root=str(mods_root))
        with (
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(
                    str(extract_dir),
                    {"id": "existing-mod", "name": "Existing", "version": "2.0.0"},
                ),
            ),
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch.object(mm, "load_mod", return_value=False),
        ):
            ok, msg, meta = mm.install_mod_package("/pkg.xcmod", activate=True)
            assert ok is False  # 加载失败
            assert "加载失败" in msg

    def test_activate_load_success(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        (extract_dir / "manifest.json").write_text(
            json.dumps({"id": "new-mod", "name": "New", "version": "1.0.0"})
        )

        mm = ModManager(mods_root=str(mods_root))
        with (
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(
                    str(extract_dir),
                    {"id": "new-mod", "name": "New", "version": "1.0.0"},
                ),
            ),
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch.object(mm, "load_mod", return_value=True),
        ):
            ok, msg, meta = mm.install_mod_package("/pkg.xcmod", activate=True)
            assert ok is True
            assert "安装成功" in msg
            assert meta is not None

    def test_no_activate_returns_success(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        (extract_dir / "manifest.json").write_text(
            json.dumps({"id": "inactive-mod", "name": "Inactive", "version": "1.0.0"})
        )

        mm = ModManager(mods_root=str(mods_root))
        with (
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(
                    str(extract_dir),
                    {"id": "inactive-mod", "name": "Inactive", "version": "1.0.0"},
                ),
            ),
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch.object(mm, "load_mod") as lm,
        ):
            ok, msg, meta = mm.install_mod_package("/pkg.xcmod", activate=False)
            assert ok is True
            assert "未激活" in msg
            lm.assert_not_called()

    def test_recoverable_error_returns_false(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "_refresh_mods_root_if_needed", side_effect=OSError("fs boom")):
            ok, msg, meta = mm.install_mod_package("/pkg.xcmod")
            assert ok is False
            assert "安装失败" in msg
            assert meta is None


# ---------------------------------------------------------------------------
# ModManager.uninstall_mod
# ---------------------------------------------------------------------------


class TestUninstallMod:
    """ModManager.uninstall_mod 分支覆盖。"""

    def test_not_loaded_employee_pack_uninstalled(self, tmp_path: Path) -> None:
        """metadata 为 None 但 employee_pack 存在 → 委托 employee_registry。"""
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        emp_dir = mods_root / "_employees" / "emp-pack"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text(json.dumps({"id": "emp-pack"}))

        mm = ModManager(mods_root=str(mods_root))
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_metadata.return_value = None
            gr.return_value = reg
            with patch("app.infrastructure.mods.employee_registry.get_employee_registry") as ge:
                er = MagicMock()
                er._root.return_value = str(mods_root / "_employees")
                er.uninstall_pack.return_value = (True, "employee pack uninstalled")
                ge.return_value = er
                ok, msg = mm.uninstall_mod("emp-pack")
                assert ok is True
                assert "employee pack uninstalled" in msg

    def test_not_loaded_no_employee_pack_returns_false(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mm = ModManager(mods_root=str(mods_root))
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_metadata.return_value = None
            gr.return_value = reg
            with patch("app.infrastructure.mods.employee_registry.get_employee_registry") as ge:
                er = MagicMock()
                er._root.return_value = str(mods_root / "_employees")
                ge.return_value = er
                ok, msg = mm.uninstall_mod("nonexistent")
                assert ok is False
                assert "未加载或不存在" in msg

    def test_loaded_mod_unloaded_and_files_removed(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mod_dir = mods_root / "loaded-mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "loaded-mod"}))

        mm = ModManager(mods_root=str(mods_root))
        mm._loaded_mods.append("loaded-mod")
        meta = ModMetadata(id="loaded-mod", name="Loaded", version="1.0.0")
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_metadata.return_value = meta
            gr.return_value = reg
            with patch.object(mm, "unload_mod") as ul:
                ok, msg = mm.uninstall_mod("loaded-mod", remove_files=True)
                assert ok is True
                ul.assert_called_once_with("loaded-mod")
                assert not mod_dir.exists()

    def test_remove_files_false_keeps_dir(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mod_dir = mods_root / "keep-mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "keep-mod"}))

        mm = ModManager(mods_root=str(mods_root))
        meta = ModMetadata(id="keep-mod", name="Keep", version="1.0.0")
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_metadata.return_value = meta
            gr.return_value = reg
            ok, msg = mm.uninstall_mod("keep-mod", remove_files=False)
            assert ok is True
            assert mod_dir.exists()  # 文件保留

    def test_recoverable_error_returns_false(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry",
            side_effect=OSError("boom"),
        ):
            ok, msg = mm.uninstall_mod("any-mod")
            assert ok is False
            assert "卸载失败" in msg


# ---------------------------------------------------------------------------
# ModManager.update_mod
# ---------------------------------------------------------------------------


class TestUpdateMod:
    """ModManager.update_mod 分支覆盖。"""

    def test_not_installed_returns_false(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_metadata.return_value = None
            gr.return_value = reg
            ok, msg, meta = mm.update_mod("missing", "/pkg.xcmod")
            assert ok is False
            assert "未安装" in msg
            assert meta is None

    def test_was_loaded_unloaded_and_reloaded_success(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mod_dir = mods_root / "up-mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "up-mod", "version": "1.0.0"}))

        mm = ModManager(mods_root=str(mods_root))
        mm._loaded_mods.append("up-mod")
        cur_meta = ModMetadata(id="up-mod", name="Up", version="1.0.0")
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        (extract_dir / "manifest.json").write_text(json.dumps({"id": "up-mod", "version": "2.0.0"}))

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.ModPackage") as MP,
            patch.object(mm, "unload_mod") as ul,
            patch.object(mm, "load_mod", return_value=True) as lm,
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = cur_meta
            gr.return_value = reg
            pkg = MagicMock()
            pkg.manifest = {"id": "up-mod", "version": "2.0.0"}
            MP.return_value = pkg
            MP.extract_package.return_value = (
                str(extract_dir),
                {"id": "up-mod", "version": "2.0.0"},
            )
            ok, msg, meta = mm.update_mod("up-mod", "/pkg.xcmod")
            assert ok is True
            assert "更新成功" in msg
            ul.assert_called_once()
            lm.assert_called_once()

    def test_was_loaded_extract_fail_reloads_old(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mod_dir = mods_root / "fail-mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "fail-mod", "version": "1.0.0"}))

        mm = ModManager(mods_root=str(mods_root))
        mm._loaded_mods.append("fail-mod")
        cur_meta = ModMetadata(id="fail-mod", name="Fail", version="1.0.0")

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.ModPackage") as MP,
            patch.object(mm, "unload_mod"),
            patch.object(mm, "load_mod", return_value=True) as lm,
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = cur_meta
            gr.return_value = reg
            pkg = MagicMock()
            pkg.manifest = {"id": "fail-mod", "version": "2.0.0"}
            MP.return_value = pkg
            MP.extract_package.side_effect = OSError("extract boom")
            ok, msg, meta = mm.update_mod("fail-mod", "/pkg.xcmod")
            assert ok is False
            assert "更新失败" in msg
            lm.assert_called_once_with("fail-mod")  # 重新加载旧的

    def test_was_loaded_reload_fails(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mod_dir = mods_root / "reload-fail"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "reload-fail", "version": "1.0.0"})
        )

        mm = ModManager(mods_root=str(mods_root))
        mm._loaded_mods.append("reload-fail")
        cur_meta = ModMetadata(id="reload-fail", name="RF", version="1.0.0")
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        (extract_dir / "manifest.json").write_text(
            json.dumps({"id": "reload-fail", "version": "2.0.0"})
        )

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.ModPackage") as MP,
            patch.object(mm, "unload_mod"),
            patch.object(mm, "load_mod", return_value=False),
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = cur_meta
            gr.return_value = reg
            pkg = MagicMock()
            pkg.manifest = {"id": "reload-fail", "version": "2.0.0"}
            MP.return_value = pkg
            MP.extract_package.return_value = (
                str(extract_dir),
                {"id": "reload-fail", "version": "2.0.0"},
            )
            ok, msg, meta = mm.update_mod("reload-fail", "/pkg.xcmod")
            assert ok is False
            assert "加载失败" in msg

    def test_not_loaded_no_reload(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mod_dir = mods_root / "nl-mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "nl-mod", "version": "1.0.0"}))

        mm = ModManager(mods_root=str(mods_root))
        cur_meta = ModMetadata(id="nl-mod", name="NL", version="1.0.0")
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        (extract_dir / "manifest.json").write_text(json.dumps({"id": "nl-mod", "version": "2.0.0"}))

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.ModPackage") as MP,
            patch.object(mm, "load_mod") as lm,
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = cur_meta
            gr.return_value = reg
            pkg = MagicMock()
            pkg.manifest = {"id": "nl-mod", "version": "2.0.0"}
            MP.return_value = pkg
            MP.extract_package.return_value = (
                str(extract_dir),
                {"id": "nl-mod", "version": "2.0.0"},
            )
            ok, msg, meta = mm.update_mod("nl-mod", "/pkg.xcmod")
            assert ok is True
            assert "更新成功" in msg
            lm.assert_not_called()

    def test_recoverable_error_returns_false(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry",
            side_effect=OSError("boom"),
        ):
            ok, msg, meta = mm.update_mod("any", "/pkg.xcmod")
            assert ok is False
            assert "更新失败" in msg


# ---------------------------------------------------------------------------
# ModManager.validate_mod_package
# ---------------------------------------------------------------------------


class TestValidateModPackage:
    """ModManager.validate_mod_package 分支覆盖。"""

    def test_not_a_file_returns_false(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        ok, msg, info = mm.validate_mod_package("/nonexistent/pkg.xcmod")
        assert ok is False
        assert "文件不存在" in msg
        assert info == {}

    def test_not_a_zip_returns_false(self, tmp_path: Path) -> None:
        pkg = tmp_path / "notzip.xcmod"
        pkg.write_text("not a zip")
        mm = ModManager(mods_root=str(tmp_path))
        ok, msg, info = mm.validate_mod_package(str(pkg))
        assert ok is False
        assert "不是有效的 ZIP" in msg

    def test_missing_id_returns_false(self, tmp_path: Path) -> None:
        pkg = tmp_path / "noid.xcmod"
        pkg.write_bytes(b"fake zip content")
        with (
            patch("zipfile.is_zipfile", return_value=True),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(str(tmp_path), {"version": "1.0.0"}),
            ),
        ):  # 无 id
            mm = ModManager(mods_root=str(tmp_path))
            ok, msg, info = mm.validate_mod_package(str(pkg))
            assert ok is False
            assert "缺少必填字段 'id'" in msg

    def test_missing_required_fields_returns_errors(self, tmp_path: Path) -> None:
        pkg = tmp_path / "incomplete.xcmod"
        pkg.write_bytes(b"fake zip content")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with (
            patch("zipfile.is_zipfile", return_value=True),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(str(extract_dir), {"id": "x", "version": "1.0.0"}),
            ),
        ):  # 缺 name
            mm = ModManager(mods_root=str(tmp_path))
            ok, msg, info = mm.validate_mod_package(str(pkg))
            assert ok is False
            assert "name" in msg
            assert info["id"] == "x"

    def test_bundle_validation(self, tmp_path: Path) -> None:
        pkg = tmp_path / "bundle.xcmod"
        pkg.write_bytes(b"fake zip content")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        manifest = {"id": "b", "name": "B", "version": "1.0.0", "artifact": "bundle"}
        with (
            patch("zipfile.is_zipfile", return_value=True),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(str(extract_dir), manifest),
            ),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="bundle"),
            patch("app.infrastructure.mods.mod_manager.validate_bundle_manifest", return_value=[]),
        ):
            mm = ModManager(mods_root=str(tmp_path))
            ok, msg, info = mm.validate_mod_package(str(pkg))
            assert ok is True
            assert info["artifact"] == "bundle"

    def test_employee_pack_validation(self, tmp_path: Path) -> None:
        pkg = tmp_path / "emp.xcmod"
        pkg.write_bytes(b"fake zip content")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        manifest = {"id": "e", "name": "E", "version": "1.0.0", "artifact": "employee_pack"}
        with (
            patch("zipfile.is_zipfile", return_value=True),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(str(extract_dir), manifest),
            ),
            patch(
                "app.infrastructure.mods.mod_manager.normalize_artifact",
                return_value="employee_pack",
            ),
            patch(
                "app.infrastructure.mods.mod_manager.validate_employee_pack_manifest",
                return_value=[],
            ),
        ):
            mm = ModManager(mods_root=str(tmp_path))
            ok, msg, info = mm.validate_mod_package(str(pkg))
            assert ok is True
            assert info["artifact"] == "employee_pack"

    def test_mod_backend_entry_missing(self, tmp_path: Path) -> None:
        pkg = tmp_path / "mod.xcmod"
        pkg.write_bytes(b"fake zip content")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        (extract_dir / "backend").mkdir()
        manifest = {
            "id": "m",
            "name": "M",
            "version": "1.0.0",
            "backend": {"entry": "missing_entry"},
        }
        with (
            patch("zipfile.is_zipfile", return_value=True),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(str(extract_dir), manifest),
            ),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="mod"),
        ):
            mm = ModManager(mods_root=str(tmp_path))
            ok, msg, info = mm.validate_mod_package(str(pkg))
            assert ok is False
            assert "后端入口文件不存在" in msg

    def test_mod_frontend_routes_missing(self, tmp_path: Path) -> None:
        pkg = tmp_path / "mod.xcmod"
        pkg.write_bytes(b"fake zip content")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        (extract_dir / "frontend").mkdir()
        manifest = {
            "id": "m",
            "name": "M",
            "version": "1.0.0",
            "frontend": {"routes": "missing_routes"},
        }
        with (
            patch("zipfile.is_zipfile", return_value=True),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(str(extract_dir), manifest),
            ),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="mod"),
        ):
            mm = ModManager(mods_root=str(tmp_path))
            ok, msg, info = mm.validate_mod_package(str(pkg))
            assert ok is False
            assert "前端路由文件不存在" in msg

    def test_mod_package_error_returns_false(self, tmp_path: Path) -> None:
        pkg = tmp_path / "bad.xcmod"
        pkg.write_bytes(b"fake zip content")
        with (
            patch("zipfile.is_zipfile", return_value=True),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                side_effect=ModPackageError("bad pkg"),
            ),
        ):
            mm = ModManager(mods_root=str(tmp_path))
            ok, msg, info = mm.validate_mod_package(str(pkg))
            assert ok is False
            assert "bad pkg" in msg

    def test_recoverable_error_returns_false(self, tmp_path: Path) -> None:
        pkg = tmp_path / "boom.xcmod"
        pkg.write_bytes(b"fake zip content")
        with (
            patch("zipfile.is_zipfile", return_value=True),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                side_effect=OSError("boom"),
            ),
        ):
            mm = ModManager(mods_root=str(tmp_path))
            ok, msg, info = mm.validate_mod_package(str(pkg))
            assert ok is False
            assert "验证失败" in msg


# ---------------------------------------------------------------------------
# ModManager.list_all_mods / get_routes / load_all_mods
# ---------------------------------------------------------------------------


class TestListAllModsBranches:
    """ModManager.list_all_mods 分支覆盖。"""

    def test_employee_registry_error_swallowed(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "scan_mods", return_value=[]),
            patch(
                "app.infrastructure.mods.employee_registry.get_employee_registry",
                side_effect=OSError("boom"),
            ),
        ):
            result = mm.list_all_mods()
            assert result == []

    def test_enterprise_filter_error_swallowed(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="m", name="M", version="1.0.0")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch("app.infrastructure.mods.employee_registry.get_employee_registry") as ge,
        ):
            er = MagicMock()
            er.list_for_mods_api.return_value = []
            ge.return_value = er
            with patch(
                "app.enterprise.mod_entitlements.filter_mod_rows_for_enterprise",
                side_effect=RuntimeError("boom"),
            ):
                result = mm.list_all_mods()
                assert len(result) == 1  # 过滤失败 → 返回未过滤列表


class TestGetRoutesBranches:
    """ModManager.get_routes 分支覆盖。"""

    def test_enterprise_filter_error_swallowed(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="m", name="M", version="1.0.0", frontend_routes="routes.js")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = mm.get_routes()
            assert len(result) == 1
            assert result[0]["mod_id"] == "m"

    def test_mod_not_visible_skipped(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="hidden", name="Hidden", version="1.0.0", frontend_routes="routes.js")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=False,
            ),
        ):
            result = mm.get_routes()
            assert result == []

    def test_empty_routes_skipped(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="m", name="M", version="1.0.0", frontend_routes="")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=True,
            ),
        ):
            result = mm.get_routes()
            assert result == []

    def test_routes_returned(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="m", name="M", version="1.0.0", frontend_routes="routes.js")
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=True,
            ),
        ):
            result = mm.get_routes()
            assert len(result) == 1
            assert result[0]["routes_path"] == "routes.js"


class TestLoadAllModsBranches:
    """ModManager.load_all_mods 分支覆盖。"""

    def test_enterprise_skip(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="hidden", name="Hidden", version="1.0.0")
        with (
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=False,
            ),
        ):
            result = mm.load_all_mods()
            assert result == []

    def test_dependencies_not_satisfied_skipped(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="dep-mod", name="Dep", version="1.0.0", dependencies={"other": "*"})
        with (
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=True,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.validate_dependencies",
                return_value=False,
            ),
        ):
            result = mm.load_all_mods()
            assert result == []
            failures = mm.get_recent_load_failures()
            assert any(f["stage"] == "dependencies" for f in failures)

    def test_load_mod_failure_skipped(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="fail-mod", name="Fail", version="1.0.0")
        with (
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=True,
            ),
            patch.object(mm, "load_mod", return_value=False),
        ):
            result = mm.load_all_mods()
            assert result == []

    def test_successful_load(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        meta1 = ModMetadata(id="mod1", name="M1", version="1.0.0", primary=True)
        meta2 = ModMetadata(id="mod2", name="M2", version="1.0.0")
        with (
            patch.object(mm, "scan_mods", return_value=[meta2, meta1]),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=True,
            ),
            patch.object(mm, "load_mod", return_value=True) as lm,
        ):
            result = mm.load_all_mods()
            assert result == ["mod1", "mod2"]  # primary 先加载
            # 验证 primary 排序
            assert lm.call_args_list[0][0][0] == "mod1"

    def test_enterprise_filter_error_swallowed(self, tmp_path: Path) -> None:
        """enterprise filter 抛异常 → 不跳过，继续尝试加载。"""
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="m", name="M", version="1.0.0")
        with (
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                side_effect=RuntimeError("boom"),
            ),
            patch.object(mm, "load_mod", return_value=True),
        ):
            result = mm.load_all_mods()
            assert result == ["m"]


# ---------------------------------------------------------------------------
# register_employee_pack_routes
# ---------------------------------------------------------------------------


class TestRegisterEmployeePackRoutes:
    """register_employee_pack_routes 分支覆盖。"""

    def test_empty_pid_returns_false(self) -> None:
        assert register_employee_pack_routes(app=None, mod_manager=None, pack_id="") is False
        assert register_employee_pack_routes(app=None, mod_manager=None, pack_id="   ") is False

    def test_disabled_returns_false(self) -> None:
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            assert register_employee_pack_routes(app=None, mod_manager=None, pack_id="p") is False

    def test_no_manifest_returns_false(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        (mods_root / "_employees" / "p").mkdir(parents=True)
        mm = ModManager(mods_root=str(mods_root))
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False):
            assert register_employee_pack_routes(app=None, mod_manager=mm, pack_id="p") is False

    def test_manifest_json_error_returns_false(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        pack_dir = mods_root / "_employees" / "p"
        pack_dir.mkdir(parents=True)
        (pack_dir / "manifest.json").write_text("not json {{{")
        mm = ModManager(mods_root=str(mods_root))
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False):
            assert register_employee_pack_routes(app=None, mod_manager=mm, pack_id="p") is False

    def test_not_employee_pack_returns_false(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        pack_dir = mods_root / "_employees" / "p"
        pack_dir.mkdir(parents=True)
        (pack_dir / "manifest.json").write_text(json.dumps({"id": "p", "artifact": "mod"}))
        mm = ModManager(mods_root=str(mods_root))
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False):
            assert register_employee_pack_routes(app=None, mod_manager=mm, pack_id="p") is False

    def test_no_entry_returns_false(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        pack_dir = mods_root / "_employees" / "p"
        pack_dir.mkdir(parents=True)
        (pack_dir / "manifest.json").write_text(
            json.dumps({"id": "p", "artifact": "employee_pack", "backend": {}})
        )
        mm = ModManager(mods_root=str(mods_root))
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False):
            assert register_employee_pack_routes(app=None, mod_manager=mm, pack_id="p") is False

    def test_already_registered_force_false_returns_true(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        pack_dir = mods_root / "_employees" / "p"
        pack_dir.mkdir(parents=True)
        (pack_dir / "manifest.json").write_text(
            json.dumps({"id": "p", "artifact": "employee_pack", "backend": {"entry": "entry"}})
        )
        mm = ModManager(mods_root=str(mods_root))
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch("app.infrastructure.mods.mod_manager._employee_pack_routes_registered", {"p"}),
        ):
            # 已注册且 force=False → 返回 True
            assert register_employee_pack_routes(app=None, mod_manager=mm, pack_id="p") is True

    def test_import_error_records_blueprint_failure(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        pack_dir = mods_root / "_employees" / "p"
        pack_dir.mkdir(parents=True)
        (pack_dir / "manifest.json").write_text(
            json.dumps({"id": "p", "artifact": "employee_pack", "backend": {"entry": "entry"}})
        )
        mm = ModManager(mods_root=str(mods_root))
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                side_effect=OSError("import boom"),
            ),
        ):
            with caplog.at_level("ERROR"):
                assert register_employee_pack_routes(app=None, mod_manager=mm, pack_id="p") is False
            failures = mm.get_blueprint_failures()
            assert len(failures) == 1

    def test_no_register_fastapi_routes_returns_false(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        pack_dir = mods_root / "_employees" / "p"
        pack_dir.mkdir(parents=True)
        (pack_dir / "manifest.json").write_text(
            json.dumps({"id": "p", "artifact": "employee_pack", "backend": {"entry": "entry"}})
        )
        # 创建 entry.py 但无 register_fastapi_routes
        (pack_dir / "backend").mkdir()
        (pack_dir / "backend" / "entry.py").write_text("X = 1\n")
        mm = ModManager(mods_root=str(mods_root))
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False):
            assert register_employee_pack_routes(app=None, mod_manager=mm, pack_id="p") is False

    def test_successful_registration(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        pack_dir = mods_root / "_employees" / "p"
        pack_dir.mkdir(parents=True)
        (pack_dir / "manifest.json").write_text(
            json.dumps({"id": "p", "artifact": "employee_pack", "backend": {"entry": "entry"}})
        )
        # 创建带 register_fastapi_routes 的 entry.py
        (pack_dir / "backend").mkdir()
        (pack_dir / "backend" / "entry.py").write_text(
            "def register_fastapi_routes(app, mod_id):\n    pass\n"
        )
        mm = ModManager(mods_root=str(mods_root))
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False):
            result = register_employee_pack_routes(app="myapp", mod_manager=mm, pack_id="p")
            assert result is True

    def test_force_reregisters(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        pack_dir = mods_root / "_employees" / "p"
        pack_dir.mkdir(parents=True)
        (pack_dir / "manifest.json").write_text(
            json.dumps({"id": "p", "artifact": "employee_pack", "backend": {"entry": "entry"}})
        )
        (pack_dir / "backend").mkdir()
        (pack_dir / "backend" / "entry.py").write_text(
            "def register_fastapi_routes(app, mod_id):\n    pass\n"
        )
        mm = ModManager(mods_root=str(mods_root))
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch("app.infrastructure.mods.mod_manager._employee_pack_routes_registered", {"p"}),
        ):
            # force=True → 重新注册
            result = register_employee_pack_routes(
                app="myapp", mod_manager=mm, pack_id="p", force=True
            )
            assert result is True


# ---------------------------------------------------------------------------
# load_employee_pack_routes
# ---------------------------------------------------------------------------


class TestLoadEmployeePackRoutes:
    """load_employee_pack_routes 分支覆盖。"""

    def test_disabled_returns(self) -> None:
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            # 不应抛异常
            load_employee_pack_routes(app=None, mod_manager=None)

    def test_no_emp_root_returns(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mm = ModManager(mods_root=str(mods_root))
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False):
            load_employee_pack_routes(app=None, mod_manager=mm)

    def test_skips_non_dir_entries(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        emp_root = mods_root / "_employees"
        emp_root.mkdir()
        (emp_root / "file.txt").write_text("not a dir")
        mm = ModManager(mods_root=str(mods_root))
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch("app.infrastructure.mods.mod_manager.register_employee_pack_routes") as reg,
        ):
            load_employee_pack_routes(app=None, mod_manager=mm)
            reg.assert_not_called()

    def test_skips_no_manifest(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        emp_root = mods_root / "_employees"
        emp_root.mkdir()
        (emp_root / "no-manifest").mkdir()
        mm = ModManager(mods_root=str(mods_root))
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch("app.infrastructure.mods.mod_manager.register_employee_pack_routes") as reg,
        ):
            load_employee_pack_routes(app=None, mod_manager=mm)
            reg.assert_not_called()

    def test_skips_manifest_json_error(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        emp_root = mods_root / "_employees"
        emp_root.mkdir()
        pack_dir = emp_root / "bad"
        pack_dir.mkdir()
        (pack_dir / "manifest.json").write_text("not json {{{")
        mm = ModManager(mods_root=str(mods_root))
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch("app.infrastructure.mods.mod_manager.register_employee_pack_routes") as reg,
        ):
            load_employee_pack_routes(app=None, mod_manager=mm)
            reg.assert_not_called()

    def test_skips_non_employee_pack(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        emp_root = mods_root / "_employees"
        emp_root.mkdir()
        pack_dir = emp_root / "mod-pack"
        pack_dir.mkdir()
        (pack_dir / "manifest.json").write_text(json.dumps({"id": "mod-pack", "artifact": "mod"}))
        mm = ModManager(mods_root=str(mods_root))
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch("app.infrastructure.mods.mod_manager.register_employee_pack_routes") as reg,
        ):
            load_employee_pack_routes(app=None, mod_manager=mm)
            reg.assert_not_called()

    def test_registers_valid_employee_pack(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        emp_root = mods_root / "_employees"
        emp_root.mkdir()
        pack_dir = emp_root / "valid"
        pack_dir.mkdir()
        (pack_dir / "manifest.json").write_text(
            json.dumps({"id": "valid", "artifact": "employee_pack"})
        )
        mm = ModManager(mods_root=str(mods_root))
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch("app.infrastructure.mods.mod_manager.register_employee_pack_routes") as reg,
        ):
            load_employee_pack_routes(app="myapp", mod_manager=mm)
            reg.assert_called_once()

    def test_mod_manager_none_uses_default(self) -> None:
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            # mod_manager=None → 调用 get_mod_manager()
            load_employee_pack_routes(app=None, mod_manager=None)


# ---------------------------------------------------------------------------
# _register_single_mod_http_routes
# ---------------------------------------------------------------------------


class TestRegisterSingleModHttpRoutes:
    """_register_single_mod_http_routes 分支覆盖。"""

    def test_empty_mid_returns_false(self) -> None:
        mm = ModManager(mods_root="/tmp")
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        assert _register_single_mod_http_routes(None, mm, "") is False
        assert _register_single_mod_http_routes(None, mm, "   ") is False

    def test_already_registered_returns_true(self) -> None:
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = ModManager(mods_root="/tmp")
        mm._http_routes_registered.add("m")
        assert _register_single_mod_http_routes(None, mm, "m") is True

    def test_no_metadata_returns_false(self) -> None:
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = ModManager(mods_root="/tmp")
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_metadata.return_value = None
            gr.return_value = reg
            assert _register_single_mod_http_routes(None, mm, "m") is False

    def test_no_backend_entry_returns_false(self) -> None:
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(id="m", name="M", version="1.0.0", backend_entry="")
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_metadata.return_value = meta
            gr.return_value = reg
            assert _register_single_mod_http_routes(None, mm, "m") is False

    def test_no_mod_path_records_failure(self) -> None:
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(id="m", name="M", version="1.0.0", backend_entry="entry", mod_path="")
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_metadata.return_value = meta
            gr.return_value = reg
            assert _register_single_mod_http_routes(None, mm, "m") is False
            failures = mm.get_blueprint_failures()
            assert len(failures) == 1

    def test_module_none_imports_and_registers(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mod_dir = mods_root / "m"
        mod_dir.mkdir()
        (mod_dir / "backend").mkdir()
        (mod_dir / "backend" / "entry.py").write_text(
            "def register_fastapi_routes(app, mod_id):\n    pass\n"
        )
        (mod_dir / "manifest.json").write_text(json.dumps({"id": "m"}))

        mm = ModManager(mods_root=str(mods_root))
        meta = ModMetadata(
            id="m", name="M", version="1.0.0", backend_entry="entry", mod_path=str(mod_dir)
        )
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr:
            reg = MagicMock()
            reg.get_mod_metadata.return_value = meta
            gr.return_value = reg
            result = _register_single_mod_http_routes("myapp", mm, "m")
            assert result is True
            assert "m" in mm._http_routes_registered
            assert "m" in mm._backend_entry_modules

    def test_register_fastapi_routes_callable(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(
            id="m", name="M", version="1.0.0", backend_entry="entry", mod_path="/mods/m"
        )
        module = MagicMock()
        module.register_fastapi_routes = MagicMock()

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.import_mod_backend_py", return_value=module),
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = meta
            gr.return_value = reg
            result = _register_single_mod_http_routes("myapp", mm, "m")
            assert result is True
            module.register_fastapi_routes.assert_called_once_with("myapp", "m")

    def test_register_websocket_routes_true(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(
            id="m", name="M", version="1.0.0", backend_entry="entry", mod_path="/mods/m"
        )
        module = MagicMock()
        module.register_fastapi_routes = MagicMock()
        module.register_websocket_routes = MagicMock(return_value=True)

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.import_mod_backend_py", return_value=module),
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = meta
            gr.return_value = reg
            result = _register_single_mod_http_routes("myapp", mm, "m")
            assert result is True
            module.register_websocket_routes.assert_called_once_with("myapp")

    def test_register_websocket_routes_false(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(
            id="m", name="M", version="1.0.0", backend_entry="entry", mod_path="/mods/m"
        )
        module = MagicMock()
        module.register_fastapi_routes = MagicMock()
        module.register_websocket_routes = MagicMock(return_value=False)

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.import_mod_backend_py", return_value=module),
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = meta
            gr.return_value = reg
            result = _register_single_mod_http_routes("myapp", mm, "m")
            assert result is True  # 仍 True，因 fastapi 已注册

    def test_no_registrar_returns_false(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(
            id="m", name="M", version="1.0.0", backend_entry="entry", mod_path="/mods/m"
        )
        module = MagicMock(spec=[])  # 无任何属性

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.import_mod_backend_py", return_value=module),
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = meta
            gr.return_value = reg
            result = _register_single_mod_http_routes("myapp", mm, "m")
            assert result is False

    def test_recoverable_error_returns_false(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = ModManager(mods_root="/tmp")
        meta = ModMetadata(
            id="m", name="M", version="1.0.0", backend_entry="entry", mod_path="/mods/m"
        )
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                side_effect=OSError("boom"),
            ),
        ):
            reg = MagicMock()
            reg.get_mod_metadata.return_value = meta
            gr.return_value = reg
            result = _register_single_mod_http_routes("myapp", mm, "m")
            assert result is False
            failures = mm.get_blueprint_failures()
            assert len(failures) == 1


# ---------------------------------------------------------------------------
# _restore_entitlements_from_session_id
# ---------------------------------------------------------------------------


class TestRestoreEntitlementsFromSessionId:
    """_restore_entitlements_from_session_id 分支覆盖。"""

    def test_empty_sid_returns(self) -> None:
        # 不应抛异常
        _restore_entitlements_from_session_id("")
        _restore_entitlements_from_session_id(None)
        _restore_entitlements_from_session_id("   ")

    def test_restore_error_swallowed(self) -> None:
        with patch(
            "app.enterprise.mod_entitlements.restore_entitlements_from_session_row",
            side_effect=OSError("boom"),
        ):
            # 不应抛异常
            _restore_entitlements_from_session_id("sid-123")

    def test_cached_empty_skips_set(self) -> None:
        with (
            patch("app.enterprise.mod_entitlements.restore_entitlements_from_session_row"),
            patch(
                "app.enterprise.mod_entitlements._session_username_for_entitlements",
                return_value="user",
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_market_identity",
                return_value=("uid", "uname"),
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
                return_value=set(),
            ),
            patch(
                "app.enterprise.mod_entitlements._augment_entitled_for_username",
                return_value=set(),  # 空 → 不调用 set_session_entitlements
            ) as aug,
            patch("app.enterprise.mod_entitlements.set_session_entitlements") as sse,
        ):
            _restore_entitlements_from_session_id("sid-123")
            aug.assert_called_once()
            sse.assert_not_called()

    def test_cached_set_calls_set_session(self) -> None:
        with (
            patch("app.enterprise.mod_entitlements.restore_entitlements_from_session_row"),
            patch(
                "app.enterprise.mod_entitlements._session_username_for_entitlements",
                return_value="user",
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_market_identity",
                return_value=("uid", "uname"),
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
                return_value={"mod1"},
            ),
            patch(
                "app.enterprise.mod_entitlements._augment_entitled_for_username",
                return_value={"mod1", "mod2"},
            ),
            patch("app.enterprise.mod_entitlements.set_session_entitlements") as sse,
        ):
            _restore_entitlements_from_session_id("sid-123")
            sse.assert_called_once()
            kwargs = sse.call_args.kwargs
            assert kwargs["market_user_id"] == "uid"
            assert kwargs["market_username"] == "user"
            assert kwargs["entitled_client_mod_ids"] == {"mod1", "mod2"}


# ---------------------------------------------------------------------------
# ensure_mod_api_ready
# ---------------------------------------------------------------------------


class TestEnsureModApiReady:
    """ensure_mod_api_ready 分支覆盖。"""

    def test_empty_mid_returns_false(self) -> None:
        assert ensure_mod_api_ready("") is False
        assert ensure_mod_api_ready("   ") is False

    def test_disabled_returns_false(self) -> None:
        with patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=True):
            assert ensure_mod_api_ready("m") is False

    def test_not_allowed_returns_false(self) -> None:
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch(
                "app.infrastructure.mods.mod_manager._mod_allowed_for_api_load",
                return_value=False,
            ),
        ):
            assert ensure_mod_api_ready("m") is False

    def test_load_mod_failure_returns_false(self) -> None:
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch(
                "app.infrastructure.mods.mod_manager._mod_allowed_for_api_load",
                return_value=True,
            ),
            patch(
                "app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id",
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as gmm,
        ):
            mm = MagicMock()
            mm._loaded_mods = []
            mm.load_mod.return_value = False
            gmm.return_value = mm
            assert ensure_mod_api_ready("m") is False

    def test_already_registered_returns_true(self) -> None:
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch(
                "app.infrastructure.mods.mod_manager._mod_allowed_for_api_load",
                return_value=True,
            ),
            patch(
                "app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id",
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as gmm,
        ):
            mm = MagicMock()
            mm._loaded_mods = ["m"]
            mm._http_routes_registered = {"m"}
            gmm.return_value = mm
            assert ensure_mod_api_ready("m") is True

    def test_get_app_failure_returns_false(self) -> None:
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch(
                "app.infrastructure.mods.mod_manager._mod_allowed_for_api_load",
                return_value=True,
            ),
            patch(
                "app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id",
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as gmm,
            patch(
                "app.fastapi_app.get_fastapi_app",
                side_effect=OSError("app boom"),
            ),
        ):
            mm = MagicMock()
            mm._loaded_mods = ["m"]
            mm._http_routes_registered = set()
            gmm.return_value = mm
            assert ensure_mod_api_ready("m") is False

    def test_register_routes_success(self) -> None:
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch(
                "app.infrastructure.mods.mod_manager._mod_allowed_for_api_load",
                return_value=True,
            ),
            patch(
                "app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id",
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as gmm,
            patch(
                "app.fastapi_app.get_fastapi_app",
                return_value="myapp",
            ),
            patch(
                "app.infrastructure.mods.mod_manager._register_single_mod_http_routes",
                return_value=True,
            ) as reg,
        ):
            mm = MagicMock()
            mm._loaded_mods = ["m"]
            mm._http_routes_registered = set()
            gmm.return_value = mm
            assert ensure_mod_api_ready("m") is True
            reg.assert_called_once_with("myapp", mm, "m")


# ---------------------------------------------------------------------------
# load_mod_routes
# ---------------------------------------------------------------------------


class TestLoadModRoutes:
    """load_mod_routes 分支覆盖。"""

    def test_mod_manager_none_uses_default(self) -> None:
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as gmm,
            patch("app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            mm = MagicMock()
            mm._loaded_mods = []
            mm._blueprint_failures = []
            gmm.return_value = mm
            reg = MagicMock()
            reg.list_mods.return_value = []
            gr.return_value = reg
            load_mod_routes(app="myapp", mod_manager=None)
            gmm.assert_called_once()

    def test_registers_routable_mods(self) -> None:
        with (
            patch("app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager._register_single_mod_http_routes") as reg,
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            mm = ModManager(mods_root="/tmp")
            mm._loaded_mods = ["mod1", "mod2"]
            meta1 = ModMetadata(id="mod1", name="M1", version="1.0.0", backend_entry="entry")
            meta2 = ModMetadata(id="mod2", name="M2", version="1.0.0", backend_entry="entry")
            reg_mock = MagicMock()
            reg_mock.list_mods.return_value = [meta1, meta2]
            gr.return_value = reg_mock
            load_mod_routes(app="myapp", mod_manager=mm)
            assert reg.call_count == 2

    def test_skips_mods_without_backend_entry(self) -> None:
        with (
            patch("app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager._register_single_mod_http_routes") as reg,
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            mm = ModManager(mods_root="/tmp")
            mm._loaded_mods = []
            meta1 = ModMetadata(id="mod1", name="M1", version="1.0.0", backend_entry="")
            reg_mock = MagicMock()
            reg_mock.list_mods.return_value = [meta1]
            gr.return_value = reg_mock
            load_mod_routes(app="myapp", mod_manager=mm)
            reg.assert_not_called()

    def test_dedupes_mod_ids(self) -> None:
        with (
            patch("app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager._register_single_mod_http_routes") as reg,
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            mm = ModManager(mods_root="/tmp")
            mm._loaded_mods = ["mod1"]
            meta1 = ModMetadata(id="mod1", name="M1", version="1.0.0", backend_entry="entry")
            meta2 = ModMetadata(id="mod1", name="M1", version="1.0.0", backend_entry="entry")
            reg_mock = MagicMock()
            reg_mock.list_mods.return_value = [meta1, meta2]  # 重复 id
            gr.return_value = reg_mock
            load_mod_routes(app="myapp", mod_manager=mm)
            assert reg.call_count == 1  # 去重

    def test_loads_employee_pack_routes(self) -> None:
        with (
            patch("app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry") as gr,
            patch("app.infrastructure.mods.mod_manager._register_single_mod_http_routes"),
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes") as lepr,
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            mm = ModManager(mods_root="/tmp")
            mm._loaded_mods = []
            reg_mock = MagicMock()
            reg_mock.list_mods.return_value = []
            gr.return_value = reg_mock
            load_mod_routes(app="myapp", mod_manager=mm)
            lepr.assert_called_once_with("myapp", mm)
