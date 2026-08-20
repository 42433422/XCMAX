"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.db.init_db")


from app.db.init_db_part02_part01 import (
    ensure_ai_conversation_bootstrap as ensure_ai_conversation_bootstrap,
)
from app.db.init_db_part02_part01 import (
    ensure_employee_run_log_bootstrap as ensure_employee_run_log_bootstrap,
)
from app.db.init_db_part02_part01 import (
    ensure_neuro_event_log_bootstrap as ensure_neuro_event_log_bootstrap,
)
from app.db.init_db_part02_part01 import (
    ensure_sqlite_enterprise_business_bootstrap as ensure_sqlite_enterprise_business_bootstrap,
)
from app.db.init_db_part02_part01 import (
    ensure_sqlite_im_bootstrap as ensure_sqlite_im_bootstrap,
)
from app.db.init_db_part02_part01 import (
    ensure_sqlite_inventory_bootstrap as ensure_sqlite_inventory_bootstrap,
)
from app.db.init_db_part02_part01 import (
    ensure_sqlite_rbac_bootstrap as ensure_sqlite_rbac_bootstrap,
)
from app.db.init_db_part02_part01 import (
    ensure_user_preferences_bootstrap as ensure_user_preferences_bootstrap,
)
from app.db.init_db_part02_part02 import (
    ensure_erp_bootstrap as ensure_erp_bootstrap,
)
from app.db.init_db_part02_part02 import (
    ensure_mobile_push_bootstrap as ensure_mobile_push_bootstrap,
)
from app.db.init_db_part02_part02 import (
    ensure_postgresql_auth_bootstrap as ensure_postgresql_auth_bootstrap,
)
from app.db.init_db_part02_part02 import (
    ensure_runtime_auth_bootstrap as ensure_runtime_auth_bootstrap,
)
from app.db.init_db_part02_part02 import (
    ensure_sessions_market_access_token_column as ensure_sessions_market_access_token_column,
)
