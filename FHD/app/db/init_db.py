"""Public database initialization API and per-call dependency composition.

Runtime operations live in semantic bootstrap components. Keep this module's
functions as late-bound patch points for startup, tests and desktop integrations.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Table
from sqlalchemy.engine import Engine

from app.db.base import Base
from app.db.bootstrap import locations, seeding
from app.legacy.db.bootstrap import legacy_tables
from app.db.bootstrap.column_repairs import LegacyColumnRepairs
from app.db.bootstrap.engine_selection import EngineSelection
from app.db.bootstrap.im_migration import ensure_message_provenance
from app.legacy.db.bootstrap.legacy_tables import TemplateTables
from app.db.bootstrap.orm_tables import GroupName, OrmBootstrap, table_group
from app.db.bootstrap.postgres_auth import PostgresAuthBootstrap
from app.db.bootstrap.runtime import RuntimeBootstrap
from app.db.etl_bootstrap import ensure_sqlite_etl_bootstrap as ensure_sqlite_etl_bootstrap
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.external_sqlite import sqlite_conn
from app.utils.path_io.path_utils import get_app_data_dir, get_base_dir, get_resource_path

logger = logging.getLogger(__name__)
DEFAULT_DB_FILES: tuple[str, ...] = (
    "products.db",
    "inventory.db",
    "voice_learning.db",
    "error_collection.db",
)
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def _orm_table(model: type[Base]) -> Table:
    return cast(Table, model.__table__)


def _engine_selection() -> EngineSelection:
    from app.db import _create_engine_for_url, _get_engine

    return EngineSelection(_create_engine_for_url, _get_engine, logger)


def _orm_bootstrap() -> OrmBootstrap:
    from sqlalchemy import inspect

    return OrmBootstrap(Base.metadata, inspect, logger)


def _column_repairs() -> LegacyColumnRepairs:
    from sqlalchemy import inspect

    return LegacyColumnRepairs(inspect, logger)


def _template_tables() -> TemplateTables:
    from sqlalchemy import inspect

    return TemplateTables(sqlite_conn, inspect)


def _database_files() -> locations.DatabaseFiles:
    return locations.DatabaseFiles(
        get_app_data_dir, _iter_seed_dirs, sqlite_conn, shutil.copy2, logger
    )


def _is_desktop_mode_env() -> bool:
    return (os.environ.get("XCAGI_DESKTOP_MODE") or "").strip().lower() in _TRUTHY_ENV_VALUES


def refresh_config_database_urls(config: Any | None = None) -> None:
    if config is not None:
        for name in ("DATABASE_URL", "VECTOR_DB_URL", "DATABASE_PATH"):
            value = os.environ.get(name)
            if value:
                setattr(config, name, value)


def _desktop_data_root(data_dir: str | None = None) -> Path:
    return locations.desktop_data_root(data_dir, os.environ, get_app_data_dir)


def _ensure_sqlite_business_tables(db_path: Path) -> None:
    locations.create_desktop_business_tables(db_path, sqlite3.connect)


def ensure_desktop_sqlite_business_tables_all_files(data_dir: str | None = None) -> None:
    locations.ensure_desktop_files(_desktop_data_root(data_dir), _ensure_sqlite_business_tables)


def ensure_runtime_database_environment() -> str:
    def refresh() -> None:
        from app.config import Config

        refresh_config_database_urls(Config)

    return locations.select_environment(
        desktop=_is_desktop_mode_env(),
        environment=os.environ,
        root=_desktop_data_root,
        ensure_tables=ensure_desktop_sqlite_business_tables_all_files,
        refresh_config=refresh,
    )


def _iter_seed_dirs() -> Iterable[str]:
    yield get_resource_path("db_seed")
    yield get_base_dir()
    if hasattr(sys, "_MEIPASS"):
        yield sys._MEIPASS


def initialize_databases(db_files: Iterable[str] = DEFAULT_DB_FILES) -> None:
    _database_files().initialize(db_files)


def ensure_sqlite_per_mod_database_copies(
    mod_ids: Sequence[str], db_files: Iterable[str] = DEFAULT_DB_FILES
) -> None:
    _database_files().copy_for_mods(mod_ids, db_files)


def build_mod_database_seed_plan() -> dict[str, Any]:
    work_dir = get_app_data_dir()
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        manager = get_mod_manager()
        mods = manager.list_loaded_mods() or manager.scan_mods()
    except RECOVERABLE_ERRORS:
        mods = []
    return locations.build_mod_seed_plan(work_dir, mods)


def get_db_path(db_name: str = "products.db") -> str:
    from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix
    from app.request_active_mod_ctx import get_request_active_mod_id

    mod_id = get_request_active_mod_id()
    filename = sqlite_filename_with_mod_suffix(db_name, mod_id) if mod_id else db_name
    return os.path.join(get_app_data_dir(), filename)


def get_distillation_db_path() -> str:
    return get_db_path("distillation.db")


def init_distillation_tables(engine: Engine) -> None:
    legacy_tables.init_distillation_tables(engine)


def init_extract_logs_tables(engine: Engine) -> None:
    legacy_tables.init_extract_logs_tables(engine)


def init_template_tables(db_path: str | None = None) -> None:
    _template_tables().init_template_tables(db_path or get_db_path("products.db"))


def init_template_tables_for_engine(engine: Engine) -> None:
    _template_tables().init_template_tables_for_engine(engine)


def _resolve_auth_bootstrap_engine(
    engine: Engine | None = None, *, database_url: str | None = None
) -> Engine | None:
    return _engine_selection().for_auth(engine, database_url)


def _seed_default_admin_user(real_engine: Engine) -> None:
    seeding.seed_admin(
        real_engine,
        environment=os.environ,
        logger=logger,
        prepare_profile=ensure_user_profile_columns,
    )


def _seed_sqlite_rbac_defaults(real_engine: Engine) -> None:
    seeding.seed_rbac(real_engine, logger=logger)


def _ensure_orm_group(
    group: GroupName,
    engine: Engine | None,
    database_url: str | None,
    swallow_errors: bool,
    *,
    seed: Callable[[Engine], None] | None = None,
) -> None:
    selected = table_group(group, _orm_table)
    real_engine = _resolve_auth_bootstrap_engine(engine, database_url=database_url)
    _orm_bootstrap().ensure(
        real_engine,
        selected,
        swallow_errors=swallow_errors,
        seed=seed,
    )


def ensure_sqlite_auth_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    _ensure_orm_group("auth", engine, database_url, swallow_errors, seed=_seed_default_admin_user)


def ensure_sqlite_rbac_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    _ensure_orm_group("rbac", engine, database_url, swallow_errors, seed=_seed_sqlite_rbac_defaults)


def ensure_sqlite_inventory_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    _ensure_orm_group("inventory", engine, database_url, swallow_errors)


def ensure_sqlite_enterprise_business_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    _ensure_orm_group("enterprise", engine, database_url, swallow_errors)


def ensure_user_preferences_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    _ensure_orm_group("preferences", engine, database_url, swallow_errors)


def ensure_neuro_event_log_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    _ensure_orm_group("neuro", engine, database_url, swallow_errors)


def ensure_sqlite_im_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    _ensure_orm_group("im", engine, database_url, swallow_errors)


def ensure_employee_run_log_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    _ensure_orm_group("employee", engine, database_url, swallow_errors)


def ensure_ai_conversation_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    _ensure_orm_group("conversations", engine, database_url, swallow_errors)


def ensure_mobile_push_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    _ensure_orm_group("mobile", engine, database_url, swallow_errors)


def ensure_erp_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    _ensure_orm_group("erp", engine, database_url, swallow_errors)


def ensure_postgresql_auth_bootstrap(
    engine: Engine | None = None, *, database_url: str | None = None
) -> None:
    from sqlalchemy import inspect

    real_engine = _resolve_auth_bootstrap_engine(engine, database_url=database_url)
    PostgresAuthBootstrap(inspect, _seed_default_admin_user, logger).ensure(real_engine)


def ensure_runtime_auth_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = False,
) -> None:
    from app.fastapi_app.sqlite_paths import is_sqlite_url, resolve_effective_database_url

    RuntimeBootstrap(
        sqlite_start=(
            ensure_sqlite_auth_bootstrap,
            ensure_sqlite_rbac_bootstrap,
            ensure_sqlite_inventory_bootstrap,
            ensure_sqlite_enterprise_business_bootstrap,
        ),
        postgres_start=ensure_postgresql_auth_bootstrap,
        common=(
            ensure_user_preferences_bootstrap,
            ensure_neuro_event_log_bootstrap,
            ensure_sqlite_im_bootstrap,
            ensure_employee_run_log_bootstrap,
            ensure_ai_conversation_bootstrap,
            ensure_mobile_push_bootstrap,
        ),
        sqlite_etl=ensure_sqlite_etl_bootstrap,
        erp=ensure_erp_bootstrap,
        effective_url=resolve_effective_database_url,
        is_sqlite=is_sqlite_url,
    ).run(engine, database_url, swallow_errors)


def _repair_columns(
    operation: Callable[[Engine], None],
    purpose: str,
    engine: Engine | None,
    database_url: str | None,
) -> None:
    selected = _engine_selection().for_columns(engine, database_url, purpose=purpose)
    if selected is not None:
        operation(selected)


def ensure_sessions_market_access_token_column(
    engine: Engine | None = None, *, database_url: str | None = None
) -> None:
    _repair_columns(
        _column_repairs().ensure_sessions_market_access_token_column,
        "sessions.market_access_token",
        engine,
        database_url,
    )


def ensure_sessions_market_refresh_token_column(
    engine: Engine | None = None, *, database_url: str | None = None
) -> None:
    _repair_columns(
        _column_repairs().ensure_sessions_market_refresh_token_column,
        "sessions.market_refresh_token",
        engine,
        database_url,
    )


def ensure_sessions_enterprise_entitlement_columns(
    engine: Engine | None = None, *, database_url: str | None = None
) -> None:
    _repair_columns(
        _column_repairs().ensure_sessions_enterprise_entitlement_columns,
        "sessions 企业权益列",
        engine,
        database_url,
    )


def ensure_sessions_account_meta_columns(
    engine: Engine | None = None, *, database_url: str | None = None
) -> None:
    _repair_columns(
        _column_repairs().ensure_sessions_account_meta_columns,
        "sessions 账号元数据列",
        engine,
        database_url,
    )


def ensure_users_tenant_id_column(
    engine: Engine | None = None, *, database_url: str | None = None
) -> None:
    _repair_columns(
        _column_repairs().ensure_users_tenant_id_column, "users.tenant_id", engine, database_url
    )


def ensure_business_tenant_id_columns(
    engine: Engine | None = None, *, database_url: str | None = None
) -> None:
    _repair_columns(
        _column_repairs().ensure_business_tenant_id_columns,
        "业务表 tenant_id",
        engine,
        database_url,
    )


def ensure_user_profile_columns(
    engine: Engine | None = None, *, database_url: str | None = None
) -> None:
    _repair_columns(
        _column_repairs().ensure_user_profile_columns,
        "users.tier/industry_id",
        engine,
        database_url,
    )


def ensure_im_customer_service_columns(engine: Engine) -> None:
    from sqlalchemy import inspect

    ensure_message_provenance(engine, inspect, logger)


def init_im_tables(engine: Engine | None = None, *, database_url: str | None = None) -> None:
    real_engine = _engine_selection().required(engine, database_url)
    _orm_bootstrap().create(
        real_engine, table_group("im", _orm_table), label="IM", swallow_errors=False
    )
    ensure_im_customer_service_columns(real_engine)


def _init_runtime_tables(group: GroupName, engine: Engine, *, label: str) -> Engine:
    selected = table_group(group, _orm_table)
    real_engine = _engine_selection().prefer_current(engine)
    _orm_bootstrap().create(real_engine, selected, label=label, swallow_errors=True)
    return real_engine


def init_approval_tables(engine: Engine) -> None:
    real_engine = _init_runtime_tables("approval", engine, label="approval")
    _column_repairs().init_approval_tables(real_engine)


def ensure_product_query_indexes(engine: Engine) -> None:
    _column_repairs().ensure_product_query_indexes(engine)


def init_service_bridge_tables(engine: Engine) -> None:
    _init_runtime_tables("bridge", engine, label="service_bridge")


def init_persona_tables(engine: Engine) -> None:
    _init_runtime_tables("persona", engine, label="persona")
