"""Route mount phases."""

from app.fastapi_routes.mounts.business import register_business_routes
from app.fastapi_routes.mounts.essential_compat import register_essential_compat_routes
from app.fastapi_routes.mounts.health import register_health_routes
from app.fastapi_routes.mounts.infrastructure import register_infrastructure_routes
from app.fastapi_routes.mounts.lan import register_lan_routes
from app.fastapi_routes.mounts.neuro import register_neuro_routes
from app.fastapi_routes.mounts.neuro_migration import register_neuro_migration_routes
from app.legacy.routes.legacy_compat import register_legacy_compat_routes
from app.legacy.routes.legacy_gap import register_legacy_gap_routers

__all__ = [
    "register_business_routes",
    "register_essential_compat_routes",
    "register_health_routes",
    "register_infrastructure_routes",
    "register_lan_routes",
    "register_legacy_compat_routes",
    "register_legacy_gap_routers",
    "register_neuro_routes",
    "register_neuro_migration_routes",
]
