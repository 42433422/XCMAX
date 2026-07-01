"""Tests for app.infrastructure.mods.mod_manager — deep coverage for remaining uncovered branches.

Focus: ModManager methods (install, uninstall, update, validate, scan, load, ensure),
module-level functions, and error paths not covered by existing tests.
"""

from __future__ import annotations

import json
import os
import sys
import zipfile
from unittest.mock import Mock, patch

import pytest

from app.infrastructure.mods.manifest import ModMetadata
from app.infrastructure.mods.mod_manager import (
    ModManager,
    _all_mods_roots,
    _backend_path_for_mod,
    _default_mods_root,
    _register_mod_hooks,
    _repo_layout_mods_candidates,
    _short_exc_message,
    import_mod_backend_py,
    is_mods_disabled,
)

# ========================= is_mods_disabled - extended ===================


class TestIsModsDisabledExtended:
    def test_env_1(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "1"}):
            assert is_mods_disabled() is True

    def test_env_true(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "true"}):
            assert is_mods_disabled() is True

    def test_env_yes(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "yes"}):
            assert is_mods_disabled() is True

    def test_env_on(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "on"}):
            assert is_mods_disabled() is True

    def test_env_false(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "0"}):
            assert is_mods_disabled() is False

    def test_env_empty(self):
        with patch.dict("os.environ", {"XCAGI_DISABLE_MODS": ""}):
            assert is_mods_disabled() is False

    def test_env_not_set(self):
        with patch.dict("os.environ", {}, clear=True):
            assert is_mods_disabled() is False


# ========================= _short_exc_message - extended ==================


class TestShortExcMessageExtended:
    def test_short_message(self):
        assert _short_exc_message(ValueError("short")) == "short"

    def test_long_message_truncated(self):
        long_msg = "A" * 600
        result = _short_exc_message(ValueError(long_msg))
        assert len(result) <= 480
        assert result.endswith("...")

    def test_empty_message_uses_type_name(self):
        result = _short_exc_message(ValueError(""))
        assert result == "ValueError"

    def test_exact_max_len(self):
        msg = "A" * 480
        result = _short_exc_message(ValueError(msg))
        assert result == msg


# ========================= _backend_path_for_mod =========================


class TestBackendPathForMod:
    def test_basic(self):
        assert _backend_path_for_mod("/mods/test_mod") == os.path.join("/mods/test_mod", "backend")

    def test_trailing_slash_preserved_join(self):
        # os.path.join collapses the redundant separator predictably.
        assert _backend_path_for_mod("/mods/m/") == os.path.join("/mods/m/", "backend")


# ========================= import_mod_backend_py =========================


class TestImportModBackendPy:
    def test_missing_file_raises_filenotfound(self, tmp_path):
        """A declared backend stem with no .py file raises FileNotFoundError naming the path."""
        mod_dir = tmp_path / "mod_a"
        (mod_dir / "backend").mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="backend file missing"):
            import_mod_backend_py(str(mod_dir), "mod_a", "ghost")

    def test_loads_module_and_executes_body(self, tmp_path):
        """A real backend .py is loaded by path and its top-level code is executed."""
        mod_dir = tmp_path / "mod_b"
        backend = mod_dir / "backend"
        backend.mkdir(parents=True)
        (backend / "svc.py").write_text("VALUE = 42\ndef greet():\n    return 'hi'\n")
        module = import_mod_backend_py(str(mod_dir), "mod_b", "svc")
        # Module-level assignment ran and the function is importable.
        assert module.VALUE == 42
        assert module.greet() == "hi"

    def test_same_mod_id_different_paths_are_distinct_modules(self, tmp_path):
        """Identical mod_id at different physical paths must not collide in sys.modules."""
        m1 = tmp_path / "loc1" / "shared"
        m2 = tmp_path / "loc2" / "shared"
        (m1 / "backend").mkdir(parents=True)
        (m2 / "backend").mkdir(parents=True)
        (m1 / "backend" / "blueprints.py").write_text("ORIGIN = 'one'\n")
        (m2 / "backend" / "blueprints.py").write_text("ORIGIN = 'two'\n")
        mod_one = import_mod_backend_py(str(m1), "shared", "blueprints")
        mod_two = import_mod_backend_py(str(m2), "shared", "blueprints")
        # The path digest in the cache key keeps the two copies separate.
        assert mod_one is not mod_two
        assert mod_one.ORIGIN == "one"
        assert mod_two.ORIGIN == "two"

    def test_second_call_returns_cached_module(self, tmp_path):
        """Re-importing the same (path, stem) returns the cached module instance."""
        mod_dir = tmp_path / "mod_c"
        backend = mod_dir / "backend"
        backend.mkdir(parents=True)
        (backend / "blueprints.py").write_text("N = 1\n")
        first = import_mod_backend_py(str(mod_dir), "mod_c", "blueprints")
        second = import_mod_backend_py(str(mod_dir), "mod_c", "blueprints")
        assert first is second


# ========================= module-level mods-root resolvers ===============


class TestModsRootResolvers:
    def test_default_mods_root_prefers_valid_env(self, tmp_path):
        valid = tmp_path / "envmods"
        valid.mkdir()
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": str(valid)}, clear=True):
            assert _default_mods_root() == os.path.abspath(str(valid))

    def test_default_mods_root_ignores_invalid_env(self, tmp_path):
        """A non-directory env value is ignored; resolution falls through to other strategies."""
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": str(tmp_path / "nope")}, clear=True):
            result = _default_mods_root()
        # Whatever the fallback resolves to, it must not be the bogus env path.
        assert result != os.path.abspath(str(tmp_path / "nope"))

    def test_all_mods_roots_dedupes_env_equal_to_primary(self, tmp_path):
        root = tmp_path / "m"
        root.mkdir()
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": str(root)}, clear=True):
            with patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=[],
            ):
                roots = _all_mods_roots(str(root))
        # Primary and env point at the same dir -> a single deduped entry.
        assert roots == [os.path.abspath(str(root))]

    def test_all_mods_roots_blank_primary_resolves_to_cwd(self, tmp_path, monkeypatch):
        """A blank primary becomes os.path.abspath('') == cwd, which is included if it exists."""
        # Run from an isolated cwd so the result is deterministic.
        work = tmp_path / "work"
        work.mkdir()
        monkeypatch.chdir(work)
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=[],
            ):
                roots = _all_mods_roots("")
        # os.path.abspath("") is the cwd; since it is a real dir it is the sole entry.
        assert roots == [os.path.abspath(str(work))]

    def test_repo_layout_candidates_returns_existing_dirs(self):
        """All returned candidates are existing absolute directories with no duplicates."""
        candidates = _repo_layout_mods_candidates()
        assert all(os.path.isabs(p) and os.path.isdir(p) for p in candidates)
        assert len(candidates) == len(set(candidates))


# ========================= _register_mod_hooks - extended =================


class TestRegisterModHooksExtended:
    def test_hooks_with_invalid_spec(self):
        """A handler spec without a `module.attr` dot is rejected; import is never attempted."""
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            hooks={"on_chat": "invalid_no_dot"},
        )
        with (
            patch("app.infrastructure.mods.mod_manager.import_mod_backend_py") as mock_import,
            patch("app.infrastructure.mods.hooks.subscribe") as mock_sub,
        ):
            _register_mod_hooks("test", meta)
        # rpartition(".") on "invalid_no_dot" -> module_name == "" -> bail before importing.
        mock_import.assert_not_called()
        mock_sub.assert_not_called()

    def test_hooks_empty_dict_is_noop(self):
        """No hooks at all -> early return without touching the hook module."""
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(id="test", name="Test", version="1.0", mod_path="/tmp/test", hooks={})
        with patch("app.infrastructure.mods.hooks.subscribe") as mock_sub:
            _register_mod_hooks("test", meta)
        mock_sub.assert_not_called()

    def test_hooks_with_backend_prefix(self):
        """`backend.` prefix is stripped, then module.attr is resolved and subscribed."""
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            hooks={"on_chat": "backend.services.handler"},
        )
        handler_fn = Mock(name="handler")
        mock_module = Mock()
        mock_module.handler = handler_fn
        with patch(
            "app.infrastructure.mods.mod_manager.import_mod_backend_py", return_value=mock_module
        ) as mock_import:
            with patch("app.infrastructure.mods.hooks.subscribe") as mock_sub:
                _register_mod_hooks("test", meta)
        # The "backend." prefix is dropped before rpartition -> module "services", attr "handler".
        mock_import.assert_called_once_with("/tmp/test", "test", "services")
        # The resolved callable is subscribed to the manifest's event key, not a mock proxy.
        mock_sub.assert_called_once_with("on_chat", handler_fn)

    def test_hooks_real_subscribe_registers_callable(self):
        """End-to-end: a real callable from backend module lands in the live HookManager."""
        from app.infrastructure.mods.hooks import HookManager
        from app.infrastructure.mods.manifest import ModMetadata

        def my_handler(*args, **kwargs):
            return "handled"

        meta = ModMetadata(
            id="real_hook_mod",
            name="Real",
            version="1.0",
            mod_path="/tmp/real",
            hooks={"on_real_event_xyz": "services.my_handler"},
        )
        mock_module = Mock()
        mock_module.my_handler = my_handler
        hm = HookManager.get_instance()
        before = list(hm.list_subscribers("on_real_event_xyz"))
        try:
            with patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                return_value=mock_module,
            ):
                _register_mod_hooks("real_hook_mod", meta)
            # The real handler is now discoverable by name in the global hook registry.
            assert "my_handler" in hm.list_subscribers("on_real_event_xyz")
            assert len(hm.list_subscribers("on_real_event_xyz")) == len(before) + 1
        finally:
            hm.unsubscribe("on_real_event_xyz", my_handler)

    def test_hooks_no_mod_path(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="",
            hooks={"on_chat": "services.handler"},
        )
        with patch("app.infrastructure.mods.hooks.subscribe") as mock_sub:
            _register_mod_hooks("test", meta)
        # Empty mod_path -> cannot resolve handlers, nothing subscribed.
        mock_sub.assert_not_called()

    def test_hooks_handler_not_callable(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            hooks={"on_chat": "services.not_callable"},
        )
        mock_module = Mock()
        mock_module.not_callable = "not a function"
        with (
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                return_value=mock_module,
            ),
            patch("app.infrastructure.mods.hooks.subscribe") as mock_sub,
        ):
            _register_mod_hooks("test", meta)
        # Resolved attribute is not callable -> skipped, nothing subscribed.
        mock_sub.assert_not_called()

    def test_hooks_import_error(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            hooks={"on_chat": "services.handler"},
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                side_effect=ImportError("no module"),
            ) as mock_import,
            patch("app.infrastructure.mods.hooks.subscribe") as mock_sub,
        ):
            # Import failure is recoverable -> swallowed (no exception propagates).
            _register_mod_hooks("test", meta)
        # Import was attempted for the resolved module name, but the failure is contained.
        mock_import.assert_called_once_with("/tmp/test", "test", "services")
        mock_sub.assert_not_called()


# ========================= ModManager - invalidate_scan_cache ============


class TestModManagerInvalidateScanCache:
    def test_invalidate(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._scan_cache_fp = "old_fp"
        mm._scan_cache_mods = [Mock()]
        mm.invalidate_scan_cache()
        assert mm._scan_cache_fp == ""
        assert mm._scan_cache_mods == []


# ========================= ModManager - _mods_scan_fingerprint ============


class TestModManagerScanFingerprint:
    def test_empty_root_lists_only_root_path(self, tmp_path):
        """A nonexistent root contributes its abspath but no per-entry mtime segments."""
        missing = tmp_path / "nonexistent"
        mm = ModManager(mods_root=str(missing))
        with patch.object(mm, "all_mods_roots", return_value=[str(missing)]):
            fp = mm._mods_scan_fingerprint()
        # The fingerprint is the abspath of the (missing) root and nothing else.
        assert fp == os.path.abspath(str(missing))
        assert ":" not in fp  # no "entry:mtime" segments for a missing directory

    def test_with_manifest_encodes_entry_and_mtime(self, tmp_path):
        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        manifest = mod_dir / "manifest.json"
        manifest.write_text('{"id": "test", "name": "Test", "version": "1.0"}')
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            fp = mm._mods_scan_fingerprint()
        # Entry name and the manifest mtime are both encoded as "entry:mtime".
        expected_seg = f"test_mod:{os.path.getmtime(manifest):.6f}"
        assert expected_seg in fp.split("|")
        # The root abspath leads the fingerprint.
        assert fp.split("|")[0] == os.path.abspath(str(tmp_path))

    def test_fingerprint_changes_when_manifest_touched(self, tmp_path):
        """Touching a manifest changes the fingerprint so the scan cache invalidates."""
        mod_dir = tmp_path / "m1"
        mod_dir.mkdir()
        manifest = mod_dir / "manifest.json"
        manifest.write_text('{"id": "m1", "name": "M1", "version": "1.0"}')
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            fp1 = mm._mods_scan_fingerprint()
            # Advance mtime deterministically (no sleep): set it 100s into the future.
            future = os.path.getmtime(manifest) + 100
            os.utime(manifest, (future, future))
            fp2 = mm._mods_scan_fingerprint()
        assert fp1 != fp2

    def test_fingerprint_skips_underscore_entries(self, tmp_path):
        """Entries starting with `_` (e.g. _employees) are excluded from the fingerprint."""
        priv = tmp_path / "_employees"
        priv.mkdir()
        (priv / "manifest.json").write_text('{"id": "x", "name": "X", "version": "1.0"}')
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]):
            fp = mm._mods_scan_fingerprint()
        assert "_employees" not in fp


# ========================= ModManager - _refresh_mods_root_if_needed ======


class TestModManagerRefreshModsRoot:
    def test_env_updates_root(self, tmp_path):
        new_root = str(tmp_path / "new_mods")
        os.makedirs(new_root)
        mm = ModManager(mods_root=str(tmp_path / "old_mods"))
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": new_root}):
            mm._refresh_mods_root_if_needed()
        assert mm.mods_root == new_root

    def test_env_not_dir_keeps_current(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": "/nonexistent/path"}):
            mm._refresh_mods_root_if_needed()
        assert mm.mods_root == str(tmp_path)

    def test_current_missing_re_resolves(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path / "missing_dir"))
        with patch(
            "app.infrastructure.mods.mod_manager._default_mods_root", return_value=str(tmp_path)
        ):
            mm._refresh_mods_root_if_needed()
        assert mm.mods_root == str(tmp_path)


# ========================= ModManager - record methods ====================


class TestModManagerRecordMethods:
    def test_record_load_failure(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._record_load_failure("mod1", "backend", "load error")
        failures = mm.get_recent_load_failures()
        # The full record is stored with all three fields intact.
        assert failures == [{"mod_id": "mod1", "stage": "backend", "message": "load error"}]

    def test_record_load_failure_truncates_message(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._record_load_failure("mod1", "backend", "X" * 999)
        failures = mm.get_recent_load_failures()
        # Messages are capped at 500 chars to bound the loading-status payload.
        assert len(failures[0]["message"]) == 500

    def test_get_recent_load_failures_returns_copy(self, tmp_path):
        """The getter returns a copy so callers cannot mutate the manager's internal list."""
        mm = ModManager(mods_root=str(tmp_path))
        mm._record_load_failure("mod1", "backend", "err")
        snapshot = mm.get_recent_load_failures()
        snapshot.append({"mod_id": "injected", "stage": "x", "message": "y"})
        assert len(mm.get_recent_load_failures()) == 1

    def test_record_blueprint_failure(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm.record_blueprint_failure("mod1", "blueprint error")
        failures = mm.get_blueprint_failures()
        assert failures == [{"mod_id": "mod1", "message": "blueprint error"}]

    def test_get_scan_manifest_errors(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._scan_manifest_errors = [{"entry": "bad_mod", "message": "invalid"}]
        errors = mm.get_scan_manifest_errors()
        assert errors == [{"entry": "bad_mod", "message": "invalid"}]
        # Returned list is a copy; mutating it leaves the source intact.
        errors.clear()
        assert len(mm.get_scan_manifest_errors()) == 1


# ========================= ModManager - ensure_mods_loaded ================


class TestModManagerEnsureModsLoaded:
    def test_mods_disabled_short_circuits_before_scan(self, tmp_path):
        """With mods disabled, ensure returns before scanning or counting attempts."""
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.dict("os.environ", {"XCAGI_DISABLE_MODS": "1"}),
            patch.object(mm, "scan_mods") as mock_scan,
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(Mock())
        mock_load.assert_not_called()
        mock_scan.assert_not_called()
        # No attempt was consumed, so a later (enabled) call can still try.
        assert mm._ensure_attempts == 0

    def test_already_loaded(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        # ensure_mods_loaded consults list_loaded_mods() (the registry view),
        # not the _loaded_mods attribute directly.
        with (
            patch.object(mm, "list_loaded_mods", return_value=[Mock()]),
            patch.object(mm, "scan_mods") as mock_scan,
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(Mock())
        # Registry already has a mod -> no reload and no disk scan.
        mock_load.assert_not_called()
        mock_scan.assert_not_called()
        assert mm._ensure_attempts == 0

    def test_no_discovered_mods(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[]),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(Mock())
        # Nothing discovered on disk -> nothing to load, no attempt consumed.
        mock_load.assert_not_called()
        assert mm._ensure_attempts == 0

    def test_throttle_rate(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        # time.monotonic() in ensure compares against _last_ensure_at; set it to the
        # current monotonic clock so (now - last) < 1.5s and the throttle trips.
        import time as _time

        mm._last_ensure_at = _time.monotonic()
        mm._ensure_attempts = 0
        with (
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[Mock()]),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(Mock())
        # Within the throttle window -> load is skipped and attempt counter untouched.
        mock_load.assert_not_called()
        assert mm._ensure_attempts == 0

    def test_max_attempts_reached(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mm._ensure_attempts = 20
        with (
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[Mock()]),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(Mock())
        # Attempt budget exhausted -> load is skipped and the counter does not grow further.
        mock_load.assert_not_called()
        assert mm._ensure_attempts == 20

    def test_happy_path_loads_and_records_attempt(self, tmp_path):
        """Empty registry + on-disk manifest within budget -> load_all_mods + load_mod_routes run."""
        mm = ModManager(mods_root=str(tmp_path))
        mm._ensure_attempts = 0
        mm._last_ensure_at = 0.0
        app = Mock()
        with (
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", return_value=[Mock()]),
            patch.object(mm, "load_all_mods") as mock_load,
            patch("app.infrastructure.mods.mod_manager.load_mod_routes") as mock_routes,
        ):
            mm.ensure_mods_loaded(app)
        mock_load.assert_called_once_with()
        mock_routes.assert_called_once_with(app, mm)
        # One attempt consumed and the throttle timestamp advanced off its initial 0.0.
        assert mm._ensure_attempts == 1
        assert mm._last_ensure_at > 0.0

    def test_recoverable_error_swallowed(self, tmp_path):
        """A scan failure is contained so /api/mods does not 500; no exception escapes."""
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "list_loaded_mods", return_value=[]),
            patch.object(mm, "scan_mods", side_effect=OSError("disk gone")),
            patch.object(mm, "load_all_mods") as mock_load,
        ):
            mm.ensure_mods_loaded(Mock())  # must not raise
        mock_load.assert_not_called()


# ========================= ModManager - resolve_mod_directory =============


class TestModManagerResolveModDirectory:
    def test_empty_mod_id(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        result = mm.resolve_mod_directory("")
        assert result is None

    def test_none_mod_id(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        result = mm.resolve_mod_directory(None)
        assert result is None

    def test_found_in_root_returns_exact_dir(self, tmp_path):
        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            '{"id": "test_mod", "name": "Test", "version": "1.0"}'
        )
        mm = ModManager(mods_root=str(tmp_path))
        result = mm.resolve_mod_directory("test_mod")
        # Resolves to the exact mod directory that holds the manifest.
        assert result == str(mod_dir)
        assert os.path.isfile(os.path.join(result, "manifest.json"))

    def test_dir_without_manifest_not_resolved(self, tmp_path):
        """A directory matching the id but lacking manifest.json is not a valid mod dir."""
        (tmp_path / "ghost_mod").mkdir()  # no manifest.json inside
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch("app.mod_sdk.industry_mod_aliases.canonical_mod_id", return_value="ghost_mod"),
            patch("app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for", return_value=[]),
        ):
            result = mm.resolve_mod_directory("ghost_mod")
        assert result is None

    def test_resolved_via_legacy_alias(self, tmp_path):
        """When the requested id misses but a legacy alias dir exists, it resolves to that dir."""
        legacy_dir = tmp_path / "old_name"
        legacy_dir.mkdir()
        (legacy_dir / "manifest.json").write_text(
            '{"id": "old_name", "name": "Legacy", "version": "1.0"}'
        )
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch("app.mod_sdk.industry_mod_aliases.canonical_mod_id", return_value="new_name"),
            patch(
                "app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for",
                return_value=["old_name"],
            ),
        ):
            result = mm.resolve_mod_directory("new_name")
        assert result == str(legacy_dir)

    def test_not_found(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch("app.mod_sdk.industry_mod_aliases.canonical_mod_id", return_value="unknown"):
            with patch("app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for", return_value=[]):
                result = mm.resolve_mod_directory("nonexistent_mod")
        assert result is None


# ========================= ModManager - scan_mods ========================


class TestModManagerScanMods:
    def test_scan_empty_root_returns_empty(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_scan_mods_from_build_index", return_value=None),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
        ):
            mods = mm.scan_mods(use_cache=False)
        assert mods == []

    def test_scan_parses_real_manifest(self, tmp_path):
        """A real manifest on disk is parsed into ModMetadata with its declared fields."""
        mod_dir = tmp_path / "alpha_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            '{"id": "alpha_mod", "name": "Alpha", "version": "2.3.1", "author": "acme"}'
        )
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_scan_mods_from_build_index", return_value=None),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
        ):
            mods = mm.scan_mods(use_cache=False)
        assert len(mods) == 1
        only = mods[0]
        assert only.id == "alpha_mod"
        assert only.name == "Alpha"
        assert only.version == "2.3.1"
        assert only.author == "acme"
        assert only.mod_path == str(mod_dir)

    def test_scan_dedupes_same_id_across_roots(self, tmp_path):
        """Two roots declaring the same mod id yield a single entry (first root wins)."""
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        for root, ver in ((root_a, "1.0"), (root_b, "9.9")):
            d = root / "dup_mod"
            d.mkdir(parents=True)
            (d / "manifest.json").write_text(
                f'{{"id": "dup_mod", "name": "Dup", "version": "{ver}"}}'
            )
        mm = ModManager(mods_root=str(root_a))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_scan_mods_from_build_index", return_value=None),
            patch.object(mm, "all_mods_roots", return_value=[str(root_a), str(root_b)]),
        ):
            mods = mm.scan_mods(use_cache=False)
        assert [m.id for m in mods] == ["dup_mod"]
        # First root wins -> version 1.0, not the shadowed 9.9 from root_b.
        assert mods[0].version == "1.0"

    def test_scan_with_cache_returns_cached_copy(self, tmp_path):
        """A fingerprint hit returns the cached mods without rescanning the disk."""
        cached = ModMetadata(id="cached_mod", name="Cached", version="1.0", mod_path="/x")
        mm = ModManager(mods_root=str(tmp_path))
        mm._scan_cache_fp = "test_fp"
        mm._scan_cache_mods = [cached]
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "_mods_scan_fingerprint", return_value="test_fp"),
            patch.object(mm, "all_mods_roots") as mock_roots,
        ):
            mods = mm.scan_mods(use_cache=True)
        assert [m.id for m in mods] == ["cached_mod"]
        # Cache hit -> the disk listing path (all_mods_roots in the scan loop) is not walked.
        mock_roots.assert_not_called()
        # The returned list is a copy: mutating it must not corrupt the cache.
        mods.append(ModMetadata(id="x", name="x", version="1"))
        assert len(mm._scan_cache_mods) == 1

    def test_scan_skips_underscore_keeps_real(self, tmp_path):
        """`_`-prefixed dirs are skipped while a sibling real mod is still discovered."""
        underscore_dir = tmp_path / "_private"
        underscore_dir.mkdir()
        (underscore_dir / "manifest.json").write_text(
            '{"id": "_private", "name": "Private", "version": "1.0"}'
        )
        real_dir = tmp_path / "real_mod"
        real_dir.mkdir()
        (real_dir / "manifest.json").write_text(
            '{"id": "real_mod", "name": "Real", "version": "1.0"}'
        )
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
        ):
            mods = mm.scan_mods(use_cache=False)
        # Only the non-underscore mod survives.
        assert [m.id for m in mods] == ["real_mod"]

    def test_scan_skip_non_dirs(self, tmp_path):
        """Loose files in the root are ignored; only directories with manifests count."""
        (tmp_path / "readme.txt").write_text("not a mod")
        (tmp_path / "manifest.json").write_text('{"id": "stray", "version": "1.0"}')
        good = tmp_path / "good_mod"
        good.mkdir()
        (good / "manifest.json").write_text('{"id": "good_mod", "name": "Good", "version": "1.0"}')
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
        ):
            mods = mm.scan_mods(use_cache=False)
        assert [m.id for m in mods] == ["good_mod"]

    def test_scan_invalid_manifest_records_error(self, tmp_path):
        mod_dir = tmp_path / "bad_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("invalid json")
        mm = ModManager(mods_root=str(tmp_path))
        with (
            patch.object(mm, "_refresh_mods_root_if_needed"),
            patch.object(mm, "all_mods_roots", return_value=[str(tmp_path)]),
        ):
            mods = mm.scan_mods(use_cache=False)
        assert mods == []
        errors = mm.get_scan_manifest_errors()
        assert len(errors) == 1
        # The error carries the offending entry name and its root for operator diagnostics.
        assert errors[0]["entry"] == "bad_mod"
        assert errors[0]["mods_root"] == str(tmp_path)
        assert "manifest" in errors[0]["message"]


# ========================= ModManager - load_mod =========================


class TestModManagerLoadModExtended:
    def test_sku_blocked(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.mod_sdk.product_skus.assert_mod_allowed_for_sku",
            side_effect=PermissionError("blocked by sku policy"),
        ):
            result = mm.load_mod("blocked_mod")
        assert result is False
        # The mod is never marked loaded, and a precise sku_policy failure is recorded.
        assert "blocked_mod" not in mm._loaded_mods
        failures = mm.get_recent_load_failures()
        assert len(failures) == 1
        assert failures[0]["mod_id"] == "blocked_mod"
        assert failures[0]["stage"] == "sku_policy"
        assert "blocked by sku policy" in failures[0]["message"]

    def test_already_loaded(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = ModMetadata(
            id="existing_mod", name="Existing", version="1.0", mod_path="/x"
        )
        # Pre-seed _loaded_mods so the "already loaded + in list" branch is taken.
        mm._loaded_mods = ["existing_mod"]
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.load_mod("existing_mod")
        assert result is True
        # Early-return path: resolve_mod_directory is never consulted (registry hit short-circuits).
        # _loaded_mods stays a single entry (no duplicate append).
        assert mm._loaded_mods == ["existing_mod"]

    def test_already_loaded_but_missing_from_list(self, tmp_path):
        """Registry has metadata but _loaded_mods lost it -> list is self-healed, no reload."""
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = ModMetadata(
            id="missing_from_list", name="M", version="1.0", mod_path="/x"
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory") as mock_resolve,
        ):
            result = mm.load_mod("missing_from_list")
        assert result is True
        assert mm._loaded_mods == ["missing_from_list"]
        # Already-registered short-circuit: never re-resolves the directory or re-registers.
        mock_resolve.assert_not_called()
        mock_registry.register_mod.assert_not_called()

    def test_mod_directory_not_found(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.mod_sdk.industry_mod_aliases.canonical_mod_id", return_value="unknown"),
            patch("app.mod_sdk.industry_mod_aliases.legacy_mod_ids_for", return_value=[]),
        ):
            result = mm.load_mod("nonexistent")
        assert result is False
        assert "nonexistent" not in mm._loaded_mods
        failures = mm.get_recent_load_failures()
        assert [f["stage"] for f in failures] == ["fs"]
        assert failures[0]["mod_id"] == "nonexistent"

    def test_invalid_manifest(self, tmp_path):
        mod_dir = tmp_path / "bad_manifest"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("invalid")
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=None),
        ):
            result = mm.load_mod("bad_manifest")
        assert result is False
        # The directory was found but parsing failed -> "manifest" stage failure, not "fs".
        failures = mm.get_recent_load_failures()
        assert [f["stage"] for f in failures] == ["manifest"]
        mock_registry.register_mod.assert_not_called()

    def test_bundle_artifact_registers_metadata_only(self, tmp_path):
        """A bundle artifact registers metadata, marks loaded, and never loads a backend."""
        mod_dir = tmp_path / "bundle_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            '{"id": "bundle_mod", "name": "Bundle", "version": "1.0", "artifact": "bundle"}'
        )
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        mock_registry.register_mod.return_value = True
        meta = ModMetadata(
            id="bundle_mod", name="Bundle", version="1.0", mod_path=str(mod_dir), artifact="bundle"
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="bundle"),
            patch.object(mm, "_load_mod_backend") as mock_backend,
        ):
            result = mm.load_mod("bundle_mod")
        assert result is True
        # The exact ModMetadata is registered, the mod is recorded loaded, and no backend runs.
        mock_registry.register_mod.assert_called_once_with(meta)
        assert "bundle_mod" in mm._loaded_mods
        mock_backend.assert_not_called()

    def test_dependency_not_satisfied(self, tmp_path):
        mod_dir = tmp_path / "dep_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            '{"id": "dep_mod", "name": "Dep", "version": "1.0", "dependencies": {"missing_dep": "*"}}'
        )
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        mock_registry.list_mod_ids.return_value = []
        meta = ModMetadata(
            id="dep_mod",
            name="Dep",
            version="1.0",
            mod_path=str(mod_dir),
            dependencies={"missing_dep": "*"},
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="mod"),
            patch("app.infrastructure.mods.mod_manager.validate_dependencies", return_value=False),
        ):
            result = mm.load_mod("dep_mod")
        assert result is False
        # Failure is attributed to the dependency stage; the mod is not registered or loaded.
        failures = mm.get_recent_load_failures()
        assert [f["stage"] for f in failures] == ["dependencies"]
        assert "dep_mod" not in mm._loaded_mods
        mock_registry.register_mod.assert_not_called()

    def test_load_mod_success_full_path(self, tmp_path):
        """Happy path: backend loaded, metadata registered, mod recorded under effective id."""
        mod_dir = tmp_path / "ok_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text('{"id": "ok_mod", "name": "OK", "version": "1.0"}')
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        mock_registry.list_mod_ids.return_value = []
        meta = ModMetadata(id="ok_mod", name="OK", version="1.0", mod_path=str(mod_dir))
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="mod"),
            patch("app.infrastructure.mods.mod_manager.validate_dependencies", return_value=True),
            patch.object(mm, "_load_mod_backend") as mock_backend,
        ):
            result = mm.load_mod("ok_mod")
        assert result is True
        mock_backend.assert_called_once_with("ok_mod", str(mod_dir), meta)
        mock_registry.register_mod.assert_called_once_with(meta)
        assert mm._loaded_mods == ["ok_mod"]
        # No failures recorded on the success path.
        assert mm.get_recent_load_failures() == []

    def test_load_mod_backend_raises_records_failure(self, tmp_path):
        """A recoverable backend error is caught, recorded as a 'backend' failure, returns False."""
        mod_dir = tmp_path / "boom_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            '{"id": "boom_mod", "name": "Boom", "version": "1.0"}'
        )
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        mock_registry.list_mod_ids.return_value = []
        meta = ModMetadata(id="boom_mod", name="Boom", version="1.0", mod_path=str(mod_dir))
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch.object(mm, "resolve_mod_directory", return_value=str(mod_dir)),
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=meta),
            patch("app.infrastructure.mods.mod_manager.normalize_artifact", return_value="mod"),
            patch("app.infrastructure.mods.mod_manager.validate_dependencies", return_value=True),
            patch.object(mm, "_load_mod_backend", side_effect=ImportError("backend kaboom")),
        ):
            result = mm.load_mod("boom_mod")
        assert result is False
        failures = mm.get_recent_load_failures()
        assert [f["stage"] for f in failures] == ["backend"]
        assert "backend kaboom" in failures[0]["message"]
        assert "boom_mod" not in mm._loaded_mods
        # register_mod is reached only after a successful backend load.
        mock_registry.register_mod.assert_not_called()


# ========================= ModManager - _load_mod_backend ================


class TestModManagerLoadModBackend:
    def test_no_backend_dir(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mod_dir = tmp_path / "no_backend"
        mod_dir.mkdir()  # no backend/ subdir
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(id="no_backend", name="No Backend", version="1.0", mod_path=str(mod_dir))
        result = mm._load_mod_backend("no_backend", str(mod_dir), meta)
        # No backend directory -> early return, no backend module registered.
        assert result is None
        assert "no_backend" not in mm._backend_entry_modules

    def test_backend_entry_with_init(self, tmp_path):
        """Backend entry is imported, cached, its init() invoked, and hooks registered."""
        mm = ModManager(mods_root=str(tmp_path))
        mod_dir = tmp_path / "entry_mod"
        backend_dir = mod_dir / "backend"
        backend_dir.mkdir(parents=True)
        (backend_dir / "main.py").write_text("INIT_CALLED = True\ndef init(): pass\n")

        meta = ModMetadata(
            id="entry_mod",
            name="Entry",
            version="1.0",
            mod_path=str(mod_dir),
            backend_entry="main",
            backend_init="init",
        )
        mock_module = Mock()
        mock_module.init = Mock()
        with (
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                return_value=mock_module,
            ) as mock_import,
            patch("app.infrastructure.mods.mod_manager._register_mod_hooks") as mock_hooks,
        ):
            mm._load_mod_backend("entry_mod", str(mod_dir), meta)
        # The declared entry module is imported and its init hook invoked exactly once.
        mock_import.assert_called_once_with(str(mod_dir), "entry_mod", "main")
        mock_module.init.assert_called_once()
        # The imported module is cached under the mod id for later route registration.
        assert mm._backend_entry_modules["entry_mod"] is mock_module
        # Manifest hooks are wired after the entry loads.
        mock_hooks.assert_called_once_with("entry_mod", meta)
        # The backend dir is placed on sys.path so intra-mod imports resolve.
        assert str(backend_dir) in sys.path

    def test_backend_entry_no_init_attr_skips_invoke(self, tmp_path):
        """If the module lacks the named init attr, no init runs but caching/hooks still happen."""
        mm = ModManager(mods_root=str(tmp_path))
        mod_dir = tmp_path / "noinit_mod"
        backend_dir = mod_dir / "backend"
        backend_dir.mkdir(parents=True)
        (backend_dir / "main.py").write_text("x = 1\n")

        meta = ModMetadata(
            id="noinit_mod",
            name="NoInit",
            version="1.0",
            mod_path=str(mod_dir),
            backend_entry="main",
            backend_init="setup",  # attribute that the module does not define
        )

        class _Bare:
            pass

        bare = _Bare()  # has no `setup` attribute
        with (
            patch("app.infrastructure.mods.mod_manager.import_mod_backend_py", return_value=bare),
            patch("app.infrastructure.mods.mod_manager._invoke_mod_init_hook") as mock_invoke,
            patch("app.infrastructure.mods.mod_manager._register_mod_hooks"),
        ):
            mm._load_mod_backend("noinit_mod", str(mod_dir), meta)
        # hasattr(module, "setup") is False -> the init invocation path is skipped.
        mock_invoke.assert_not_called()
        assert mm._backend_entry_modules["noinit_mod"] is bare

    def test_backend_no_entry_only_hooks(self, tmp_path):
        """With no backend_entry declared, no import happens but hooks are still registered."""
        mm = ModManager(mods_root=str(tmp_path))
        mod_dir = tmp_path / "hooks_only"
        (mod_dir / "backend").mkdir(parents=True)
        meta = ModMetadata(
            id="hooks_only", name="Hooks", version="1.0", mod_path=str(mod_dir), backend_entry=""
        )
        with (
            patch("app.infrastructure.mods.mod_manager.import_mod_backend_py") as mock_import,
            patch("app.infrastructure.mods.mod_manager._register_mod_hooks") as mock_hooks,
        ):
            mm._load_mod_backend("hooks_only", str(mod_dir), meta)
        mock_import.assert_not_called()
        assert "hooks_only" not in mm._backend_entry_modules
        mock_hooks.assert_called_once_with("hooks_only", meta)

    def test_backend_entry_import_error(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mod_dir = tmp_path / "fail_mod"
        backend_dir = mod_dir / "backend"
        backend_dir.mkdir(parents=True)
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="fail_mod",
            name="Fail",
            version="1.0",
            mod_path=str(mod_dir),
            backend_entry="missing",
            backend_init="init",
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.import_mod_backend_py",
                side_effect=ImportError("no module"),
            ),
            pytest.raises(ImportError),
        ):
            mm._load_mod_backend("fail_mod", str(mod_dir), meta)


# ========================= ModManager - unload_mod ========================


class TestModManagerUnloadMod:
    def test_unload_with_cleanup(self, tmp_path):
        """Full unload: instance.cleanup, registry.unregister_mod, comms cleanup, list pruned."""
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["test_mod", "other_mod"]
        mock_registry = Mock()
        mock_instance = Mock()
        mock_instance.cleanup = Mock()
        mock_registry.get_mod_instance.return_value = mock_instance
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.comms.get_mod_comms") as mock_comms,
        ):
            comms_obj = Mock()
            mock_comms.return_value = comms_obj
            result = mm.unload_mod("test_mod")
        assert result is True
        mock_instance.cleanup.assert_called_once()
        mock_registry.unregister_mod.assert_called_once_with("test_mod")
        comms_obj.unregister_all.assert_called_once_with("test_mod")
        # Only the targeted mod is removed; siblings remain.
        assert mm._loaded_mods == ["other_mod"]

    def test_unload_instance_without_cleanup_attr(self, tmp_path):
        """An instance lacking a cleanup() method is skipped without error; unload still succeeds."""
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["plain_mod"]
        mock_registry = Mock()
        # object() has no `cleanup` attribute -> hasattr() guard is exercised.
        mock_registry.get_mod_instance.return_value = object()
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.comms.get_mod_comms", side_effect=ImportError),
        ):
            result = mm.unload_mod("plain_mod")
        assert result is True
        mock_registry.unregister_mod.assert_called_once_with("plain_mod")
        assert mm._loaded_mods == []

    def test_unload_cleanup_error(self, tmp_path):
        """A failing cleanup() is swallowed; the mod is still unregistered and unload succeeds."""
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["test_mod"]
        mock_registry = Mock()
        mock_instance = Mock()
        mock_instance.cleanup.side_effect = RuntimeError("cleanup failed")
        mock_registry.get_mod_instance.return_value = mock_instance
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.comms.get_mod_comms", side_effect=ImportError),
        ):
            result = mm.unload_mod("test_mod")
        assert result is True
        # Despite the cleanup error, the registry unregister and list pruning still run.
        mock_registry.unregister_mod.assert_called_once_with("test_mod")
        assert "test_mod" not in mm._loaded_mods


# ========================= ModManager - validate_mod_package ==============


class TestModManagerValidateModPackage:
    def test_file_not_exists(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        ok, msg, detail = mm.validate_mod_package("/nonexistent/path.xcmod")
        assert ok is False
        assert msg == "文件不存在"
        assert detail == {}

    def test_not_zip(self, tmp_path):
        not_zip = tmp_path / "not_zip.xcmod"
        not_zip.write_text("not a zip")
        mm = ModManager(mods_root=str(tmp_path))
        ok, msg, detail = mm.validate_mod_package(str(not_zip))
        assert ok is False
        assert "ZIP" in msg
        assert detail == {}

    def _make_zip(self, src_dir, zip_path):
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            for root, _dirs, files in os.walk(str(src_dir)):
                for f in files:
                    full = os.path.join(root, f)
                    arcname = os.path.relpath(full, str(src_dir))
                    zf.write(full, arcname)

    def test_valid_package_returns_detail(self, tmp_path):
        """A well-formed mod validates True and echoes parsed manifest fields in the detail dict."""
        mod_dir = tmp_path / "valid_mod"
        mod_dir.mkdir()
        manifest = {
            "id": "valid_mod",
            "name": "Valid",
            "version": "1.2.0",
            "author": "acme",
        }
        (mod_dir / "manifest.json").write_text(json.dumps(manifest))
        (mod_dir / "backend").mkdir()
        (mod_dir / "backend" / "blueprints.py").write_text("# blueprints")

        zip_path = tmp_path / "valid.xcmod"
        self._make_zip(mod_dir, zip_path)

        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            return_value=(str(mod_dir), manifest),
        ):
            ok, msg, detail = mm.validate_mod_package(str(zip_path))
        assert ok is True
        assert msg == "验证通过"
        assert detail["id"] == "valid_mod"
        assert detail["name"] == "Valid"
        assert detail["version"] == "1.2.0"
        assert detail["author"] == "acme"
        assert detail["artifact"] == "mod"
        assert detail["errors"] == []

    def test_missing_id_field(self, tmp_path):
        """A manifest without `id` fails validation with a precise message and empty detail."""
        mod_dir = tmp_path / "no_id"
        mod_dir.mkdir()
        manifest = {"name": "No ID", "version": "1.0"}
        (mod_dir / "manifest.json").write_text(json.dumps(manifest))
        zip_path = tmp_path / "noid.xcmod"
        self._make_zip(mod_dir, zip_path)

        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            return_value=(str(mod_dir), manifest),
        ):
            ok, msg, detail = mm.validate_mod_package(str(zip_path))
        assert ok is False
        assert msg == "缺少必填字段 'id'"
        assert detail == {}

    def test_missing_backend_entry_file_collects_error(self, tmp_path):
        """Manifest declares a backend entry whose .py is absent -> invalid with that error listed."""
        mod_dir = tmp_path / "broken_mod"
        mod_dir.mkdir()
        manifest = {
            "id": "broken_mod",
            "name": "Broken",
            "version": "1.0",
            "backend": {"entry": "main"},
        }
        (mod_dir / "manifest.json").write_text(json.dumps(manifest))
        # backend/ exists but main.py is intentionally missing.
        (mod_dir / "backend").mkdir()
        zip_path = tmp_path / "broken.xcmod"
        self._make_zip(mod_dir, zip_path)

        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            return_value=(str(mod_dir), manifest),
        ):
            ok, msg, detail = mm.validate_mod_package(str(zip_path))
        assert ok is False
        assert "main.py" in msg
        assert any("main.py" in e for e in detail["errors"])


# ========================= ModManager - get_mod / list_loaded_mods ========


class TestModManagerGetMod:
    def test_get_mod(self, tmp_path):
        """get_mod delegates to the registry and returns its ModMetadata unchanged."""
        mm = ModManager(mods_root=str(tmp_path))
        meta = ModMetadata(id="test_mod", name="T", version="3.0", mod_path="/x")
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = meta
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.get_mod("test_mod")
        assert result is meta
        mock_registry.get_mod_metadata.assert_called_once_with("test_mod")

    def test_get_mod_unknown_returns_none(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.get_mod("ghost")
        assert result is None

    def test_list_loaded_mods(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        m1 = ModMetadata(id="m1", name="M1", version="1.0", mod_path="/a")
        m2 = ModMetadata(id="m2", name="M2", version="1.0", mod_path="/b")
        mock_registry = Mock()
        mock_registry.list_mods.return_value = [m1, m2]
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            result = mm.list_loaded_mods()
        # Returns exactly the registry's view, preserving order and identity.
        assert [m.id for m in result] == ["m1", "m2"]
        assert result[0] is m1


# ========================= ModManager - _metadata_to_api_dict =============


class TestModManagerMetadataToApiDict:
    def test_basic_conversion(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            author="dev",
            description="A test mod",
            primary=True,
        )
        result = ModManager._metadata_to_api_dict(meta)
        assert result["id"] == "test"
        assert result["name"] == "Test"
        assert result["version"] == "1.0"
        assert result["author"] == "dev"
        assert result["description"] == "A test mod"
        assert result["primary"] is True
        # Defaults for a plain mod: artifact "mod", empty collections, no "type" key.
        assert result["artifact"] == "mod"
        assert result["industry"] == {}
        assert result["ui_labels"] == {}
        assert result["menu"] == []
        assert result["comms_exports"] == []
        assert "type" not in result

    def test_bundle_adds_type_key(self):
        """A bundle artifact surfaces a `type: bundle` marker for the frontend."""
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(id="b", name="B", version="1.0", mod_path="/tmp/b", artifact="bundle")
        result = ModManager._metadata_to_api_dict(meta)
        assert result["artifact"] == "bundle"
        assert result["type"] == "bundle"

    def test_with_industry_and_ui_labels(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            industry={"sector": "manufacturing"},
            ui_labels={"title": "Test Title"},
        )
        result = ModManager._metadata_to_api_dict(meta)
        assert result["industry"] == {"sector": "manufacturing"}
        assert result["ui_labels"] == {"title": "Test Title"}

    def test_with_frontend_menu(self):
        from app.infrastructure.mods.manifest import ModMetadata

        meta = ModMetadata(
            id="test",
            name="Test",
            version="1.0",
            mod_path="/tmp/test",
            frontend_menu=[{"label": "Test", "path": "/test"}],
        )
        result = ModManager._metadata_to_api_dict(meta)
        # The manifest menu rows are passed through verbatim under the "menu" key.
        assert result["menu"] == [{"label": "Test", "path": "/test"}]


# ========================= ModManager - install_mod_package ===============


class TestModManagerInstallModPackage:
    def test_signature_error(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            side_effect=__import__(
                "app.infrastructure.mods.package", fromlist=["ModSignatureError"]
            ).ModSignatureError("bad sig"),
        ):
            result = mm.install_mod_package("/fake/path.xcmod")
        assert result[0] is False
        assert "签名" in result[1]

    def test_package_error(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            side_effect=__import__(
                "app.infrastructure.mods.package", fromlist=["ModPackageError"]
            ).ModPackageError("bad pkg"),
        ):
            result = mm.install_mod_package("/fake/path.xcmod")
        assert result[0] is False
        assert "无效" in result[1]

    def test_missing_id_in_manifest(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path / "root"))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            return_value=("/tmp/extract", {"name": "No ID", "version": "1.0"}),
        ):
            ok, msg, meta = mm.install_mod_package("/fake/path.xcmod")
        assert ok is False
        assert msg == "MOD 包缺少 id 字段"
        assert meta is None

    def test_sku_blocked_on_install(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path / "root"))
        with (
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=("/tmp/extract", {"id": "blocked", "version": "1.0"}),
            ),
            patch(
                "app.mod_sdk.product_skus.assert_mod_allowed_for_sku",
                side_effect=PermissionError("sku says no"),
            ),
        ):
            ok, msg, meta = mm.install_mod_package("/fake/path.xcmod")
        assert ok is False
        # The PermissionError message is surfaced to the caller verbatim.
        assert msg == "sku says no"
        assert meta is None
        # Nothing was copied into the mods root.
        assert not os.path.isdir(os.path.join(mm.mods_root, "blocked"))

    def test_activate_false_copies_files_without_loading(self, tmp_path):
        """activate=False copies the package into mods_root but never calls load_mod."""
        mm = ModManager(mods_root=str(tmp_path / "root"))
        # Separate extract dir (not under mods_root) so the copytree source is preserved.
        extract_dir = tmp_path / "extract" / "test_mod"
        extract_dir.mkdir(parents=True)
        (extract_dir / "manifest.json").write_text(
            '{"id": "test_mod", "name": "Test", "version": "1.0"}'
        )
        installed_meta = ModMetadata(
            id="test_mod", name="Test", version="1.0", mod_path=str(extract_dir)
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(
                    str(extract_dir),
                    {"id": "test_mod", "name": "Test", "version": "1.0"},
                ),
            ),
            patch(
                "app.infrastructure.mods.mod_manager.parse_manifest",
                return_value=installed_meta,
            ),
            patch.object(mm, "load_mod") as mock_load,
        ):
            ok, msg, meta = mm.install_mod_package("/fake/path.xcmod", activate=False)
        assert ok is True
        assert "未激活" in msg
        assert meta is installed_meta
        # Files landed under mods_root/<id>, and activation was deliberately skipped.
        assert os.path.isfile(os.path.join(mm.mods_root, "test_mod", "manifest.json"))
        mock_load.assert_not_called()

    def test_activate_true_loads_mod(self, tmp_path):
        """activate=True copies files then loads the mod, returning its metadata."""
        mm = ModManager(mods_root=str(tmp_path / "root"))
        extract_dir = tmp_path / "extract" / "test_mod"
        extract_dir.mkdir(parents=True)
        (extract_dir / "manifest.json").write_text(
            '{"id": "test_mod", "name": "Test", "version": "1.0"}'
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(
                    str(extract_dir),
                    {"id": "test_mod", "name": "Test", "version": "1.0"},
                ),
            ),
            patch(
                "app.infrastructure.mods.mod_manager.parse_manifest",
                return_value=ModMetadata(
                    id="test_mod", name="Test", version="1.0", mod_path=str(extract_dir)
                ),
            ),
            patch.object(mm, "load_mod", return_value=True) as mock_load,
        ):
            ok, msg, meta = mm.install_mod_package("/fake/path.xcmod", activate=True)
        assert ok is True
        assert "安装成功" in msg
        assert meta is not None and meta.id == "test_mod"
        mock_load.assert_called_once_with("test_mod")

    def test_activate_true_load_failure(self, tmp_path):
        """If activation's load_mod fails, install reports success-but-load-failed."""
        mm = ModManager(mods_root=str(tmp_path / "root"))
        extract_dir = tmp_path / "extract" / "test_mod"
        extract_dir.mkdir(parents=True)
        (extract_dir / "manifest.json").write_text(
            '{"id": "test_mod", "name": "Test", "version": "1.0"}'
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(
                    str(extract_dir),
                    {"id": "test_mod", "name": "Test", "version": "1.0"},
                ),
            ),
            patch.object(mm, "load_mod", return_value=False),
        ):
            ok, msg, meta = mm.install_mod_package("/fake/path.xcmod", activate=True)
        assert ok is False
        assert "加载失败" in msg
        assert meta is None

    def test_signature_error_message(self, tmp_path):
        """A signature failure maps to the 签名验证失败 message, not a generic install error."""
        from app.infrastructure.mods.package import ModSignatureError

        mm = ModManager(mods_root=str(tmp_path / "root"))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            side_effect=ModSignatureError("untrusted"),
        ):
            ok, msg, meta = mm.install_mod_package("/fake/path.xcmod")
        assert ok is False
        assert msg.startswith("签名验证失败")
        assert meta is None

    def test_generic_exception(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path / "root"))
        with patch(
            "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
            side_effect=RuntimeError("unexpected"),
        ):
            ok, msg, meta = mm.install_mod_package("/fake/path.xcmod")
        assert ok is False
        assert "安装失败" in msg
        assert "unexpected" in msg
        assert meta is None


# ========================= ModManager - uninstall_mod ====================


class TestModManagerUninstallMod:
    def test_unload_not_in_registry(self, tmp_path):
        """Unknown mod with no employee-pack dir -> failure with a not-found message."""
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.employee_registry.get_employee_registry") as mock_er,
        ):
            mock_er_inst = Mock()
            mock_er.return_value = mock_er_inst
            mock_er_inst._root.return_value = str(tmp_path)
            # mod_id dir doesn't exist in employee root -> falls through to "未加载或不存在".
            ok, msg = mm.uninstall_mod("nonexistent")
        assert ok is False
        assert "nonexistent" in msg
        assert "未加载或不存在" in msg
        # No employee-pack uninstall is attempted when the dir is absent.
        mock_er_inst.uninstall_pack.assert_not_called()

    def test_unload_with_remove_files(self, tmp_path):
        """A loaded mod is unregistered, removed from disk, and pruned from _loaded_mods."""
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["test_mod"]
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = Mock()
        mock_registry.get_mod_instance.return_value = None
        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("{}")
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.comms.get_mod_comms", side_effect=ImportError),
        ):
            ok, msg = mm.uninstall_mod("test_mod", remove_files=True)
        assert ok is True
        assert "卸载成功" in msg
        assert not mod_dir.exists()
        # unload_mod ran as part of uninstall -> registry unregister + list pruning.
        mock_registry.unregister_mod.assert_called_once_with("test_mod")
        assert mm._loaded_mods == []

    def test_unload_keep_files(self, tmp_path):
        """remove_files=False unregisters the mod but leaves its directory on disk."""
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["keep_mod"]
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = Mock()
        mock_registry.get_mod_instance.return_value = None
        mod_dir = tmp_path / "keep_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("{}")
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.comms.get_mod_comms", side_effect=ImportError),
        ):
            ok, msg = mm.uninstall_mod("keep_mod", remove_files=False)
        assert ok is True
        # Directory survives because remove_files was False.
        assert mod_dir.exists()
        mock_registry.unregister_mod.assert_called_once_with("keep_mod")

    def test_unload_generic_error(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.side_effect = RuntimeError("db error")
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            ok, msg = mm.uninstall_mod("test_mod")
        assert ok is False
        assert "卸载失败" in msg
        assert "db error" in msg


# ========================= ModManager - update_mod =======================


class TestModManagerUpdateMod:
    def test_mod_not_installed(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = None
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            ok, msg, meta = mm.update_mod("nonexistent", "/fake/path.xcmod")
        assert ok is False
        assert "未安装" in msg
        assert meta is None

    def test_update_was_loaded(self, tmp_path):
        """A loaded mod is unloaded, files replaced, reloaded, and the new version reported."""
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["test_mod"]
        mock_registry = Mock()
        current_meta = ModMetadata(id="test_mod", name="T", version="1.0", mod_path="/x")
        mock_registry.get_mod_metadata.return_value = current_meta
        # Separate extract dir (not under mods_root) for the copytree source.
        extract_dir = tmp_path / "extract" / "test_mod"
        extract_dir.mkdir(parents=True)
        (extract_dir / "manifest.json").write_text('{"id": "test_mod", "version": "2.0"}')
        # Pre-seed an existing install so the rmtree-before-copy branch runs.
        old_install = tmp_path / "test_mod"
        old_install.mkdir()
        (old_install / "old.txt").write_text("stale")
        mock_pkg = Mock()
        mock_pkg.manifest = {"id": "test_mod", "version": "2.0"}
        new_meta = ModMetadata(id="test_mod", name="T", version="2.0", mod_path=str(old_install))
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.mod_manager.ModPackage", return_value=mock_pkg),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                return_value=(str(extract_dir), {"id": "test_mod", "version": "2.0"}),
            ),
            patch.object(mm, "unload_mod", return_value=True) as mock_unload,
            patch.object(mm, "load_mod", return_value=True) as mock_load,
            patch("app.infrastructure.mods.mod_manager.parse_manifest", return_value=new_meta),
        ):
            ok, msg, meta = mm.update_mod("test_mod", "/fake/path.xcmod")
        assert ok is True
        assert "2.0" in msg  # new version surfaced in the message
        assert meta is new_meta
        # Was loaded -> unloaded then reloaded; new files copied in (stale file gone).
        mock_unload.assert_called_once_with("test_mod")
        mock_load.assert_called_once_with("test_mod")
        assert (old_install / "manifest.json").exists()
        assert not (old_install / "old.txt").exists()

    def test_update_extract_error_rollback(self, tmp_path):
        """If extraction fails after unload, the previously-loaded mod is reloaded (rollback)."""
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods = ["test_mod"]
        mock_registry = Mock()
        mock_registry.get_mod_metadata.return_value = ModMetadata(
            id="test_mod", name="T", version="1.0", mod_path="/x"
        )
        mock_pkg = Mock()
        mock_pkg.manifest = {"id": "test_mod", "version": "2.0"}
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
            ),
            patch("app.infrastructure.mods.mod_manager.ModPackage", return_value=mock_pkg),
            patch(
                "app.infrastructure.mods.mod_manager.ModPackage.extract_package",
                side_effect=RuntimeError("extract failed"),
            ),
            patch.object(mm, "unload_mod", return_value=True) as mock_unload,
            patch.object(mm, "load_mod", return_value=True) as mock_load,
        ):
            ok, msg, meta = mm.update_mod("test_mod", "/fake/path.xcmod")
        assert ok is False
        assert "更新失败" in msg
        assert "extract failed" in msg
        assert meta is None
        # Rollback: the mod that was unloaded is reloaded so the host is not left broken.
        mock_unload.assert_called_once_with("test_mod")
        mock_load.assert_called_once_with("test_mod")

    def test_update_generic_error(self, tmp_path):
        mm = ModManager(mods_root=str(tmp_path))
        mock_registry = Mock()
        mock_registry.get_mod_metadata.side_effect = RuntimeError("unexpected boom")
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_registry", return_value=mock_registry
        ):
            ok, msg, meta = mm.update_mod("test_mod", "/fake/path.xcmod")
        assert ok is False
        assert "更新失败" in msg
        assert "unexpected boom" in msg
        assert meta is None


# ========================= ModManager - all_mods_roots ====================


class TestModManagerAllModsRoots:
    def test_primary_root_is_first_and_absolute(self, tmp_path):
        """The configured (existing) primary root leads the deduped, absolute roots list."""
        mm = ModManager(mods_root=str(tmp_path))
        # No env override -> only repo-layout candidates may follow the primary.
        with patch.dict("os.environ", {}, clear=True):
            roots = mm.all_mods_roots()
        assert roots[0] == os.path.abspath(str(tmp_path))
        # All entries are absolute and unique.
        assert all(os.path.isabs(r) for r in roots)
        assert len(roots) == len(set(roots))

    def test_env_root_appended_after_primary(self, tmp_path):
        """A valid XCAGI_MODS_ROOT env dir is included alongside the primary, deduped."""
        primary = tmp_path / "primary"
        primary.mkdir()
        env_root = tmp_path / "env_root"
        env_root.mkdir()
        mm = ModManager(mods_root=str(primary))
        with patch.dict("os.environ", {"XCAGI_MODS_ROOT": str(env_root)}, clear=True):
            roots = mm.all_mods_roots()
        # _refresh_mods_root_if_needed promotes the env dir to the primary slot.
        assert os.path.abspath(str(env_root)) in roots
        assert roots[0] == os.path.abspath(str(env_root))

    def test_missing_primary_excluded(self, tmp_path):
        """A nonexistent primary root is not returned (only real directories survive)."""
        missing = tmp_path / "does_not_exist"
        mm = ModManager(mods_root=str(missing))
        with (
            patch.dict("os.environ", {}, clear=True),
            # Keep _default_mods_root from re-resolving to a real repo dir.
            patch(
                "app.infrastructure.mods.mod_manager._default_mods_root",
                return_value=str(missing),
            ),
            patch(
                "app.infrastructure.mods.mod_manager._repo_layout_mods_candidates",
                return_value=[],
            ),
        ):
            roots = mm.all_mods_roots()
        assert os.path.abspath(str(missing)) not in roots
