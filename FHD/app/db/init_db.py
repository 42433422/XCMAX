"""
XCAGI 数据库路径与初始化入口（应用内）。

目标：
- 让 app/* 不再依赖仓库根目录 db.py
- 兼容 PyInstaller（_MEIPASS）与开发环境
- 支持从 resources/db_seed 复制初始 sqlite
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from app.db.etl_bootstrap import ensure_sqlite_etl_bootstrap
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.external_sqlite import sqlite_conn

if TYPE_CHECKING:
    from sqlalchemy import Table
    from sqlalchemy.engine import Engine

from app.utils.path_io.path_utils import get_app_data_dir, get_base_dir, get_resource_path

logger = logging.getLogger(__name__)


DEFAULT_DB_FILES: tuple[str, ...] = (
    "products.db",
    "inventory.db",
    "voice_learning.db",
    "error_collection.db",
)

_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


from app.db.init_db_part01 import (
    _desktop_data_root as _desktop_data_root,
)
from app.db.init_db_part01 import (
    _ensure_sqlite_business_tables as _ensure_sqlite_business_tables,
)
from app.db.init_db_part01 import (
    _is_desktop_mode_env as _is_desktop_mode_env,
)
from app.db.init_db_part01 import (
    _iter_seed_dirs as _iter_seed_dirs,
)
from app.db.init_db_part01 import (
    _orm_table as _orm_table,
)
from app.db.init_db_part01 import (
    _resolve_auth_bootstrap_engine as _resolve_auth_bootstrap_engine,
)
from app.db.init_db_part01 import (
    _seed_default_admin_user as _seed_default_admin_user,
)
from app.db.init_db_part01 import (
    _seed_sqlite_rbac_defaults as _seed_sqlite_rbac_defaults,
)
from app.db.init_db_part01 import (
    build_mod_database_seed_plan as build_mod_database_seed_plan,
)
from app.db.init_db_part01 import (
    ensure_desktop_sqlite_business_tables_all_files as ensure_desktop_sqlite_business_tables_all_files,
)
from app.db.init_db_part01 import (
    ensure_runtime_database_environment as ensure_runtime_database_environment,
)
from app.db.init_db_part01 import (
    ensure_sqlite_auth_bootstrap as ensure_sqlite_auth_bootstrap,
)
from app.db.init_db_part01 import (
    ensure_sqlite_per_mod_database_copies as ensure_sqlite_per_mod_database_copies,
)
from app.db.init_db_part01 import (
    get_db_path as get_db_path,
)
from app.db.init_db_part01 import (
    get_distillation_db_path as get_distillation_db_path,
)
from app.db.init_db_part01 import (
    init_distillation_tables as init_distillation_tables,
)
from app.db.init_db_part01 import (
    init_extract_logs_tables as init_extract_logs_tables,
)
from app.db.init_db_part01 import (
    init_template_tables as init_template_tables,
)
from app.db.init_db_part01 import (
    init_template_tables_for_engine as init_template_tables_for_engine,
)
from app.db.init_db_part01 import (
    initialize_databases as initialize_databases,
)
from app.db.init_db_part01 import (
    refresh_config_database_urls as refresh_config_database_urls,
)
from app.db.init_db_part02 import (
    ensure_ai_conversation_bootstrap as ensure_ai_conversation_bootstrap,
)
from app.db.init_db_part02 import (
    ensure_employee_run_log_bootstrap as ensure_employee_run_log_bootstrap,
)
from app.db.init_db_part02 import (
    ensure_erp_bootstrap as ensure_erp_bootstrap,
)
from app.db.init_db_part02 import (
    ensure_mobile_push_bootstrap as ensure_mobile_push_bootstrap,
)
from app.db.init_db_part02 import (
    ensure_neuro_event_log_bootstrap as ensure_neuro_event_log_bootstrap,
)
from app.db.init_db_part02 import (
    ensure_postgresql_auth_bootstrap as ensure_postgresql_auth_bootstrap,
)
from app.db.init_db_part02 import (
    ensure_runtime_auth_bootstrap as ensure_runtime_auth_bootstrap,
)
from app.db.init_db_part02 import (
    ensure_sessions_market_access_token_column as ensure_sessions_market_access_token_column,
)
from app.db.init_db_part02 import (
    ensure_sqlite_enterprise_business_bootstrap as ensure_sqlite_enterprise_business_bootstrap,
)
from app.db.init_db_part02 import (
    ensure_sqlite_im_bootstrap as ensure_sqlite_im_bootstrap,
)
from app.db.init_db_part02 import (
    ensure_sqlite_inventory_bootstrap as ensure_sqlite_inventory_bootstrap,
)
from app.db.init_db_part02 import (
    ensure_sqlite_rbac_bootstrap as ensure_sqlite_rbac_bootstrap,
)
from app.db.init_db_part02 import (
    ensure_user_preferences_bootstrap as ensure_user_preferences_bootstrap,
)
from app.db.init_db_part03 import (
    ensure_business_tenant_id_columns as ensure_business_tenant_id_columns,
)
from app.db.init_db_part03 import (
    ensure_product_query_indexes as ensure_product_query_indexes,
)
from app.db.init_db_part03 import (
    ensure_sessions_account_meta_columns as ensure_sessions_account_meta_columns,
)
from app.db.init_db_part03 import (
    ensure_sessions_enterprise_entitlement_columns as ensure_sessions_enterprise_entitlement_columns,
)
from app.db.init_db_part03 import (
    ensure_sessions_market_refresh_token_column as ensure_sessions_market_refresh_token_column,
)
from app.db.init_db_part03 import (
    ensure_user_profile_columns as ensure_user_profile_columns,
)
from app.db.init_db_part03 import (
    ensure_users_tenant_id_column as ensure_users_tenant_id_column,
)
from app.db.init_db_part03 import (
    init_approval_tables as init_approval_tables,
)
from app.db.init_db_part03 import (
    init_im_tables as init_im_tables,
)
from app.db.init_db_part03 import (
    init_persona_tables as init_persona_tables,
)
from app.db.init_db_part03 import (
    init_service_bridge_tables as init_service_bridge_tables,
)
# ruff: noqa: F401
