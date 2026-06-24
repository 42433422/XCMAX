"""Behavioral coverage for the still-uncovered branches of
``app.fastapi_routes.mod_store_routes``.

Companion file ``tests/test_mod_sdk/test_aux_employee_store.py`` MUST run first
(it initializes the real ``app`` package and sidesteps an ``app.services``
circular-import collection error).

This file targets the functions that the sibling ``test_mod_store_routes_cov.py``
deliberately leaves alone:

* ``_remote_rows``                       (lines 223, 226, 228-229)
* ``_install_from_catalog``              (lines 388, 394-457)
* ``_ensure_host_foundation_employee_on_disk`` (lines 756-758)

Every external dependency (catalog iteration / download, host_foundation,
employee_registry, mod_manager, artifact peeking, filesystem) is mocked so the
tests are deterministic, offline, and fast. Inner ``from ... import ...`` calls
are patched at the *real* module path they resolve to at call time.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.fastapi_routes.mod_store_routes as _mod

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _async_gen(rows: list[dict[str, Any]]):
    """Build a callable that returns a fresh async generator yielding rows."""

    async def _gen():
        for r in rows:
            yield r

    return _gen


# ===========================================================================
# _remote_rows  — lines 219-230
# ===========================================================================


class TestRemoteRows:
    async def test_skips_rows_without_id(self):
        """Line 223: a catalog row producing an empty id is skipped (continue)."""
        rows = [{"id": "", "name": ""}, {"id": "good-mod", "name": "Good"}]
        with patch.object(_mod, "iter_catalog_packages", _async_gen(rows)):
            with patch.object(_mod, "_installed_by_id", return_value={}):
                with patch(
                    "app.mod_sdk.host_foundation.is_infrastructure_mod_hidden_from_store",
                    return_value=False,
                ):
                    out = await _mod._remote_rows()
        ids = [r["id"] for r in out]
        assert ids == ["good-mod"]

    async def test_hidden_infra_mod_without_public_listing_skipped(self):
        """Line 225-226: infra-hidden mod without public_listing is dropped."""
        rows = [
            {"id": "infra-secret", "name": "Secret", "public_listing": False},
            {"id": "visible", "name": "Visible", "public_listing": False},
        ]

        def _hidden(mid):
            return mid == "infra-secret"

        with patch.object(_mod, "iter_catalog_packages", _async_gen(rows)):
            with patch.object(_mod, "_installed_by_id", return_value={}):
                with patch(
                    "app.mod_sdk.host_foundation.is_infrastructure_mod_hidden_from_store",
                    side_effect=_hidden,
                ):
                    out = await _mod._remote_rows()
        ids = [r["id"] for r in out]
        assert "infra-secret" not in ids
        assert "visible" in ids

    async def test_hidden_infra_mod_with_public_listing_kept(self):
        """The public_listing=True branch keeps an otherwise-hidden infra mod."""
        rows = [{"id": "infra-listed", "name": "Listed", "public_listing": True}]

        with patch.object(_mod, "iter_catalog_packages", _async_gen(rows)):
            with patch.object(_mod, "_installed_by_id", return_value={}):
                with patch(
                    "app.mod_sdk.host_foundation.is_infrastructure_mod_hidden_from_store",
                    return_value=True,
                ):
                    out = await _mod._remote_rows()
        ids = [r["id"] for r in out]
        assert "infra-listed" in ids

    async def test_http_exception_during_iteration_returns_partial(self):
        """Lines 228-229: HTTPException mid-iteration → warn + return what we have."""
        from fastapi import HTTPException

        async def _gen_then_raise():
            yield {"id": "first-mod", "name": "First"}
            raise HTTPException(status_code=503, detail="catalog down")

        with patch.object(_mod, "iter_catalog_packages", _gen_then_raise):
            with patch.object(_mod, "_installed_by_id", return_value={}):
                with patch(
                    "app.mod_sdk.host_foundation.is_infrastructure_mod_hidden_from_store",
                    return_value=False,
                ):
                    out = await _mod._remote_rows()
        # The row yielded before the exception is preserved; no crash.
        ids = [r["id"] for r in out]
        assert ids == ["first-mod"]

    async def test_http_exception_immediately_returns_empty(self):
        """Lines 228-229: exception before any yield → empty fallback list."""
        from fastapi import HTTPException

        async def _gen_raise():
            raise HTTPException(status_code=502, detail="bad gateway")
            yield  # pragma: no cover - unreachable, marks function as a generator

        with patch.object(_mod, "iter_catalog_packages", _gen_raise):
            with patch.object(_mod, "_installed_by_id", return_value={}):
                out = await _mod._remote_rows()
        assert out == []


# ===========================================================================
# _install_from_catalog  — lines 385-457
# ===========================================================================


class TestInstallFromCatalog:
    async def test_host_foundation_employee_pack_delegates(self):
        """Lines 394-395: host-foundation pack id routes to internal installer."""
        sentinel = _mod.ModStoreInstallResult(success=True, message="hf-ok", data={"ready": True})
        with patch(
            "app.mod_sdk.host_foundation.is_host_foundation_employee_pack",
            return_value=True,
        ):
            with patch.object(
                _mod, "_install_host_foundation_internal", AsyncMock(return_value=sentinel)
            ) as internal:
                result = await _mod._install_from_catalog("xcagi-host-foundation-employee", "")
        internal.assert_awaited_once_with(edition=None)
        assert result is sentinel
        assert result.message == "hf-ok"

    async def test_aux_employee_pack_seed_success_returns_early(self):
        """Lines 397-400: aux pack repo-seed install succeeds → returns immediately."""
        with patch(
            "app.mod_sdk.host_foundation.is_host_foundation_employee_pack",
            return_value=False,
        ):
            with patch(
                "app.mod_sdk.host_foundation.is_aux_employee_pack_mod_id",
                return_value=True,
            ):
                with patch(
                    "app.mod_sdk.host_foundation.install_aux_employee_pack_from_repo_seed",
                    return_value=(True, "seeded from repo"),
                ) as seed:
                    result = await _mod._install_from_catalog("aux-pack", "1.0", activate=False)
        seed.assert_called_once_with("aux-pack", activate=False)
        assert result.success is True
        assert result.message == "seeded from repo"
        assert result.data == {"id": "aux-pack"}

    async def test_aux_employee_pack_seed_failure_falls_through_to_catalog(self):
        """Line 401: aux seed install fails → logs and continues to catalog path."""
        meta = _DummyMeta(name="dl-mod")
        mm = MagicMock()
        mm.install_mod_package.return_value = (True, "installed via catalog", meta)

        with patch(
            "app.mod_sdk.host_foundation.is_host_foundation_employee_pack",
            return_value=False,
        ):
            with patch(
                "app.mod_sdk.host_foundation.is_aux_employee_pack_mod_id",
                return_value=True,
            ):
                with patch(
                    "app.mod_sdk.host_foundation.install_aux_employee_pack_from_repo_seed",
                    return_value=(False, "no repo seed"),
                ):
                    with self._catalog_download_ctx(peek="mod", mm=mm):
                        result = await _mod._install_from_catalog("aux-pack", "2.0")
        # fell through to catalog install
        assert result.success is True
        assert result.message == "installed via catalog"

    async def test_missing_pkg_id_raises_400(self):
        """Lines 403-404: empty pkg_id → HTTPException 400."""
        from fastapi import HTTPException

        with patch(
            "app.mod_sdk.host_foundation.is_host_foundation_employee_pack",
            return_value=False,
        ):
            with patch(
                "app.mod_sdk.host_foundation.is_aux_employee_pack_mod_id",
                return_value=False,
            ):
                with pytest.raises(HTTPException) as exc:
                    await _mod._install_from_catalog("", "")
        assert exc.value.status_code == 400
        assert "pkg_id" in exc.value.detail

    async def test_version_resolved_from_versions_dict_entry(self):
        """Lines 405-411: no version → fetch versions list, first entry is dict."""
        meta = _DummyMeta(name="resolved")
        mm = MagicMock()
        mm.install_mod_package.return_value = (True, "ok", meta)
        versions_payload = {"versions": [{"version": "3.4.5"}, {"version": "1.0.0"}]}

        with self._no_special_pkg():
            with patch.object(
                _mod, "catalog_get_json", AsyncMock(return_value=versions_payload)
            ) as get_json:
                with self._catalog_download_ctx(peek="mod", mm=mm) as dl:
                    await _mod._install_from_catalog("some-mod", "")
        # versions endpoint queried; the chosen version reached the download URL
        get_json.assert_awaited_once()
        download_path = dl["download"].call_args.args[0]
        assert "3.4.5" in download_path

    async def test_version_resolved_from_versions_string_entry(self):
        """Lines 412-413: first version entry is a bare string, not a dict."""
        meta = _DummyMeta(name="resolved2")
        mm = MagicMock()
        mm.install_mod_package.return_value = (True, "ok", meta)
        versions_payload = {"versions": ["9.9.9"]}

        with self._no_special_pkg():
            with patch.object(_mod, "catalog_get_json", AsyncMock(return_value=versions_payload)):
                with self._catalog_download_ctx(peek="mod", mm=mm) as dl:
                    await _mod._install_from_catalog("strver-mod", "")
        download_path = dl["download"].call_args.args[0]
        assert "9.9.9" in download_path

    async def test_no_version_after_lookup_raises_400(self):
        """Lines 414-415: versions list empty → still no version → 400."""
        from fastapi import HTTPException

        with self._no_special_pkg():
            with patch.object(_mod, "catalog_get_json", AsyncMock(return_value={"versions": []})):
                with pytest.raises(HTTPException) as exc:
                    await _mod._install_from_catalog("no-ver-mod", "")
        assert exc.value.status_code == 400
        assert "version" in exc.value.detail

    async def test_employee_pack_artifact_uses_employee_registry(self):
        """Lines 430-436: peek == employee_pack → registry.install_from_package."""
        registry = MagicMock()
        registry.install_from_package.return_value = (True, "emp installed")

        with self._no_special_pkg():
            with self._catalog_download_ctx(peek=_mod_artifact_employee_pack(), registry=registry):
                result = await _mod._install_from_catalog("emp-mod", "1.0")
        registry.install_from_package.assert_called_once()
        # verify_signature=False is forced
        _, kwargs = registry.install_from_package.call_args
        assert kwargs.get("verify_signature") is False
        assert result.success is True
        assert result.message == "emp installed"
        assert result.data is None

    async def test_regular_mod_artifact_returns_metadata_asdict(self):
        """Lines 438-450: non-employee artifact → mod_manager + dataclass asdict."""
        meta = _DummyMeta(name="cool-mod", version="1.0")
        mm = MagicMock()
        mm.install_mod_package.return_value = (True, "mod installed", meta)

        with self._no_special_pkg():
            with self._catalog_download_ctx(peek="mod", mm=mm):
                result = await _mod._install_from_catalog("cool-mod", "1.0", activate=True)
        assert result.success is True
        assert result.message == "mod installed"
        assert result.data == dataclasses.asdict(meta)
        assert result.data["name"] == "cool-mod"

    async def test_regular_mod_no_metadata_yields_none_data(self):
        """Lines 445-450: metadata is None → data stays None."""
        mm = MagicMock()
        mm.install_mod_package.return_value = (False, "failed install", None)

        with self._no_special_pkg():
            with self._catalog_download_ctx(peek="mod", mm=mm):
                result = await _mod._install_from_catalog("bad-mod", "1.0")
        assert result.success is False
        assert result.message == "failed install"
        assert result.data is None

    async def test_temp_files_cleaned_up_in_finally(self):
        """Lines 451-457: temp + normalized files are removed in finally."""
        meta = _DummyMeta(name="m")
        mm = MagicMock()
        mm.install_mod_package.return_value = (True, "ok", meta)
        unlinked: list[str] = []

        def _fake_unlink(p):
            unlinked.append(p)

        with self._no_special_pkg():
            with self._catalog_download_ctx(peek="mod", mm=mm) as dl:
                with patch.object(_mod.os, "unlink", side_effect=_fake_unlink):
                    with patch.object(_mod.os.path, "exists", return_value=True):
                        await _mod._install_from_catalog("clean-mod", "1.0")
        # both the raw temp path and the normalized path get unlink attempts
        assert len(unlinked) >= 1
        normalized = dl["normalized_path"]
        assert normalized in unlinked

    async def test_cleanup_swallows_oserror(self):
        """Lines 454-457: os.unlink raising OSError is logged, not propagated."""
        meta = _DummyMeta(name="m")
        mm = MagicMock()
        mm.install_mod_package.return_value = (True, "ok", meta)

        with self._no_special_pkg():
            with self._catalog_download_ctx(peek="mod", mm=mm):
                with patch.object(_mod.os.path, "exists", return_value=True):
                    with patch.object(_mod.os, "unlink", side_effect=OSError("locked")):
                        # must not raise despite unlink failing
                        result = await _mod._install_from_catalog("locked-mod", "1.0")
        assert result.success is True

    # ----- shared context helpers -----

    def _no_special_pkg(self):
        """Patch the three host_foundation predicates so we reach the catalog body."""
        return _MultiPatch(
            patch(
                "app.mod_sdk.host_foundation.is_host_foundation_employee_pack",
                return_value=False,
            ),
            patch(
                "app.mod_sdk.host_foundation.is_aux_employee_pack_mod_id",
                return_value=False,
            ),
        )

    def _catalog_download_ctx(self, *, peek, mm=None, registry=None, tmp_name=None):
        """Patch tempfile + download + normalize + artifact peek + registry/manager.

        Returns a context manager that, on enter, yields a dict with the
        AsyncMock for catalog_download_to (key 'download'), the raw temp path
        (key 'tmp_path') and the normalized path string (key 'normalized_path').
        ``tempfile.NamedTemporaryFile`` is stubbed so no real file is created.
        """
        return _CatalogDownloadCtx(_mod, peek=peek, mm=mm, registry=registry, tmp_name=tmp_name)


@dataclasses.dataclass
class _DummyMeta:
    name: str = "meta"
    version: str = "1.0.0"


def _mod_artifact_employee_pack() -> str:
    from app.infrastructure.mods.artifact_constants import ARTIFACT_EMPLOYEE_PACK

    return ARTIFACT_EMPLOYEE_PACK


class _MultiPatch:
    """Combine several unittest.mock patchers into one context manager."""

    def __init__(self, *patchers):
        self._patchers = patchers

    def __enter__(self):
        return [p.start() for p in self._patchers]

    def __exit__(self, *exc):
        for p in reversed(self._patchers):
            p.stop()
        return False


class _CatalogDownloadCtx:
    """Patches everything inside the catalog-install body of _install_from_catalog."""

    def __init__(self, mod, *, peek, mm=None, registry=None, tmp_name=None):
        self._mod = mod
        self._peek = peek
        self._mm = mm
        self._registry = registry
        self._tmp_name = tmp_name or "/tmp/xcagi-mod-fake.zip"
        self._patchers: list[Any] = []
        self.state: dict[str, Any] = {}

    def __enter__(self):
        normalized_path = "/tmp/xcagi-normalized.zip"
        self.state["normalized_path"] = normalized_path
        self.state["tmp_path"] = self._tmp_name

        # Stub tempfile.NamedTemporaryFile so no real file ever touches disk.
        fake_handle = MagicMock()
        fake_handle.name = self._tmp_name
        fake_handle.close = MagicMock()
        self._patchers.append(
            patch.object(
                self._mod.tempfile,
                "NamedTemporaryFile",
                return_value=fake_handle,
            )
        )

        download = AsyncMock(return_value=None)
        self._patchers.append(patch.object(self._mod, "catalog_download_to", download))
        self.state["download"] = download

        self._patchers.append(
            patch.object(self._mod, "_normalize_package_zip", lambda p: normalized_path)
        )
        self._patchers.append(
            patch("app.infrastructure.mods.artifact_package.peek_artifact", return_value=self._peek)
        )
        if self._mm is not None:
            self._patchers.append(
                patch(
                    "app.infrastructure.mods.mod_manager.get_mod_manager",
                    return_value=self._mm,
                )
            )
        if self._registry is not None:
            self._patchers.append(
                patch(
                    "app.infrastructure.mods.employee_registry.get_employee_registry",
                    return_value=self._registry,
                )
            )
        for p in self._patchers:
            p.start()
        return self.state

    def __exit__(self, *exc):
        for p in reversed(self._patchers):
            p.stop()
        return False


# ===========================================================================
# _ensure_host_foundation_employee_on_disk  — lines 749-758
# ===========================================================================


class TestEnsureHostFoundationOnDisk:
    async def test_already_present_returns_true(self):
        """Lines 751-752: dest dir already exists → no copy."""
        registry = MagicMock(mods_root="/fake/mods")
        with patch(
            "app.infrastructure.mods.employee_registry.get_employee_registry",
            return_value=registry,
        ):
            with patch(
                "app.infrastructure.mods.employee_registry.employees_root",
                return_value="/fake/mods/_employees_root",
            ):
                with patch.object(_mod.os.path, "isdir", return_value=True):
                    ok, msg = await _mod._ensure_host_foundation_employee_on_disk()
        assert ok is True
        assert msg == "employee pack present"

    async def test_source_missing_returns_false(self):
        """Lines 754-755: dest absent AND src absent → False with reason."""
        registry = MagicMock(mods_root="/fake/mods")

        # dest not a dir; src not a dir → both isdir() calls return False
        with patch(
            "app.infrastructure.mods.employee_registry.get_employee_registry",
            return_value=registry,
        ):
            with patch(
                "app.infrastructure.mods.employee_registry.employees_root",
                return_value="/fake/mods/_employees_root",
            ):
                with patch.object(_mod.os.path, "isdir", return_value=False):
                    ok, msg = await _mod._ensure_host_foundation_employee_on_disk()
        assert ok is False
        assert "缺失" in msg

    async def test_seeds_from_source_copytree(self, tmp_path):
        """Lines 756-758: dest absent, src present → makedirs + copytree → True."""
        registry = MagicMock(mods_root="/fake/mods")

        made_dirs: list[str] = []
        copied: list[tuple[str, str]] = []

        # First isdir() (dest) → False, second isdir() (src) → True
        isdir_results = iter([False, True])

        def _fake_isdir(_p):
            return next(isdir_results)

        with patch(
            "app.infrastructure.mods.employee_registry.get_employee_registry",
            return_value=registry,
        ):
            with patch(
                "app.infrastructure.mods.employee_registry.employees_root",
                return_value="/fake/mods/_employees_root",
            ):
                with patch.object(_mod.os.path, "isdir", side_effect=_fake_isdir):
                    with patch.object(
                        _mod.os,
                        "makedirs",
                        side_effect=lambda d, exist_ok=False: made_dirs.append(d),
                    ):
                        with patch(
                            "shutil.copytree",
                            side_effect=lambda s, d: copied.append((s, d)),
                        ):
                            ok, msg = await _mod._ensure_host_foundation_employee_on_disk()
        assert ok is True
        assert msg == "employee pack seeded"
        assert made_dirs, "makedirs should have been called for dest parent"
        assert copied, "copytree should have been called to seed the pack"
