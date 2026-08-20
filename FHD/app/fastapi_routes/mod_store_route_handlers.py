# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Install, lifecycle, and catalog route handlers for the MOD store."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.mod_store_routes")


from app.fastapi_routes.mod_store_route_handlers_part01 import (
    _install_from_catalog as _install_from_catalog,
)
from app.fastapi_routes.mod_store_route_handlers_part01 import (
    mod_store_catalog as mod_store_catalog,
)
from app.fastapi_routes.mod_store_route_handlers_part01 import (
    mod_store_details as mod_store_details,
)
from app.fastapi_routes.mod_store_route_handlers_part01 import (
    mod_store_install as mod_store_install,
)
from app.fastapi_routes.mod_store_route_handlers_part01 import (
    mod_store_install_customer_delivery_seed as mod_store_install_customer_delivery_seed,
)
from app.fastapi_routes.mod_store_route_handlers_part01 import (
    mod_store_install_industry_seed as mod_store_install_industry_seed,
)
from app.fastapi_routes.mod_store_route_handlers_part01 import (
    mod_store_market_catalog as mod_store_market_catalog,
)
from app.fastapi_routes.mod_store_route_handlers_part01 import (
    mod_store_popular as mod_store_popular,
)
from app.fastapi_routes.mod_store_route_handlers_part01 import (
    mod_store_recent as mod_store_recent,
)
from app.fastapi_routes.mod_store_route_handlers_part01 import (
    mod_store_search as mod_store_search,
)
from app.fastapi_routes.mod_store_route_handlers_part01 import (
    mod_store_upload as mod_store_upload,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    _can_materialize_host_foundation_without_employee_marker as _can_materialize_host_foundation_without_employee_marker,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    _ensure_host_foundation_employee_on_disk as _ensure_host_foundation_employee_on_disk,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    _install_host_foundation_internal as _install_host_foundation_internal,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    mod_store_bootstrap_edition_pack as mod_store_bootstrap_edition_pack,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    mod_store_delete_package as mod_store_delete_package,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    mod_store_dependencies as mod_store_dependencies,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    mod_store_download as mod_store_download,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    mod_store_install_host_foundation as mod_store_install_host_foundation,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    mod_store_rate as mod_store_rate,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    mod_store_rebuild_index as mod_store_rebuild_index,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    mod_store_reload_employees as mod_store_reload_employees,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    mod_store_sync_modstore_library as mod_store_sync_modstore_library,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    mod_store_uninstall as mod_store_uninstall,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    mod_store_update as mod_store_update,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    mod_store_updates as mod_store_updates,
)
from app.fastapi_routes.mod_store_route_handlers_part02 import (
    mod_store_validate as mod_store_validate,
)
