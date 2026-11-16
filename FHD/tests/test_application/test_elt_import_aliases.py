"""Runtime code uses ELT names only; leftover ETL data/config must be upgraded explicitly."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.application.elt_env import LegacyEltEnvError, reject_legacy_elt_env
from tests.test_services.test_erp_schema_migration import _alembic_config
from tests.test_services.test_erp_schema_migration import _db_url as _db_url


def test_retired_etl_modules_are_not_importable():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.application.shipment_excel_etl_ocr")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.compat.elt_import_aliases")


def test_legacy_etl_permission_code_is_not_an_alias():
    from app.domain.shared_services.auth_service import AuthService

    service = AuthService()
    service.get_user_permissions = lambda _user: ["elt.read", "elt.execute"]
    user = SimpleNamespace(role="user", tier="user", tenant_id=1)
    with patch("app.db.bootstrap.guarded.enabled", return_value=False):
        assert service.has_permission(user, "elt.execute") is True
        assert service.has_permission(user, "etl.execute") is False


def test_legacy_etl_env_is_rejected(monkeypatch):
    monkeypatch.setenv("FHD_SHIPMENT_ETL_LLM", "auto")
    with pytest.raises(LegacyEltEnvError, match="FHD_SHIPMENT_ETL_LLM → FHD_SHIPMENT_ELT_LLM"):
        reject_legacy_elt_env()


def test_empty_upgrade_has_only_elt_run_tables(_db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _db_url)
    command.upgrade(_alembic_config(), "head")
    engine = create_engine(_db_url)
    try:
        names = set(inspect(engine).get_table_names())
        assert "elt_run_rows" in names
        assert "etl_run_rows" not in names
        if "permissions" in names:
            codes = list(engine.connect().execute(text("SELECT code FROM permissions")).scalars())
            assert all(not str(code).startswith("etl.") for code in codes)
        heads = list(
            engine.connect().execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
        assert heads == ["2026_11_16_elt_permission_cutover"]
    finally:
        engine.dispose()


def test_cutover_migrates_leftover_etl_permission_rows(_db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _db_url)
    cfg = _alembic_config()
    command.upgrade(cfg, "2026_11_16_merge_persona_delivery")
    engine = create_engine(_db_url)
    try:
        with engine.begin() as connection:
            if "permissions" not in set(inspect(connection).get_table_names()):
                pytest.skip("permissions table not present on this upgrade path")
            connection.execute(
                text(
                    "INSERT INTO permissions (name, code, description, module) "
                    "VALUES ('旧读取', 'etl.read', 'legacy', 'etl')"
                )
            )
        command.upgrade(cfg, "head")
        with engine.connect() as connection:
            codes = list(connection.execute(text("SELECT code FROM permissions")).scalars())
            modules = list(
                connection.execute(
                    text("SELECT module FROM permissions WHERE code = 'elt.read'")
                ).scalars()
            )
        assert "etl.read" not in codes
        assert "elt.read" in codes
        assert modules
        assert modules[0] != "etl"
    finally:
        engine.dispose()
