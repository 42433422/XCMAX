"""Compat re-export — canonical at compat_db_base (debt19 noisy basename rename)."""

from app.infrastructure.persistence.compat_db.compat_db_base import *  # noqa: F403
from app.infrastructure.persistence.compat_db.compat_db_base import (  # noqa: F401
    _business_mod_json_block,
    _customer_body_name_contact,
    _customers_write_raise,
)
