"""
XCAGI 数据库路径与初始化入口（应用内）。

目标：
- 让 app/* 不再依赖仓库根目录 db.py
- 兼容 PyInstaller（_MEIPASS）与开发环境
- 支持从 resources/db_seed 复制初始 sqlite

实现已拆分至 ``init_desktop_sqlite`` / ``init_seed_bootstrap`` / ``init_table_domains``；
本模块保留为兼容 re-export facade。
"""

from __future__ import annotations

import shutil
import sys

from app.db.init_desktop_sqlite import (
    _desktop_data_root,
    _is_desktop_mode_env,
    ensure_desktop_sqlite_business_tables_all_files,
    ensure_runtime_database_environment,
    get_db_path,
    get_distillation_db_path,
    refresh_config_database_urls,
)
from app.db.init_seed_bootstrap import (
    DEFAULT_DB_FILES,
    _iter_seed_dirs,
    _resolve_auth_bootstrap_engine,
    _seed_default_admin_user,
    _seed_sqlite_rbac_defaults,
    build_mod_database_seed_plan,
    ensure_neuro_event_log_bootstrap,
    ensure_postgresql_auth_bootstrap,
    ensure_runtime_auth_bootstrap,
    ensure_sqlite_auth_bootstrap,
    ensure_sqlite_enterprise_business_bootstrap,
    ensure_sqlite_im_bootstrap,
    ensure_sqlite_inventory_bootstrap,
    ensure_sqlite_per_mod_database_copies,
    ensure_sqlite_rbac_bootstrap,
    ensure_user_preferences_bootstrap,
    initialize_databases,
)
from app.db.init_table_domains import (
    ensure_business_tenant_id_columns,
    ensure_product_query_indexes,
    ensure_sessions_account_meta_columns,
    ensure_sessions_enterprise_entitlement_columns,
    ensure_sessions_market_access_token_column,
    ensure_sessions_market_refresh_token_column,
    ensure_user_profile_columns,
    ensure_users_tenant_id_column,
    init_approval_tables,
    init_distillation_tables,
    init_extract_logs_tables,
    init_im_tables,
    init_persona_tables,
    init_service_bridge_tables,
    init_template_tables,
    init_template_tables_for_engine,
    init_wechat_tasks_table,
)
from app.utils.external_sqlite import sqlite_conn
from app.utils.path_utils import get_app_data_dir, get_base_dir, get_resource_path

__all__ = [
    "DEFAULT_DB_FILES",
    "_desktop_data_root",
    "_is_desktop_mode_env",
    "_iter_seed_dirs",
    "_resolve_auth_bootstrap_engine",
    "_seed_default_admin_user",
    "_seed_sqlite_rbac_defaults",
    "build_mod_database_seed_plan",
    "ensure_business_tenant_id_columns",
    "ensure_desktop_sqlite_business_tables_all_files",
    "ensure_neuro_event_log_bootstrap",
    "ensure_postgresql_auth_bootstrap",
    "ensure_product_query_indexes",
    "ensure_runtime_auth_bootstrap",
    "ensure_runtime_database_environment",
    "ensure_sessions_account_meta_columns",
    "ensure_sessions_enterprise_entitlement_columns",
    "ensure_sessions_market_access_token_column",
    "ensure_sessions_market_refresh_token_column",
    "ensure_sqlite_auth_bootstrap",
    "ensure_sqlite_enterprise_business_bootstrap",
    "ensure_sqlite_im_bootstrap",
    "ensure_sqlite_inventory_bootstrap",
    "ensure_sqlite_per_mod_database_copies",
    "ensure_sqlite_rbac_bootstrap",
    "ensure_user_preferences_bootstrap",
    "ensure_user_profile_columns",
    "ensure_users_tenant_id_column",
    "get_app_data_dir",
    "get_base_dir",
    "get_db_path",
    "get_distillation_db_path",
    "get_resource_path",
    "init_approval_tables",
    "init_distillation_tables",
    "init_extract_logs_tables",
    "init_im_tables",
    "init_persona_tables",
    "init_service_bridge_tables",
    "init_template_tables",
    "init_template_tables_for_engine",
    "init_wechat_tasks_table",
    "initialize_databases",
    "refresh_config_database_urls",
    "shutil",
    "sqlite_conn",
    "sys",
]
