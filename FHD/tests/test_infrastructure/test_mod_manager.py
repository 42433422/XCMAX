"""Behavior tests for app.infrastructure.mods.mod_manager.

These tests assert concrete return values / observable state changes rather than
mere "did not raise" smoke coverage. Mocks are confined to genuine external
collaborators (registry, SKU policy, enterprise entitlements); the assertions
always land on the manager's own observable behavior.
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.infrastructure.mods.mod_manager import (
    ModManager,
    _all_mods_roots,
    _register_mod_hooks,
    _repo_layout_mods_candidates,
    _short_exc_message,
    import_mod_backend_py,
    is_mods_disabled,
)

# ========================= is_mods_disabled ==============================


class TestIsModsDisabled:
    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "Yes", "on", " On "])
    def test_truthy_values_disable(self, val):
        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": val}):
            assert is_mods_disabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", "", "garbage"])
    def test_falsy_or_unknown_values_enabled(self, val):
        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": val}):
            assert is_mods_disabled() is False

    def test_unset_is_enabled(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XCAGI_DISABLE_MODS", None)
            assert is_mods_disabled() is False


# ========================= _short_exc_message ============================


class TestShortExcMessage:
    def test_keeps_short_message_verbatim(self):
        assert _short_exc_message(ValueError("boom")) == "boom"

    def test_empty_message_falls_back_to_type_name(self):
        assert _short_exc_message(ValueError("")) == "ValueError"

    def test_long_message_truncated_with_ellipsis(self):
        msg = "x" * 600
        out = _short_exc_message(ValueError(msg), max_len=480)
        assert len(out) == 480
        assert out.endswith("...")
        assert out.startswith("x" * 10)


# ========================= _repo_layout_mods_candidates ==================


class TestRepoLayoutModsCandidates:
    def test_every_candidate_is_an_existing_directory(self):
        result = _repo_layout_mods_candidates()
        # All returned paths must be real directories and absolute.
        for p in result:
            assert os.path.isdir(p), f"non-dir candidate leaked: {p}"
            assert os.path.isabs(p)

    def test_no_duplicate_candidates(self):
        result = _repo_layout_mods_candidates()
        assert len(result) == len(set(result))


# ========================= _all_mods_roots ===============================


class TestAllModsRoots:
    def test_empty_primary_omits_blank_entry(self, tmp_path):
        result = _all_mods_roots("")
        # A blank primary must never appear as a root.
        assert "" not in result
        assert all(os.path.isdir(p) for p in result)

    def test_valid_primary_is_first(self, tmp_path):
        mods_dir = str(tmp_path / "mods")
        os.makedirs(mods_dir)
        result = _all_mods_roots(mods_dir)
        assert result[0] == os.path.abspath(mods_dir)

    def test_nonexistent_primary_excluded(self, tmp_path):
        missing = str(tmp_path / "does_not_exist")
        result = _all_mods_roots(missing)
        assert missing not in result

    def test_env_root_appended_without_duplicating_primary(self, tmp_path):
        mods_dir = str(tmp_path / "mods")
        os.makedirs(mods_dir)
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": mods_dir}):
            result = _all_mods_roots(mods_dir)
        # primary and env point at the same dir -> exactly one occurrence.
        assert result.count(os.path.abspath(mods_dir)) == 1

    def test_distinct_env_root_added_as_extra_root(self, tmp_path):
        primary = str(tmp_path / "primary")
        env_root = str(tmp_path / "env_extra")
        os.makedirs(primary)
        os.makedirs(env_root)
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": env_root}):
            result = _all_mods_roots(primary)
        assert os.path.abspath(primary) in result
        assert os.path.abspath(env_root) in result
        # primary stays ahead of the env-supplied root.
        assert result.index(os.path.abspath(primary)) < result.index(os.path.abspath(env_root))


# ========================= import_mod_backend_py =========================


class TestImportModBackendPy:
    def test_file_not_found_message_names_path(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="backend file missing"):
            import_mod_backend_py(str(tmp_path / "nonexistent"), "test_mod", "blueprints")

    def test_successful_import_exposes_module_globals(self, tmp_path):
        mod_path = str(tmp_path / "test_mod")
        backend_path = os.path.join(mod_path, "backend")
        os.makedirs(backend_path)
        Path(os.path.join(backend_path, "services.py")).write_text("VALUE = 42\nNAME = 'svc'\n")
        module = import_mod_backend_py(mod_path, "test_mod", "services")
        assert module.VALUE == 42
        assert module.NAME == "svc"

    def test_repeated_import_returns_cached_module(self, tmp_path):
        mod_path = str(tmp_path / "test_mod2")
        backend_path = os.path.join(mod_path, "backend")
        os.makedirs(backend_path)
        Path(os.path.join(backend_path, "cached.py")).write_text("COUNTER = 0\n")
        m1 = import_mod_backend_py(mod_path, "test_mod2", "cached")
        # Mutate the module; a cached re-import must observe the mutation (same object).
        m1.COUNTER = 5
        m2 = import_mod_backend_py(mod_path, "test_mod2", "cached")
        assert m2 is m1
        assert m2.COUNTER == 5

    def test_same_mod_id_different_paths_are_isolated(self, tmp_path):
        # Same mod_id but two physical roots must yield distinct modules (path is in cache key).
        for idx, val in ((1, "alpha"), (2, "beta")):
            backend = tmp_path / f"root{idx}" / "backend"
            backend.mkdir(parents=True)
            (backend / "conf.py").write_text(f"FLAVOR = {val!r}\n")
        m1 = import_mod_backend_py(str(tmp_path / "root1"), "dup", "conf")
        m2 = import_mod_backend_py(str(tmp_path / "root2"), "dup", "conf")
        assert m1 is not m2
        assert m1.FLAVOR == "alpha"
        assert m2.FLAVOR == "beta"


# ========================= _register_mod_hooks ===========================


class TestRegisterModHooks:
    """_register_mod_hooks must actually subscribe valid handlers into the live
    HookManager and skip the invalid/unresolvable ones. Assertions read the
    HookManager's observable subscriber list and trigger semantics."""

    def _hook_manager(self):
        from app.infrastructure.mods.hooks import get_hook_manager

        return get_hook_manager()

    def test_no_hooks_subscribes_nothing(self):
        from app.infrastructure.mods.manifest import ModMetadata

        hm = self._hook_manager()
        before = list(hm.list_subscribers("evt.none"))
        meta = ModMetadata(id="t1", name="T", version="1.0", mod_path="/tmp/test")
        _register_mod_hooks("t1", meta)
        assert hm.list_subscribers("evt.none") == before

    def test_valid_hook_is_subscribed_and_invokable(self, tmp_path):
        from app.infrastructure.mods.manifest import ModMetadata

        backend = tmp_path / "backend"
        backend.mkdir()
        # Handler records a side effect so we can prove the *right* callable was wired.
        (backend / "handlers.py").write_text(
            "SEEN = []\ndef on_order(*args, **kwargs):\n    SEEN.append(kwargs.get('n'))\n"
        )
        meta = ModMetadata(
            id="hookmod",
            name="H",
            version="1.0",
            mod_path=str(tmp_path),
            hooks={"hookmod.order.created": "backend.handlers.on_order"},
        )
        hm = self._hook_manager()
        _register_mod_hooks("hookmod", meta)
        assert "on_order" in hm.list_subscribers("hookmod.order.created")
        # Trigger flows through to the real handler.
        hm.trigger("hookmod.order.created", n=99)
        module = import_mod_backend_py(str(tmp_path), "hookmod", "handlers")
        assert module.SEEN == [99]

    def test_no_mod_path_skips_subscription(self):
        from app.infrastructure.mods.manifest import ModMetadata

        hm = self._hook_manager()
        meta = ModMetadata(
            id="nopath",
            name="Test",
            version="1.0",
            mod_path="",
            hooks={"nopath.event": "backend.handler.fn"},
        )
        _register_mod_hooks("nopath", meta)
        # Missing mod_path -> handler can't be resolved -> nothing subscribed.
        assert hm.list_subscribers("nopath.event") == []

    def test_invalid_spec_without_dot_skips_subscription(self):
        from app.infrastructure.mods.manifest import ModMetadata

        hm = self._hook_manager()
        meta = ModMetadata(
            id="baddot",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            hooks={"baddot.event": "invalid_no_dot"},
        )
        _register_mod_hooks("baddot", meta)
        assert hm.list_subscribers("baddot.event") == []


# ========================= ModManager._mods_scan_fingerprint =============


class TestModsScanFingerprint:
    def test_empty_dir_fingerprint_has_no_mod_entries(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        mm = ModManager(mods_root=str(mods_dir))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
            fp = mm._mods_scan_fingerprint()
        # Only the root path component, no "<entry>:<mtime>" pieces.
        assert fp == os.path.abspath(str(mods_dir))

    def test_manifest_entry_present_in_fingerprint(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "test-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            '{"id": "test-mod", "name": "Test", "version": "1.0"}'
        )
        mm = ModManager(mods_root=str(mods_dir))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
            fp = mm._mods_scan_fingerprint()
        assert "test-mod:" in fp

    def test_fingerprint_changes_when_manifest_modified(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "fp-mod"
        mod_dir.mkdir(parents=True)
        manifest = mod_dir / "manifest.json"
        manifest.write_text('{"id": "fp-mod", "name": "T", "version": "1.0"}')
        mm = ModManager(mods_root=str(mods_dir))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
            fp1 = mm._mods_scan_fingerprint()
            # Bump mtime well past the original.
            future = os.path.getmtime(manifest) + 1000
            os.utime(manifest, (future, future))
            fp2 = mm._mods_scan_fingerprint()
        assert fp1 != fp2

    def test_underscore_entries_excluded_from_fingerprint(self, tmp_path):
        mods_dir = tmp_path / "mods"
        priv = mods_dir / "_private"
        priv.mkdir(parents=True)
        (priv / "manifest.json").write_text('{"id": "priv", "name": "P", "version": "1.0"}')
        mm = ModManager(mods_root=str(mods_dir))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
            fp = mm._mods_scan_fingerprint()
        assert "_private" not in fp


# ========================= ModManager._refresh_mods_root_if_needed =======


class TestRefreshModsRootIfNeeded:
    def test_env_var_updates_root_and_resets_attempts(self, tmp_path):
        mods_dir = str(tmp_path / "env_mods")
        os.makedirs(mods_dir)
        mm = ModManager(mods_root="/tmp/old_nonexistent")
        mm._ensure_attempts = 7
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": mods_dir}):
            mm._refresh_mods_root_if_needed()
        assert mm.mods_root == mods_dir
        assert mm._ensure_attempts == 0

    def test_missing_root_falls_back_to_default(self, tmp_path):
        fallback = str(tmp_path / "fallback")
        mm = ModManager(mods_root="/tmp/nonexistent_path_for_test")
        with patch(
            "app.infrastructure.mods.mod_manager._default_mods_root",
            return_value=fallback,
        ):
            mm._refresh_mods_root_if_needed()
        assert mm.mods_root == fallback

    def test_env_var_not_a_dir_keeps_existing_root(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict(os.environ, {"XCAGI_MODS_ROOT": "/tmp/nonexistent_env_dir"}):
            mm._refresh_mods_root_if_needed()
        assert mm.mods_root == str(tmp_path)

    def test_valid_existing_root_unchanged_no_env(self, tmp_path):
        # No env override + existing dir -> root stays put, no fallback resolution.
        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XCAGI_MODS_ROOT", None)
            os.environ.pop("XCAGI_MODS_DIR", None)
            with patch("app.infrastructure.mods.mod_manager._default_mods_root") as default:
                mm._refresh_mods_root_if_needed()
        assert mm.mods_root == str(tmp_path)
        default.assert_not_called()


# ========================= ModManager.ensure_mods_loaded ==================


class TestEnsureModsLoaded:
    def test_disabled_short_circuits_before_scan(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": "1"}):
            with (
                patch.object(mm, "scan_mods") as scan,
                patch.object(mm, "load_all_mods") as load_all,
            ):
                mm.ensure_mods_loaded(None)
        scan.assert_not_called()
        load_all.assert_not_called()
        assert mm._ensure_attempts == 0

    def test_already_loaded_does_not_scan_or_load(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "list_loaded_mods", return_value=[Mock()]),
            patch.object(mm, "scan_mods") as scan,
            patch.object(mm, "load_all_mods") as load_all,
        ):
            mm.ensure_mods_loaded(None)
        scan.assert_not_called()
        load_all.assert_not_called()

    def test_no_discovered_mods_skips_load(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[]),
            patch.object(mm, "load_all_mods") as load_all,
        ):
            mm.ensure_mods_loaded(None)
        load_all.assert_not_called()
        assert mm._ensure_attempts == 0

    def test_throttled_recent_attempt_skips_load(self, tmp_path):
        import time

        mm = ModManager(mods_root=str(tmp_path))
        mm._last_ensure_at = time.monotonic()  # just now -> within 1.5s window
        mm._ensure_attempts = 1
        with (
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[Mock()]),
            patch.object(mm, "load_all_mods") as load_all,
        ):
            mm.ensure_mods_loaded(None)
        load_all.assert_not_called()
        # Attempt counter is not advanced while throttled.
        assert mm._ensure_attempts == 1

    def test_max_attempts_exhausted_skips_load(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._ensure_attempts = 20
        with (
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[Mock()]),
            patch.object(mm, "load_all_mods") as load_all,
        ):
            mm.ensure_mods_loaded(None)
        load_all.assert_not_called()
        assert mm._ensure_attempts == 20

    def test_happy_path_loads_and_registers_routes(self, tmp_path):
        sentinel_app = object()
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[Mock()]),
            patch.object(mm, "load_all_mods") as load_all,
            patch("app.infrastructure.mods.mod_manager.load_mod_routes") as routes,
        ):
            mm.ensure_mods_loaded(sentinel_app)
        load_all.assert_called_once_with()
        routes.assert_called_once_with(sentinel_app, mm)
        assert mm._ensure_attempts == 1
        assert mm._last_ensure_at > 0


# ========================= ModManager.scan_mods ===========================


class TestScanMods:
    def test_scan_empty_dir_returns_empty_list(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        mm = ModManager(mods_root=str(mods_dir))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
            result = mm.scan_mods(use_cache=False)
        assert result == []

    def test_scan_returns_parsed_metadata(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "test-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "test-mod", "name": "Test Mod", "version": "1.2.3"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
            result = mm.scan_mods(use_cache=False)
        assert [m.id for m in result] == ["test-mod"]
        assert result[0].name == "Test Mod"
        assert result[0].version == "1.2.3"
        assert result[0].mod_path == str(mod_dir)

    def test_cache_returns_equal_content_across_calls(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "test-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "test-mod", "name": "Test Mod", "version": "1.0.0"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
            r1 = mm.scan_mods(use_cache=True)
            r2 = mm.scan_mods(use_cache=True)
        assert [m.id for m in r1] == [m.id for m in r2] == ["test-mod"]
        # Cache fingerprint is populated after the first scan.
        assert mm._scan_cache_fp != ""

    def test_underscore_dirs_skipped(self, tmp_path):
        mods_dir = tmp_path / "mods"
        (mods_dir / "_private").mkdir(parents=True)
        (mods_dir / "_private" / "manifest.json").write_text(
            json.dumps({"id": "private", "name": "Private", "version": "1.0"})
        )
        (mods_dir / "real-mod").mkdir()
        (mods_dir / "real-mod" / "manifest.json").write_text(
            json.dumps({"id": "real-mod", "name": "Real", "version": "1.0"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
            result = mm.scan_mods(use_cache=False)
        ids = [m.id for m in result]
        assert ids == ["real-mod"]
        assert "private" not in ids

    def test_duplicate_ids_deduplicated_keeping_first(self, tmp_path):
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        for root, ver in ((root_a, "1.0"), (root_b, "2.0")):
            d = root / "dup"
            d.mkdir(parents=True)
            (d / "manifest.json").write_text(
                json.dumps({"id": "dup", "name": "Dup", "version": ver})
            )
        mm = ModManager(mods_root=str(root_a))
        with patch.object(mm, "all_mods_roots", return_value=[str(root_a), str(root_b)]):
            result = mm.scan_mods(use_cache=False)
        assert len(result) == 1
        # First root wins -> version 1.0.
        assert result[0].version == "1.0"

    def test_unparseable_manifest_recorded_as_scan_error(self, tmp_path):
        mods_dir = tmp_path / "mods"
        bad = mods_dir / "bad-mod"
        bad.mkdir(parents=True)
        (bad / "manifest.json").write_text("not json {{{")
        mm = ModManager(mods_root=str(mods_dir))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]):
            result = mm.scan_mods(use_cache=False)
        assert result == []
        errors = mm.get_scan_manifest_errors()
        assert len(errors) == 1
        assert errors[0]["entry"] == "bad-mod"


# ========================= ModManager.load_mod ===========================


class TestLoadMod:
    def test_sku_blocked_records_failure(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.mod_sdk.product_skus.assert_mod_allowed_for_sku",
            side_effect=PermissionError("blocked"),
        ):
            result = mm.load_mod("blocked-mod")
        assert result is False
        failures = mm.get_recent_load_failures()
        assert len(failures) == 1
        assert failures[0]["mod_id"] == "blocked-mod"
        assert failures[0]["stage"] == "sku_policy"
        assert "blocked" in failures[0]["message"]
        # Blocked mod must not be marked loaded.
        assert "blocked-mod" not in mm._loaded_mods

    def test_already_in_registry_returns_true_and_syncs_list(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = Mock()
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.load_mod("sync-mod")
        assert result is True
        # The "registry has it but _loaded_mods missed it" repair path runs.
        assert mm._loaded_mods == ["sync-mod"]

    def test_mod_not_found_records_fs_failure(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=None),
        ):
            result = mm.load_mod("missing-mod")
        assert result is False
        assert mm.get_recent_load_failures()[0]["stage"] == "fs"

    def test_invalid_manifest_records_manifest_failure(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "bad-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text("invalid json{{{")
        mm = ModManager(mods_root=str(mods_dir))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
        ):
            result = mm.load_mod("bad-mod")
        assert result is False
        assert mm.get_recent_load_failures()[0]["stage"] == "manifest"

    def test_bundle_registers_metadata_only(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "bundle-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {"id": "bundle-mod", "name": "Bundle", "version": "1.0", "artifact": "bundle"}
            )
        )
        mm = ModManager(mods_root=str(mods_dir))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        mock_registry.register_mod.return_value = True
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
        ):
            result = mm.load_mod("bundle-mod")
        assert result is True
        # Bundle was registered and the registered metadata carries the bundle artifact.
        mock_registry.register_mod.assert_called_once()
        registered_meta = mock_registry.register_mod.call_args.args[0]
        assert registered_meta.artifact == "bundle"
        assert "bundle-mod" in mm._loaded_mods

    def test_unsatisfied_dependencies_records_failure(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "dep-mod"
        mod_dir.mkdir(parents=True)
        # xcagi version requirement that cannot be met forces a real validate_dependencies=False.
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "dep-mod",
                    "name": "Dep Mod",
                    "version": "1.0",
                    "dependencies": {"xcagi": ">=99.0.0"},
                }
            )
        )
        mm = ModManager(mods_root=str(mods_dir))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        mock_registry.list_mod_ids.return_value = []
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
        ):
            result = mm.load_mod("dep-mod")
        assert result is False
        assert mm.get_recent_load_failures()[0]["stage"] == "dependencies"
        mock_registry.register_mod.assert_not_called()

    def test_load_with_real_backend_invokes_init_and_registers(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "backend-mod"
        backend_dir = mod_dir / "backend"
        backend_dir.mkdir(parents=True)
        # Real backend module whose init records a side effect.
        (backend_dir / "init.py").write_text(
            "INIT_CALLS = []\ndef setup():\n    INIT_CALLS.append(True)\n"
        )
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "backend-mod",
                    "name": "Backend Mod",
                    "version": "1.0",
                    "backend": {"entry": "init", "init": "setup"},
                }
            )
        )
        mm = ModManager(mods_root=str(mods_dir))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        mock_registry.list_mod_ids.return_value = []
        mock_registry.register_mod.return_value = True
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
        ):
            result = mm.load_mod("backend-mod")
        assert result is True
        assert "backend-mod" in mm._loaded_mods
        # The real backend entry module was cached and its init() actually ran.
        module = mm._backend_entry_modules["backend-mod"]
        assert module.INIT_CALLS == [True]
        mock_registry.register_mod.assert_called_once()

    def test_backend_load_exception_records_backend_failure(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "boom-mod"
        backend_dir = mod_dir / "backend"
        backend_dir.mkdir(parents=True)
        # Module raises at import time -> backend stage failure, load_mod returns False.
        (backend_dir / "init.py").write_text("raise RuntimeError('import boom')\n")
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "boom-mod",
                    "name": "Boom",
                    "version": "1.0",
                    "backend": {"entry": "init", "init": "setup"},
                }
            )
        )
        mm = ModManager(mods_root=str(mods_dir))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        mock_registry.list_mod_ids.return_value = []
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
        ):
            result = mm.load_mod("boom-mod")
        assert result is False
        assert mm.get_recent_load_failures()[0]["stage"] == "backend"
        assert "boom-mod" not in mm._loaded_mods


# ========================= ModManager.unload_mod =========================


class TestUnloadMod:
    def test_basic_unload_removes_from_loaded_and_unregisters(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods.append("test-mod")
        mock_registry = Mock()
        mock_registry.get_mod_instance.return_value = None
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.comms.get_mod_comms", side_effect=ImportError),
        ):
            result = mm.unload_mod("test-mod")
        assert result is True
        assert "test-mod" not in mm._loaded_mods
        mock_registry.unregister_mod.assert_called_once_with("test-mod")

    def test_unload_invokes_instance_cleanup(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods.append("cleanup-mod")
        mock_instance = Mock()
        mock_registry = Mock()
        mock_registry.get_mod_instance.return_value = mock_instance
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.comms.get_mod_comms", side_effect=ImportError),
        ):
            result = mm.unload_mod("cleanup-mod")
        assert result is True
        mock_instance.cleanup.assert_called_once()
        mock_registry.unregister_mod.assert_called_once_with("cleanup-mod")

    def test_unload_swallows_cleanup_error_and_still_unregisters(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods.append("err-mod")
        mock_instance = Mock()
        mock_instance.cleanup.side_effect = OSError("cleanup boom")
        mock_registry = Mock()
        mock_registry.get_mod_instance.return_value = mock_instance
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.comms.get_mod_comms", side_effect=ImportError),
        ):
            result = mm.unload_mod("err-mod")
        # A failing cleanup is recoverable: unload still succeeds and unregisters.
        assert result is True
        assert "err-mod" not in mm._loaded_mods
        mock_registry.unregister_mod.assert_called_once_with("err-mod")


# ========================= ModManager.uninstall_mod ======================


class TestUninstallMod:
    def test_unknown_mod_returns_false_with_message(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.employee_registry.get_employee_registry") as mock_er,
        ):
            mock_er_instance = Mock()
            mock_er_instance._root.return_value = str(tmp_path)
            mock_er.return_value = mock_er_instance
            result, msg = mm.uninstall_mod("unknown-mod")
        assert result is False
        assert "unknown-mod" in msg

    def test_uninstall_removes_files_and_unloads(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "uninstall-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "uninstall-mod", "name": "Test", "version": "1.0"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        mm._loaded_mods.append("uninstall-mod")
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = Mock()
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "unload_mod", return_value=True) as unload,
        ):
            result, msg = mm.uninstall_mod("uninstall-mod", remove_files=True)
        assert result is True
        assert "卸载成功" in msg
        assert not mod_dir.exists()
        unload.assert_called_once_with("uninstall-mod")

    def test_uninstall_keeps_files_when_remove_files_false(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "keep-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "keep-mod", "name": "Test", "version": "1.0"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = Mock()
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result, _ = mm.uninstall_mod("keep-mod", remove_files=False)
        assert result is True
        # Files left intact when remove_files=False.
        assert mod_dir.exists()


# ========================= ModManager.validate_mod_package ================


class TestValidateModPackage:
    def _make_xcmod(self, tmp_path, name, manifest_data, extra_files=None):
        build = tmp_path / f"build_{name}"
        build.mkdir()
        (build / "manifest.json").write_text(json.dumps(manifest_data))
        for rel, content in (extra_files or {}).items():
            target = build / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        zip_path = tmp_path / f"{name}.xcmod"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            for f in build.rglob("*"):
                if f.is_file():
                    zf.write(str(f), str(f.relative_to(build)))
        return str(zip_path)

    def test_nonexistent_file_returns_false(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        ok, msg, info = mm.validate_mod_package(str(tmp_path / "missing.xcmod"))
        assert ok is False
        assert msg == "文件不存在"
        assert info == {}

    def test_not_a_zip_returns_false(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        plain = tmp_path / "plain.xcmod"
        plain.write_text("this is not a zip")
        ok, msg, info = mm.validate_mod_package(str(plain))
        assert ok is False
        assert "ZIP" in msg

    def test_valid_package_reports_metadata(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        zip_path = self._make_xcmod(
            tmp_path,
            "valid",
            {"id": "okmod", "name": "OK", "version": "2.0", "author": "alice"},
        )
        ok, msg, info = mm.validate_mod_package(zip_path)
        assert ok is True
        assert msg == "验证通过"
        assert info["id"] == "okmod"
        assert info["name"] == "OK"
        assert info["version"] == "2.0"
        assert info["author"] == "alice"
        assert info["errors"] == []

    def test_missing_required_fields_lists_them(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        zip_path = self._make_xcmod(tmp_path, "partial", {"id": "onlyid"})
        ok, msg, info = mm.validate_mod_package(zip_path)
        assert ok is False
        # Both name and version are required and missing.
        assert "name" in msg
        assert "version" in msg
        assert any("name" in e for e in info["errors"])
        assert any("version" in e for e in info["errors"])

    def test_missing_backend_entry_file_is_error(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        zip_path = self._make_xcmod(
            tmp_path,
            "noentry",
            {
                "id": "bm",
                "name": "BM",
                "version": "1.0",
                "backend": {"entry": "main"},
            },
            extra_files={"backend/placeholder.txt": "x"},
        )
        ok, msg, info = mm.validate_mod_package(zip_path)
        assert ok is False
        assert any("main.py" in e for e in info["errors"])


# ========================= ModManager._metadata_to_api_dict ==============


class TestMetadataToApiDict:
    def _meta(self, **over):
        from app.infrastructure.mods.manifest import ModMetadata

        base = {"id": "m", "name": "M", "version": "1.0", "mod_path": "/tmp/m"}
        base.update(over)
        return ModMetadata(**base)

    def test_plain_mod_has_no_type_key(self):
        result = ModManager._metadata_to_api_dict(self._meta())
        assert "type" not in result
        assert result["artifact"] == "mod"

    def test_bundle_marked_with_type(self):
        result = ModManager._metadata_to_api_dict(self._meta(artifact="bundle"))
        assert result["type"] == "bundle"
        assert result["artifact"] == "bundle"

    def test_core_fields_round_trip(self):
        result = ModManager._metadata_to_api_dict(
            self._meta(
                name="Cool Mod",
                version="3.4.5",
                author="bob",
                description="desc",
                primary=True,
            )
        )
        assert result["id"] == "m"
        assert result["name"] == "Cool Mod"
        assert result["version"] == "3.4.5"
        assert result["author"] == "bob"
        assert result["description"] == "desc"
        assert result["primary"] is True

    def test_valid_industry_dict_passed_through(self):
        result = ModManager._metadata_to_api_dict(
            self._meta(industry={"id": "retail", "name": "Retail"})
        )
        assert result["industry"] == {"id": "retail", "name": "Retail"}


# ========================= ModManager.list_all_mods ======================


class TestListAllMods:
    def test_disabled_returns_empty(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": "1"}):
            result = mm.list_all_mods()
        assert result == []

    def test_scanned_mod_rendered_as_api_row(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "list-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "list-mod", "name": "List Mod", "version": "1.5"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        with (
            patch(
                "app.infrastructure.mods.employee_registry.get_employee_registry",
                side_effect=ImportError,
            ),
            patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]),
        ):
            result = mm.list_all_mods()
        ids = [r["id"] for r in result]
        assert "list-mod" in ids
        row = next(r for r in result if r["id"] == "list-mod")
        assert row["name"] == "List Mod"
        assert row["version"] == "1.5"


# ========================= ModManager.get_routes =========================


class TestGetRoutes:
    def test_disabled_returns_empty(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict(os.environ, {"XCAGI_DISABLE_MODS": "1"}):
            result = mm.get_routes()
        assert result == []

    def test_mod_with_frontend_routes_included(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "route-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "route-mod",
                    "name": "Route Mod",
                    "version": "1.0",
                    "frontend": {"routes": "routes"},
                }
            )
        )
        mm = ModManager(mods_root=str(mods_dir))
        with (
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                side_effect=ImportError,
            ),
            patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]),
        ):
            result = mm.get_routes()
        assert result == [{"mod_id": "route-mod", "routes_path": "routes"}]

    def test_mod_without_frontend_routes_excluded(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "no-route-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "no-route-mod", "name": "No Route", "version": "1.0"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        with (
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                side_effect=ImportError,
            ),
            patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]),
        ):
            result = mm.get_routes()
        # No frontend.routes -> the mod contributes no route entry.
        assert result == []


# ========================= ModManager.load_all_mods ======================


class TestLoadAllMods:
    def test_empty_dir_loads_nothing(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        mm = ModManager(mods_root=str(mods_dir))
        with (
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                side_effect=ImportError,
            ),
            patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]),
        ):
            result = mm.load_all_mods()
        assert result == []

    def test_loads_discovered_mod(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "load-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "load-mod", "name": "Load Mod", "version": "1.0"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        with (
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                side_effect=ImportError,
            ),
            patch.object(mm, "load_mod", return_value=True) as load_mod,
            patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]),
        ):
            result = mm.load_all_mods()
        assert result == ["load-mod"]
        load_mod.assert_called_once_with("load-mod")

    def test_failed_mod_excluded_from_result(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "fail-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "fail-mod", "name": "Fail", "version": "1.0"})
        )
        mm = ModManager(mods_root=str(mods_dir))
        with (
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                side_effect=ImportError,
            ),
            patch.object(mm, "load_mod", return_value=False),
            patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]),
        ):
            result = mm.load_all_mods()
        # load_mod returned False -> id is not in the loaded list.
        assert result == []

    def test_primary_mod_loaded_before_secondary(self, tmp_path):
        mods_dir = tmp_path / "mods"
        for mid, primary in (("zsecondary", False), ("aprimary", True)):
            d = mods_dir / mid
            d.mkdir(parents=True)
            (d / "manifest.json").write_text(
                json.dumps({"id": mid, "name": mid, "version": "1.0", "primary": primary})
            )
        mm = ModManager(mods_root=str(mods_dir))
        order: list[str] = []
        with (
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                side_effect=ImportError,
            ),
            patch.object(mm, "load_mod", side_effect=lambda mid: order.append(mid) or True),
            patch.object(mm, "all_mods_roots", return_value=[str(mods_dir)]),
        ):
            result = mm.load_all_mods()
        # primary mod is loaded first despite alphabetic ordering.
        assert order[0] == "aprimary"
        assert set(result) == {"aprimary", "zsecondary"}


# ========================= ModManager._scan_mods_from_build_index ========


class TestScanModsFromBuildIndex:
    def test_no_index_file_returns_none(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm._scan_mods_from_build_index("fp1")
        assert result is None

    def test_fingerprint_mismatch_returns_none(self, tmp_path):
        (tmp_path / "mods-index.json").write_text(
            json.dumps({"fingerprint": "other_fp", "mods": []})
        )
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm._scan_mods_from_build_index("fp1")
        assert result is None

    def test_matching_index_returns_metadata(self, tmp_path):
        mods_dir = tmp_path / "mods"
        mod_dir = mods_dir / "idx-mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "idx-mod", "name": "Idx Mod", "version": "9.9"})
        )
        (tmp_path / "mods-index.json").write_text(
            json.dumps({"fingerprint": "fp1", "mods": [{"mod_path": str(mod_dir)}]})
        )
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm._scan_mods_from_build_index("fp1")
        assert result is not None
        assert [m.id for m in result] == ["idx-mod"]
        assert result[0].version == "9.9"

    def test_index_rows_with_missing_manifest_skipped(self, tmp_path):
        # Index references a path whose manifest no longer exists -> no mods -> None.
        (tmp_path / "mods-index.json").write_text(
            json.dumps(
                {
                    "fingerprint": "fp1",
                    "mods": [{"mod_path": str(tmp_path / "ghost")}],
                }
            )
        )
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            result = mm._scan_mods_from_build_index("fp1")
        assert result is None


# ========================= ModManager._load_mod_backend ==================


class TestLoadModBackend:
    def test_no_backend_dir_is_noop(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mod_dir = tmp_path / "no_backend_mod"
        mod_dir.mkdir()
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(id="nb", name="NB", version="1.0", mod_path=str(mod_dir))
        mm._load_mod_backend("nb", str(mod_dir), meta)
        # Nothing to import -> no backend module cached.
        assert "nb" not in mm._backend_entry_modules

    def test_real_backend_entry_caches_module_and_runs_init(self, tmp_path):
        mod_dir = tmp_path / "ok_mod"
        backend_dir = mod_dir / "backend"
        backend_dir.mkdir(parents=True)
        (backend_dir / "entry.py").write_text(
            "STATE = {'init': 0}\ndef setup():\n    STATE['init'] += 1\n"
        )
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="okb",
            name="OK",
            version="1.0",
            mod_path=str(mod_dir),
            backend_entry="entry",
            backend_init="setup",
        )
        mm = ModManager(mods_root=str(tmp_path))
        mm._load_mod_backend("okb", str(mod_dir), meta)
        module = mm._backend_entry_modules["okb"]
        assert module.STATE["init"] == 1

    def test_missing_backend_entry_file_raises_file_not_found(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mod_dir = tmp_path / "fail_mod"
        backend_dir = mod_dir / "backend"
        backend_dir.mkdir(parents=True)
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="fail",
            name="Fail",
            version="1.0",
            mod_path=str(mod_dir),
            backend_entry="missing",
            backend_init="setup",
        )
        with pytest.raises(FileNotFoundError, match="backend file missing"):
            mm._load_mod_backend("fail", str(mod_dir), meta)


# ========================= Module-level functions ========================


class TestGetModManager:
    def test_returns_singleton_instance(self):
        from app.infrastructure.mods.mod_manager import get_mod_manager

        with (
            patch("app.infrastructure.mods.mod_manager._mod_manager", None),
            patch(
                "app.infrastructure.mods.mod_manager._default_mods_root",
                return_value="/tmp/test_mods",
            ),
        ):
            mm1 = get_mod_manager()
            mm2 = get_mod_manager()
        assert mm1 is mm2
        assert isinstance(mm1, ModManager)
        assert mm1.mods_root == "/tmp/test_mods"


class TestLoadModBlueprintsNoop:
    def test_load_mod_blueprints_is_noop(self):
        """Documented as a no-op compatibility shim: must not touch the registry
        or attempt route registration. It should return None and call nothing."""
        from app.infrastructure.mods.mod_manager import load_mod_blueprints

        app = object()
        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as registry:
            result = load_mod_blueprints(app)
        assert result is None
        registry.assert_not_called()


class TestLoadModRoutes:
    def test_registers_routes_for_loaded_backend_mod(self, tmp_path):
        from app.infrastructure.mods.manifest import ModMetadata
        from app.infrastructure.mods.mod_manager import load_mod_routes

        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods.append("routed-mod")
        meta = ModMetadata(
            id="routed-mod",
            name="Routed",
            version="1.0",
            mod_path=str(tmp_path),
            backend_entry="entry",
        )
        mock_registry = Mock()
        mock_registry.list_mods.return_value = [meta]
        app = object()
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry",
                return_value=mock_registry,
            ),
            patch(
                "app.infrastructure.mods.mod_manager._register_single_mod_http_routes",
                return_value=True,
            ) as reg_one,
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last") as spa_last,
        ):
            load_mod_routes(app, mm)
        # The single mod with a backend_entry is routed exactly once...
        reg_one.assert_called_once_with(app, mm, "routed-mod")
        # ...and the SPA fallback is re-pinned to last.
        spa_last.assert_called_once_with(app)

    def test_skips_mods_without_backend_entry(self, tmp_path):
        from app.infrastructure.mods.manifest import ModMetadata
        from app.infrastructure.mods.mod_manager import load_mod_routes

        mm = ModManager(mods_root=str(tmp_path))
        # backend_entry empty -> not routable.
        meta = ModMetadata(id="ui-only", name="UI", version="1.0", mod_path=str(tmp_path))
        mock_registry = Mock()
        mock_registry.list_mods.return_value = [meta]
        app = object()
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry",
                return_value=mock_registry,
            ),
            patch(
                "app.infrastructure.mods.mod_manager._register_single_mod_http_routes",
                return_value=True,
            ) as reg_one,
            patch("app.infrastructure.mods.mod_manager.load_employee_pack_routes"),
            patch("app.fastapi_routes.spa_fallback.ensure_spa_fallback_last"),
        ):
            load_mod_routes(app, mm)
        reg_one.assert_not_called()
