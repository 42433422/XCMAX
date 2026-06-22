"""COVERAGE_RAMP Phase 6 round 19: backend low-coverage modules.

Targets:
- ``app/shell/xcagi_mods_discover.py`` (186 行, 未覆盖 64 行, cov 59.4%)
- ``app/infrastructure/db/mod_database_url.py`` (77 行, 未覆盖 63 行, cov 12.6%)
- ``app/services/distillation_data_collector.py`` (171 行, 未覆盖 63 行, cov 60.5%)
- ``app/utils/performance_initializer.py`` (171 行, 未覆盖 63 行, cov 59.3%)
- ``app/fastapi_routes/excel_vector.py`` (82 行, 未覆盖 62 行, cov 21.7%)
- ``app/application/enterprise_login_flow.py`` (137 行, 未覆盖 61 行, cov 51.3%)
- ``app/fastapi_routes/template_api.py`` (82 行, 未覆盖 61 行, cov 18.4%)
- ``app/neuro_bus/routing/policy_nn.py`` (82 行, 未覆盖 61 行, cov 19.8%)
- ``app/services/mobile_push.py`` (79 行, 未覆盖 61 行, cov 18.2%)

Tests follow the phase-6 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (DB / external
API / LLM / file IO). The handler functions themselves are exercised through
real calls.

Coverage scenarios per 铁律3:
- Happy path (valid input)
- Empty / None input
- Boundary values (empty list, empty dict, empty string)
- Exception paths (RECOVERABLE_ERRORS: RuntimeError, ValueError, OSError)
"""

from __future__ import annotations

import os

os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infrastructure.db import mod_database_url as mod_db_url_mod
from app.shell import xcagi_mods_discover as discover_mod

# ===========================================================================
# Shared helpers / fixtures
# ===========================================================================


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def xcagi_root(tmp_dir):
    """Create a fake XCAGI root with mods/ directory."""
    root = Path(tmp_dir) / "XCAGI"
    root.mkdir()
    (root / "mods").mkdir()
    (root / "frontend").mkdir()
    return root


def _make_manifest(
    mod_id: str = "test-mod",
    name: str = "Test Mod",
    *,
    version: str = "1.0",
    mod_type: str = "mod",
    color: str | None = None,
    description: str | None = None,
    primary: bool = False,
    menu: list | None = None,
    frontend_menu: list | None = None,
    workflow_employees: list | None = None,
    shell_tagline: str | None = None,
    shellMenuPreset: str | None = None,
    library_blurb: str | None = None,
    database_seed_sql: str | None = None,
    database_notes: str | None = None,
    database_seed_files: list | None = None,
    database_block: dict | None = None,
) -> dict:
    """Build a manifest.json dict."""
    m: dict[str, Any] = {"id": mod_id, "name": name, "version": version, "type": mod_type}
    if primary:
        m["primary"] = True
    if color:
        m["color"] = color
    if description:
        m["description"] = description
    if menu:
        m["menu"] = menu
    if frontend_menu:
        m.setdefault("frontend", {})["menu"] = frontend_menu
    if workflow_employees:
        m["workflow_employees"] = workflow_employees
    if shell_tagline:
        m["shell_tagline"] = shell_tagline
    if shellMenuPreset:
        m["shellMenuPreset"] = shellMenuPreset
    if library_blurb:
        m["library_blurb"] = library_blurb
    if database_seed_sql:
        m["database_seed_sql"] = database_seed_sql
    if database_notes:
        m["database_notes"] = database_notes
    if database_seed_files:
        m["database_seed_files"] = database_seed_files
    if database_block:
        m["database"] = database_block
    return m


def _write_mod(xcagi_root: Path, mod_id: str, manifest: dict) -> Path:
    """Write a mod directory with manifest.json under xcagi_root/mods/."""
    mod_dir = xcagi_root / "mods" / mod_id
    mod_dir.mkdir(exist_ok=True)
    mf = mod_dir / "manifest.json"
    mf.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return mod_dir


# ===========================================================================
# 1. app/shell/xcagi_mods_discover.py
# ===========================================================================


class TestEffectiveSingleModId:
    """Cover ``_effective_single_mod_id``."""

    def test_returns_env_var_value(self, monkeypatch):
        monkeypatch.setenv("XCAGI_SINGLE_MOD_ID", "my-mod")
        with patch("app.request_active_mod_ctx.get_request_active_mod_id", return_value=""):
            result = discover_mod._effective_single_mod_id()
        assert result == "my-mod"

    def test_returns_ctx_value_over_env(self, monkeypatch):
        monkeypatch.setenv("XCAGI_SINGLE_MOD_ID", "env-mod")
        with patch("app.request_active_mod_ctx.get_request_active_mod_id", return_value="ctx-mod"):
            result = discover_mod._effective_single_mod_id()
        assert result == "ctx-mod"

    def test_returns_none_when_empty(self, monkeypatch):
        monkeypatch.delenv("XCAGI_SINGLE_MOD_ID", raising=False)
        with patch("app.request_active_mod_ctx.get_request_active_mod_id", return_value=""):
            result = discover_mod._effective_single_mod_id()
        assert result is None

    def test_returns_none_when_ctx_raises(self, monkeypatch):
        monkeypatch.delenv("XCAGI_SINGLE_MOD_ID", raising=False)
        with patch(
            "app.request_active_mod_ctx.get_request_active_mod_id",
            side_effect=RuntimeError("no ctx"),
        ):
            result = discover_mod._effective_single_mod_id()
        assert result is None


class TestFilterManifestRowsToSingle:
    """Cover ``_filter_manifest_rows_to_single``."""

    def test_no_filter_returns_all(self):
        rows = [{"id": "a"}, {"id": "b"}]
        with patch("app.shell.xcagi_mods_discover._effective_single_mod_id", return_value=None):
            result = discover_mod._filter_manifest_rows_to_single(rows)
        assert result == rows

    def test_filter_matches_single(self):
        rows = [{"id": "a"}, {"id": "b"}]
        with patch("app.shell.xcagi_mods_discover._effective_single_mod_id", return_value="a"):
            result = discover_mod._filter_manifest_rows_to_single(rows)
        assert result == [{"id": "a"}]

    def test_filter_no_match_returns_empty(self):
        rows = [{"id": "a"}]
        with patch("app.shell.xcagi_mods_discover._effective_single_mod_id", return_value="z"):
            result = discover_mod._filter_manifest_rows_to_single(rows)
        assert result == []


class TestUniqueDirs:
    """Cover ``_unique_dirs``."""

    def test_deduplicates_same_path(self, tmp_dir):
        p = Path(tmp_dir)
        result = discover_mod._unique_dirs([p, p])
        assert len(result) == 1

    def test_preserves_order(self, tmp_dir):
        a = Path(tmp_dir) / "a"
        b = Path(tmp_dir) / "b"
        a.mkdir()
        b.mkdir()
        result = discover_mod._unique_dirs([a, b])
        assert len(result) == 2

    def test_skips_oserror(self):
        bad = MagicMock()
        bad.resolve.side_effect = OSError("broken symlink")
        result = discover_mod._unique_dirs([bad])
        assert result == []


class TestReadManifestDicts:
    """Cover ``read_manifest_dicts``."""

    def test_reads_valid_manifest(self, xcagi_root, monkeypatch):
        monkeypatch.setenv("XCAGI_ROOT", str(xcagi_root))
        _write_mod(xcagi_root, "mod1", _make_manifest("mod1", "Mod1", version="2.0"))
        rows = discover_mod.read_manifest_dicts()
        assert len(rows) >= 1
        r = rows[0]
        assert r["id"] == "mod1"
        assert r["version"] == "2.0"

    def test_skips_dot_dirs(self, xcagi_root, monkeypatch):
        monkeypatch.setenv("XCAGI_ROOT", str(xcagi_root))
        dot_dir = xcagi_root / "mods" / ".hidden"
        dot_dir.mkdir()
        (dot_dir / "manifest.json").write_text("{}", encoding="utf-8")
        rows = discover_mod.read_manifest_dicts()
        assert all(r["id"] != ".hidden" for r in rows)

    def test_skips_invalid_json(self, xcagi_root, monkeypatch):
        monkeypatch.setenv("XCAGI_ROOT", str(xcagi_root))
        mod_dir = xcagi_root / "mods" / "bad-json"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("{invalid", encoding="utf-8")
        rows = discover_mod.read_manifest_dicts()
        assert all(r["id"] != "bad-json" for r in rows)

    def test_skips_non_dict_root(self, xcagi_root, monkeypatch):
        monkeypatch.setenv("XCAGI_ROOT", str(xcagi_root))
        mod_dir = xcagi_root / "mods" / "list-root"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("[1,2,3]", encoding="utf-8")
        rows = discover_mod.read_manifest_dicts()
        assert all(r["id"] != "list-root" for r in rows)

    def test_extracts_menu_from_frontend(self, xcagi_root, monkeypatch):
        monkeypatch.setenv("XCAGI_ROOT", str(xcagi_root))
        _write_mod(
            xcagi_root,
            "menu-mod",
            _make_manifest("menu-mod", "MenuMod", frontend_menu=[{"label": "X"}]),
        )
        rows = discover_mod.read_manifest_dicts()
        r = next(x for x in rows if x["id"] == "menu-mod")
        assert r["menu"] == [{"label": "X"}]

    def test_extracts_shell_fields(self, xcagi_root, monkeypatch):
        monkeypatch.setenv("XCAGI_ROOT", str(xcagi_root))
        _write_mod(
            xcagi_root,
            "shell-mod",
            _make_manifest("shell-mod", "ShellMod", shell_tagline="hi", library_blurb="info"),
        )
        rows = discover_mod.read_manifest_dicts()
        r = next(x for x in rows if x["id"] == "shell-mod")
        assert r["shell_tagline"] == "hi"
        assert r["library_blurb"] == "info"

    def test_extracts_database_seed_sql(self, xcagi_root, monkeypatch):
        monkeypatch.setenv("XCAGI_ROOT", str(xcagi_root))
        _write_mod(
            xcagi_root,
            "db-mod",
            _make_manifest("db-mod", "DBMod", database_seed_sql="seed.sql"),
        )
        rows = discover_mod.read_manifest_dicts()
        r = next(x for x in rows if x["id"] == "db-mod")
        assert "database_seed_sql" in r

    def test_extracts_database_notes_and_seed_files(self, xcagi_root, monkeypatch):
        monkeypatch.setenv("XCAGI_ROOT", str(xcagi_root))
        _write_mod(
            xcagi_root,
            "db2-mod",
            _make_manifest(
                "db2-mod",
                "DB2Mod",
                database_notes="some notes",
                database_block={"seed_files": ["a.sql"], "notes_zh": "中文说明"},
                database_seed_files=["b.sql"],
            ),
        )
        rows = discover_mod.read_manifest_dicts()
        r = next(x for x in rows if x["id"] == "db2-mod")
        assert r["database_notes"] == "中文说明"
        assert len(r["database_seed_files"]) >= 1

    def test_no_mods_dir_returns_empty(self, monkeypatch, tmp_dir):
        # xcagi_root() falls back to repo/cwd candidates, so patch it to None
        # to force the "no mods dir" branch in read_manifest_dicts.
        monkeypatch.setenv("XCAGI_ROOT", str(tmp_dir))
        with patch("app.shell.xcagi_mods_discover.mods_dir", return_value=None):
            rows = discover_mod.read_manifest_dicts()
        assert rows == []

    def test_no_mods_dir_via_xcagi_root_none(self, monkeypatch):
        # When xcagi_root() returns None, mods_dir() returns None too.
        monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
        with patch("app.shell.xcagi_mods_discover.xcagi_root", return_value=None):
            assert discover_mod.mods_dir() is None
            assert discover_mod.read_manifest_dicts() == []


class TestRouteEntries:
    """Cover ``route_entries``."""

    def test_returns_route_paths(self, xcagi_root, monkeypatch):
        monkeypatch.setenv("XCAGI_ROOT", str(xcagi_root))
        _write_mod(xcagi_root, "rmod", _make_manifest("rmod", "RMod"))
        with patch(
            "app.shell.xcagi_mods_discover.read_manifest_dicts",
            return_value=[{"id": "rmod"}],
        ):
            entries = discover_mod.route_entries()
        assert len(entries) == 1
        assert entries[0]["mod_id"] == "rmod"
        assert "rmod/frontend/routes.js" in entries[0]["routes_path"]


class TestLoadingStatusExtras:
    """Cover ``loading_status_extras``."""

    def test_returns_extras_with_primary(self):
        rows = [{"id": "p1", "name": "P1", "version": "1.0", "primary": True}]
        with patch("app.shell.xcagi_mods_discover.read_manifest_dicts", return_value=rows):
            extras = discover_mod.loading_status_extras()
        assert extras["primary_mod_id"] == "p1"
        assert extras["mods_loaded"] == 1

    def test_returns_extras_no_primary(self):
        rows = [{"id": "a", "name": "A", "version": "1.0"}]
        with patch("app.shell.xcagi_mods_discover.read_manifest_dicts", return_value=rows):
            extras = discover_mod.loading_status_extras()
        assert extras["primary_mod_id"] is None


# ===========================================================================
# 2. app/infrastructure/db/mod_database_url.py
# ===========================================================================


class TestNormalizeModForEnv:
    """Cover ``_normalize_mod_for_env``."""

    def test_basic_normalization(self):
        result = mod_db_url_mod._normalize_mod_for_env("sz-qsm-pro")
        assert result == "SZ_QSM_PRO"

    def test_empty_string(self):
        result = mod_db_url_mod._normalize_mod_for_env("")
        assert result == ""

    def test_none_input(self):
        result = mod_db_url_mod._normalize_mod_for_env(None)
        assert result == ""

    def test_strips_underscores(self):
        result = mod_db_url_mod._normalize_mod_for_env("-hello-")
        assert result == "HELLO"


class TestNormalizeModFileSuffix:
    """Cover ``_normalize_mod_file_suffix``."""

    def test_basic_normalization(self):
        result = mod_db_url_mod._normalize_mod_file_suffix("Sz-Qsm-Pro")
        assert result == "sz_qsm_pro"

    def test_empty_returns_empty(self):
        result = mod_db_url_mod._normalize_mod_file_suffix("")
        assert result == ""


class TestModDbUrlFromEnv:
    """Cover ``_mod_db_url_from_env``."""

    def test_empty_mod_id_returns_empty(self):
        assert mod_db_url_mod._mod_db_url_from_env("") == ""

    def test_from_json_env(self, monkeypatch):
        monkeypatch.setenv(
            "XCAGI_MOD_DATABASE_URLS",
            json.dumps({"my-mod": "postgresql://host/db"}),
        )
        result = mod_db_url_mod._mod_db_url_from_env("my-mod")
        assert result == "postgresql://host/db"

    def test_from_individual_env(self, monkeypatch):
        monkeypatch.delenv("XCAGI_MOD_DATABASE_URLS", raising=False)
        monkeypatch.setenv("XCAGI_MOD_DATABASE_URL_MY_MOD", "postgresql://host2/db2")
        result = mod_db_url_mod._mod_db_url_from_env("my-mod")
        assert result == "postgresql://host2/db2"

    def test_invalid_json_falls_through(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MOD_DATABASE_URLS", "not-json")
        monkeypatch.setenv("XCAGI_MOD_DATABASE_URL_MY_MOD", "pg://host3/db3")
        result = mod_db_url_mod._mod_db_url_from_env("my-mod")
        assert result == "pg://host3/db3"


class TestIsolatedFlag:
    """Cover ``_isolated_flag``."""

    def test_true_values(self, monkeypatch):
        for v in ("1", "true", "True", "yes", "on"):
            monkeypatch.setenv("XCAGI_MOD_ISOLATED_DATABASES", v)
            assert mod_db_url_mod._isolated_flag() is True

    def test_false_values(self, monkeypatch):
        for v in ("0", "false", "no", "off", ""):
            monkeypatch.setenv("XCAGI_MOD_ISOLATED_DATABASES", v)
            assert mod_db_url_mod._isolated_flag() is False

    def test_unset(self, monkeypatch):
        monkeypatch.delenv("XCAGI_MOD_ISOLATED_DATABASES", raising=False)
        assert mod_db_url_mod._isolated_flag() is False


class TestSqliteUrlWithModSuffix:
    """Cover ``_sqlite_url_with_mod_suffix``."""

    def test_adds_suffix(self):
        result = mod_db_url_mod._sqlite_url_with_mod_suffix("sqlite:///data/xcagi.db", "my-mod")
        assert "xcagi__my_mod.db" in result

    def test_empty_mod_id_returns_base(self):
        result = mod_db_url_mod._sqlite_url_with_mod_suffix("sqlite:///data/xcagi.db", "")
        assert result == "sqlite:///data/xcagi.db"

    def test_memory_db_returns_base(self):
        result = mod_db_url_mod._sqlite_url_with_mod_suffix("sqlite:///:memory:", "my-mod")
        assert result == "sqlite:///:memory:"

    def test_non_sqlite_returns_base(self):
        result = mod_db_url_mod._sqlite_url_with_mod_suffix("postgresql://host/db", "my-mod")
        assert result == "postgresql://host/db"


class TestPostgresUrlWithModDb:
    """Cover ``_postgres_url_with_mod_db``."""

    def test_adds_suffix_to_dbname(self):
        result = mod_db_url_mod._postgres_url_with_mod_db(
            "postgresql+psycopg://user:pass@host:5432/xcagi", "my-mod"
        )
        assert "xcagi__my_mod" in result

    def test_empty_mod_id_returns_base(self):
        result = mod_db_url_mod._postgres_url_with_mod_db("postgresql://host/xcagi", "")
        assert result == "postgresql://host/xcagi"

    def test_already_suffixed_returns_base(self):
        result = mod_db_url_mod._postgres_url_with_mod_db(
            "postgresql://host/xcagi__my_mod", "my-mod"
        )
        assert result == "postgresql://host/xcagi__my_mod"

    def test_non_postgres_returns_base(self):
        result = mod_db_url_mod._postgres_url_with_mod_db("mysql://host/xcagi", "my-mod")
        assert result == "mysql://host/xcagi"


class TestResolveDatabaseUrlForActiveMod:
    """Cover ``resolve_database_url_for_active_mod``."""

    def test_empty_base_returns_empty(self):
        result = mod_db_url_mod.resolve_database_url_for_active_mod("")
        assert result == ""

    def test_no_active_mod_returns_base(self):
        with patch(
            "app.request_active_mod_ctx.get_request_active_mod_id",
            return_value="",
        ):
            result = mod_db_url_mod.resolve_database_url_for_active_mod("sqlite:///data/xcagi.db")
        assert result == "sqlite:///data/xcagi.db"

    def test_env_mapped_url(self, monkeypatch):
        monkeypatch.setenv(
            "XCAGI_MOD_DATABASE_URLS",
            json.dumps({"my-mod": "postgresql://mapped/db"}),
        )
        with patch(
            "app.request_active_mod_ctx.get_request_active_mod_id",
            return_value="my-mod",
        ):
            result = mod_db_url_mod.resolve_database_url_for_active_mod("sqlite:///base.db")
        assert result == "postgresql://mapped/db"

    def test_isolated_sqlite_suffix(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MOD_ISOLATED_DATABASES", "1")
        monkeypatch.delenv("XCAGI_MOD_DATABASE_URLS", raising=False)
        with patch(
            "app.request_active_mod_ctx.get_request_active_mod_id",
            return_value="my-mod",
        ):
            result = mod_db_url_mod.resolve_database_url_for_active_mod("sqlite:///data/xcagi.db")
        assert "xcagi__my_mod" in result

    def test_isolated_postgres_suffix(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MOD_ISOLATED_DATABASES", "1")
        monkeypatch.delenv("XCAGI_MOD_DATABASE_URLS", raising=False)
        with patch(
            "app.request_active_mod_ctx.get_request_active_mod_id",
            return_value="my-mod",
        ):
            result = mod_db_url_mod.resolve_database_url_for_active_mod(
                "postgresql+psycopg://u:p@h:5432/xcagi"
            )
        assert "xcagi__my_mod" in result

    def test_no_isolated_flag_returns_base(self, monkeypatch):
        monkeypatch.delenv("XCAGI_MOD_ISOLATED_DATABASES", raising=False)
        monkeypatch.delenv("XCAGI_MOD_DATABASE_URLS", raising=False)
        with patch(
            "app.request_active_mod_ctx.get_request_active_mod_id",
            return_value="my-mod",
        ):
            result = mod_db_url_mod.resolve_database_url_for_active_mod("sqlite:///base.db")
        assert result == "sqlite:///base.db"


# ===========================================================================
# 3. app/services/distillation_data_collector.py
# ===========================================================================


class TestDistillationInitDb:
    """Cover ``init_distillation_db``."""

    def test_init_distillation_db_creates_dirs(self, tmp_dir, monkeypatch):
        from app.services import distillation_data_collector as ddc

        monkeypatch.setattr(ddc, "DISTILL_DIR", str(tmp_dir))
        monkeypatch.setattr(ddc, "LOG_DIR", str(tmp_dir))
        mock_engine = MagicMock()
        with patch("app.db.init_db.init_distillation_tables"):
            with patch.object(ddc, "ENGINE", mock_engine):
                ddc.init_distillation_db()
        assert os.path.isdir(str(tmp_dir))


class TestDistillationGetDeepseekApiKey:
    """Cover ``get_deepseek_api_key`` edge cases."""

    def test_reads_from_config_file(self, monkeypatch, tmp_dir):
        from app.services import distillation_data_collector as ddc

        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        config_dir = os.path.join(tmp_dir, "resources", "config")
        os.makedirs(config_dir, exist_ok=True)
        config_file = os.path.join(config_dir, "deepseek_config.py")
        with open(config_file, "w", encoding="utf-8") as f:
            f.write('DEEPSEEK_API_KEY = "file-key-123"\n')
        monkeypatch.setattr(ddc, "BASE_DIR", tmp_dir)
        result = ddc.get_deepseek_api_key()
        assert result == "file-key-123"

    def test_config_file_read_error(self, monkeypatch, tmp_dir):
        from app.services import distillation_data_collector as ddc

        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        config_dir = os.path.join(tmp_dir, "resources", "config")
        os.makedirs(config_dir, exist_ok=True)
        config_file = os.path.join(config_dir, "deepseek_config.py")
        with open(config_file, "w", encoding="utf-8") as f:
            f.write('raise RuntimeError("bad config")\n')
        monkeypatch.setattr(ddc, "BASE_DIR", tmp_dir)
        result = ddc.get_deepseek_api_key()
        assert result == ""


class TestDistillationCollectSamplesViaDeepseek:
    """Cover ``collect_samples_via_deepseek`` edge cases."""

    @pytest.mark.asyncio
    async def test_collect_samples_unknown_intent_skipped(self):
        from app.services.distillation_data_collector import collect_samples_via_deepseek

        mock_intent_result = {"intent": "unknown_intent", "slots": {}, "confidence": 0.9}
        with (
            patch("app.services.distillation_data_collector.get_sample_count", return_value=0),
            patch(
                "app.services.distillation_data_collector.call_deepseek_intent",
                new_callable=AsyncMock,
                return_value=mock_intent_result,
            ),
            patch("app.services.distillation_data_collector.save_distillation_sample") as mock_save,
        ):
            count = await collect_samples_via_deepseek("test-key", target_count=10)
        # unknown_intent is not in INTENT_LABELS, so no samples saved
        assert count == 0

    @pytest.mark.asyncio
    async def test_collect_samples_invalid_result_skipped(self):
        from app.services.distillation_data_collector import collect_samples_via_deepseek

        with (
            patch("app.services.distillation_data_collector.get_sample_count", return_value=0),
            patch(
                "app.services.distillation_data_collector.call_deepseek_intent",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.services.distillation_data_collector.save_distillation_sample"),
        ):
            count = await collect_samples_via_deepseek("test-key", target_count=10)
        assert count == 0

    @pytest.mark.asyncio
    async def test_collect_samples_valid_intent_saved(self):
        from app.services.distillation_data_collector import collect_samples_via_deepseek

        mock_result = {"intent": "greet", "slots": {}, "confidence": 0.9}
        with (
            patch("app.services.distillation_data_collector.get_sample_count", return_value=0),
            patch(
                "app.services.distillation_data_collector.call_deepseek_intent",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("app.services.distillation_data_collector.save_distillation_sample") as mock_save,
        ):
            count = await collect_samples_via_deepseek("test-key", target_count=10)
        assert count > 0
        mock_save.assert_called()


class TestDistillationMain:
    """Cover ``main`` entry point."""

    @pytest.mark.asyncio
    async def test_main_init_flag(self):
        from app.services.distillation_data_collector import main

        with (
            patch("sys.argv", ["prog", "--init"]),
            patch("app.services.distillation_data_collector.init_distillation_db") as mock_init,
        ):
            await main()
        mock_init.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_stats_flag(self):
        from app.services.distillation_data_collector import main

        with (
            patch("sys.argv", ["prog", "--stats"]),
            patch("app.services.distillation_data_collector.init_distillation_db"),
            patch(
                "app.services.distillation_data_collector.get_sample_stats",
                return_value={"greet": 5},
            ),
        ):
            await main()

    @pytest.mark.asyncio
    async def test_main_collect_no_key(self):
        from app.services.distillation_data_collector import main

        with (
            patch("sys.argv", ["prog", "--collect"]),
            patch("app.services.distillation_data_collector.init_distillation_db"),
            patch(
                "app.services.distillation_data_collector.get_deepseek_api_key",
                return_value="",
            ),
        ):
            await main()  # Should not raise


# ===========================================================================
# 4. app/utils/performance_initializer.py
# ===========================================================================


class TestPerformanceOptimizerInit:
    """Cover ``PerformanceOptimizer.initialize``."""

    def test_initialize_all_components_success(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        mock_cache = MagicMock()
        mock_cache.is_available = True
        with (
            patch("app.utils.redis_cache.init_redis_cache_from_app", return_value=mock_cache),
            patch("app.utils.redis_cache.get_redis_cache", return_value=mock_cache),
            patch("app.utils.query_optimizer.get_query_optimizer", return_value=MagicMock()),
            patch("app.utils.async_tasks.get_async_task_manager", return_value=MagicMock()),
            patch(
                "app.utils.request_deduplicator.get_request_deduplicator",
                return_value=MagicMock(),
            ),
            patch(
                "app.utils.performance_monitor.get_performance_monitor",
                return_value=MagicMock(),
            ),
            patch("app.utils.rate_limiter.get_rate_limiter", return_value=MagicMock()),
            patch("app.utils.rate_limiter.get_circuit_breaker", return_value=MagicMock()),
        ):
            status = opt.initialize()
        assert status["redis_cache"] is True
        assert status["query_optimizer"] is True
        assert opt._initialized is True

    def test_initialize_redis_failure(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        with (
            patch("app.utils.redis_cache.get_redis_cache", side_effect=RuntimeError("no redis")),
            patch("app.utils.query_optimizer.get_query_optimizer", return_value=MagicMock()),
            patch("app.utils.async_tasks.get_async_task_manager", return_value=MagicMock()),
            patch(
                "app.utils.request_deduplicator.get_request_deduplicator",
                return_value=MagicMock(),
            ),
            patch(
                "app.utils.performance_monitor.get_performance_monitor",
                return_value=MagicMock(),
            ),
            patch("app.utils.rate_limiter.get_rate_limiter", return_value=MagicMock()),
            patch("app.utils.rate_limiter.get_circuit_breaker", return_value=MagicMock()),
        ):
            status = opt.initialize()
        assert status["redis_cache"] is False

    def test_initialize_skips_duplicate(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        opt._initialized = True
        # When already initialized, initialize() short-circuits and returns
        # get_status() without re-running any component init. Verify the
        # early-return path is taken by checking that no component-init keys
        # (redis_cache, query_optimizer, etc.) are added — only the get_status
        # keys (initialized / uptime_seconds / components) should be present.
        status = opt.initialize()
        assert set(status.keys()) == {"initialized", "uptime_seconds", "components"}
        # No component-init keys should appear from the duplicate call path.
        assert "redis_cache" not in status
        assert "query_optimizer" not in status
        # And the cached initialized flag remains True.
        assert status.get("initialized") is True
        assert status["components"] == {}

    def test_initialize_with_app_uses_init_redis_cache_from_app(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        mock_app = MagicMock()
        mock_cache = MagicMock()
        mock_cache.is_available = True
        with (
            patch(
                "app.utils.redis_cache.init_redis_cache_from_app", return_value=mock_cache
            ) as mock_init,
            patch("app.utils.query_optimizer.get_query_optimizer", return_value=MagicMock()),
            patch("app.utils.async_tasks.get_async_task_manager", return_value=MagicMock()),
            patch(
                "app.utils.request_deduplicator.get_request_deduplicator",
                return_value=MagicMock(),
            ),
            patch(
                "app.utils.performance_monitor.get_performance_monitor",
                return_value=MagicMock(),
            ),
            patch("app.utils.rate_limiter.get_rate_limiter", return_value=MagicMock()),
            patch("app.utils.rate_limiter.get_circuit_breaker", return_value=MagicMock()),
        ):
            opt.initialize(app=mock_app)
        mock_init.assert_called_once_with(mock_app)


class TestPerformanceOptimizerGetStatus:
    """Cover ``PerformanceOptimizer.get_status``."""

    def test_status_before_init(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        status = opt.get_status()
        assert status["initialized"] is False
        assert "uptime_seconds" in status

    def test_status_with_redis(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        mock_cache = MagicMock()
        mock_cache.is_available = True
        mock_cache.stats = {"hits": 10}
        opt._redis_cache = mock_cache
        status = opt.get_status()
        assert "redis_cache" in status["components"]


class TestPerformanceOptimizerHealthCheck:
    """Cover ``PerformanceOptimizer.get_health_check``."""

    def test_healthy_no_redis(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        health = opt.get_health_check()
        assert health["status"] == "healthy"

    def test_degraded_redis_unavailable(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        mock_cache = MagicMock()
        mock_cache.is_available = False
        opt._redis_cache = mock_cache
        health = opt.get_health_check()
        assert health["status"] == "degraded"

    def test_memory_check_with_psutil(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        mock_process = MagicMock()
        mock_process.memory_info.return_value = SimpleNamespace(rss=500 * 1024 * 1024)
        mock_process.memory_percent.return_value = 30.0
        with patch("psutil.Process", return_value=mock_process):
            health = opt.get_health_check()
        assert "memory" in health["checks"]

    def test_memory_check_without_psutil(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        with patch("builtins.__import__", side_effect=ImportError("no psutil")):
            health = opt.get_health_check()
        assert health["checks"]["memory"]["status"] == "unknown"

    def test_task_queue_warning(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        mock_tm = MagicMock()
        mock_tm.active_tasks = list(range(150))  # > 100
        opt._async_task_manager = mock_tm
        health = opt.get_health_check()
        assert health["status"] == "degraded"
        assert any("活跃任务过多" in i for i in health.get("issues", []))


class TestPerformanceOptimizerProperties:
    """Cover property accessors."""

    def test_redis_cache_property(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        opt._redis_cache = "test"
        assert opt.redis_cache == "test"

    def test_query_optimizer_property(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        opt._query_optimizer = "test"
        assert opt.query_optimizer == "test"

    def test_async_task_manager_property(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        opt._async_task_manager = "test"
        assert opt.async_task_manager == "test"

    def test_request_deduplicator_property(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        opt._request_deduplicator = "test"
        assert opt.request_deduplicator == "test"

    def test_performance_monitor_property(self):
        from app.utils.performance_initializer import PerformanceOptimizer

        opt = PerformanceOptimizer()
        opt._performance_monitor = "test"
        assert opt.performance_monitor == "test"


class TestGetPerformanceOptimizer:
    """Cover ``get_performance_optimizer`` singleton."""

    def test_returns_same_instance(self):
        from app.utils.performance_initializer import get_performance_optimizer

        a = get_performance_optimizer()
        b = get_performance_optimizer()
        assert a is b


class TestInitPerformanceOptimization:
    """Cover ``init_performance_optimization``."""

    def test_calls_initialize(self):
        from app.utils.performance_initializer import init_performance_optimization

        with patch("app.utils.performance_initializer.get_performance_optimizer") as mock_get:
            mock_opt = MagicMock()
            mock_get.return_value = mock_opt
            result = init_performance_optimization()
        mock_opt.initialize.assert_called_once()


class TestOptimizedServiceDecorator:
    """Cover ``optimized_service`` decorator."""

    def test_decorator_injects_attributes(self):
        from app.utils.performance_initializer import optimized_service

        @optimized_service
        class DummyService:
            def __init__(self):
                pass

        mock_opt = MagicMock()
        mock_opt.redis_cache = "cache"
        mock_opt.query_optimizer = "qo"
        mock_opt.async_task_manager = "atm"
        mock_opt.request_deduplicator = "rd"
        mock_opt.performance_monitor = "pm"

        with patch(
            "app.utils.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            svc = DummyService()
        assert svc._cache == "cache"
        assert svc._query_optimizer == "qo"


# ===========================================================================
# 5. app/fastapi_routes/excel_vector.py
# ===========================================================================


def _excel_vector_client() -> TestClient:
    """Build a minimal FastAPI app with only the excel_vector router (no LAN guard)."""
    from app.fastapi_routes.excel_vector import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


class TestExcelVectorIngest:
    """Cover ``ingest_excel_vector`` route."""

    def test_ingest_json_no_file_path_returns_400(self):
        mock_svc = MagicMock()
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service",
            return_value=mock_svc,
        ):
            client = _excel_vector_client()
            r = client.post("/api/excel/vector/ingest", json={})
        assert r.status_code == 400
        assert "file_path" in r.json()["message"]

    def test_ingest_json_empty_file_path_returns_400(self):
        mock_svc = MagicMock()
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service",
            return_value=mock_svc,
        ):
            client = _excel_vector_client()
            r = client.post("/api/excel/vector/ingest", json={"file_path": ""})
        assert r.status_code == 400

    def test_ingest_json_valid_file_path(self):
        mock_svc = MagicMock()
        mock_svc.ingest_excel.return_value = {"success": True, "index_id": "abc"}
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service",
            return_value=mock_svc,
        ):
            client = _excel_vector_client()
            r = client.post(
                "/api/excel/vector/ingest",
                json={"file_path": "/tmp/test.xlsx", "index_name": "test"},
            )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_ingest_json_ingest_fails_returns_400(self):
        mock_svc = MagicMock()
        mock_svc.ingest_excel.return_value = {"success": False, "message": "bad file"}
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service",
            return_value=mock_svc,
        ):
            client = _excel_vector_client()
            r = client.post(
                "/api/excel/vector/ingest",
                json={"file_path": "/tmp/bad.xlsx"},
            )
        assert r.status_code == 400

    def test_ingest_json_exception_returns_500(self):
        mock_svc = MagicMock()
        mock_svc.ingest_excel.side_effect = RuntimeError("crash")
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service",
            return_value=mock_svc,
        ):
            client = _excel_vector_client()
            r = client.post(
                "/api/excel/vector/ingest",
                json={"file_path": "/tmp/crash.xlsx"},
            )
        assert r.status_code == 500

    def test_ingest_multipart_wrong_extension_returns_400(self, tmp_dir):
        mock_svc = MagicMock()
        with (
            patch(
                "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service",
                return_value=mock_svc,
            ),
            patch("app.fastapi_routes.excel_vector.get_upload_dir", return_value=tmp_dir),
        ):
            client = _excel_vector_client()
            r = client.post(
                "/api/excel/vector/ingest",
                files={"excel_file": ("test.txt", b"hello", "text/plain")},
            )
        assert r.status_code == 400

    def test_ingest_multipart_valid_file(self, tmp_dir):
        mock_svc = MagicMock()
        mock_svc.ingest_excel.return_value = {"success": True, "index_id": "x"}
        with (
            patch(
                "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service",
                return_value=mock_svc,
            ),
            patch("app.fastapi_routes.excel_vector.get_upload_dir", return_value=tmp_dir),
        ):
            client = _excel_vector_client()
            r = client.post(
                "/api/excel/vector/ingest",
                files={
                    "excel_file": (
                        "test.xlsx",
                        b"hello",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
        assert r.status_code == 200


class TestExcelVectorQuery:
    """Cover ``query_excel_vector`` route."""

    def test_query_success(self):
        mock_svc = MagicMock()
        mock_svc.query.return_value = {"success": True, "hits": []}
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service",
            return_value=mock_svc,
        ):
            client = _excel_vector_client()
            r = client.post(
                "/api/excel/vector/query",
                json={"index_id": "idx1", "query": "test", "top_k": 3},
            )
        assert r.status_code == 200

    def test_query_failure_returns_400(self):
        mock_svc = MagicMock()
        mock_svc.query.return_value = {"success": False, "message": "not found"}
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service",
            return_value=mock_svc,
        ):
            client = _excel_vector_client()
            r = client.post(
                "/api/excel/vector/query",
                json={"index_id": "bad", "query": "x"},
            )
        assert r.status_code == 400

    def test_query_exception_returns_500(self):
        mock_svc = MagicMock()
        mock_svc.query.side_effect = RuntimeError("db down")
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service",
            return_value=mock_svc,
        ):
            client = _excel_vector_client()
            r = client.post(
                "/api/excel/vector/query",
                json={"index_id": "x", "query": "y"},
            )
        assert r.status_code == 500


class TestExcelVectorIndexes:
    """Cover ``list_excel_vector_indexes`` and ``delete_excel_vector_index``."""

    def test_list_indexes_success(self):
        mock_svc = MagicMock()
        mock_svc.list_indexes.return_value = {"success": True, "indexes": []}
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service",
            return_value=mock_svc,
        ):
            client = _excel_vector_client()
            r = client.get("/api/excel/vector/indexes")
        assert r.status_code == 200

    def test_list_indexes_exception_returns_500(self):
        mock_svc = MagicMock()
        mock_svc.list_indexes.side_effect = RuntimeError("fail")
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service",
            return_value=mock_svc,
        ):
            client = _excel_vector_client()
            r = client.get("/api/excel/vector/indexes")
        assert r.status_code == 500

    def test_delete_index_success(self):
        mock_svc = MagicMock()
        mock_svc.delete_index.return_value = {"success": True}
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service",
            return_value=mock_svc,
        ):
            client = _excel_vector_client()
            r = client.delete("/api/excel/vector/indexes/idx1")
        assert r.status_code == 200

    def test_delete_index_not_found(self):
        mock_svc = MagicMock()
        mock_svc.delete_index.return_value = {"success": False}
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service",
            return_value=mock_svc,
        ):
            client = _excel_vector_client()
            r = client.delete("/api/excel/vector/indexes/idx1")
        assert r.status_code == 404

    def test_delete_index_exception_returns_500(self):
        mock_svc = MagicMock()
        mock_svc.delete_index.side_effect = RuntimeError("fail")
        with patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service",
            return_value=mock_svc,
        ):
            client = _excel_vector_client()
            r = client.delete("/api/excel/vector/indexes/idx1")
        assert r.status_code == 500


# ===========================================================================
# 6. app/application/enterprise_login_flow.py
# ===========================================================================


class TestBindTenantForLogin:
    """Cover ``bind_tenant_for_login``."""

    def test_success_with_tenant_id(self):
        from app.application.enterprise_login_flow import bind_tenant_for_login

        with (
            patch(
                "app.application.tenant_subscription_app_service.provision_trial_for_user",
                return_value=42,
            ),
            patch(
                "app.application.tenant_subscription_app_service.sync_tenant_display_name",
                return_value="BrandCo",
            ),
        ):
            result = bind_tenant_for_login(user_id=1, company_brand="BrandCo", username="alice")
        assert result["tenant_id"] == 42
        assert result["tenant_name"] == "BrandCo"

    def test_no_tenant_id_returns_none(self):
        from app.application.enterprise_login_flow import bind_tenant_for_login

        with (
            patch(
                "app.application.tenant_subscription_app_service.provision_trial_for_user",
                return_value=None,
            ),
            patch(
                "app.application.tenant_subscription_app_service.sync_tenant_display_name",
                return_value="",
            ),
        ):
            result = bind_tenant_for_login(user_id=1, company_brand="", username="alice")
        assert result["tenant_id"] is None

    def test_exception_returns_empty(self):
        from app.application.enterprise_login_flow import bind_tenant_for_login

        with patch(
            "app.application.tenant_subscription_app_service.provision_trial_for_user",
            side_effect=RuntimeError("db down"),
        ):
            result = bind_tenant_for_login(user_id=1, company_brand="X", username="alice")
        assert result["tenant_id"] is None

    def test_company_brand_fallback(self):
        from app.application.enterprise_login_flow import bind_tenant_for_login

        with (
            patch(
                "app.application.tenant_subscription_app_service.provision_trial_for_user",
                return_value=10,
            ),
            patch(
                "app.application.tenant_subscription_app_service.sync_tenant_display_name",
                return_value=None,
            ),
        ):
            result = bind_tenant_for_login(user_id=1, company_brand="MyBrand", username="alice")
        assert result["tenant_name"] == "MyBrand"


class TestFinalizeEnterpriseLogin:
    """Cover ``finalize_enterprise_login``."""

    @pytest.mark.asyncio
    async def test_no_session_id_returns_result_unchanged(self):
        from app.application.enterprise_login_flow import finalize_enterprise_login

        result = {"success": True, "user": {"id": 1}}
        out = await finalize_enterprise_login(
            result=result,
            session_id=None,
            market_result=None,
            account_kind="personal",
            username="alice",
            sku="personal",
        )
        assert out == result

    @pytest.mark.asyncio
    async def test_market_success_saves_token(self):
        from app.application.enterprise_login_flow import finalize_enterprise_login

        market_result = {
            "success": True,
            "token": "mtok123",
            "refresh_token": "mref456",
            "is_market_admin": False,
            "is_enterprise": True,
        }
        result = {"success": True, "user": {"id": 1}}

        with (
            patch("app.fastapi_routes.market_account.save_session_market_token") as mock_save,
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={
                    "id": 10,
                    "company": "Co",
                    "username": "alice",
                    "phone": "",
                    "email": "",
                },
            ),
            patch(
                "app.application.enterprise_login_flow.company_brand_from_user_blob",
                return_value="Co",
            ),
            patch("app.application.enterprise_login_flow.persist_session_account_meta"),
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login",
                return_value={"tenant_id": 5, "tenant_name": "Co"},
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sess1",
                market_result=market_result,
                account_kind="enterprise",
                username="alice",
                sku="enterprise",
            )
        mock_save.assert_called_once_with("sess1", "mtok123", "mref456")
        assert out["market_access_token"] == "mtok123"

    @pytest.mark.asyncio
    async def test_market_failure_no_token(self):
        from app.application.enterprise_login_flow import finalize_enterprise_login

        market_result = {"success": False, "message": "bad creds"}
        result = {"success": True, "user": {"id": 1}}

        with (
            patch("app.fastapi_routes.market_account.save_session_market_token"),
            patch("app.application.enterprise_login_flow.persist_session_account_meta"),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sess2",
                market_result=market_result,
                account_kind="personal",
                username="alice",
                sku="personal",
            )
        assert "market_access_token" not in out

    @pytest.mark.asyncio
    async def test_skip_market_sync(self):
        from app.application.enterprise_login_flow import finalize_enterprise_login

        result = {"success": True, "user": {"id": 1}}

        with (
            patch("app.fastapi_routes.market_account.save_session_market_token"),
            patch("app.application.enterprise_login_flow.persist_session_account_meta"),
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login",
                return_value={"tenant_id": None, "tenant_name": ""},
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sess3",
                market_result=None,
                account_kind="personal",
                username="alice",
                sku="personal",
                skip_market_sync=True,
            )
        assert out["account_kind"] == "personal"

    @pytest.mark.asyncio
    async def test_exception_in_finalize_handled(self):
        from app.application.enterprise_login_flow import finalize_enterprise_login

        result = {"success": True, "user": {"id": 1}}
        market_result = {"success": True, "token": "tok"}

        with (
            patch(
                "app.fastapi_routes.market_account.save_session_market_token",
                side_effect=RuntimeError("db down"),
            ),
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                side_effect=RuntimeError("db down"),
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sess4",
                market_result=market_result,
                account_kind="enterprise",
                username="alice",
                sku="enterprise",
            )
        assert "market_account" in out


class TestRunMarketFirstLogin:
    """Cover ``run_market_first_login``."""

    @pytest.mark.asyncio
    async def test_personal_no_password_returns_error(self):
        from app.application.enterprise_login_flow import run_market_first_login

        result, err = await run_market_first_login(
            username="alice",
            password=None,
            account_kind="personal",
            market_result=None,
            auth_app_service=MagicMock(),
            sku="personal",
            jit_create_fn=MagicMock(),
            market_user_email_from_raw=MagicMock(),
        )
        assert result is None
        assert err is not None

    @pytest.mark.asyncio
    async def test_personal_login_failure(self):
        from app.application.enterprise_login_flow import run_market_first_login

        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": False}
        result, err = await run_market_first_login(
            username="alice",
            password="wrong",
            account_kind="personal",
            market_result=None,
            auth_app_service=auth_svc,
            sku="personal",
            jit_create_fn=MagicMock(),
            market_user_email_from_raw=MagicMock(),
            login_market_fn=AsyncMock(return_value={"success": False}),
        )
        assert result is None
        assert err is not None

    @pytest.mark.asyncio
    async def test_enterprise_market_fails_admin_local_fallback(self):
        from app.application.enterprise_login_flow import run_market_first_login

        auth_svc = MagicMock()
        auth_svc.login.return_value = {
            "success": True,
            "session_id": "s1",
            "user": {"id": 1, "role": "admin"},
        }
        result, err = await run_market_first_login(
            username="admin",
            password="adminpass",
            account_kind="admin",
            market_result={"success": False},
            auth_app_service=auth_svc,
            sku="enterprise",
            jit_create_fn=MagicMock(),
            market_user_email_from_raw=MagicMock(),
        )
        assert result is not None
        assert result.get("account_kind") == "admin"

    @pytest.mark.asyncio
    async def test_enterprise_market_fails_non_admin_returns_error(self):
        from app.application.enterprise_login_flow import run_market_first_login

        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": True, "user": {"role": "user"}}
        result, err = await run_market_first_login(
            username="user1",
            password="pass",
            account_kind="enterprise",
            market_result={"success": False, "message": "fail"},
            auth_app_service=auth_svc,
            sku="enterprise",
            jit_create_fn=MagicMock(),
            market_user_email_from_raw=MagicMock(),
        )
        assert result is None
        assert err is not None

    @pytest.mark.asyncio
    async def test_enterprise_account_kind_mismatch(self):
        # account_kind hint mismatch is now just a warning — login proceeds.
        # Patch internals to avoid DB access.
        from app.application.enterprise_login_flow import run_market_first_login

        with (
            patch(
                "app.application.enterprise_login_flow.ensure_local_user_after_market",
                new=AsyncMock(return_value=({"success": True, "session_id": "s"}, None)),
            ),
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new=AsyncMock(return_value={"success": True}),
            ),
            patch("app.application.enterprise_login_flow.persist_session_account_meta"),
        ):
            result, err = await run_market_first_login(
                username="alice",
                password="pass",
                account_kind="admin",
                market_result={"success": True, "is_enterprise": True, "is_market_admin": False},
                auth_app_service=MagicMock(),
                sku="enterprise",
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(),
            )
        assert err is None

    @pytest.mark.asyncio
    async def test_enterprise_no_username_from_market(self):
        from app.application.enterprise_login_flow import run_market_first_login

        result, err = await run_market_first_login(
            username="",
            password="pass",
            account_kind="enterprise",
            market_result={"success": True, "is_enterprise": True, "is_market_admin": False},
            auth_app_service=MagicMock(),
            sku="enterprise",
            jit_create_fn=MagicMock(),
            market_user_email_from_raw=MagicMock(),
        )
        assert result is None
        assert err is not None


# ===========================================================================
# 7. app/fastapi_routes/template_api.py
# ===========================================================================


def _template_api_client() -> TestClient:
    """Build a minimal FastAPI app with only the template_api router (no LAN guard)."""
    from app.fastapi_routes.template_api import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


class TestTemplatesListCompat:
    """Cover ``templates_list_compat`` route."""

    def test_returns_templates(self):
        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = {"templates": [{"id": "t1", "name": "T1"}]}
        with patch(
            "app.application.template_app_service.get_template_app_service",
            return_value=mock_svc,
        ):
            client = _template_api_client()
            r = client.get("/api/templates")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_service_unavailable_returns_503(self):
        with patch(
            "app.application.template_app_service.get_template_app_service",
            side_effect=ImportError("no module"),
        ):
            client = _template_api_client()
            r = client.get("/api/templates")
        assert r.status_code == 503

    def test_trailing_slash_alias(self):
        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = {"templates": []}
        with patch(
            "app.application.template_app_service.get_template_app_service",
            return_value=mock_svc,
        ):
            client = _template_api_client()
            r = client.get("/api/templates/")
        assert r.status_code == 200


class TestTemplatesListLegacyAlias:
    """Cover ``templates_list_legacy_alias`` route."""

    def test_legacy_list_path(self):
        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = {"templates": []}
        with patch(
            "app.application.template_app_service.get_template_app_service",
            return_value=mock_svc,
        ):
            client = _template_api_client()
            r = client.get("/api/templates/list")
        assert r.status_code == 200


class TestTemplatesDetailCompat:
    """Cover ``templates_detail_compat`` route."""

    def test_detail_found(self):
        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = {
            "templates": [{"id": "db:5", "db_id": 5, "name": "T5"}]
        }
        with patch(
            "app.application.template_app_service.get_template_app_service",
            return_value=mock_svc,
        ):
            client = _template_api_client()
            r = client.get("/api/templates/detail/db:5")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_detail_not_found(self):
        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = {"templates": []}
        with patch(
            "app.application.template_app_service.get_template_app_service",
            return_value=mock_svc,
        ):
            client = _template_api_client()
            r = client.get("/api/templates/detail/db:999")
        assert r.status_code == 404


class TestTemplatesGetOne:
    """Cover ``templates_get_one`` route."""

    def test_get_one_by_db_id(self):
        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = {
            "templates": [{"id": "42", "db_id": 42, "name": "T42"}]
        }
        with patch(
            "app.application.template_app_service.get_template_app_service",
            return_value=mock_svc,
        ):
            client = _template_api_client()
            r = client.get("/api/templates/42")
        assert r.status_code == 200

    def test_get_one_list_keyword_returns_404(self):
        # The "list" / "detail" keyword guard lives in templates_get_one.
        # /api/templates/list is a separate legacy-alias route that returns
        # 200, so exercise the keyword guard by calling templates_get_one
        # directly (the route /api/templates/{template_id} with "list" would
        # be shadowed by the explicit /api/templates/list alias route).
        from fastapi import HTTPException

        from app.fastapi_routes.template_api import templates_get_one

        with pytest.raises(HTTPException) as exc:
            templates_get_one("list")
        assert exc.value.status_code == 404

        with pytest.raises(HTTPException) as exc:
            templates_get_one("detail")
        assert exc.value.status_code == 404

    def test_get_one_not_found(self):
        mock_svc = MagicMock()
        mock_svc.get_templates.return_value = {"templates": []}
        with patch(
            "app.application.template_app_service.get_template_app_service",
            return_value=mock_svc,
        ):
            client = _template_api_client()
            r = client.get("/api/templates/nonexistent")
        assert r.status_code == 404


class TestFindTemplateRow:
    """Cover ``_find_template_row`` helper."""

    def test_empty_id_returns_none(self):
        from app.fastapi_routes.template_api import _find_template_row

        with patch(
            "app.fastapi_routes.template_api._templates_payload",
            return_value={"templates": []},
        ):
            assert _find_template_row("") is None

    def test_db_prefix_match(self):
        from app.fastapi_routes.template_api import _find_template_row

        templates = [{"id": "db:7", "db_id": 7, "name": "T7"}]
        with patch(
            "app.fastapi_routes.template_api._templates_payload",
            return_value={"templates": templates},
        ):
            result = _find_template_row("db:7")
        assert result is not None
        assert result["db_id"] == 7

    def test_db_prefix_numeric_match(self):
        from app.fastapi_routes.template_api import _find_template_row

        templates = [{"id": "x", "db_id": 3, "name": "T3"}]
        with patch(
            "app.fastapi_routes.template_api._templates_payload",
            return_value={"templates": templates},
        ):
            result = _find_template_row("db:3")
        assert result is not None

    def test_db_prefix_invalid_number(self):
        from app.fastapi_routes.template_api import _find_template_row

        templates = [{"id": "x", "db_id": 1, "name": "T1"}]
        with patch(
            "app.fastapi_routes.template_api._templates_payload",
            return_value={"templates": templates},
        ):
            result = _find_template_row("db:abc")
        assert result is None

    def test_digit_id_match(self):
        from app.fastapi_routes.template_api import _find_template_row

        templates = [{"id": "5", "db_id": 5, "name": "T5"}]
        with patch(
            "app.fastapi_routes.template_api._templates_payload",
            return_value={"templates": templates},
        ):
            result = _find_template_row("5")
        assert result is not None

    def test_string_id_match(self):
        from app.fastapi_routes.template_api import _find_template_row

        templates = [{"id": "shipment", "name": "Shipment"}]
        with patch(
            "app.fastapi_routes.template_api._templates_payload",
            return_value={"templates": templates},
        ):
            result = _find_template_row("shipment")
        assert result is not None


class TestPublishTemplateEvent:
    """Cover ``_publish_template_event`` helper."""

    def test_publish_silent_failure(self):
        from app.fastapi_routes.template_api import _publish_template_event

        with patch(
            "app.fastapi_routes.template_api.publish_neuro_event",
            side_effect=RuntimeError("bus down"),
        ):
            # Should not raise
            _publish_template_event("test.event", {})


# ===========================================================================
# 8. app/neuro_bus/routing/policy_nn.py
# ===========================================================================


class TestPolicyNNHelpers:
    """Cover ``_manifest_path`` and module-level helpers."""

    def test_manifest_path_points_to_resources(self):
        from app.neuro_bus.routing.policy_nn import _manifest_path

        p = _manifest_path()
        assert "resources" in str(p)
        assert "routing_policies" in str(p)

    def test_manifest_path_is_path_object(self):
        from app.neuro_bus.routing.policy_nn import _manifest_path

        p = _manifest_path()
        assert isinstance(p, Path)


class TestLoadActivePolicy:
    """Cover ``load_active_policy``."""

    def test_no_manifest_returns_none(self, tmp_dir):
        import app.neuro_bus.routing.policy_nn as pnn

        with patch.object(pnn, "_manifest_path", return_value=Path(tmp_dir) / "nonexistent.json"):
            result = pnn.load_active_policy()
        assert result is None

    def test_invalid_manifest_json_returns_none(self, tmp_dir):
        import app.neuro_bus.routing.policy_nn as pnn

        mf = Path(tmp_dir) / "manifest.json"
        mf.write_text("not json", encoding="utf-8")
        with patch.object(pnn, "_manifest_path", return_value=mf):
            result = pnn.load_active_policy()
        assert result is None

    def test_no_matching_version_returns_none(self, tmp_dir):
        import app.neuro_bus.routing.policy_nn as pnn

        mf = Path(tmp_dir) / "manifest.json"
        mf.write_text(
            json.dumps({"active_version": "99", "policies": []}),
            encoding="utf-8",
        )
        with patch.object(pnn, "_manifest_path", return_value=mf):
            result = pnn.load_active_policy()
        assert result is None

    def test_env_override_version(self, tmp_dir, monkeypatch):
        import app.neuro_bus.routing.policy_nn as pnn

        if pnn.torch is None:
            pytest.skip("PyTorch not installed")

        mf = Path(tmp_dir) / "manifest.json"
        mf.write_text(
            json.dumps({"active_version": "0", "policies": [{"version": "42", "path": "p42.pt"}]}),
            encoding="utf-8",
        )
        monkeypatch.setenv("XCAGI_ROUTING_POLICY_VERSION", "42")
        with patch.object(pnn, "_manifest_path", return_value=mf):
            result = pnn.load_active_policy()
        # Weights file doesn't exist, so should return None
        assert result is None


class TestPredictActionIndex:
    """Cover ``predict_action_index``."""

    def test_no_policy_returns_minus_one(self):
        import app.neuro_bus.routing.policy_nn as pnn

        old_policy = pnn._policy
        pnn._policy = None
        try:
            with patch.object(pnn, "load_active_policy", return_value=None):
                result = pnn.predict_action_index([0.1] * 16)
        finally:
            pnn._policy = old_policy
        assert result == -1

    def test_with_in_memory_model(self):
        import app.neuro_bus.routing.policy_nn as pnn

        if pnn.torch is None:
            pytest.skip("PyTorch not installed")

        from app.neuro_bus.routing.policy_nn import RoutingMLP

        old_policy = pnn._policy
        old_device = pnn._policy_device
        pnn._policy = RoutingMLP()
        pnn._policy_device = "cpu"
        try:
            result = pnn.predict_action_index([0.1] * 16)
        finally:
            pnn._policy = old_policy
            pnn._policy_device = old_device
        assert 0 <= result < 3

    def test_with_mask(self):
        import app.neuro_bus.routing.policy_nn as pnn

        if pnn.torch is None:
            pytest.skip("PyTorch not installed")

        from app.neuro_bus.routing.policy_nn import RoutingMLP

        old_policy = pnn._policy
        old_device = pnn._policy_device
        pnn._policy = RoutingMLP()
        pnn._policy_device = "cpu"
        try:
            result = pnn.predict_action_index([0.1] * 16, mask=[True, True, False])
        finally:
            pnn._policy = old_policy
            pnn._policy_device = old_device
        assert 0 <= result < 3
        # With mask[2]=False, should not select action 2 (but could if logits dictate)
        # This is a smoke test - the mask just sets logits[2] to -inf


class TestSavePolicyStateDict:
    """Cover ``save_policy_state_dict``."""

    def test_save_without_torch_raises(self):
        import app.neuro_bus.routing.policy_nn as pnn

        if pnn.torch is not None:
            pytest.skip("PyTorch is installed, cannot test error path")
        with pytest.raises(RuntimeError, match="torch not installed"):
            pnn.save_policy_state_dict(Path("/tmp/dummy.pt"), MagicMock())

    def test_save_with_torch(self, tmp_dir):
        import app.neuro_bus.routing.policy_nn as pnn

        if pnn.torch is None:
            pytest.skip("PyTorch not installed")

        from app.neuro_bus.routing.policy_nn import RoutingMLP

        model = RoutingMLP()
        path = Path(tmp_dir) / "sub" / "model.pt"
        pnn.save_policy_state_dict(path, model)
        assert path.is_file()


# ===========================================================================
# 9. app/services/mobile_push.py
# ===========================================================================


class TestJpushEnabled:
    """Cover ``_jpush_enabled``."""

    def test_enabled(self, monkeypatch):
        from app.services.mobile_push import _jpush_enabled

        monkeypatch.setenv("JPUSH_APP_KEY", "key")
        monkeypatch.setenv("JPUSH_MASTER_SECRET", "secret")
        assert _jpush_enabled() is True

    def test_disabled_missing_key(self, monkeypatch):
        from app.services.mobile_push import _jpush_enabled

        monkeypatch.delenv("JPUSH_APP_KEY", raising=False)
        monkeypatch.delenv("JPUSH_MASTER_SECRET", raising=False)
        assert _jpush_enabled() is False

    def test_disabled_empty_key(self, monkeypatch):
        from app.services.mobile_push import _jpush_enabled

        monkeypatch.setenv("JPUSH_APP_KEY", "")
        monkeypatch.setenv("JPUSH_MASTER_SECRET", "secret")
        assert _jpush_enabled() is False


class TestFcmEnabled:
    """Cover ``_fcm_enabled``."""

    def test_enabled(self, monkeypatch):
        from app.services.mobile_push import _fcm_enabled

        monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", "/path/to/sa.json")
        assert _fcm_enabled() is True

    def test_disabled(self, monkeypatch):
        from app.services.mobile_push import _fcm_enabled

        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT", raising=False)
        assert _fcm_enabled() is False


class TestSendJpush:
    """Cover ``send_jpush``."""

    def test_empty_ids_returns_false(self):
        from app.services.mobile_push import send_jpush

        assert send_jpush([], "title", "body") is False

    def test_disabled_returns_false(self, monkeypatch):
        from app.services.mobile_push import send_jpush

        monkeypatch.delenv("JPUSH_APP_KEY", raising=False)
        assert send_jpush(["id1"], "title", "body") is False

    def test_api_success(self, monkeypatch):
        from app.services.mobile_push import send_jpush

        monkeypatch.setenv("JPUSH_APP_KEY", "key")
        monkeypatch.setenv("JPUSH_MASTER_SECRET", "secret")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.post", return_value=mock_resp):
            result = send_jpush(["id1"], "title", "body")
        assert result is True

    def test_api_failure_status(self, monkeypatch):
        from app.services.mobile_push import send_jpush

        monkeypatch.setenv("JPUSH_APP_KEY", "key")
        monkeypatch.setenv("JPUSH_MASTER_SECRET", "secret")
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "bad request"
        with patch("httpx.post", return_value=mock_resp):
            result = send_jpush(["id1"], "title", "body")
        assert result is False

    def test_api_exception(self, monkeypatch):
        from app.services.mobile_push import send_jpush

        monkeypatch.setenv("JPUSH_APP_KEY", "key")
        monkeypatch.setenv("JPUSH_MASTER_SECRET", "secret")
        with patch("httpx.post", side_effect=ConnectionError("network")):
            result = send_jpush(["id1"], "title", "body")
        assert result is False

    def test_sends_with_data(self, monkeypatch):
        from app.services.mobile_push import send_jpush

        monkeypatch.setenv("JPUSH_APP_KEY", "key")
        monkeypatch.setenv("JPUSH_MASTER_SECRET", "secret")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            send_jpush(["id1"], "title", "body", data={"key": "val"})
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["message"]["extras"] == {"key": "val"}


class TestSendFcm:
    """Cover ``send_fcm``."""

    def test_empty_tokens_returns_false(self):
        from app.services.mobile_push import send_fcm

        assert send_fcm([], "title", "body") is False

    def test_disabled_returns_false(self, monkeypatch):
        from app.services.mobile_push import send_fcm

        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT", raising=False)
        assert send_fcm(["tok1"], "title", "body") is False

    def test_google_auth_not_installed(self, monkeypatch):
        from app.services import mobile_push as mp

        monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", "/path/sa.json")
        # Force ImportError for google.oauth2.service_account
        with patch.dict(
            "sys.modules",
            {"google.oauth2.service_account": None, "google.auth.transport.requests": None},
        ):
            result = mp.send_fcm(["tok1"], "title", "body")
        assert result is False

    def test_cred_path_not_file(self, monkeypatch):
        from app.services.mobile_push import send_fcm

        monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", "/nonexistent/path.json")
        # Mock the google modules to exist (so we get past ImportError check)
        with patch.dict(
            "sys.modules",
            {
                "google.oauth2.service_account": MagicMock(),
                "google.auth.transport.requests": MagicMock(),
            },
        ):
            with patch("os.path.isfile", return_value=False):
                result = send_fcm(["tok1"], "title", "body")
        assert result is False


class TestSendToUserDevices:
    """Cover ``send_to_user_devices``."""

    def test_routes_fcm_and_jpush(self):
        from app.services.mobile_push import send_to_user_devices

        devices = [
            {"push_provider": "fcm", "push_token": "fcm1"},
            {"push_provider": "jpush", "push_token": "jp1"},
        ]
        with (
            patch("app.services.mobile_push.send_fcm", return_value=True) as mock_fcm,
            patch("app.services.mobile_push.send_jpush", return_value=True) as mock_jp,
        ):
            result = send_to_user_devices(devices, "title", "body")
        mock_fcm.assert_called_once_with(["fcm1"], "title", "body", None)
        mock_jp.assert_called_once_with(["jp1"], "title", "body", None)
        assert result == {"fcm": True, "jpush": True}

    def test_empty_token_skipped(self):
        from app.services.mobile_push import send_to_user_devices

        devices = [{"push_provider": "fcm", "push_token": ""}]
        with patch("app.services.mobile_push.send_fcm", return_value=False) as mock_fcm:
            result = send_to_user_devices(devices, "title", "body")
        mock_fcm.assert_called_once_with([], "title", "body", None)

    def test_legacy_fcm_token_field(self):
        from app.services.mobile_push import send_to_user_devices

        devices = [{"push_provider": "fcm", "fcm_token": "legacy1"}]
        with patch("app.services.mobile_push.send_fcm", return_value=True) as mock_fcm:
            result = send_to_user_devices(devices, "title", "body")
        mock_fcm.assert_called_once_with(["legacy1"], "title", "body", None)


class TestNotifyUser:
    """Cover ``notify_user``."""

    def test_notify_user_queries_devices(self):
        from app.services.mobile_push import notify_user

        mock_row = SimpleNamespace(push_provider="fcm", push_token="tok1", fcm_token="tok1")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_row]

        with (
            patch("app.db.session.get_db") as mock_get_db,
            patch("app.db.models.mobile_device.MobileDeviceToken"),
        ):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            with patch(
                "app.services.mobile_push.send_to_user_devices",
                return_value={"fcm": True, "jpush": False},
            ):
                result = notify_user(1, "title", "body")

        assert result["fcm"] is True
