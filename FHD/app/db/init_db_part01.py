# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.db.init_db")


from app.db.init_db_part01_part01 import (
    _desktop_data_root as _desktop_data_root,
)
from app.db.init_db_part01_part01 import (
    _ensure_sqlite_business_tables as _ensure_sqlite_business_tables,
)
from app.db.init_db_part01_part01 import (
    _is_desktop_mode_env as _is_desktop_mode_env,
)
from app.db.init_db_part01_part01 import (
    _iter_seed_dirs as _iter_seed_dirs,
)
from app.db.init_db_part01_part01 import (
    _orm_table as _orm_table,
)
from app.db.init_db_part01_part01 import (
    build_mod_database_seed_plan as build_mod_database_seed_plan,
)
from app.db.init_db_part01_part01 import (
    ensure_desktop_sqlite_business_tables_all_files as ensure_desktop_sqlite_business_tables_all_files,
)
from app.db.init_db_part01_part01 import (
    ensure_runtime_database_environment as ensure_runtime_database_environment,
)
from app.db.init_db_part01_part01 import (
    ensure_sqlite_per_mod_database_copies as ensure_sqlite_per_mod_database_copies,
)
from app.db.init_db_part01_part01 import (
    get_db_path as get_db_path,
)
from app.db.init_db_part01_part01 import (
    get_distillation_db_path as get_distillation_db_path,
)
from app.db.init_db_part01_part01 import (
    init_distillation_tables as init_distillation_tables,
)
from app.db.init_db_part01_part01 import (
    init_extract_logs_tables as init_extract_logs_tables,
)
from app.db.init_db_part01_part01 import (
    initialize_databases as initialize_databases,
)
from app.db.init_db_part01_part01 import (
    refresh_config_database_urls as refresh_config_database_urls,
)
from app.db.init_db_part01_part02 import (
    _resolve_auth_bootstrap_engine as _resolve_auth_bootstrap_engine,
)
from app.db.init_db_part01_part02 import (
    _seed_default_admin_user as _seed_default_admin_user,
)
from app.db.init_db_part01_part02 import (
    _seed_sqlite_rbac_defaults as _seed_sqlite_rbac_defaults,
)
from app.db.init_db_part01_part02 import (
    ensure_sqlite_auth_bootstrap as ensure_sqlite_auth_bootstrap,
)
from app.db.init_db_part01_part02 import (
    init_template_tables as init_template_tables,
)
from app.db.init_db_part01_part02 import (
    init_template_tables_for_engine as init_template_tables_for_engine,
)
