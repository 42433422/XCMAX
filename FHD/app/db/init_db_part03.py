"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.db.init_db")


from app.db.init_db_part03_part01 import (
    ensure_business_tenant_id_columns as ensure_business_tenant_id_columns,
)
from app.db.init_db_part03_part01 import (
    ensure_sessions_account_meta_columns as ensure_sessions_account_meta_columns,
)
from app.db.init_db_part03_part01 import (
    ensure_sessions_enterprise_entitlement_columns as ensure_sessions_enterprise_entitlement_columns,
)
from app.db.init_db_part03_part01 import (
    ensure_sessions_market_refresh_token_column as ensure_sessions_market_refresh_token_column,
)
from app.db.init_db_part03_part01 import (
    ensure_user_profile_columns as ensure_user_profile_columns,
)
from app.db.init_db_part03_part01 import (
    ensure_users_tenant_id_column as ensure_users_tenant_id_column,
)
from app.db.init_db_part03_part02 import (
    ensure_product_query_indexes as ensure_product_query_indexes,
)
from app.db.init_db_part03_part02 import (
    init_approval_tables as init_approval_tables,
)
from app.db.init_db_part03_part02 import (
    init_im_tables as init_im_tables,
)
from app.db.init_db_part03_part02 import (
    init_persona_tables as init_persona_tables,
)
from app.db.init_db_part03_part02 import (
    init_service_bridge_tables as init_service_bridge_tables,
)
