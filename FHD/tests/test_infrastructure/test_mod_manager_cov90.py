"""Targeted coverage for app.infrastructure.mods.mod_manager — remaining gaps (cov90).

Each test below hits a branch/line that the existing test_mod_manager*.py suite leaves
uncovered. Companion file test_aux_employee_store.py must be collected first to avoid a
known app.services circular-import collection error.

Targeted lines (per term-missing on the existing subset):
  _default_mods_root cwd / walk-up branches (75-76, 83-84),
  _invoke_mod_init_hook sig.bind TypeError fallback (234-236),
  _mods_scan_fingerprint non-dir root continue (268),
  resolve_mod_directory empty candidate (385) + legacy alias hit (403-405),
  _scan_mods_from_build_index non-dict row skip (429), scan_mods build-index return (450-452),
  load_mod bundle already-registered-after-parse (563) + backend except (594-597),
  _load_mod_backend init-hook TypeError (617-618),
  install_mod_package update-existing + activate paths (707-716, 722-726),
  update_mod rmtree + reload success/fail + not-loaded (816, 835-838),
  validate_mod_package bundle/employee/backend/frontend (882, 884, 890-892, 896-900),
  list_all_mods entitlement-filter exception (989),
  load_all_mods per-mod failure log (1054),
  register_employee_pack_routes success/error (1085, 1096-1120),
  load_employee_pack_routes register call (1139, 1146-1153),
  _register_single_mod_http_routes ws success + no-registrar (1199, 1203-1204),
  ensure_mod_api_ready final register (1293), load_mod_routes ordering (1312, 1325-1340).
"""

from __future__ import annotations

import json
import os
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.mods.artifact_constants import (
    ARTIFACT_BUNDLE,
    ARTIFACT_EMPLOYEE_PACK,
)
from app.infrastructure.mods.manifest import ModMetadata
from app.infrastructure.mods.mod_manager import (
    ModManager,
    _default_mods_root,
    _invoke_mod_init_hook,
    ensure_mod_api_ready,
    load_employee_pack_routes,
    load_mod_routes,
    register_employee_pack_routes,
)

# ---------------------------------------------------------------------------
# _default_mods_root — ./mods from cwd (75-76) and walk-up (83-84)
# ---------------------------------------------------------------------------


class TestDefaultModsRootCwdBranches:
    def test_cwd_mods_branch(self, tmp_path):
        """When pkg-relative path is absent but ./mods exists under cwd, return it (75-76)."""
        cwd_mods = tmp_path / "mods"
        cwd_mods.mkdir()
        with (
            patch.dict(os.environ, {"XCAGI_MODS_ROOT": "", "XCAGI_MODS_DIR": ""}, clear=False),
            patch("os.getcwd", return_value=str(tmp_path)),
            # Force pkg-layout candidate to be a non-dir so we fall through to the cwd check.
            patch(
                "app.infrastructure.mods.mod_manager.os.path.isdir",
                side_effect=lambda p: p == str(cwd_mods),
            ),
        ):
            result = _default_mods_root()
        assert result == str(cwd_mods)

    def test_walk_up_branch(self, tmp_path):
        """When ./mods is absent but a parent dir has mods/, walk up to find it (83-84)."""
        parent = tmp_path / "parent"
        child = parent / "child"
        child.mkdir(parents=True)
        ancestor_mods = parent / "mods"
        ancestor_mods.mkdir()

        def _isdir(p: str) -> bool:
            # Only the ancestor mods dir is a directory; pkg-layout and ./child/mods are not.
            return p == str(ancestor_mods)

        with (
            patch.dict(os.environ, {"XCAGI_MODS_ROOT": "", "XCAGI_MODS_DIR": ""}, clear=False),
            patch("os.getcwd", return_value=str(child)),
            patch("app.infrastructure.mods.mod_manager.os.path.isdir", side_effect=_isdir),
        ):
            result = _default_mods_root()
        assert result == str(ancestor_mods)


# ---------------------------------------------------------------------------
# _invoke_mod_init_hook — sig.bind raises TypeError -> bare call fallback (234-236)
# ---------------------------------------------------------------------------


class TestInvokeModInitHookBindFallback:
    def test_bind_typeerror_falls_back_to_bare_call(self):
        """sig.bind(**kwargs) raising TypeError must fall back to calling init_fn() bare."""
        calls: list[tuple] = []

        def init_fn(app=None):
            calls.append((app,))

        # The hook resolves app -> None, then sig.bind(app=None) is attempted; force it to
        # raise TypeError so the except branch (init_fn() with no kwargs) runs.
        import inspect

        real_bind = inspect.Signature.bind

        def fake_bind(self, *args, **kwargs):
            raise TypeError("forced bind failure")

        with patch.object(inspect.Signature, "bind", fake_bind):
            _invoke_mod_init_hook(init_fn, mod_id="m1")

        # Fallback path calls init_fn() with no args -> app defaults to None.
        assert calls == [(None,)]
        # sanity: original bind still intact after patch context
        assert inspect.Signature.bind is real_bind


# ---------------------------------------------------------------------------
# _mods_scan_fingerprint — non-dir root is recorded but skipped (268)
# ---------------------------------------------------------------------------


class TestModsScanFingerprintNonDirRoot:
    def test_non_dir_root_path_recorded_but_skipped(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(missing)]):
            fp = mm._mods_scan_fingerprint()
        # The abspath of the missing root is included, but no manifest entries follow it.
        assert os.path.abspath(str(missing)) in fp
        assert ":" not in fp  # no "entry:mtime" suffix since dir doesn't exist


# ---------------------------------------------------------------------------
# resolve_mod_directory — empty candidate (385) and legacy alias hit (403-405)
# ---------------------------------------------------------------------------


class TestResolveModDirectory:
    def test_empty_candidate_returns_none_via_direct(self, tmp_path):
        """canonical_mod_id returning empty string exercises the empty-candidate guard (385)."""
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch("app.mod_sdk.industry_mod_aliases.canonical_mod_id", return_value="   "),
            patch("app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for", return_value=()),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
        ):
            result = mm.resolve_mod_directory("missing")
        assert result is None

    def test_legacy_alias_hit(self, tmp_path):
        """When direct + canonical miss but a legacy id maps to a dir on disk, return it (403-405)."""
        legacy_dir = tmp_path / "legacy-mod"
        legacy_dir.mkdir()
        (legacy_dir / "manifest.json").write_text(json.dumps({"id": "legacy-mod"}))

        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch(
                "app.mod_sdk.industry_mod_aliases.canonical_mod_id",
                return_value="neutral-mod",
            ),
            patch(
                "app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for",
                return_value=("legacy-mod",),
            ),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
        ):
            result = mm.resolve_mod_directory("neutral-mod")
        assert result == str(legacy_dir)


# ---------------------------------------------------------------------------
# _scan_mods_from_build_index — non-dict row skipped (429)
# ---------------------------------------------------------------------------


class TestScanModsBuildIndexNonDictRow:
    def test_non_dict_row_skipped(self, tmp_path):
        index_path = tmp_path / "mods-index.json"
        index_path.write_text(json.dumps({"fingerprint": "fp1", "mods": ["not_a_dict", 42, None]}))
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm._scan_mods_from_build_index("fp1")
        # All rows are non-dict -> nothing parsed -> None.
        assert result is None


# ---------------------------------------------------------------------------
# scan_mods — build index returns mods and is cached (450-452)
# ---------------------------------------------------------------------------


class TestScanModsUsesBuildIndex:
    def test_scan_mods_returns_indexed_and_caches(self, tmp_path):
        meta = ModMetadata(id="idx", name="Idx", version="1.0", mod_path=str(tmp_path / "idx"))
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
            patch.object(mm, "_mods_scan_fingerprint", return_value="fp1"),
            patch.object(mm, "_scan_mods_from_build_index", return_value=[meta]) as mock_idx,
        ):
            result = mm.scan_mods(use_cache=True)
        assert [m.id for m in result] == ["idx"]
        mock_idx.assert_called_once_with("fp1")
        # The indexed result is cached under the fingerprint.
        assert mm._scan_cache_fp == "fp1"
        assert mm._scan_cache_mods == [meta]


# ---------------------------------------------------------------------------
# load_mod — bundle path: registry already has metadata after parse (563)
# ---------------------------------------------------------------------------


class TestLoadModBundleAlreadyRegisteredAfterParse:
    def test_bundle_registered_between_checks_returns_true(self, tmp_path):
        meta = ModMetadata(
            id="bundle-x", name="B", version="1.0", mod_path=str(tmp_path), artifact="bundle"
        )
        registry = MagicMock()
        # First get_mod_metadata (top of load_mod) -> None (not loaded yet);
        # second (inside the bundle branch, line 562) -> truthy -> early return True (563).
        registry.get_mod_metadata.side_effect = [None, meta]

        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=registry),
            patch.object(mm, "resolve_mod_directory", return_value=str(tmp_path)),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
        ):
            result = mm.load_mod("bundle-x")
        assert result is True
        # register_mod must NOT be called on this early-return path.
        registry.register_mod.assert_not_called()


# ---------------------------------------------------------------------------
# load_mod — backend load raises recoverable error -> failure recorded (594-597)
# ---------------------------------------------------------------------------


class TestLoadModBackendException:
    def test_backend_failure_records_and_returns_false(self, tmp_path):
        meta = ModMetadata(id="boom", name="Boom", version="1.0", mod_path=str(tmp_path))
        registry = MagicMock()
        registry.get_mod_metadata.return_value = None
        registry.list_mod_ids.return_value = []

        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=registry),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch("app.infrastructure.mods.mod_manager.validate_dependencies", return_value=True),
            patch.object(mm, "resolve_mod_directory", return_value=str(tmp_path)),
            patch.object(mm, "_load_mod_backend", side_effect=RuntimeError("backend exploded")),
        ):
            result = mm.load_mod("boom")
        assert result is False
        assert len(mm._recent_load_failures) == 1
        assert mm._recent_load_failures[0]["stage"] == "backend"
        assert "backend exploded" in mm._recent_load_failures[0]["message"]


# ---------------------------------------------------------------------------
# _load_mod_backend — init hook raises TypeError -> warning, no raise (617-618)
# ---------------------------------------------------------------------------


class TestLoadModBackendInitTypeError:
    def test_init_hook_typeerror_logged_not_raised(self, tmp_path):
        mod_dir = tmp_path / "tmod"
        backend_dir = mod_dir / "backend"
        backend_dir.mkdir(parents=True)

        meta = ModMetadata(
            id="tmod",
            name="T",
            version="1.0",
            mod_path=str(mod_dir),
            backend_entry="entry",
            backend_init="setup",
        )

        module = MagicMock()
        module.setup = MagicMock()  # present & callable

        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                return_value=module,
            ),
            patch(
                "app.infrastructure.mods.mod_manager._invoke_mod_init_hook",
                side_effect=TypeError("bad init signature"),
            ),
            patch("app.infrastructure.mods.mod_manager._register_mod_hooks"),
        ):
            # TypeError from the init hook is caught and logged; must not propagate.
            mm._load_mod_backend("tmod", str(mod_dir), meta)
        # The entry module is still cached even though init raised TypeError.
        assert mm._backend_entry_modules["tmod"] is module


# ---------------------------------------------------------------------------
# install_mod_package — update existing target + activate success/fail (707-726)
# ---------------------------------------------------------------------------


def _make_xcmod(tmp_path, manifest: dict, name: str = "pkg.xcmod") -> str:
    """Build a minimal .xcmod zip whose extract dir holds manifest.json."""
    src = tmp_path / f"src_{name}"
    src.mkdir()
    (src / "manifest.json").write_text(json.dumps(manifest))
    zip_path = tmp_path / name
    with zipfile.ZipFile(str(zip_path), "w") as zf:
        zf.write(str(src / "manifest.json"), "manifest.json")
    return str(zip_path)


class TestInstallModPackageUpdateAndActivate:
    def test_update_existing_then_activate_success(self, tmp_path):
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        # Pre-existing install of m1 (v1) so the "already exists -> rmtree" branch runs (707-716).
        existing = mods_root / "m1"
        existing.mkdir()
        (existing / "manifest.json").write_text(
            json.dumps({"id": "m1", "name": "M1", "version": "1.0"})
        )

        manifest = {"id": "m1", "name": "M1", "version": "2.0"}
        pkg = _make_xcmod(tmp_path, manifest)

        new_meta = ModMetadata(id="m1", name="M1", version="2.0", mod_path=str(existing))
        mm = ModManager(mods_root=str(mods_root))
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch.object(mm, "load_mod", return_value=True) as mock_load,
            patch(
                "app.infrastructure.mods.mod_manager.parse_manifest",
                return_value=new_meta,
            ),
        ):
            ok, msg, meta = mm.install_mod_package(pkg, verify_signature=False, activate=True)
        assert ok is True
        assert "安装成功" in msg
        assert meta is new_meta
        mock_load.assert_called_once_with("m1")
        # Old directory replaced by the freshly extracted one.
        assert (mods_root / "m1" / "manifest.json").is_file()

    def test_activate_load_failure_returns_false(self, tmp_path):
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        manifest = {"id": "m2", "name": "M2", "version": "1.0"}
        pkg = _make_xcmod(tmp_path, manifest, name="pkg2.xcmod")

        mm = ModManager(mods_root=str(mods_root))
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch.object(mm, "load_mod", return_value=False),
        ):
            ok, msg, meta = mm.install_mod_package(pkg, verify_signature=False, activate=True)
        # Files installed but load failed -> (False, "...加载失败", None) (726).
        assert ok is False
        assert "加载失败" in msg
        assert meta is None

    def test_no_activate_returns_metadata(self, tmp_path):
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        manifest = {"id": "m3", "name": "M3", "version": "1.0"}
        pkg = _make_xcmod(tmp_path, manifest, name="pkg3.xcmod")

        no_act_meta = ModMetadata(id="m3", name="M3", version="1.0", mod_path="/x")
        mm = ModManager(mods_root=str(mods_root))
        with (
            patch("app.mod_sdk.product_skus.assert_mod_allowed_for_sku"),
            patch(
                "app.infrastructure.mods.mod_manager.parse_manifest",
                return_value=no_act_meta,
            ),
        ):
            ok, msg, meta = mm.install_mod_package(pkg, verify_signature=False, activate=False)
        assert ok is True
        assert "未激活" in msg
        assert meta is no_act_meta


# ---------------------------------------------------------------------------
# update_mod — extract success + reload (816, 835-838)
# ---------------------------------------------------------------------------


class TestUpdateModSuccess:
    def test_update_loaded_reload_success(self, tmp_path):
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        target = mods_root / "u1"
        target.mkdir()  # pre-existing dir so rmtree branch runs (816)

        cur_meta = MagicMock()
        cur_meta.version = "1.0"
        new_meta = ModMetadata(id="u1", name="U1", version="2.0", mod_path=str(target))

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        (extract_dir / "manifest.json").write_text(json.dumps({"id": "u1", "version": "2.0"}))

        registry = MagicMock()
        registry.get_mod_metadata.return_value = cur_meta

        mm = ModManager(mods_root=str(mods_root))
        mm._loaded_mods.append("u1")

        pkg_instance = MagicMock()
        pkg_instance.manifest = {"version": "2.0"}

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=registry),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage", return_value=pkg_instance
            ) as mock_pkg_cls,
            patch.object(mm, "unload_mod"),
            patch.object(mm, "load_mod", return_value=True) as mock_load,
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=new_meta),
        ):
            mock_pkg_cls.extract_package.return_value = (str(extract_dir), {})
            ok, msg, meta = mm.update_mod("u1", "/fake.xcmod", verify_signature=False)
        assert ok is True
        assert "更新成功" in msg and "2.0" in msg
        assert meta is new_meta
        mock_load.assert_called_once_with("u1")

    def test_update_loaded_reload_failure(self, tmp_path):
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        cur_meta = MagicMock()
        cur_meta.version = "1.0"

        extract_dir = tmp_path / "extracted2"
        extract_dir.mkdir()
        (extract_dir / "manifest.json").write_text(json.dumps({"id": "u2"}))

        registry = MagicMock()
        registry.get_mod_metadata.return_value = cur_meta

        mm = ModManager(mods_root=str(mods_root))
        mm._loaded_mods.append("u2")

        pkg_instance = MagicMock()
        pkg_instance.manifest = {"version": "2.0"}

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=registry),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage", return_value=pkg_instance
            ) as mock_pkg_cls,
            patch.object(mm, "unload_mod"),
            patch.object(mm, "load_mod", return_value=False),
        ):
            mock_pkg_cls.extract_package.return_value = (str(extract_dir), {})
            ok, msg, meta = mm.update_mod("u2", "/fake.xcmod", verify_signature=False)
        # Files updated but reload failed -> (False, "...加载失败", None) (835).
        assert ok is False
        assert "加载失败" in msg
        assert meta is None

    def test_update_not_loaded_returns_metadata(self, tmp_path):
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        cur_meta = MagicMock()
        cur_meta.version = "1.0"

        extract_dir = tmp_path / "extracted3"
        extract_dir.mkdir()
        (extract_dir / "manifest.json").write_text(json.dumps({"id": "u3"}))

        registry = MagicMock()
        registry.get_mod_metadata.return_value = cur_meta

        new_meta = ModMetadata(id="u3", name="U3", version="3.0", mod_path="/x")
        mm = ModManager(mods_root=str(mods_root))
        # NOT in _loaded_mods -> was_loaded False -> else branch (837-838)

        pkg_instance = MagicMock()
        pkg_instance.manifest = {"version": "3.0"}

        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=registry),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage", return_value=pkg_instance
            ) as mock_pkg_cls,
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=new_meta),
        ):
            mock_pkg_cls.extract_package.return_value = (str(extract_dir), {})
            ok, msg, meta = mm.update_mod("u3", "/fake.xcmod", verify_signature=False)
        assert ok is True
        assert "更新成功" in msg
        assert meta is new_meta


# ---------------------------------------------------------------------------
# validate_mod_package — bundle / employee_pack / backend+frontend (882-900)
# ---------------------------------------------------------------------------


class TestValidateModPackageArtifactBranches:
    def _zip_with_dirs(self, tmp_path, manifest, *, backend=False, frontend=False, name="v.xcmod"):
        src = tmp_path / f"src_{name}"
        src.mkdir()
        (src / "manifest.json").write_text(json.dumps(manifest))
        files = [(str(src / "manifest.json"), "manifest.json")]
        if backend:
            (src / "backend").mkdir()
            # intentionally NO entry file -> error path (892)
            (src / "backend" / "keep.txt").write_text("x")
            files.append((str(src / "backend" / "keep.txt"), "backend/keep.txt"))
        if frontend:
            (src / "frontend").mkdir()
            (src / "frontend" / "keep.txt").write_text("x")
            files.append((str(src / "frontend" / "keep.txt"), "frontend/keep.txt"))
        zip_path = tmp_path / name
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            for fp, arc in files:
                zf.write(fp, arc)
        return str(zip_path)

    def test_bundle_artifact_calls_bundle_validator(self, tmp_path):
        manifest = {"id": "b1", "name": "B1", "version": "1.0", "artifact": "bundle"}
        pkg = self._zip_with_dirs(tmp_path, manifest, name="bundle.xcmod")
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.validate_bundle_manifest",
            return_value=["bundle err"],
        ) as mock_v:
            ok, msg, info = mm.validate_mod_package(pkg)
        assert ok is False
        assert "bundle err" in msg
        assert info["artifact"] == ARTIFACT_BUNDLE
        mock_v.assert_called_once()

    def test_employee_pack_calls_employee_validator(self, tmp_path):
        manifest = {"id": "e1", "name": "E1", "version": "1.0", "artifact": "employee_pack"}
        pkg = self._zip_with_dirs(tmp_path, manifest, name="emp.xcmod")
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.validate_employee_pack_manifest",
            return_value=["emp err"],
        ) as mock_v:
            ok, msg, info = mm.validate_mod_package(pkg)
        assert ok is False
        assert "emp err" in msg
        assert info["artifact"] == ARTIFACT_EMPLOYEE_PACK
        mock_v.assert_called_once()

    def test_backend_entry_missing_file_error(self, tmp_path):
        # plain mod (no artifact) with backend dir + declared entry but missing entry file (890-892)
        manifest = {
            "id": "p1",
            "name": "P1",
            "version": "1.0",
            "backend": {"entry": "main"},
        }
        pkg = self._zip_with_dirs(tmp_path, manifest, backend=True, name="be.xcmod")
        mm = ModManager(mods_root=str(tmp_path))
        ok, msg, info = mm.validate_mod_package(pkg)
        assert ok is False
        assert "后端入口文件不存在" in msg

    def test_frontend_routes_missing_file_error(self, tmp_path):
        # plain mod with frontend dir + declared routes but missing routes file (896-900)
        manifest = {
            "id": "p2",
            "name": "P2",
            "version": "1.0",
            "frontend": {"routes": "routes"},
        }
        pkg = self._zip_with_dirs(tmp_path, manifest, frontend=True, name="fe.xcmod")
        mm = ModManager(mods_root=str(tmp_path))
        ok, msg, info = mm.validate_mod_package(pkg)
        assert ok is False
        assert "前端路由文件不存在" in msg


# ---------------------------------------------------------------------------
# list_all_mods — entitlement filter raises -> swallowed (989)
# ---------------------------------------------------------------------------


class TestListAllModsFilterException:
    def test_filter_exception_swallowed(self, tmp_path):
        meta = ModMetadata(id="lam", name="L", version="1.0", mod_path="/x")
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(
                "app.infrastructure.mods.employee_registry.get_employee_registry",
                side_effect=ImportError("no er"),
            ),
            patch(
                "app.enterprise.mod_entitlements.filter_mod_rows_for_enterprise",
                side_effect=RuntimeError("filter boom"),
            ),
        ):
            result = mm.list_all_mods()
        # Filter exception is swallowed; the unfiltered scan rows are returned.
        assert any(r["id"] == "lam" for r in result)


# ---------------------------------------------------------------------------
# load_all_mods — per-mod load failure logs (1054)
# ---------------------------------------------------------------------------


class TestLoadAllModsFailure:
    def test_failed_mod_not_in_result(self, tmp_path):
        meta = ModMetadata(id="failmod", name="F", version="1.0", mod_path="/x")
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "scan_mods", return_value=[meta]),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=True,
            ),
            patch.object(mm, "load_mod", return_value=False),
        ):
            result = mm.load_all_mods()
        # load_mod returned False -> mod not appended; the failure-log branch runs.
        assert result == []


# ---------------------------------------------------------------------------
# register_employee_pack_routes — success + error (1085, 1096-1120)
# ---------------------------------------------------------------------------


def _write_emp_pack(tmp_path, pid, manifest):
    pack_dir = tmp_path / "_employees" / pid
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.json").write_text(json.dumps(manifest))
    return pack_dir


class TestRegisterEmployeePackRoutes:
    def test_resolves_mod_manager_when_none(self, tmp_path):
        """mod_manager=None resolves the singleton (1085); missing manifest -> False."""
        singleton = MagicMock()
        singleton.mods_root = str(tmp_path)
        with patch("app.infrastructure.mods.mod_manager.get_mod_manager", return_value=singleton):
            result = register_employee_pack_routes(MagicMock(), None, "ghost")
        assert result is False

    def test_invalid_json_returns_false(self, tmp_path):
        pack_dir = tmp_path / "_employees" / "badjson"
        pack_dir.mkdir(parents=True)
        (pack_dir / "manifest.json").write_text("{ not valid json")
        mm = MagicMock()
        mm.mods_root = str(tmp_path)
        result = register_employee_pack_routes(MagicMock(), mm, "badjson")
        assert result is False

    def test_success_registers_routes(self, tmp_path):
        manifest = {
            "id": "emp1",
            "artifact": "employee_pack",
            "backend": {"entry": "main"},
        }
        _write_emp_pack(tmp_path, "emp1", manifest)
        mm = MagicMock()
        mm.mods_root = str(tmp_path)

        module = MagicMock()
        reg = MagicMock()
        module.register_fastapi_routes = reg

        from app.infrastructure.mods import mod_manager as mm_mod

        # ensure not pre-registered from another test
        mm_mod._employee_pack_routes_registered.discard("emp1")
        with patch(
            "app.infrastructure.mods.mod_manager.import_mod_backend_py", return_value=module
        ):
            app = MagicMock()
            result = register_employee_pack_routes(app, mm, "emp1")
        try:
            assert result is True
            reg.assert_called_once_with(app, "emp1")
            assert "emp1" in mm_mod._employee_pack_routes_registered
        finally:
            mm_mod._employee_pack_routes_registered.discard("emp1")

    def test_registration_error_records_failure(self, tmp_path):
        manifest = {
            "id": "emp2",
            "artifact": "employee_pack",
            "backend": {"entry": "main"},
        }
        _write_emp_pack(tmp_path, "emp2", manifest)
        mm = MagicMock()
        mm.mods_root = str(tmp_path)

        from app.infrastructure.mods import mod_manager as mm_mod

        mm_mod._employee_pack_routes_registered.discard("emp2")
        with patch(
            "app.infrastructure.mods.mod_manager.import_mod_backend_py",
            side_effect=RuntimeError("import fail"),
        ):
            result = register_employee_pack_routes(MagicMock(), mm, "emp2")
        assert result is False
        mm.record_blueprint_failure.assert_called_once()


# ---------------------------------------------------------------------------
# load_employee_pack_routes — iterates and registers a valid pack (1146-1153)
# ---------------------------------------------------------------------------


class TestLoadEmployeePackRoutesRegisters:
    def test_registers_valid_pack(self, tmp_path):
        _write_emp_pack(
            tmp_path,
            "good",
            {"id": "good", "artifact": "employee_pack", "backend": {"entry": "main"}},
        )
        # A bad-json dir to exercise the continue (1146-1147)
        bad = tmp_path / "_employees" / "bad"
        bad.mkdir(parents=True)
        (bad / "manifest.json").write_text("{not json")
        # A dir with no manifest.json to exercise the isfile continue (1142)
        (tmp_path / "_employees" / "nomanifest").mkdir(parents=True)
        # A non-dir entry to exercise the isdir continue (1139)
        (tmp_path / "_employees" / "afile").write_text("x")

        mm = MagicMock()
        mm.mods_root = str(tmp_path)
        with patch("app.infrastructure.mods.mod_manager.register_employee_pack_routes") as mock_reg:
            load_employee_pack_routes(MagicMock(), mm)
        # Only the valid employee_pack triggers a registration call.
        mock_reg.assert_called_once()
        assert mock_reg.call_args.args[2] == "good"


# ---------------------------------------------------------------------------
# _register_single_mod_http_routes — ws success + no HTTP registrar (1199, 1203-1204)
# ---------------------------------------------------------------------------


class TestRegisterSingleModHttpRoutesBranches:
    def test_websocket_success_logged(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = MagicMock()
        mm._http_routes_registered = set()
        mm._backend_entry_modules = {}
        meta = MagicMock()
        meta.backend_entry = "entry"
        meta.mod_path = str(tmp_path)

        module = MagicMock()
        module.register_fastapi_routes = MagicMock()
        module.register_websocket_routes = MagicMock(return_value=True)  # ws OK (1199)

        registry = MagicMock()
        registry.get_mod_metadata.return_value = meta
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=registry),
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                return_value=module,
            ),
        ):
            result = _register_single_mod_http_routes(MagicMock(), mm, "wsmod")
        assert result is True
        module.register_websocket_routes.assert_called_once()

    def test_no_http_registrar_returns_false(self, tmp_path):
        from app.infrastructure.mods.mod_manager import _register_single_mod_http_routes

        mm = MagicMock()
        mm._http_routes_registered = set()
        mm._backend_entry_modules = {}
        meta = MagicMock()
        meta.backend_entry = "entry"
        meta.mod_path = str(tmp_path)

        # Module has neither register_fastapi_routes nor register_websocket_routes.
        module = MagicMock(spec=[])

        registry = MagicMock()
        registry.get_mod_metadata.return_value = meta
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=registry),
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                return_value=module,
            ),
        ):
            result = _register_single_mod_http_routes(MagicMock(), mm, "noreg")
        # registered stays False -> "no HTTP route registrar" branch -> return False (1203-1204).
        assert result is False
        assert "noreg" not in mm._http_routes_registered


# ---------------------------------------------------------------------------
# ensure_mod_api_ready — reaches final register call (1293)
# ---------------------------------------------------------------------------


class TestEnsureModApiReadyFinalRegister:
    def test_calls_register_single_mod_http_routes(self):
        mm = MagicMock()
        mm._loaded_mods = ["m1"]
        mm._http_routes_registered = set()
        app = MagicMock()
        with (
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
            patch("app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id"),
            patch(
                "app.infrastructure.mods.mod_manager._mod_allowed_for_api_load",
                return_value=True,
            ),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mm),
            patch("app.fastapi_app.get_fastapi_app", return_value=app),
            patch(
                "app.infrastructure.mods.mod_manager._register_single_mod_http_routes",
                return_value=True,
            ) as mock_reg,
        ):
            result = ensure_mod_api_ready("m1")
        assert result is True
        mock_reg.assert_called_once_with(app, mm, "m1")


# ---------------------------------------------------------------------------
# load_mod_routes — ordering: registry id not in _loaded_mods appended (1325-1340)
# ---------------------------------------------------------------------------


class TestLoadModRoutesOrdering:
    def test_routable_appended_after_loaded(self):
        mm = MagicMock()
        # _loaded_mods has "a" (routable) plus "ghost" (NOT in registry -> skipped: 1334)
        mm._loaded_mods = ["a", "ghost"]
        mm._blueprint_failures = ["stale"]

        meta_a = MagicMock()
        meta_a.id = "a"
        meta_a.backend_entry = "entry"
        meta_b = MagicMock()
        meta_b.id = "b"  # in registry, not in _loaded_mods -> appended via routable (1338-1340)
        meta_b.backend_entry = "entry"
        meta_dup = MagicMock()
        meta_dup.id = "a"  # duplicate id -> seen_ids continue (1327)
        meta_dup.backend_entry = "entry"
        meta_noentry = MagicMock()
        meta_noentry.id = "c"
        meta_noentry.backend_entry = ""  # skipped (no backend_entry)

        registry = MagicMock()
        registry.list_mods.return_value = [meta_a, meta_b, meta_dup, meta_noentry]

        app = MagicMock()
        calls: list[str] = []
        with (
            patch("app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=registry),
            patch(
                "app.infrastructure.mods.mod_manager._register_single_mod_http_routes",
                side_effect=lambda a, m, mid: calls.append(mid),
            ),
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            load_mod_routes(app, mm)
        # "a" first (from _loaded_mods order), then "b" appended from routable; "ghost"/"c" excluded.
        assert calls == ["a", "b"]
        assert mm._blueprint_failures == []

    def test_resolves_singleton_when_mod_manager_none(self):
        """load_mod_routes(app, None) resolves get_mod_manager() (1312)."""
        mm = MagicMock()
        mm._loaded_mods = []
        mm._blueprint_failures = []
        registry = MagicMock()
        registry.list_mods.return_value = []
        app = MagicMock()
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mm
            ) as mock_get_mm,
            patch("app.infrastructure.mods.mod_manager.mount_on_disk_primary_client_mods"),
            patch("app.infrastructure.mods.mod_manager.get_mod_registry", return_value=registry),
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            load_mod_routes(app, None)
        mock_get_mm.assert_called_once()
