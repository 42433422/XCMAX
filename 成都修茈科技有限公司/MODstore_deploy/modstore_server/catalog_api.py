"""兼容层：路由已迁至 ``modstore_server.api.catalog_public_routes``。"""

from __future__ import annotations

import warnings

warnings.warn(
    "modstore_server.catalog_api is deprecated; use modstore_server.api.catalog_public_routes",
    DeprecationWarning,
    stacklevel=2,
)

from modstore_server.api.catalog_public_routes import *  # noqa: F403
from modstore_server.api.catalog_public_routes import router

__all__ = ["router"]
