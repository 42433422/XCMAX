"""LAN 域路由聚合（user / admin / settings）。"""
from app.fastapi_routes.domains.lan.admin_routes import router as lan_admin_router
from app.fastapi_routes.domains.lan.settings_routes import router as lan_settings_router
from app.fastapi_routes.domains.lan.user_routes import router as lan_router

__all__ = ["lan_router", "lan_admin_router", "lan_settings_router"]
